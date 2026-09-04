"""
Marking a submission: pair each extracted answer with the model answer it
belongs to, ask an LLM for a mark, and record it.

The pairing is the load-bearing part. A Question is a *paper*, and its
Tiptap doc holds several sub-questions in order:

    [question text] -> answerBox      (student writes here, printed)
                    -> groundTruthBox (model answer, never printed)
    [question text] -> answerBox -> groundTruthBox ...

answerBox and groundTruthBox have separate ids and no foreign key between
them, so the only thing that says "this answer belongs to that model
answer" is their position in the document. Everything else in the codebase
already reads the doc that way — doc_renderer's up_to_gt_box_id,
_question_nodes_by_gt_box_id, and the author page's preview grid all
segment on groundTruthBox — so this does too rather than inventing a
second, conflicting convention.
"""

from __future__ import annotations

import logging
import re
import io
from dataclasses import dataclass, field

from services.llm_provider import LLMProvider, extract_image_ids, extract_plain_text

logger = logging.getLogger(__name__)

GRADING_SYSTEM_PROMPT = """You are marking a handwritten exam answer.

You are given the question, the official model answer, and images of what \
the student actually wrote.

FIRST, transcribe exactly what appears in the student's images. Copy only \
marks that are actually there. Do not complete, correct or infer any step. \
If the images contain no writing at all, the transcript is NOTHING WRITTEN.

THEN award a mark, based only on your own transcript.

Never credit a step that does not appear in your transcript. The question \
and model answer are given to you for comparison only — they are NOT the \
student's work, and reproducing them as if the student wrote them is a \
serious error.

If the transcript is NOTHING WRITTEN, the score is 0.
If there is writing but you cannot make it out, the score is UNREADABLE.

Otherwise mark the reasoning, not the handwriting: award partial credit \
for work that is correct as far as it goes, give full marks for a \
different but mathematically valid method, and ignore untidiness, \
crossings-out and spelling.

Reply in exactly this format and nothing else:

TRANSCRIPT: <what is actually written, or NOTHING WRITTEN>
SCORE: <a number from 0 to the maximum, or UNREADABLE>
FEEDBACK: <one or two sentences addressed to the student>
"""


# Fraction of a crop that must be markedly darker than the paper before we
# accept there is handwriting on it.
#
# Measured: a genuinely blank crop reads 0.0000% even when photographed
# grey or full of scanner noise, while the faintest realistic answer — a
# short pencil "x = 3" — reads 0.20%. The gap is three orders of
# magnitude, so this sits far below the faintest writing rather than near
# it. Erring the other way costs a student an unfair zero; erring this way
# costs one wasted model call.
BLANK_INK_FRACTION = 0.0002


def looks_blank(image_bytes: bytes) -> bool:
    """
    Whether a crop has essentially no ink on it.

    Asked here rather than of the model. Tested against a real 7B vision
    model, a blank crop is not recognised as blank at all: shown the
    question and model answer for comparison, it reproduces them as though
    the student had written them and awards partial credit — inventing
    marks for work that does not exist. Whether a region contains ink is a
    question we can answer ourselves, exactly, so we do.

    Compares against the crop's own paper tone rather than pure white, so a
    grey photograph or a shadowed scan isn't read as covered in ink.
    """
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes)).convert("L")
    except Exception:  # noqa: BLE001 — an unopenable crop isn't ours to judge
        logger.warning("Could not inspect a crop for blankness; treating it as written on")
        return False

    # Trim the edge, which is usually the printed box border rather than
    # anything the student wrote.
    w, h = img.size
    if w > 20 and h > 20:
        m_x, m_y = int(w * 0.04), int(h * 0.04)
        img = img.crop((m_x, m_y, w - m_x, h - m_y))

    pixels = list(img.getdata())  # noqa: PIL deprecation — kept for Pillow <11 compat
    if not pixels:
        return True

    # The paper's own tone, taken high enough up the distribution to ignore
    # any writing present.
    paper = sorted(pixels)[int(len(pixels) * 0.9)]
    threshold = paper - 60
    ink = sum(1 for p in pixels if p < threshold)

    return (ink / len(pixels)) < BLANK_INK_FRACTION


