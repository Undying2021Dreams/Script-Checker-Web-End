"""
LLM Provider — two capabilities, one interface, four interchangeable
backends (GeminiProvider, OpenAIProvider, ClaudeProvider,
SelfHostedProvider):

  - suggest_rubric: given the question's text + each answer box's
    label/points, propose a rubric (criteria + point split) per box for
    the teacher to review and edit — never auto-applied.
  - equation_from_image: given a photo/screenshot of a single equation,
    transcribe it to LaTeX so a teacher who doesn't know LaTeX can still
    author equations. Also never auto-applied — the frontend shows the
    result in an editable preview before it becomes a real EquationNode.
  - check_correctness: given a question's text and its own ground-truth
    answer (text and/or images), sanity-check that the answer is actually
    correct for that question and that the question itself is answerable
    as worded — catches a teacher's own mistakes before students see them.
    Purely advisory, same as the other two.

Keys for the three hosted providers are server-side config (deployer
sets them once via .env), not per-teacher — a teacher just picks a
provider from a dropdown. SelfHostedProvider talks to any OpenAI-
chat-completions-compatible endpoint (e.g. a Kaggle-notebook-hosted
open model tunneled out via ngrok — see kaggle_self_hosted_llm.py at
the repo root).
"""

from __future__ import annotations

import base64
import json
import logging
import re
from abc import ABC, abstractmethod

import httpx

from config import settings

logger = logging.getLogger(__name__)

RUBRIC_SYSTEM_PROMPT = """\
You are a teaching assistant helping a teacher draft grading rubrics.
You will receive the plain-text question content and a list of answer
boxes (id, label, current point value).

For each answer box, propose:
  - "suggested_points": an integer point value (you may keep their current
    value if it already looks reasonable)
  - "rubric": a short (1-3 sentence) description of what a full-credit
    answer should contain

Do NOT solve the question yourself if it's ambiguous without more context
— give a generic but useful rubric based on what's visible.

Return ONLY a JSON array, no prose, no markdown fences:
[{"id": "...", "suggested_points": 5, "rubric": "..."}]
"""

EQUATION_SYSTEM_PROMPT = """\
You are a precise math OCR assistant. You will be shown an image
containing a single mathematical equation or expression (printed or
handwritten).

Transcribe it EXACTLY as LaTeX — preserve every symbol, subscript,
superscript, fraction, and operator faithfully. Do not solve, simplify,
or correct the math even if it looks wrong.

Return ONLY the raw LaTeX code for the expression itself — no $ or $$
delimiters, no \\[ \\] or \\( \\) wrappers, no markdown code fences, no
explanation, no surrounding text. Just the LaTeX.
"""

CORRECTNESS_SYSTEM_PROMPT = """\
You are helping a teacher sanity-check one exam question and its own
marked-correct answer (ground truth) before it goes out to students. You
will receive the question's text and its ground truth answer's text —
LaTeX may be embedded inline as $...$ (inline) or $$...$$ (block) — and
possibly one or more images that are part of the answer.

Decide whether the ground truth answer is a correct, complete, and
unambiguous response to the question, AND whether the question itself is
clearly worded and answerable as stated.

Respond in EXACTLY this plain-text format — NOT JSON, NOT markdown code
fences. Write LaTeX commands with a single literal backslash exactly as
you normally would (\\frac{a}{b}, \\neq, \\theta, ...) — this is plain
text, not a JSON string, so backslashes must NEVER be doubled or escaped:

OK: true or false
ISSUE: question or answer or both or none
---EXPLANATION---
A short (1-3 sentence) explanation a teacher can immediately understand.
---SUGGESTED_QUESTION---
NONE, or a corrected replacement for the question text if (and only if)
the question itself needs a fix.
---SUGGESTED_ANSWER---
NONE, or a corrected replacement for the answer text if (and only if) the
answer needs a fix.
---END---

Write "OK: true" only if both the question and the answer are correct
and consistent with each other. Never rewrite a side that is already
fine — write NONE for it instead of repeating it back. Preserve the same
LaTeX delimiter style ($...$ / $$...$$) as the input when writing
suggested text. ALWAYS write at least one full sentence in EXPLANATION —
even when OK is true, briefly say why the question and answer check out.
Never leave EXPLANATION blank.

Example of a complete response:
OK: false
ISSUE: answer
---EXPLANATION---
The answer claims 2+2=5, but the correct sum is 4 — the arithmetic is
wrong.
---SUGGESTED_QUESTION---
NONE
---SUGGESTED_ANSWER---
$$2+2=4$$
---END---
"""


