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
from dataclasses import dataclass, field

from services.llm_provider import LLMProvider, extract_image_ids, extract_plain_text

logger = logging.getLogger(__name__)

GRADING_SYSTEM_PROMPT = """You are marking a handwritten exam answer.

You are given the question, the official model answer, and images of what \
the student actually wrote. Award a mark out of the stated maximum.

Mark the reasoning, not the handwriting. Award partial credit for work \
that is correct as far as it goes. A different but mathematically valid \
method earns full marks. Ignore untidiness, crossings-out and spelling.

If the images are unreadable, or show no attempt at all, say so rather \
than guessing at a mark.

Reply in exactly this format and nothing else:

SCORE: <a number from 0 to the maximum, or UNREADABLE>
FEEDBACK: <one or two sentences addressed to the student>
"""


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