@dataclass
class AnswerToGrade:
    """One answer box paired with the model answer it should be marked against."""

    answer_box_id: str
    label: str
    max_score: int
    question_text: str
    ground_truth_text: str
    ground_truth_images: list[tuple[bytes, str]] = field(default_factory=list)
    crops: list[tuple[bytes, str]] = field(default_factory=list)
    # Set when this can't be marked automatically; grading records it for
    # manual review instead of inventing a mark.
    blocked_reason: str | None = None


def pair_answer_boxes_with_ground_truth(content_doc: dict | None) -> dict[str, str | None]:
    """
    Map answer_box_id -> ground_truth_box_id, by document order.

    Each answerBox is paired with the next groundTruthBox that follows it,
    since the model answer is authored after the space the student writes
    in. An answerBox with no groundTruthBox after it maps to None — it
    can't be auto-marked, and the caller flags it rather than guessing.
    """
    pairing: dict[str, str | None] = {}
    if not isinstance(content_doc, dict):
        return pairing

    pending: list[str] = []
    for node in content_doc.get("content", []) or []:
        node_type = node.get("type")
        attrs = node.get("attrs") or {}

        if node_type == "answerBox":
            if attrs.get("id"):
                pending.append(attrs["id"])
        elif node_type == "groundTruthBox":
            gt_id = attrs.get("id")
            for answer_box_id in pending:
                pairing[answer_box_id] = gt_id
            pending = []

    # Trailing answer boxes with no model answer after them.
    for answer_box_id in pending:
        pairing[answer_box_id] = None

    return pairing


def question_text_by_ground_truth_box(content_doc: dict | None) -> dict[str, str]:
    """Sub-question text preceding each groundTruthBox, as plain text."""
    result: dict[str, str] = {}
    if not isinstance(content_doc, dict):
        return result

    buffer: list = []
    for node in content_doc.get("content", []) or []:
        node_type = node.get("type")
        if node_type == "groundTruthBox":
            gt_id = (node.get("attrs") or {}).get("id")
            if gt_id:
                result[gt_id] = extract_plain_text(buffer)
            buffer = []
            continue
        if node_type == "answerBox":
            continue
        buffer.append(node)

    return result


_SCORE_RE = re.compile(r"SCORE:\s*(.+)", re.IGNORECASE)
_FEEDBACK_RE = re.compile(r"FEEDBACK:\s*(.+)", re.IGNORECASE | re.DOTALL)
_TRANSCRIPT_RE = re.compile(r"TRANSCRIPT:\s*(.*?)(?=\n\s*SCORE:|$)", re.IGNORECASE | re.DOTALL)

# Phrasings a model reaches for when the page turns out to be empty.
_NOTHING_WRITTEN = re.compile(
    r"^\W*(nothing written|nothing|none|blank|empty|no writing|no answer|n/?a|-+)\W*$",
    re.IGNORECASE,
)


def parse_grading_response(text: str, max_score: int) -> dict:
    """
    Pull a mark out of the model's reply.

    Returns {score, feedback, unreadable, parse_error}. A reply that can't
    be parsed, or a score outside 0..max, is reported rather than coerced
    into a number — a wrong mark that looks confident is worse than an
    obvious "needs a human".
    """
    raw = (text or "").strip()
    feedback_match = _FEEDBACK_RE.search(raw)
    feedback = feedback_match.group(1).strip() if feedback_match else ""
    # FEEDBACK is last in the format, so strip anything the model added after.
    feedback = feedback.split("SCORE:")[0].strip()

    # A blank page must never earn marks. Tested against a real model, it
    # will happily "mark" an empty image by reproducing the model answer it
    # was shown for comparison and describing it as the student's work, so
    # the transcript is enforced here rather than trusted to the prompt.
    transcript_match = _TRANSCRIPT_RE.search(raw)
    transcript = transcript_match.group(1).strip() if transcript_match else None
    if transcript is not None and (not transcript or _NOTHING_WRITTEN.match(transcript)):
        return {
            "score": 0.0,
            "feedback": "Nothing was written in this answer box.",
            "unreadable": False,
            "parse_error": False,
        }

    score_match = _SCORE_RE.search(raw)
    if not score_match:
        return {"score": None, "feedback": feedback, "unreadable": False, "parse_error": True}

    score_text = score_match.group(1).strip().split("\n")[0].strip()
    if score_text.upper().startswith("UNREADABLE"):
        return {"score": None, "feedback": feedback, "unreadable": True, "parse_error": False}

    number = re.search(r"-?\d+(?:\.\d+)?", score_text)
    if not number:
        return {"score": None, "feedback": feedback, "unreadable": False, "parse_error": True}

    score = float(number.group(0))
    if score < 0 or score > max_score:
        logger.warning("Grading returned %s, outside 0..%s", score, max_score)
        return {"score": None, "feedback": feedback, "unreadable": False, "parse_error": True}

    return {"score": score, "feedback": feedback, "unreadable": False, "parse_error": False}