def _build_user_message(question_text: str, boxes: list[dict]) -> str:
    return json.dumps({"question_text": question_text, "answer_boxes": boxes}, ensure_ascii=False)


def _build_correctness_message(question_text: str, answer_text: str) -> str:
    return json.dumps({"question_text": question_text, "answer_text": answer_text}, ensure_ascii=False)


def _clean_latex(text: str) -> str:
    """Strip wrapping a model might add despite instructions: markdown
    fences, $ / $$ / \\( \\) / \\[ \\] delimiters."""
    t = text.strip()
    if t.startswith("```"):
        lines = [l for l in t.split("\n") if not l.strip().startswith("```")]
        t = "\n".join(lines).strip()
    for open_d, close_d in (("$$", "$$"), ("\\[", "\\]"), ("\\(", "\\)"), ("$", "$")):
        if t.startswith(open_d) and t.endswith(close_d) and len(t) > len(open_d) + len(close_d):
            t = t[len(open_d):-len(close_d)].strip()
            break
    return t


def _to_data_url(image_bytes: bytes, content_type: str) -> str:
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return f"data:{content_type};base64,{b64}"


def _parse_response(response_text: str, boxes: list[dict]) -> list[dict]:
    text = response_text.strip()
    if text.startswith("```"):
        text = "\n".join(l for l in text.split("\n") if not l.strip().startswith("```")).strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"LLM returned invalid JSON: {e}") from e

    by_id = {p.get("id"): p for p in parsed if isinstance(p, dict)}
    results = []
    for b in boxes:
        p = by_id.get(b["id"], {})
        results.append({
            "id": b["id"],
            "suggested_points": p.get("suggested_points", b.get("points", 1)),
            "rubric": p.get("rubric", ""),
        })
    return results


_CORRECTNESS_SECTION_RE = re.compile(r"---([A-Z_]+)---[ \t]*\n(.*?)(?=\n---[A-Z_]+---|\Z)", re.DOTALL)


def _parse_correctness_response(response_text: str) -> dict:
    """Parses the plain-text (not JSON!) format CORRECTNESS_SYSTEM_PROMPT
    asks for. Deliberately NOT JSON: LaTeX is full of backslash sequences
    that collide with JSON string escapes — a model writing \\neq or
    \\frac without doubling the backslash (very easy to do, since that's
    literally correct LaTeX) silently corrupts under json.loads: \\n
    parses as a newline, \\f as a form feed, \\t as a tab, turning
    "1 \\neq 0" into "1" + newline + "eq 0". A delimited plain-text format
    sidesteps that whole class of bug — nothing here is ever unescaped."""
    text = response_text.strip()
    if text.startswith("```"):
        text = "\n".join(l for l in text.split("\n") if not l.strip().startswith("```")).strip()

    ok_match = re.search(r"^\s*OK:\s*(true|false)", text, re.IGNORECASE | re.MULTILINE)
    if not ok_match:
        raise ValueError(f"LLM response missing OK field: {text[:300]!r}")

    issue_match = re.search(r"^\s*ISSUE:\s*(\w+)", text, re.IGNORECASE | re.MULTILINE)
    issue = issue_match.group(1).lower() if issue_match else "none"
    if issue not in ("question", "answer", "both"):
        issue = None

    sections = {name.upper(): body.strip() for name, body in _CORRECTNESS_SECTION_RE.findall(text)}

    def _norm(s):
        return None if (not s or s.strip().upper() == "NONE") else s.strip()

    return {
        "ok": ok_match.group(1).lower() == "true",
        "issue": issue,
        "explanation": sections.get("EXPLANATION", ""),
        "suggested_question": _norm(sections.get("SUGGESTED_QUESTION")),
        "suggested_answer": _norm(sections.get("SUGGESTED_ANSWER")),
    }


