"""
Submission upload + extraction endpoints.
"""

from __future__ import annotations

import io
import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models import Submission, SubmissionImage, CropImage, Question, Course, Enrollment, User
from schemas import (
    ExtractionResult,
    SubmissionSummary,
    TabletSubmission,
    GroupedSubmissionOut,
    GroupedAnswerBoxOut,
    AnswerPartOut,
)
from services.extractor import extract_page
from routers.questions import _question_to_dict
from security import get_current_user
from services.grading_runner import submission_totals

router = APIRouter(prefix="/submissions", tags=["submissions"])


def _get_question_for_submission(question_id: str, db: Session, user: User) -> Question:
    """
    A question the caller may submit against: one in a course they're
    enrolled in, or one they teach (a teacher scanning a stack of papers
    on their students' behalf is a normal flow).
    """
    q = db.query(Question).filter(Question.id == question_id).first()
    if not q:
        raise HTTPException(status_code=404, detail=f"Question {question_id} not found")

    if user.role == "admin":
        return q

    course = db.query(Course).filter(Course.id == q.course_id).first()
    if course is None:
        raise HTTPException(status_code=404, detail=f"Question {question_id} not found")
    if course.teacher_id == user.id:
        return q

    enrolled = (
        db.query(Enrollment.id)
        .filter(Enrollment.course_id == course.id, Enrollment.student_id == user.id)
        .first()
    )
    if not enrolled:
        raise HTTPException(status_code=404, detail=f"Question {question_id} not found")
    return q


def _get_submission_or_404(submission_id: str, db: Session, user: User) -> Submission:
    """A submission the caller may read: their own, or one in a course they teach."""
    sub = db.query(Submission).filter(Submission.id == submission_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail=f"Submission {submission_id} not found")

    if user.role == "admin" or sub.student_id == user.id:
        return sub

    q = db.query(Question).filter(Question.id == sub.question_id).first()
    course = db.query(Course).filter(Course.id == q.course_id).first() if q else None
    if course is None or course.teacher_id != user.id:
        raise HTTPException(status_code=404, detail=f"Submission {submission_id} not found")
    return sub


def _pdf_to_images(pdf_bytes: bytes) -> list[bytes]:
    try:
        from pdf2image import convert_from_bytes
        images = convert_from_bytes(pdf_bytes, dpi=settings.SUBMISSION_PDF_DPI, fmt="png")
        result = []
        for img in images:
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            result.append(buf.getvalue())
        return result
    except ImportError:
        raise HTTPException(status_code=500, detail="pdf2image not installed — cannot process PDF uploads")


def _tiff_to_images(tiff_bytes: bytes) -> list[bytes]:
    from PIL import Image as PILImage
    img = PILImage.open(io.BytesIO(tiff_bytes))
    result = []
    try:
        for i in range(1000):
            img.seek(i)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            result.append(buf.getvalue())
    except EOFError:
        pass
    return result


def _store_page_data(
    db: Session,
    submission_id: str,
    page_index: int,
    image_bytes: bytes,
    content_type: str,
    page_result: dict,
    question_dict: dict | None = None,
):
    """Persist one page's raw image + crops. If this page_index was
    already submitted before (a page can now be resubmitted — see
    create_submission's submission_id param), clears out whatever was
    stored for it first, so a retaken photo replaces the old one instead
    of piling up alongside it.

    Clears every (answer_box_id, part) pair the QUESTION says belongs to
    this page — not just the ones the fresh extraction happened to
    return crops for — so if a retake extracts worse than before (e.g.
    fewer markers detected this time), stale crops from the earlier,
    better attempt don't linger and silently outlive the failed retry.
    """
    db.query(SubmissionImage).filter(
        SubmissionImage.submission_id == submission_id,
        SubmissionImage.page_index == page_index,
    ).delete(synchronize_session=False)

    if question_dict is not None:
        from services.extractor import get_page_segments
        for box, part_idx, _bbox in get_page_segments(question_dict, page_index):
            db.query(CropImage).filter(
                CropImage.submission_id == submission_id,
                CropImage.answer_box_id == box["id"],
                CropImage.part == part_idx,
            ).delete(synchronize_session=False)

    db_img = SubmissionImage(
        submission_id=submission_id,
        page_index=page_index,
        content_type=content_type,
        data=image_bytes,
    )
    db.add(db_img)

    for crop in page_result.get("crops", []):
        if "data" in crop:
            db_crop = CropImage(
                submission_id=submission_id,
                answer_box_id=crop["answer_box_id"],
                part=crop.get("part", 0),
                content_type=crop.get("content_type", "image/png"),
                data=crop["data"],
                qr_check=crop.get("qr_check"),
                warped_bbox=crop.get("warped_bbox"),
                registration=crop.get("registration", "global"),
            )
            db.add(db_crop)


