"""
File-serving endpoints — images, crops and PDFs are read from the database
so the app can run on a read-only filesystem.

Component-1 served all of these unauthenticated, which was fine for a
single-user test harness. Here they carry real student work, so every
route resolves the file back to its course and checks the caller against
it: the course's teacher, or the student who made the submission.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from database import get_db
from models import Course, CropImage, Question, Submission, SubmissionImage, UploadedImage, User
from security import get_current_user

router = APIRouter(tags=["files"])


def _assert_owns_question(question_id: str, db: Session, user: User) -> None:
    question = db.query(Question).filter(Question.id == question_id).first()
    if question is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if user.role == "admin":
        return
    course = db.query(Course).filter(Course.id == question.course_id).first()
    if course is None or course.teacher_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")


def _assert_can_read_submission(submission_id: str, db: Session, user: User) -> Submission:
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    if submission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if user.role == "admin" or submission.student_id == user.id:
        return submission

    question = db.query(Question).filter(Question.id == submission.question_id).first()
    course = (
        db.query(Course).filter(Course.id == question.course_id).first() if question else None
    )
    if course is None or course.teacher_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    return submission


@router.get("/images/{image_id}")
def get_uploaded_image(
    image_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    img = db.query(UploadedImage).filter(UploadedImage.id == image_id).first()
    if not img:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")

    _assert_owns_question(img.question_id, db, user)

    headers = {}
    if img.filename:
        # inline (not attachment) — the <img> embedded in the editor should
        # still render normally; this only supplies the real filename for
        # "Save Image As", since the URL is an opaque id with no extension.
        safe_name = img.filename.replace('"', "'").replace("\n", "").replace("\r", "")
        headers["Content-Disposition"] = f'inline; filename="{safe_name}"'
    return Response(content=img.data, media_type=img.content_type or "image/png", headers=headers)


@router.get("/submissions/{submission_id}/images/{page_index}")
def get_submission_image(
    submission_id: str,
    page_index: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _assert_can_read_submission(submission_id, db, user)

    img = (
        db.query(SubmissionImage)
        .filter(
            SubmissionImage.submission_id == submission_id,
            SubmissionImage.page_index == page_index,
        )
        .first()
    )
    if not img:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission image not found")
    return Response(content=img.data, media_type=img.content_type or "image/jpeg")


@router.get("/crops/{submission_id}/{answer_box_id}")
def get_crop_image(
    submission_id: str,
    answer_box_id: str,
    part: int = 0,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _assert_can_read_submission(submission_id, db, user)

    crop = (
        db.query(CropImage)
        .filter(
            CropImage.submission_id == submission_id,
            CropImage.answer_box_id == answer_box_id,
            CropImage.part == part,
        )
        .first()
    )
    if not crop:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Crop not found")
    return Response(content=crop.data, media_type=crop.content_type or "image/png")
