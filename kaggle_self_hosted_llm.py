# ─────────────────────────────────────────────────────────────────
# Self-hosted multimodal LLM server for NLP-OCR's SelfHostedProvider.
#
# Run this as a Kaggle notebook (paste into cells, or run as one script
# with `!python` — cell breaks are marked below). Requires:
#   - Notebook settings: Accelerator = GPU (P100 or T4 x2), Internet = On
#   - A free ngrok account -> https://dashboard.ngrok.com/get-started/your-authtoken
#
# Serves an OpenAI-compatible POST /chat/completions endpoint. Handles
# BOTH shapes the app sends:
#   - text-only (rubric suggestion): content is a plain string
#   - multimodal (equation-from-image): content is a list of
#     {"type": "text", "text": ...} / {"type": "image_url", "image_url": {"url": "data:...;base64,..."}}
#
# Once running, copy the printed ngrok URL into the app's
# SELF_HOSTED_LLM_URL env var (backend/.env), e.g.:
#   SELF_HOSTED_LLM_URL=https://xxxx.ngrok-free.app
# ─────────────────────────────────────────────────────────────────

# ── Cell 1: install deps ────────────────────────────────────────────
# Deliberately NOT listing pillow here — nothing in this script imports
# PIL directly (qwen_vl_utils.process_vision_info handles image decoding
# internally), and force-upgrading it with -U risks exactly the kind of
# partial-upgrade breakage ("cannot import name '_Ink' from
# PIL._typing") that pins Pillow's pure-Python and compiled parts to
# different versions. Let qwen-vl-utils pull in whatever Pillow version
# it actually declares as a dependency instead.
# Qwen3-VL needs a recent transformers; -U covers it.
# !pip install -q -U transformers accelerate bitsandbytes qwen-vl-utils \
#     fastapi uvicorn pyngrok nest_asyncio

# ── Cell 2: load the model (4-bit, fits comfortably in 16GB) ────────
import time

import torch
# AutoModelForImageTextToText rather than a version-specific class, so
# changing MODEL_ID below is the only edit needed to move between Qwen
# generations — Qwen2.5-VL and Qwen3-VL use different class names.
from transformers import AutoModelForImageTextToText, AutoProcessor, BitsAndBytesConfig
from qwen_vl_utils import process_vision_info

# The one knob. What fits depends on the accelerator Kaggle gives you:
#
#   T4 x2 (32GB total, the roomier option — pick this for anything big)
#     Qwen/Qwen3-VL-8B-Instruct     best quality per GB; start here
#     Qwen/Qwen2.5-VL-32B-Instruct  stronger judgement, slow to load,
#                                   splits across both cards in 4-bit
#   P100 (16GB, single card)
#     Qwen/Qwen2.5-VL-7B-Instruct   the safe default
#     Qwen/Qwen3-VL-8B-Instruct     fits in 4-bit, tight
#
# P100 is Pascal (compute 6.0) and bitsandbytes 4-bit kernels are
# unreliable below 7.0, so prefer T4 x2 whenever you have the quota.
# 72B and larger do not fit on Kaggle's free tier at all.
#
# Staying within Qwen matters beyond quality: process_vision_info below
# is Qwen's own helper. A model from another family (Llama 4, MiniCPM,
# Pixtral) needs its own message-preparation code, not just a new id.
MODEL_ID = "Qwen/Qwen3-VL-8B-Instruct"

quant_config = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_compute_dtype=torch.float16,
    bnb_4bit_quant_type="nf4",
)

# qwen_vl_utils.process_vision_info resizes images to fit a pixel budget,
# but its defaults are tuned for much larger GPUs than a free-tier T4/P100
# (14.56GiB usable here) — a full-resolution phone photo can still produce
# enough vision tokens to try to allocate 20+GiB during generation and
# OOM. These are Qwen's own officially documented values for exactly this
# constrained-memory scenario (see the Qwen2-VL/2.5-VL model card):
# 256*28*28 (~200K px, plenty to read a cropped equation) as the floor,
# 1280*28*28 (~1MP) as the ceiling, applied on the processor itself so
# every image is capped regardless of what the client uploaded.
MIN_PIXELS = 256 * 28 * 28
MAX_PIXELS = 1280 * 28 * 28

print("Loading model — first run downloads ~8GB, takes a few minutes...")
processor = AutoProcessor.from_pretrained(MODEL_ID, min_pixels=MIN_PIXELS, max_pixels=MAX_PIXELS)
model = AutoModelForImageTextToText.from_pretrained(
    MODEL_ID,
    quantization_config=quant_config,
    device_map="auto",
    torch_dtype=torch.float16,
)
print("Model loaded.")