def _clean_page_result(page_result: dict) -> dict:
    cleaned = dict(page_result)
    crops = []
    for crop in cleaned.get("crops", []):
        clean_crop = {
            "answer_box_id": crop["answer_box_id"],
            "part": crop.get("part", 0),
            "qr_check": crop.get("qr_check"),
            "warped_bbox": crop.get("warped_bbox"),
            "registration": crop.get("registration", "global"),
        }
        crops.append(clean_crop)
    cleaned["crops"] = crops
    return cleaned


@router.post("", response_model=ExtractionResult)
async def create_submission(
    question_id: str = Form(...),
    modality: str = Form(...),
    page_index: int = Form(0),
    image: UploadFile = File(...),
    submission_id: str | None = Form(None),
    user: User = Depends(get_current_user), db: Session = Depends(get_db),
):
    """Extract answer boxes from one uploaded page (or every page of a
    multi-page PDF/TIFF in one call).

    A student photographing a multi-page answer normally submits one
    photo per page, separately, over several calls — not one PDF. Pass
    the submission_id this endpoint returned for that page's photo when
    submitting the NEXT page, and it attaches to the same submission
    (merged into the same manifest, same crop-images table rows) instead
    of starting an unrelated one. Omit it to start a new submission.
    Resubmitting a page_index that's already part of the submission (e.g.
    retaking a blurry photo) replaces that page's stored image and crops
    rather than duplicating them. The response always reflects the FULL
    submission's pages so far, not just the page just uploaded.
    """
    if modality not in ("photo", "scanner"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid modality '{modality}'. Use 'photo' or 'scanner'. "
            f"For tablet submissions, use POST /api/submissions/tablet.",
        )

    q = _get_question_for_submission(question_id, db, user)
    if q.state != "finalized":
        raise HTTPException(status_code=400, detail="Question must be finalized before submissions can be processed.")

    sub = None
    if submission_id:
        sub = _get_submission_or_404(submission_id, db, user)
        if sub.question_id != question_id:
            raise HTTPException(
                status_code=400,
                detail=f"Submission {submission_id} belongs to a different question ({sub.question_id}).",
            )

    sub_id = sub.id if sub else str(uuid.uuid4())
    pages_by_index: dict[int, dict] = {
        p["page_index"]: p for p in ((sub.manifest or {}).get("pages", []) if sub else [])
    }

    if sub is None:
        # The row has to exist before extraction stores any crops against
        # it: crop_images.submission_id is a real foreign key, and Postgres
        # enforces it. Component-1 built the submission last and got away
        # with it only because SQLite leaves foreign keys unenforced by
        # default — the manifest and dpi are filled in below once
        # extraction has actually produced them.
        sub = Submission(
            id=sub_id,
            question_id=question_id,
            # A teacher uploading a scanned stack isn't its author, so only
            # attribute the submission when a student submits their own.
            student_id=user.id if user.role == "student" else None,
            modality=modality,
        )
        db.add(sub)
        db.flush()

    question_dict = _question_to_dict(q)

    raw_bytes = await image.read()
    filename = image.filename or ""
    content_type = image.content_type or ""
    is_pdf = filename.lower().endswith(".pdf") or "pdf" in content_type
    is_tiff = filename.lower().endswith((".tif", ".tiff")) or "tiff" in content_type

    if is_pdf:
        page_images = _pdf_to_images(raw_bytes)
        if not page_images:
            raise HTTPException(status_code=400, detail="PDF contains no pages")
    elif is_tiff:
        page_images = _tiff_to_images(raw_bytes)
        if not page_images:
            raise HTTPException(status_code=400, detail="TIFF contains no pages")
    else:
        page_images = None

    if page_images is not None:
        n_pages = len(page_images)
        if q.page_count:
            n_pages = min(n_pages, q.page_count)
        for i in range(n_pages):
            try:
                result = extract_page(
                    question=question_dict, image_bytes=page_images[i],
                    modality=modality, page_index=i, submission_id=sub_id,
                )
                _store_page_data(db, sub_id, i, page_images[i], content_type or "image/png", result, question_dict)
                pages_by_index[i] = _clean_page_result(result)
            except ValueError as e:
                pages_by_index[i] = {
                    "page_index": i, "markers_detected": "N/A", "transform_type": "none",
                    "crops": [], "image_resolution": None, "image_dpi": None, "error": str(e),
                }
    else:
        try:
            result = extract_page(
                question=question_dict, image_bytes=raw_bytes,
                modality=modality, page_index=page_index, submission_id=sub_id,
            )
            _store_page_data(db, sub_id, page_index, raw_bytes, content_type or "image/png", result, question_dict)
            pages_by_index[page_index] = _clean_page_result(result)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    page_results = [pages_by_index[k] for k in sorted(pages_by_index)]

    manifest = {
        "submission_id": sub_id,
        "question_id": question_id,
        "modality": modality,
        "pages": page_results,
    }

    sub.modality = modality
    sub.image_dpi = page_results[0].get("image_dpi") if page_results else sub.image_dpi
    sub.manifest = manifest

    db.commit()

    return ExtractionResult(**manifest)


