import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from database import SessionLocal, get_db
from models import AnswerBox, AnswerGrade, Course, Enrollment, Question, Submission, User
from schemas import (
    AnswerGradeOut,
    BulkGradeStarted,
    BulkGradeRequest,
    GradeOverride,
    GradeRunRequest,
    SubmissionGradesOut,
)
from ratelimit import BULK_LLM_LIMIT, LLM_LIMIT, limiter
from security import get_current_user
from services.grading_runner import grade_submission, submission_totals
from services.llm_provider import get_provider

logger = logging.getLogger(__name__)

router = APIRouter(tags=["grading"])


def _get_submission_for_teacher(submission_id: str, db: Session, user: User) -> Submission:
    """Grading and overriding are the teacher's, never the student's."""
    sub = db.query(Submission).filter(Submission.id == submission_id).first()
    if sub is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")

    if user.role == "admin":
        return sub

    question = db.query(Question).filter(Question.id == sub.question_id).first()
    course = db.query(Course).filter(Course.id == question.course_id).first() if question else None
    if course is None or course.teacher_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")
    return sub


def _grades_payload(db: Session, sub: Submission, *, include_feedback: bool = True) -> SubmissionGradesOut:
    grades = (
        db.query(AnswerGrade, AnswerBox)
        .join(AnswerBox, AnswerBox.id == AnswerGrade.answer_box_id)
        .filter(AnswerGrade.submission_id == sub.id)
        .order_by(AnswerBox.order_index)
        .all()
    )
    totals = submission_totals(db, sub.id)

    return SubmissionGradesOut(
        submission_id=sub.id,
        question_id=sub.question_id,
        student_id=sub.student_id,
        grading_status=sub.grading_status,
        grading_error=sub.grading_error,
        released=sub.released_at is not None,
        earned=totals["earned"],
        max_score=totals["max"],
        needs_review_count=totals["needs_review_count"],
        grades=[
            AnswerGradeOut(
                answer_box_id=g.answer_box_id,
                label=box.label or "",
                order_index=box.order_index,
                max_score=g.max_score,
                score=g.score,
                llm_score=g.llm_score,
                override_score=g.override_score,
                feedback=(g.override_feedback or g.llm_feedback) if include_feedback else None,
                provider=g.provider,
                needs_manual_review=g.needs_manual_review,
                review_reason=g.review_reason,
            )
            for g, box in grades
        ],
    )


async def _grade_in_background(submission_id: str, provider_name: str) -> None:
    """
    Runs after the response is sent, on its own session.

    The request's session is closed by then, so this opens and closes its
    own. Any failure is recorded on the submission rather than raised —
    there's no client left to receive it.
    """
    db = SessionLocal()
    try:
        sub = db.query(Submission).filter(Submission.id == submission_id).first()
        if sub is None:
            return
        await grade_submission(db, sub, get_provider(provider_name), provider_name)
    except Exception as exc:  # noqa: BLE001 — nowhere to propagate to
        logger.exception("Background grading failed for %s", submission_id)
        sub = db.query(Submission).filter(Submission.id == submission_id).first()
        if sub is not None:
            sub.grading_status = "failed"
            sub.grading_error = str(exc)
            db.commit()
    finally:
        db.close()