def run_chat(messages: list[dict], max_tokens: int = 512, temperature: float = 0.1) -> str:
    """messages: OpenAI-style list of {role, content}. content is either a
    plain string, or a list of {"type": "text"|"image_url", ...} parts.

    Qwen's chat template/processor accept a base64 data: URI directly as
    an image's "image" value, and qwen_vl_utils.process_vision_info
    handles decoding + resizing to a safe pixel budget automatically —
    important since a teacher's uploaded photo could be several
    megapixels, which would otherwise risk OOM on a free-tier GPU.
    """
    qwen_messages = []
    for m in messages:
        content = m["content"]
        if isinstance(content, str):
            qwen_messages.append({"role": m["role"], "content": [{"type": "text", "text": content}]})
            continue

        parts = []
        for part in content:
            if part.get("type") == "text":
                parts.append({"type": "text", "text": part["text"]})
            elif part.get("type") == "image_url":
                parts.append({"type": "image", "image": part["image_url"]["url"]})
        qwen_messages.append({"role": m["role"], "content": parts})

    text_prompt = processor.apply_chat_template(qwen_messages, tokenize=False, add_generation_prompt=True)
    image_inputs, video_inputs = process_vision_info(qwen_messages)
    inputs = processor(
        text=[text_prompt],
        images=image_inputs,
        videos=video_inputs,
        padding=True,
        return_tensors="pt",
    ).to(model.device)

    with torch.no_grad():
        generated = model.generate(
            **inputs,
            max_new_tokens=max_tokens,
            do_sample=temperature > 0,
            temperature=max(temperature, 0.01),
        )

    trimmed = [out[len(inp):] for inp, out in zip(inputs.input_ids, generated)]
    result = processor.batch_decode(trimmed, skip_special_tokens=True, clean_up_tokenization_spaces=False)
    return result[0].strip()


# ── Cell 3: FastAPI server + ngrok tunnel ───────────────────────────
import traceback

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pyngrok import ngrok

app = FastAPI()


@app.post("/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    max_tokens = body.get("max_tokens", 512)
    temperature = body.get("temperature", 0.1)

    started = time.time()
    try:
        text = run_chat(messages, max_tokens=max_tokens, temperature=temperature)
    except Exception as e:
        # An unhandled exception here would otherwise become an opaque
        # 500 with no detail on the client side — print the full
        # traceback to this notebook's own console (for you) AND return
        # the message in the response body (so it shows up in the app's
        # error banner directly, no need to come back and check here).
        # Also clear the CUDA cache — an OOM on one request can otherwise
        # leave fragmented memory that makes the *next* request fail too,
        # even on an image that would normally fit fine.
        traceback.print_exc()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        return JSONResponse(
            status_code=500,
            content={"error": f"{type(e).__name__}: {e}"},
        )
    print(f"Generated {len(text)} chars in {time.time() - started:.1f}s")

    return {
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "model": MODEL_ID,
    }


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_ID}


# Paste your ngrok authtoken here (free account, from
# https://dashboard.ngrok.com/get-started/your-authtoken):
NGROK_AUTHTOKEN = "PASTE_YOUR_NGROK_AUTHTOKEN_HERE"
ngrok.set_auth_token(NGROK_AUTHTOKEN)

# Pin the account's reserved domain rather than taking a random one.
# ngrok's free tier includes one permanent domain (dashboard -> Domains);
# with it pinned the URL never changes, so SELF_HOSTED_LLM_URL survives
# every restart of this notebook — without it, a deployed instance breaks
# each time the tunnel is re-established.
NGROK_DOMAIN = ""  # e.g. "your-name.ngrok-free.dev"; blank = random URL
tunnel = ngrok.connect(8000, domain=NGROK_DOMAIN) if NGROK_DOMAIN else ngrok.connect(8000)
print("=" * 70)
print(f"Public URL — put this in backend/.env as SELF_HOSTED_LLM_URL:")
print(f"  {tunnel.public_url}")
print("=" * 70)

# uvicorn.run() calls asyncio.run() internally, which raises
# "cannot be called from a running event loop" inside a notebook kernel
# (Jupyter/Kaggle already runs one). Using the lower-level Server API
# with `await` runs on the notebook's own existing loop instead — no
# event-loop patching needed, and it's the pattern that actually works
# across Python/uvicorn versions where nest_asyncio's monkey-patching
# doesn't fully cover newer asyncio internals.
config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="info")
server = uvicorn.Server(config)
await server.serve()