@router.post("/tablet", response_model=ExtractionResult)
def create_tablet_submission(body: TabletSubmission, page_index: int = 0, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    q = _get_question_for_submission(body.question_id, db, user)
    if q.state != "finalized":
        raise HTTPException(status_code=400, detail="Question must be finalized before submissions can be processed.")

    question_dict = _question_to_dict(q)
    sub_id = str(uuid.uuid4())
    ink_data = [{"points": s.points} for s in body.ink_strokes]

    try:
        page_result = extract_page(
            question=question_dict, image_bytes=None, modality="tablet",
            page_index=page_index, ink_strokes=ink_data, submission_id=sub_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _store_page_data(db, sub_id, page_index, b"", "image/png", page_result)
    clean_result = _clean_page_result(page_result)

    manifest = {"submission_id": sub_id, "question_id": body.question_id, "modality": "tablet", "pages": [clean_result]}
    submission = Submission(
        id=sub_id,
        question_id=body.question_id,
        student_id=user.id if user.role == "student" else None,
        modality="tablet",
        manifest=manifest,
    )
    db.add(submission)
    db.commit()
    return ExtractionResult(**manifest)


@router.get("", response_model=list[SubmissionSummary])
def list_submissions(
    question_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Submissions for a question.

    A teacher sees every submission on their own question; a student sees
    only their own, and only the marks that have been released to them.
    """
    q = _get_question_for_submission(question_id, db, user)

    course = db.query(Course).filter(Course.id == q.course_id).first()
    is_teacher = user.role == "admin" or (course is not None and course.teacher_id == user.id)

    query = db.query(Submission).filter(Submission.question_id == question_id)
    if not is_teacher:
        query = query.filter(Submission.student_id == user.id)

    submissions = query.order_by(Submission.created_at.desc()).all()

    students = {
        u.id: u
        for u in db.query(User)
        .filter(User.id.in_([s.student_id for s in submissions if s.student_id]))
        .all()
    } if submissions else {}

    out = []
    for sub in submissions:
        totals = submission_totals(db, sub.id)
        student = students.get(sub.student_id) if sub.student_id else None
        released = sub.released_at is not None

        out.append(
            SubmissionSummary(
                id=sub.id,
                question_id=sub.question_id,
                student_id=sub.student_id,
                student_name=student.display_name if student else None,
                modality=sub.modality,
                created_at=sub.created_at,
                grading_status=sub.grading_status,
                released=released,
                # Withhold the marks themselves from a student until they're
                # released — the list view must not leak what the detail
                # view deliberately gates.
                earned=totals["earned"] if (is_teacher or released) else None,
                max_score=totals["max"] if (is_teacher or released) else None,
                needs_review_count=totals["needs_review_count"] if is_teacher else None,
            )
        )
    return out


@router.get("/{submission_id}")
def get_submission(submission_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    sub = _get_submission_or_404(submission_id, db, user)
    return sub.manifest


@router.get("/{submission_id}/answers", response_model=GroupedSubmissionOut)
def get_submission_answers(submission_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Extraction crops grouped by answer box (document order) with each
    box's own multi-page segments already sorted into part order — the
    shape a consumer (e.g. an LLM evaluation call, which needs "this
    box's whole answer" as one unit) actually wants, as opposed to
    GET /{submission_id} / POST /submissions's page-by-page shape, which
    mirrors how extraction physically happens instead.

    Includes every answer box the question has, even ones with zero
    crops (never extracted — e.g. that page wasn't part of this
    submission) — a consumer needs to know a box is missing, not have it
    silently absent from the response."""
    sub = _get_submission_or_404(submission_id, db, user)
    q = _get_question_for_submission(sub.question_id, db, user)

    crops = (
        db.query(CropImage)
        .filter(CropImage.submission_id == submission_id)
        .order_by(CropImage.answer_box_id, CropImage.part)
        .all()
    )
    crops_by_box: dict[str, list[CropImage]] = defaultdict(list)
    for c in crops:
        crops_by_box[c.answer_box_id].append(c)

    answer_boxes_out = []
    for box in sorted(q.answer_boxes, key=lambda b: b.order_index):
        expected_parts = len(box.segments_json) if box.segments_json else 1
        box_crops = crops_by_box.get(box.id, [])

        parts_out = []
        for crop in box_crops:
            page_index = None
            if box.segments_json and crop.part < len(box.segments_json):
                page_index = box.segments_json[crop.part][0]
            parts_out.append(AnswerPartOut(
                part=crop.part,
                page_index=page_index,
                qr_check=crop.qr_check,
                warped_bbox=crop.warped_bbox,
                registration=crop.registration,
                crop_url=f"{settings.public_base_url}/api/submissions/{submission_id}/crops/{box.id}?part={crop.part}",
            ))

        found_parts = {c.part for c in box_crops}
        complete = found_parts == set(range(expected_parts))

        answer_boxes_out.append(GroupedAnswerBoxOut(
            answer_box_id=box.id,
            label=box.label or "",
            points=box.points,
            order_index=box.order_index,
            expected_parts=expected_parts,
            parts=parts_out,
            complete=complete,
        ))

    return GroupedSubmissionOut(
        submission_id=sub.id,
        question_id=sub.question_id,
        modality=sub.modality,
        answer_boxes=answer_boxes_out,
    )


@router.get("/{submission_id}/crops/{answer_box_id}")
def get_crop_image(submission_id: str, answer_box_id: str, part: int = 0, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
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
        raise HTTPException(status_code=404, detail=f"Crop for answer box {answer_box_id} (part {part}) not found")
    from fastapi.responses import Response
    return Response(content=crop.data, media_type=crop.content_type or "image/png")

