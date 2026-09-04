"""
The student's side of a course.

Deliberately a separate router rather than relaxed checks on the
authoring one. A Question's `content` holds the model answers inline as
groundTruthBox nodes, and QuestionOut carries ground_truth_boxes, so
loosening those routes would hand students the answer key. Nothing here
returns document content: the paper reaches a student as the rendered
PDF, which the renderer builds with the groundTruthBox nodes skipped.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from database import get_db
from models import AnswerBox, Course, Enrollment, Question, QuestionPdf, Submission, User
from schemas import StudentAssignment
from security import get_current_user
from services.grading_runner import submission_totals

router = APIRouter(prefix="/student", tags=["student"])


def _assert_enrolled(course_id: str, db: Session, user: User) -> Course:
    course = db.query(Course).filter(Course.id == course_id).first()
    if course is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found")

    if user.role == "admin" or course.teacher_id == user.id:
        return course

    enrolled = (
        db.query(Enrollment.id)
        .filter(Enrollment.course_id == course_id, Enrollment.student_id == user.id)
        .first()
    )
    if not enrolled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found")
    return course


def _my_latest_submission(question_id: str, db: Session, user: User) -> Submission | None:
    return (
        db.query(Submission)
        .filter(Submission.question_id == question_id, Submission.student_id == user.id)
        .order_by(Submission.created_at.desc())
        .first()
    )


def _to_assignment(q: Question, db: Session, user: User) -> StudentAssignment:
    total_marks = sum(
        points for (points,) in db.query(AnswerBox.points).filter(AnswerBox.question_id == q.id).all()
    )
    sub = _my_latest_submission(q.id, db, user)

    earned = max_score = None
    if sub is not None and sub.released_at is not None:
        totals = submission_totals(db, sub.id)
        earned, max_score = totals["earned"], totals["max"]

    return StudentAssignment(
        question_id=q.id,
        course_id=q.course_id,
        total_marks=total_marks,
        page_count=q.page_count,
        finalized_at=q.finalized_at,
        submission_id=sub.id if sub else None,
        # A student is told their work is being marked, but not the marks
        # themselves until the teacher releases them.
        submission_status=sub.grading_status if sub else None,
        released=bool(sub and sub.released_at),
        earned=earned,
        max_score=max_score,
    )


@router.get("/assignments", response_model=list[StudentAssignment])
def list_assignments(
    course_id: str = Query(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Papers set for a course, with this student's own progress on each.

    Only finalized questions appear — a draft is a teacher's work in
    progress and has no printable paper yet.
    """
    _assert_enrolled(course_id, db, user)

    questions = (
        db.query(Question)
        .filter(Question.course_id == course_id, Question.state == "finalized")
        .order_by(Question.finalized_at.desc())
        .all()
    )
    return [_to_assignment(q, db, user) for q in questions]


@router.get("/assignments/{question_id}/pdf")
def get_assignment_pdf(
    question_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    The question paper.

    Safe to hand a student because the renderer omits groundTruthBox
    nodes, so the printed page carries the questions and answer boxes but
    never the model answers.
    """
    q = db.query(Question).filter(Question.id == question_id).first()
    if q is None or q.state != "finalized":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")

    _assert_enrolled(q.course_id, db, user)

    pdf = db.query(QuestionPdf).filter(QuestionPdf.question_id == question_id).first()
    if pdf is None or not pdf.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No paper has been generated for this assignment")

    return Response(
        content=bytes(pdf.data),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="paper-{question_id[:8]}.pdf"'},
    )
