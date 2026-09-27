"""
Grading runs on a student's phone.

The phone marks each answer box itself and posts the results in one
call. This file is the second writer of AnswerGrade rows, beside
grading_runner.grade_submission, and writes the same columns. It does
not change grading_runner; it reuses its helpers.

A run is a lease. Starting one records `on_device_started_at` and a
token; posting with that token saves the marks. A run that has not
finished within ON_DEVICE_LEASE_MINUTES, fallback included, is marked
failed, so the teacher's Grade button works again and the phone can
start over.

Times are naive UTC, as the columns are `timestamp without time zone`.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy.orm import Session

from config import settings
from database import SessionLocal
from models import AnswerBox, AnswerGrade, Course, Question, Submission, User
from services.grading import AnswerToGrade, grade_one
from services.grading_runner import (
    MAX_CONCURRENT_CALLS,
    build_grading_items,
    protected_answer_box_ids,
    submission_totals,
)
from services.llm_provider import get_provider
from services.notify import notify

logger = logging.getLogger(__name__)

PROVIDER_ON_DEVICE = "on_device"
PROVIDER_FALLBACK = "self_hosted"

# The row state of a box waiting for the server's re-mark. Pending is
# this reason, no mark, not flagged for review, on a posted run.
AWAITING_REMARK = "Awaiting server re-mark"
FALLBACK_UNAVAILABLE = "Fallback unavailable"
REMARK_DID_NOT_FINISH = "Server re-mark did not finish"
PHONE_NEEDS_REVIEW = "The phone could not mark this answer"
BLANK_FEEDBACK = "Nothing was written in this answer box."

LEASE_EXPIRED_ERROR = (
    "On-device grading didn't finish in time. Grade it on the website, "
    "or ask the student to reopen the app."
)

# How often the background sweeper looks for expired runs.
SWEEP_INTERVAL_SECONDS = 60


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def lease() -> timedelta:
    return timedelta(minutes=settings.ON_DEVICE_LEASE_MINUTES)


def lease_expires_at(sub: Submission) -> datetime | None:
    if sub.on_device_started_at is None:
        return None
    return sub.on_device_started_at + lease()


def is_phone_run_active(sub: Submission) -> bool:
    return sub.grading_status == "grading" and sub.on_device_started_at is not None


def is_pending(grade: AnswerGrade, sub: Submission) -> bool:
    return (
        sub.grading_status == "grading"
        and sub.on_device_posted_at is not None
        and grade.score is None
        and not grade.needs_manual_review
        and grade.review_reason == AWAITING_REMARK
    )


# ── The pack ────────────────────────────────────────────────────────

def pack_items(db: Session, question: Question) -> dict[str, AnswerToGrade]:
    """
    build_grading_items' own output for this paper, keyed by box id.

    Called with a stand-in submission that has no crops, so the text,
    maximum and blocked reason are exactly what a server run would use.
    Nothing is re-derived here; the pack cannot drift from the grader.
    """
    stand_in = SimpleNamespace(id=None, question_id=question.id)
    return {item.answer_box_id: item for item in build_grading_items(db, stand_in)}


# ── Starting a run ──────────────────────────────────────────────────

def eligible_box_ids(db: Session, sub: Submission) -> tuple[list[str], list[str]]:
    """(every box minus the protected ones, the protected ones), in order."""
    boxes = (
        db.query(AnswerBox)
        .filter(AnswerBox.question_id == sub.question_id)
        .order_by(AnswerBox.order_index)
        .all()
    )
    protected = protected_answer_box_ids(db, sub)
    return (
        [b.id for b in boxes if b.id not in protected],
        [b.id for b in boxes if b.id in protected],
    )


def start_run(db: Session, sub: Submission) -> str:
    token = uuid.uuid4().hex
    sub.on_device_run_token = token
    sub.on_device_started_at = utcnow()
    sub.on_device_posted_at = None
    sub.grading_status = "grading"
    sub.grading_error = None
    db.commit()
    db.refresh(sub)
    return token


# ── Saving the phone's results ──────────────────────────────────────

def save_results(
    db: Session,
    sub: Submission,
    results: dict[str, "object"],
    fallback_ids: set[str],
    fallback_available: bool,
) -> list[str]:
    """
    Write one row per eligible box, as posted. Returns the box ids left
    pending for the server's re-mark.

    `results` maps box id to the posted OnDeviceBoxResult; the caller
    has already checked it covers every eligible box and nothing else.
    Blocked reasons are recomputed here: the client is not trusted.
    """
    question = db.query(Question).filter(Question.id == sub.question_id).first()
    items = pack_items(db, question) if question else {}
    boxes = {b.id: b for b in db.query(AnswerBox).filter(AnswerBox.question_id == sub.question_id)}
    existing = {
        g.answer_box_id: g
        for g in db.query(AnswerGrade).filter(AnswerGrade.submission_id == sub.id).all()
    }

    pending: list[str] = []
    for box_id, posted in results.items():
        box = boxes[box_id]
        item = items.get(box_id)
        blocked = item.blocked_reason if item else None

        grade = existing.get(box_id)
        if grade is None:
            grade = AnswerGrade(submission_id=sub.id, answer_box_id=box_id, max_score=box.points or 0)
            db.add(grade)

        grade.max_score = box.points or 0
        grade.provider = PROVIDER_ON_DEVICE
        grade.raw_response = posted.raw_response

        if blocked:
            grade.llm_score = None
            grade.llm_feedback = None
            grade.needs_manual_review = True
            grade.review_reason = blocked
        elif box_id in fallback_ids and fallback_available:
            grade.llm_score = None
            grade.llm_feedback = None
            grade.needs_manual_review = False
            grade.review_reason = AWAITING_REMARK
            pending.append(box_id)
        elif box_id in fallback_ids:
            grade.llm_score = None
            grade.llm_feedback = posted.feedback
            grade.needs_manual_review = True
            grade.review_reason = FALLBACK_UNAVAILABLE
        elif posted.outcome == "blank":
            grade.llm_score = 0.0
            grade.llm_feedback = BLANK_FEEDBACK
            grade.needs_manual_review = False
            grade.review_reason = None
        elif posted.outcome == "scored":
            grade.llm_score = posted.score
            grade.llm_feedback = posted.feedback
            grade.needs_manual_review = False
            grade.review_reason = None
        else:
            grade.llm_score = None
            grade.llm_feedback = posted.feedback
            grade.needs_manual_review = True
            grade.review_reason = posted.review_reason or PHONE_NEEDS_REVIEW

    sub.on_device_posted_at = utcnow()
    return pending


def finish_run(db: Session, sub: Submission) -> None:
    """Every box is terminal: mark the paper graded and tell the teacher.
    Does not commit. The token and posted time stay, so a repeat post of
    the same run is recognised and answered unchanged."""
    sub.grading_status = "graded"
    sub.grading_error = None
    sub.graded_at = utcnow()
    sub.on_device_started_at = None
    notify_teacher_graded(db, sub)


def notify_teacher_graded(db: Session, sub: Submission) -> None:
    question = db.query(Question).filter(Question.id == sub.question_id).first()
    course = db.query(Course).filter(Course.id == question.course_id).first() if question else None
    if course is None or course.teacher_id == sub.student_id:
        return
    student = db.query(User).filter(User.id == sub.student_id).first()
    name = student.display_name if student else "A student"
    paper = (question.title if question and question.title else "Untitled paper")

    db.flush()
    totals = submission_totals(db, sub.id)
    body = f"{totals['earned']:g} of {totals['max']}"
    if totals["needs_review_count"]:
        body += f", {totals['needs_review_count']} need review"

    notify(
        db,
        course.teacher_id,
        kind="graded_on_device",
        title=f"{name}: {paper} was marked on the phone",
        body=body,
        link=f"/submissions/{sub.id}",
    )


def _still_this_run(sub: Submission | None, token: str) -> bool:
    return (
        sub is not None
        and sub.on_device_run_token == token
        and is_phone_run_active(sub)
        and sub.on_device_posted_at is not None
    )


async def run_fallback(submission_id: str, token: str, box_ids: list[str]) -> None:
    """
    Re-mark only the pending boxes with the self-hosted model.

    Runs after the response, on its own session. Works from the server's
    own crops (build_grading_items), never touches any other box or a
    protected one, and discards its work if the run was superseded,
    expired or reset while it ran. When done the paper is graded and the
    teacher is told.
    """
    db = SessionLocal()
    try:
        sub = db.query(Submission).filter(Submission.id == submission_id).first()
        if not _still_this_run(sub, token):
            return

        wanted = set(box_ids) - protected_answer_box_ids(db, sub)
        items = [i for i in build_grading_items(db, sub) if i.answer_box_id in wanted]

        try:
            provider = get_provider(PROVIDER_FALLBACK)
            semaphore = asyncio.Semaphore(MAX_CONCURRENT_CALLS)

            async def _run(item: AnswerToGrade) -> tuple[AnswerToGrade, dict]:
                async with semaphore:
                    return item, await grade_one(provider, item)

            results = await asyncio.gather(*(_run(item) for item in items))
            failure = None
        except Exception as exc:  # noqa: BLE001 — recorded on the rows
            logger.exception("Fallback re-mark failed for submission %s", submission_id)
            results, failure = [], f"Server re-mark failed: {exc}"

        # The run may have ended while the model was working.
        db.expire_all()
        sub = db.query(Submission).filter(Submission.id == submission_id).first()
        if not _still_this_run(sub, token):
            return

        rows = {
            g.answer_box_id: g
            for g in db.query(AnswerGrade).filter(AnswerGrade.submission_id == sub.id).all()
        }
        done = set()
        for item, result in results:
            grade = rows.get(item.answer_box_id)
            if grade is None or grade.overridden_at is not None or grade.review_reason != AWAITING_REMARK:
                continue
            grade.max_score = item.max_score
            grade.llm_score = result["score"]
            grade.llm_feedback = result["feedback"]
            grade.raw_response = result["raw"]
            grade.provider = PROVIDER_FALLBACK
            grade.needs_manual_review = result["needs_manual_review"]
            grade.review_reason = result["review_reason"]
            done.add(item.answer_box_id)

        # Anything still waiting (a failed call, a box that vanished)
        # goes to the teacher rather than staying pending for ever.
        for box_id in wanted - done:
            grade = rows.get(box_id)
            if grade is not None and grade.review_reason == AWAITING_REMARK:
                grade.needs_manual_review = True
                grade.review_reason = failure or REMARK_DID_NOT_FINISH

        finish_run(db, sub)
        db.commit()
    except Exception:  # noqa: BLE001 — nowhere to propagate to; the lease sweeper recovers
        logger.exception("Fallback task crashed for submission %s", submission_id)
        db.rollback()
    finally:
        db.close()


# ── Expiry ──────────────────────────────────────────────────────────

def expire_stale_runs(db: Session, submission_id: str | None = None, now: datetime | None = None) -> int:
    """
    Mark every phone run older than the lease as failed. Returns how many.

    Covers a phone that never posted and a fallback lost to a server
    restart alike. Boxes still waiting for a re-mark go to teacher
    review. The token is cleared, so a late post gets 409 and the app
    starts again. Called by the sweeper and lazily by the routes, so
    correctness never depends on the loop running.
    """
    cutoff = (now or utcnow()) - lease()
    query = db.query(Submission).filter(
        Submission.grading_status == "grading",
        Submission.on_device_started_at.isnot(None),
        Submission.on_device_started_at < cutoff,
    )
    if submission_id is not None:
        query = query.filter(Submission.id == submission_id)

    expired = query.all()
    for sub in expired:
        for grade in db.query(AnswerGrade).filter(
            AnswerGrade.submission_id == sub.id,
            AnswerGrade.review_reason == AWAITING_REMARK,
            AnswerGrade.llm_score.is_(None),
        ):
            grade.needs_manual_review = True
            grade.review_reason = REMARK_DID_NOT_FINISH
        sub.grading_status = "failed"
        sub.grading_error = LEASE_EXPIRED_ERROR
        sub.on_device_run_token = None
        sub.on_device_started_at = None
        sub.on_device_posted_at = None

    if expired:
        db.commit()
    return len(expired)


def sweep_once() -> int:
    db = SessionLocal()
    try:
        return expire_stale_runs(db)
    finally:
        db.close()


async def sweep_forever(interval: float = SWEEP_INTERVAL_SECONDS) -> None:
    """The background sweeper started with the app (main.py)."""
    while True:
        try:
            count = await asyncio.to_thread(sweep_once)
            if count:
                logger.info("Expired %d on-device grading run(s)", count)
        except Exception:  # noqa: BLE001 — a bad sweep must not kill the loop
            logger.exception("On-device sweep failed")
        await asyncio.sleep(interval)