class LLMProvider(ABC):
    @abstractmethod
    async def suggest_rubric(self, question_text: str, boxes: list[dict]) -> list[dict]:
        ...

    @abstractmethod
    async def equation_from_image(self, image_bytes: bytes, content_type: str) -> str:
        """Return raw LaTeX (no delimiters) transcribed from the image."""
        ...

    @abstractmethod
    async def check_correctness(
        self, question_text: str, answer_text: str, answer_images: list[tuple[bytes, str]]
    ) -> dict:
        """Return {ok, issue, explanation, suggested_question, suggested_answer}."""
        ...

    @abstractmethod
    async def complete(
        self, system_prompt: str, user_text: str, images: list[tuple[bytes, str]]
    ) -> str:
        """
        Raw multimodal completion — returns the model's text verbatim.

        The methods above each bake one prompt into four transports.
        Grading instead keeps its prompt and parser in services/grading.py
        and reaches the model through this, so a change to how answers are
        marked is one edit rather than four.
        """
        ...


class GeminiProvider(LLMProvider):
    MODEL = "gemini-2.5-flash"

    async def suggest_rubric(self, question_text: str, boxes: list[dict]) -> list[dict]:
        api_key = settings.GEMINI_API_KEY
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set.")

        genai = self._sdk()
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(self.MODEL)
        user_msg = _build_user_message(question_text, boxes)

        response = model.generate_content(
            [{"role": "user", "parts": [RUBRIC_SYSTEM_PROMPT + "\n\n" + user_msg]}],
            generation_config={"temperature": 0.2, "max_output_tokens": 2048},
        )
        return _parse_response(response.text, boxes)

    async def equation_from_image(self, image_bytes: bytes, content_type: str) -> str:
        api_key = settings.GEMINI_API_KEY
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set.")

        genai = self._sdk()
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(self.MODEL)

        response = model.generate_content(
            [{"role": "user", "parts": [
                EQUATION_SYSTEM_PROMPT,
                {"mime_type": content_type, "data": image_bytes},
            ]}],
            generation_config={"temperature": 0.1, "max_output_tokens": 1024},
        )
        return _clean_latex(response.text)

    async def check_correctness(
        self, question_text: str, answer_text: str, answer_images: list[tuple[bytes, str]]
    ) -> dict:
        api_key = settings.GEMINI_API_KEY
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set.")

        genai = self._sdk()
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(self.MODEL)

        parts = [CORRECTNESS_SYSTEM_PROMPT + "\n\n" + _build_correctness_message(question_text, answer_text)]
        for image_bytes, content_type in answer_images:
            parts.append({"mime_type": content_type, "data": image_bytes})

        response = model.generate_content(
            [{"role": "user", "parts": parts}],
            # gemini-2.5-flash spends part of max_output_tokens on internal
            # "thinking" before the visible answer, and the installed
            # google-generativeai SDK (deprecated, no bug fixes upstream —
            # see https://github.com/google-gemini/deprecated-generative-
            # ai-python) exposes no thinking_config/thinking_budget knob to
            # cap that separately. 1024-2048 was getting silently eaten by
            # thinking and truncating the visible response mid-sentence;
            # give enough headroom that the real answer always fits too.
            generation_config={"temperature": 0.2, "max_output_tokens": 4096},
        )
        return _parse_correctness_response(response.text)

    async def complete(
        self, system_prompt: str, user_text: str, images: list[tuple[bytes, str]]
    ) -> str:
        api_key = settings.GEMINI_API_KEY
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not set.")

        genai = self._sdk()
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(self.MODEL)

        parts = [system_prompt + "\n\n" + user_text]
        for image_bytes, content_type in images:
            parts.append({"mime_type": content_type, "data": image_bytes})

        response = model.generate_content(
            [{"role": "user", "parts": parts}],
            # Same headroom as check_correctness — this model spends part of
            # max_output_tokens on internal thinking before the visible text.
            generation_config={"temperature": 0.2, "max_output_tokens": 4096},
        )
        return response.text

    @staticmethod
    def _sdk():
        try:
            import google.generativeai as genai
            return genai
        except ImportError:
            raise ImportError("google-generativeai package is required for Gemini provider")


