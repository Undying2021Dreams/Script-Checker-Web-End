"""
Assembles grading work from the database and records the results.

Kept apart from services/grading.py so the pairing, prompt and parsing
stay testable without a database, and this file stays about persistence.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from models import (
    AnswerBox,
    AnswerGrade,
    CropImage,
    GroundTruthBox,
    GroundTruthImage,
    Question,
    Submission,
)
from services.grading import (
    AnswerToGrade,
    grade_one,
    pair_answer_boxes_with_ground_truth,
    question_text_by_ground_truth_box,
)
from services.llm_provider import LLMProvider, extract_plain_text

logger = logging.getLogger(__name__)

# A paper's worth of answers at once is fine; a whole class is not. Bound
# the fan-out so one run can't open hundreds of sockets to the model host
# (the self-hosted one is a single GPU notebook and will simply fall over).
MAX_CONCURRENT_CALLS = 4


def build_grading_items(db: Session, submission: Submission) -> list[AnswerToGrade]:
    question = db.query(Question).filter(Question.id == submission.question_id).first()
    if question is None:
        return []

    pairing = pair_answer_boxes_with_ground_truth(question.content)
    question_text_by_gt = question_text_by_ground_truth_box(question.content)
    whole_paper_text = extract_plain_text(question.content or {})

    gt_boxes = {b.id: b for b in question.ground_truth_boxes}

    crops_by_box: dict[str, list[CropImage]] = {}
    for crop in (
        db.query(CropImage)
        .filter(CropImage.submission_id == submission.id)
        .order_by(CropImage.part)
        .all()
    ):
        crops_by_box.setdefault(crop.answer_box_id, []).append(crop)

    items: list[AnswerToGrade] = []
    for box in sorted(question.answer_boxes, key=lambda b: b.order_index):
        gt_ids = [gt_id for gt_id in pairing.get(box.id, []) if gt_id in gt_boxes]
        paired: list[GroundTruthBox] = [gt_boxes[gt_id] for gt_id in gt_ids]

        blocked = None
        if box.points is None:
            # What the part is worth was never decided — the marking
            # scheme stated no figure and nobody set one by hand. Marking
            # it out of some assumed number is how a ten-mark scheme came
            # to be marked out of one, so it waits for a human instead.
            blocked = "No marks set for this part — give it a marking scheme, or set them by hand"
        elif not paired:
            # Nothing to mark against. Recorded for a human rather than
            # guessed at — an invented mark is worse than an obvious gap.
            blocked = "No model answer is paired with this answer box"

        # A box can be marked against several model answers at once, when
        # the paper asks a few sub-questions and leaves one space for all
        # the working. Their text and images are concatenated in document
        # order so the marking scheme the teacher wrote for each part
        # reaches the model with the part it belongs to.
        gt_images: list[tuple[bytes, str]] = []
        for gt_box in paired:
            for img in (
                db.query(GroundTruthImage)
                .filter(GroundTruthImage.ground_truth_box_id == gt_box.id)
                .order_by(GroundTruthImage.page_index)
                .all()
            ):
                if img.data:
                    gt_images.append((bytes(img.data), img.content_type or "image/png"))

        ground_truth_text = "\n\n".join(
            text
            for text in (extract_plain_text(gt_box.content or {}) for gt_box in paired)
            if text.strip()
        )
        question_text = "\n\n".join(
            text
            for text in (question_text_by_gt.get(gt_id, "") for gt_id in gt_ids)
            if text.strip()
        )

        items.append(
            AnswerToGrade(
                answer_box_id=box.id,
                label=box.label or "",
                max_score=box.points or 0,
                question_text=question_text or whole_paper_text,
                ground_truth_text=ground_truth_text,
                ground_truth_images=gt_images,
                crops=[
                    (bytes(c.data), c.content_type or "image/png")
                    for c in crops_by_box.get(box.id, [])
                    if c.data
                ],
                blocked_reason=blocked,
            )
        )

    return items


async def grade_submission(
    db: Session,
    submission: Submission,
    provider: LLMProvider,
    provider_name: str,
) -> Submission:
    """
    Mark every answer box on a submission and persist the results.

    Re-grading replaces the model's marks but leaves any teacher override
    untouched — a human decision shouldn't be silently undone by rerunning
    the machine.
    """
    items = build_grading_items(db, submission)
    if not items:
        submission.grading_status = "failed"
        submission.grading_error = "Submission's question has no answer boxes"
        db.commit()
        return submission

    submission.grading_status = "grading"
    submission.grading_error = None
    db.commit()

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_CALLS)

    async def _run(item: AnswerToGrade) -> tuple[AnswerToGrade, dict]:
        async with semaphore:
            return item, await grade_one(provider, item)

    try:
        results = await asyncio.gather(*(_run(item) for item in items))
    except Exception as exc:  # noqa: BLE001 — recorded on the submission
        logger.exception("Grading run failed for submission %s", submission.id)
        submission.grading_status = "failed"
        submission.grading_error = str(exc)
        db.commit()
        return submission

    existing = {
        g.answer_box_id: g
        for g in db.query(AnswerGrade).filter(AnswerGrade.submission_id == submission.id).all()
    }

    for item, result in results:
        grade = existing.get(item.answer_box_id)
        if grade is None:
            grade = AnswerGrade(
                submission_id=submission.id,
                answer_box_id=item.answer_box_id,
                max_score=item.max_score,
            )
            db.add(grade)

        grade.max_score = item.max_score
        grade.llm_score = result["score"]
        grade.llm_feedback = result["feedback"]
        grade.raw_response = result["raw"]
        grade.provider = provider_name
        grade.needs_manual_review = result["needs_manual_review"]
        grade.review_reason = result["review_reason"]

    submission.grading_status = "graded"
    submission.graded_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(submission)
    return submission


def submission_totals(db: Session, submission_id: str) -> dict:
    """
    Marks for one submission, summed from the rows rather than stored.

    Nothing is denormalized, so a total can't drift away from the marks it
    came from after an override.
    """
    grades = db.query(AnswerGrade).filter(AnswerGrade.submission_id == submission_id).all()
    scored = [g for g in grades if g.score is not None]
    return {
        "earned": sum(g.score for g in scored),
        "max": sum(g.max_score for g in grades),
        "graded_count": len(scored),
        "total_count": len(grades),
        "needs_review_count": sum(1 for g in grades if g.needs_manual_review),
    }