@router.post("/submissions/{submission_id}/grade", response_model=SubmissionGradesOut)
@limiter.limit(LLM_LIMIT)
def run_grading(
    request: Request,
    submission_id: str,
    body: GradeRunRequest,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Start marking a submission and return immediately.

    Grading runs in the background because each answer box is its own
    model call, and the self-hosted provider allows up to 120s per call —
    a paper with several parts would otherwise hold an HTTP request open
    far past any sensible timeout. Poll GET .../grades for progress.

    This is the expensive endpoint — every call costs real money or GPU
    time — so it's teacher-only. Marks are advisory and stay invisible to
    the student until released.

    Note the tradeoff of using in-process background work rather than a
    durable queue: a restart mid-run loses that run (already-written marks
    survive) and it has to be triggered again. That's deliberate — a
    managed Redis is a real cost on a fixed student credit, and this is a
    demo deployment. arq is the upgrade path if that changes.
    """
    sub = _get_submission_for_teacher(submission_id, db, user)

    if sub.grading_status in ("queued", "grading"):
        raise HTTPException(status.HTTP_409_CONFLICT, "This submission is already being graded")

    # Fail before queueing if the provider isn't usable, so the caller
    # gets a real error instead of a background failure they must poll for.
    try:
        get_provider(body.provider)
    except (ValueError, ImportError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    sub.grading_status = "queued"
    sub.grading_error = None
    db.commit()
    db.refresh(sub)

    background.add_task(_grade_in_background, sub.id, body.provider)
    return _grades_payload(db, sub)


async def _grade_many_in_background(submission_ids: list[str], provider_name: str) -> None:
    """
    Mark a batch, one submission after another.

    Deliberately sequential. The self-hosted provider is a single GPU
    process behind a tunnel, and firing concurrent requests at it fails
    outright rather than queueing. Answer boxes within one submission are
    already run a few at a time, which is as much concurrency as it takes.
    """
    provider = get_provider(provider_name)
    for submission_id in submission_ids:
        db = SessionLocal()
        try:
            sub = db.query(Submission).filter(Submission.id == submission_id).first()
            if sub is None:
                continue
            await grade_submission(db, sub, provider, provider_name)
        except Exception as exc:  # noqa: BLE001 — one failure mustn't stop the batch
            logger.exception("Bulk grading failed for %s", submission_id)
            sub = db.query(Submission).filter(Submission.id == submission_id).first()
            if sub is not None:
                sub.grading_status = "failed"
                sub.grading_error = str(exc)
                db.commit()
        finally:
            db.close()


@router.post("/questions/{question_id}/grade-all", response_model=BulkGradeStarted)
@limiter.limit(BULK_LLM_LIMIT)
def grade_all_submissions(
    request: Request,
    question_id: str,
    body: BulkGradeRequest,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Mark every submission on a paper in one go.

    Already-graded work is skipped unless asked for, so a rerun after a
    few new submissions arrive doesn't spend calls re-marking the rest.
    Teacher overrides survive a re-grade either way.
    """
    question = db.query(Question).filter(Question.id == question_id).first()
    if question is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")

    course = db.query(Course).filter(Course.id == question.course_id).first()
    if user.role != "admin" and (course is None or course.teacher_id != user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Question not found")

    try:
        get_provider(body.provider)
    except (ValueError, ImportError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    submissions = db.query(Submission).filter(Submission.question_id == question_id).all()

    to_grade, skipped = [], 0
    for sub in submissions:
        # Never restart something already running, and leave graded work
        # alone unless the teacher asked to redo it.
        if sub.grading_status in ("queued", "grading"):
            skipped += 1
            continue
        if sub.grading_status == "graded" and not body.include_graded:
            skipped += 1
            continue
        to_grade.append(sub)

    for sub in to_grade:
        sub.grading_status = "queued"
        sub.grading_error = None
    db.commit()

    if to_grade:
        background.add_task(
            _grade_many_in_background, [s.id for s in to_grade], body.provider
        )

    return BulkGradeStarted(queued=len(to_grade), skipped=skipped)


@router.get("/submissions/{submission_id}/grades", response_model=SubmissionGradesOut)
def get_grades(
    submission_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Marks for a submission.

    A student sees their own only once the teacher has released them —
    an unreviewed machine mark is not a grade yet.
    """
    sub = db.query(Submission).filter(Submission.id == submission_id).first()
    if sub is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")

    if user.role != "admin":
        question = db.query(Question).filter(Question.id == sub.question_id).first()
        course = db.query(Course).filter(Course.id == question.course_id).first() if question else None
        is_teacher = course is not None and course.teacher_id == user.id

        if not is_teacher:
            if sub.student_id != user.id:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")
            if sub.released_at is None:
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN,
                    "Your marks for this submission haven't been released yet",
                )

    return _grades_payload(db, sub)


@router.patch("/submissions/{submission_id}/grades/{answer_box_id}", response_model=SubmissionGradesOut)
def override_grade(
    submission_id: str,
    answer_box_id: str,
    body: GradeOverride,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Set a teacher's mark for one answer box.

    The model's own score is kept alongside rather than replaced, so a
    disputed mark can still be traced back to what was proposed and what a
    human decided.
    """
    sub = _get_submission_for_teacher(submission_id, db, user)

    grade = (
        db.query(AnswerGrade)
        .filter(AnswerGrade.submission_id == sub.id, AnswerGrade.answer_box_id == answer_box_id)
        .one_or_none()
    )
    if grade is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No mark for that answer box")

    if body.score is not None and (body.score < 0 or body.score > grade.max_score):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Score must be between 0 and {grade.max_score}",
        )

    grade.override_score = body.score
    grade.override_feedback = body.feedback
    grade.overridden_by = user.id
    grade.overridden_at = datetime.now(timezone.utc)
    # A human has looked at it, so it's no longer waiting on one.
    if body.score is not None:
        grade.needs_manual_review = False

    db.commit()
    return _grades_payload(db, sub)


@router.post("/submissions/{submission_id}/release", response_model=SubmissionGradesOut)
def release_grades(
    submission_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Make this submission's marks visible to the student who made it."""
    sub = _get_submission_for_teacher(submission_id, db, user)
    if sub.grading_status != "graded":
        raise HTTPException(status.HTTP_409_CONFLICT, "Grade the submission before releasing it")

    sub.released_at = datetime.now(timezone.utc)
    db.commit()
    return _grades_payload(db, sub)


@router.post("/submissions/{submission_id}/unrelease", response_model=SubmissionGradesOut)
def unrelease_grades(
    submission_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Withdraw released marks — e.g. a mistake spotted after publishing."""
    sub = _get_submission_for_teacher(submission_id, db, user)
    sub.released_at = None
    db.commit()
    return _grades_payload(db, sub)


@router.get("/courses/{course_id}/gradebook")
def gradebook(
    course_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Every student's marks across every question in a course."""
    course = db.query(Course).filter(Course.id == course_id).first()
    if course is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found")
    if user.role != "admin" and course.teacher_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the course's teacher can see the gradebook")

    questions = (
        db.query(Question)
        .filter(Question.course_id == course_id)
        .order_by(Question.created_at)
        .all()
    )
    question_ids = [q.id for q in questions]

    students = (
        db.query(User)
        .join(Enrollment, Enrollment.student_id == User.id)
        .filter(Enrollment.course_id == course_id)
        .order_by(User.display_name)
        .all()
    )

    submissions = (
        db.query(Submission).filter(Submission.question_id.in_(question_ids)).all()
        if question_ids
        else []
    )
    by_student: dict[tuple[str, str], Submission] = {}
    for sub in submissions:
        if sub.student_id:
            # Latest submission wins if a student submitted more than once.
            key = (sub.student_id, sub.question_id)
            current = by_student.get(key)
            if current is None or sub.created_at > current.created_at:
                by_student[key] = sub

    rows = []
    for student in students:
        cells = []
        for question in questions:
            sub = by_student.get((student.id, question.id))
            if sub is None:
                cells.append({"question_id": question.id, "submission_id": None, "status": "no_submission"})
                continue
            totals = submission_totals(db, sub.id)
            cells.append({
                "question_id": question.id,
                "submission_id": sub.id,
                "status": sub.grading_status,
                "released": sub.released_at is not None,
                "earned": totals["earned"],
                "max": totals["max"],
                "needs_review_count": totals["needs_review_count"],
            })
        rows.append({
            "student_id": student.id,
            "display_name": student.display_name,
            "email": student.email,
            "cells": cells,
        })

    return {
        "course_id": course_id,
        "questions": [
            {"id": q.id, "title": q.title, "state": q.state, "created_at": q.created_at}
            for q in questions
        ],
        "rows": rows,
    }