def build_user_message(item: AnswerToGrade) -> str:
    parts = [
        f"QUESTION:\n{item.question_text.strip() or '(not provided)'}",
        f"\nMODEL ANSWER:\n{item.ground_truth_text.strip() or '(provided as an image below)'}",
        f"\nMAXIMUM MARK: {item.max_score}",
    ]
    if item.label:
        parts.insert(0, f"Part: {item.label}")

    # Both the model answer and the student's work can arrive as images in
    # the same list, so the message has to say which is which — otherwise
    # the model can mark the answer key against itself.
    n_gt = len(item.ground_truth_images)
    n_crops = len(item.crops)
    if n_gt:
        parts.append(
            f"\nIMAGES: the first {n_gt} image(s) are the official model answer. "
            f"The remaining {n_crops} image(s) are the student's handwritten answer, "
            f"in order."
        )
    else:
        parts.append(f"\nIMAGES: {n_crops} image(s) of the student's handwritten answer, in order.")

    return "\n".join(parts)


async def grade_one(provider: LLMProvider, item: AnswerToGrade) -> dict:
    """
    Mark a single answer box.

    Never raises for an expected failure — a model that errors, returns
    nonsense, or is handed an unreadable scan produces a row flagged for
    manual review, so one bad answer can't sink a whole class's run.
    """
    if item.blocked_reason:
        return {
            "score": None, "feedback": None, "raw": None,
            "needs_manual_review": True, "review_reason": item.blocked_reason,
        }

    if not item.crops:
        return {
            "score": None, "feedback": None, "raw": None,
            "needs_manual_review": True,
            "review_reason": "No extracted answer image for this box",
        }

    # Settle blankness before spending a model call on it — the model
    # cannot be trusted to notice, and an unattempted answer is a real 0
    # rather than something needing review. The teacher sees the crop
    # beside this mark, so a misjudgement here is visible and one click to
    # override.
    if all(looks_blank(data) for data, _ in item.crops):
        return {
            "score": 0.0,
            "feedback": "Nothing was written in this answer box.",
            "raw": None,
            "needs_manual_review": False,
            "review_reason": None,
        }

    try:
        raw = await provider.complete(
            GRADING_SYSTEM_PROMPT,
            build_user_message(item),
            # Model answer first, student's work after — build_user_message
            # tells the model that's the order.
            item.ground_truth_images + item.crops,
        )
    except Exception as exc:  # noqa: BLE001 — surfaced on the row, not raised
        logger.exception("Grading call failed for box %s", item.answer_box_id)
        return {
            "score": None, "feedback": None, "raw": None,
            "needs_manual_review": True,
            "review_reason": f"Grading request failed: {exc}",
        }

    parsed = parse_grading_response(raw, item.max_score)
    if parsed["unreadable"]:
        return {
            "score": None, "feedback": parsed["feedback"] or None, "raw": raw,
            "needs_manual_review": True,
            "review_reason": "Model could not read the answer",
        }
    if parsed["parse_error"]:
        return {
            "score": None, "feedback": parsed["feedback"] or None, "raw": raw,
            "needs_manual_review": True,
            "review_reason": "Could not read a valid mark from the model's reply",
        }

    return {
        "score": parsed["score"], "feedback": parsed["feedback"], "raw": raw,
        "needs_manual_review": False, "review_reason": None,
    }