class OpenAIProvider(LLMProvider):
    MODEL = "gpt-4o-mini"
    BASE_URL = "https://api.openai.com/v1/chat/completions"

    def _headers(self) -> dict:
        api_key = settings.OPENAI_API_KEY
        if not api_key:
            raise ValueError("OPENAI_API_KEY is not set.")
        return {"Authorization": f"Bearer {api_key}"}

    async def suggest_rubric(self, question_text: str, boxes: list[dict]) -> list[dict]:
        payload = {
            "model": self.MODEL,
            "messages": [
                {"role": "system", "content": RUBRIC_SYSTEM_PROMPT},
                {"role": "user", "content": _build_user_message(question_text, boxes)},
            ],
            "temperature": 0.2,
            "max_tokens": 2048,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(self.BASE_URL, json=payload, headers=self._headers())
            resp.raise_for_status()
        return _parse_response(resp.json()["choices"][0]["message"]["content"], boxes)

    async def equation_from_image(self, image_bytes: bytes, content_type: str) -> str:
        payload = {
            "model": self.MODEL,
            "messages": [
                {"role": "system", "content": EQUATION_SYSTEM_PROMPT},
                {"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": _to_data_url(image_bytes, content_type)}},
                ]},
            ],
            "temperature": 0.1,
            "max_tokens": 1024,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(self.BASE_URL, json=payload, headers=self._headers())
            resp.raise_for_status()
        return _clean_latex(resp.json()["choices"][0]["message"]["content"])

    async def check_correctness(
        self, question_text: str, answer_text: str, answer_images: list[tuple[bytes, str]]
    ) -> dict:
        content = [{"type": "text", "text": _build_correctness_message(question_text, answer_text)}]
        for image_bytes, content_type in answer_images:
            content.append({"type": "image_url", "image_url": {"url": _to_data_url(image_bytes, content_type)}})

        payload = {
            "model": self.MODEL,
            "messages": [
                {"role": "system", "content": CORRECTNESS_SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            "temperature": 0.2,
            "max_tokens": 2048,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(self.BASE_URL, json=payload, headers=self._headers())
            resp.raise_for_status()
        return _parse_correctness_response(resp.json()["choices"][0]["message"]["content"])

    async def complete(
        self, system_prompt: str, user_text: str, images: list[tuple[bytes, str]]
    ) -> str:
        content = [{"type": "text", "text": user_text}]
        for image_bytes, content_type in images:
            content.append({"type": "image_url", "image_url": {"url": _to_data_url(image_bytes, content_type)}})

        payload = {
            "model": self.MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
            "temperature": 0.2,
            "max_tokens": 2048,
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(self.BASE_URL, json=payload, headers=self._headers())
            resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


class ClaudeProvider(LLMProvider):
    MODEL = "claude-haiku-4-5-20251001"
    BASE_URL = "https://api.anthropic.com/v1/messages"

    def _headers(self) -> dict:
        api_key = settings.ANTHROPIC_API_KEY
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set.")
        return {"x-api-key": api_key, "anthropic-version": "2023-06-01"}

    async def suggest_rubric(self, question_text: str, boxes: list[dict]) -> list[dict]:
        payload = {
            "model": self.MODEL,
            "max_tokens": 2048,
            "temperature": 0.2,
            "system": RUBRIC_SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": _build_user_message(question_text, boxes)}],
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(self.BASE_URL, json=payload, headers=self._headers())
            resp.raise_for_status()
        return _parse_response(resp.json()["content"][0]["text"], boxes)

    async def equation_from_image(self, image_bytes: bytes, content_type: str) -> str:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        payload = {
            "model": self.MODEL,
            "max_tokens": 1024,
            "temperature": 0.1,
            "system": EQUATION_SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": content_type, "data": b64}},
            ]}],
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(self.BASE_URL, json=payload, headers=self._headers())
            resp.raise_for_status()
        return _clean_latex(resp.json()["content"][0]["text"])

    async def check_correctness(
        self, question_text: str, answer_text: str, answer_images: list[tuple[bytes, str]]
    ) -> dict:
        content = [{"type": "text", "text": _build_correctness_message(question_text, answer_text)}]
        for image_bytes, content_type in answer_images:
            b64 = base64.b64encode(image_bytes).decode("ascii")
            content.append({"type": "image", "source": {"type": "base64", "media_type": content_type, "data": b64}})

        payload = {
            "model": self.MODEL,
            "max_tokens": 2048,
            "temperature": 0.2,
            "system": CORRECTNESS_SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": content}],
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(self.BASE_URL, json=payload, headers=self._headers())
            resp.raise_for_status()
        return _parse_correctness_response(resp.json()["content"][0]["text"])

    async def complete(
        self, system_prompt: str, user_text: str, images: list[tuple[bytes, str]]
    ) -> str:
        content = [{"type": "text", "text": user_text}]
        for image_bytes, content_type in images:
            b64 = base64.b64encode(image_bytes).decode("ascii")
            content.append({"type": "image", "source": {"type": "base64", "media_type": content_type, "data": b64}})

        payload = {
            "model": self.MODEL,
            "max_tokens": 2048,
            "temperature": 0.2,
            "system": system_prompt,
            "messages": [{"role": "user", "content": content}],
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(self.BASE_URL, json=payload, headers=self._headers())
            resp.raise_for_status()
        return resp.json()["content"][0]["text"]


async def _post_self_hosted(url: str, payload: dict, timeout: float) -> dict:
    """POST to the self-hosted endpoint, raising with whatever error detail
    the server actually returned rather than httpx's generic "500 Internal
    Server Error" (which drops the response body). kaggle_self_hosted_llm.py
    returns {"error": "<type>: <message>"} on failure — fall back to raw
    response text for any other OpenAI-compatible server that doesn't."""
    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload)
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("error", resp.text)
            except Exception:
                detail = resp.text
            raise ValueError(f"Self-hosted server error ({resp.status_code}): {detail}")
        return resp.json()


class SelfHostedProvider(LLMProvider):
    async def suggest_rubric(self, question_text: str, boxes: list[dict]) -> list[dict]:
        endpoint = settings.SELF_HOSTED_LLM_URL
        if not endpoint:
            raise ValueError("SELF_HOSTED_LLM_URL is not set.")

        url = endpoint.rstrip("/") + "/chat/completions"
        user_msg = _build_user_message(question_text, boxes)
        payload = {
            "model": "default",
            "messages": [
                {"role": "system", "content": RUBRIC_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "temperature": 0.2,
            "max_tokens": 2048,
        }
        data = await _post_self_hosted(url, payload, timeout=60.0)
        return _parse_response(data["choices"][0]["message"]["content"], boxes)

    async def equation_from_image(self, image_bytes: bytes, content_type: str) -> str:
        endpoint = settings.SELF_HOSTED_LLM_URL
        if not endpoint:
            raise ValueError("SELF_HOSTED_LLM_URL is not set.")

        url = endpoint.rstrip("/") + "/chat/completions"
        payload = {
            "model": "default",
            "messages": [
                {"role": "system", "content": EQUATION_SYSTEM_PROMPT},
                {"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": _to_data_url(image_bytes, content_type)}},
                ]},
            ],
            "temperature": 0.1,
            "max_tokens": 1024,
        }
        # Longer timeout than the hosted providers — a free-tier notebook
        # GPU is meaningfully slower than a commercial inference API.
        data = await _post_self_hosted(url, payload, timeout=120.0)
        return _clean_latex(data["choices"][0]["message"]["content"])

    async def check_correctness(
        self, question_text: str, answer_text: str, answer_images: list[tuple[bytes, str]]
    ) -> dict:
        endpoint = settings.SELF_HOSTED_LLM_URL
        if not endpoint:
            raise ValueError("SELF_HOSTED_LLM_URL is not set.")

        url = endpoint.rstrip("/") + "/chat/completions"
        content = [{"type": "text", "text": _build_correctness_message(question_text, answer_text)}]
        for image_bytes, content_type in answer_images:
            content.append({"type": "image_url", "image_url": {"url": _to_data_url(image_bytes, content_type)}})

        payload = {
            "model": "default",
            "messages": [
                {"role": "system", "content": CORRECTNESS_SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            "temperature": 0.2,
            "max_tokens": 2048,
        }
        data = await _post_self_hosted(url, payload, timeout=120.0)
        return _parse_correctness_response(data["choices"][0]["message"]["content"])

    async def complete(
        self, system_prompt: str, user_text: str, images: list[tuple[bytes, str]]
    ) -> str:
        endpoint = settings.SELF_HOSTED_LLM_URL
        if not endpoint:
            raise ValueError("SELF_HOSTED_LLM_URL is not set.")

        url = endpoint.rstrip("/") + "/chat/completions"
        content = [{"type": "text", "text": user_text}]
        for image_bytes, content_type in images:
            content.append({"type": "image_url", "image_url": {"url": _to_data_url(image_bytes, content_type)}})

        payload = {
            "model": "default",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ],
            "temperature": 0.2,
            "max_tokens": 2048,
        }
        # Longer timeout than the hosted providers: this one is a GPU
        # notebook behind a tunnel, and a cold model load is slow.
        data = await _post_self_hosted(url, payload, timeout=120.0)
        return data["choices"][0]["message"]["content"]


def get_provider(name: str) -> LLMProvider:
    providers = {
        "gemini": GeminiProvider,
        "openai": OpenAIProvider,
        "claude": ClaudeProvider,
        "self_hosted": SelfHostedProvider,
    }
    cls = providers.get(name)
    if cls is None:
        raise ValueError(f"Unknown LLM provider: {name!r}. Choose from {list(providers)}")
    return cls()


def extract_plain_text(tiptap_doc) -> str:
    """Flatten a Tiptap doc's text content for sending to the LLM (skips
    answer boxes and image src — just the wording itself). Equation nodes
    are atoms with no "content" array (latex/display live in attrs, see
    EquationNode.jsx) so they'd otherwise be silently dropped — inline them
    as $...$ / $$...$$ instead, since that's a representation LLMs already
    read natively.

    Accepts either a full doc ({"type": "doc", "content": [...]}, as on
    Question.content) or a bare node list (as on GroundTruthBox.content —
    see _extract_ground_truth_box_contents, which stores just the box's
    inner `content` array, not a wrapping doc node)."""
    lines = []

    def walk(node):
        if isinstance(node, list):
            for child in node:
                walk(child)
            return
        if not isinstance(node, dict):
            return
        t = node.get("type")
        if t == "text":
            lines.append(node.get("text", ""))
        elif t == "equation":
            latex = (node.get("attrs") or {}).get("latex", "")
            if latex:
                delim = "$$" if (node.get("attrs") or {}).get("display") else "$"
                lines.append(f"{delim}{latex}{delim}")
        for child in node.get("content", []) or []:
            walk(child)
        if t in ("paragraph", "heading"):
            lines.append("\n")

    walk(tiptap_doc or {})
    return "".join(lines).strip()


def extract_image_ids(tiptap_doc) -> list[str]:
    """Collect UploadedImage ids referenced by inline <image> nodes in a
    Tiptap doc or bare node list (see extract_plain_text) — src is
    ".../api/images/{id}", so the id is the last path segment."""
    ids = []

    def walk(node):
        if isinstance(node, list):
            for child in node:
                walk(child)
            return
        if not isinstance(node, dict):
            return
        if node.get("type") == "image":
            src = (node.get("attrs") or {}).get("src", "")
            img_id = src.rstrip("/").rsplit("/", 1)[-1]
            if img_id:
                ids.append(img_id)
        for child in node.get("content", []) or []:
            walk(child)

    walk(tiptap_doc or {})
    return ids
