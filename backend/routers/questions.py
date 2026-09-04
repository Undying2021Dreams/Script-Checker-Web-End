"""
Question CRUD + finalize + PDF export endpoints.

NOTE: `render_finalized_question()` is imported from services.doc_renderer,
which is delivered in the next part (Playwright-based render + measure +
PDF bake). This router is written against that interface already so it
can be dropped in without further changes to this file:

    render_finalized_question(question_dict: dict) -> dict with keys:
        page_w_px: int
        page_h_px: int
        page_count: int
        boxes: dict[str, list[int]]   # answer_box_id -> [x, y, w, h]
        pdf_data: bytes

The old /normalize (LLM LaTeX-cleanup) endpoint is removed — equations are
now typed directly as LaTeX in the editor with a live KaTeX preview, so
there's nothing left to normalize. A replacement /suggest-rubric endpoint
(LLM proposes point values per answer box) lands in the next part too.
"""

from __future__ import annotations

import base64
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import Response
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models import (
    Question, AnswerBox, UploadedImage, QuestionPdf, GroundTruthBox,
    GroundTruthImage, QuestionImage, Course, User,
)
from security import get_current_user, require_teacher
from schemas import (
    QuestionCreate,
    QuestionContentUpdate,
    QuestionMetaUpdate,
    QuestionOut,
    AnswerBoxOut,
    GroundTruthBoxIn,
    GroundTruthBoxOut,
    RubricSuggestRequest,
    CorrectnessCheckRequest,
)

router = APIRouter(prefix="/questions", tags=["questions"])
logger = logging.getLogger(__name__)


# ── Helpers ────────────────────────────────────────────────────────

def _box_to_out(b: AnswerBox) -> AnswerBoxOut:
    bbox = None
    if b.bbox_x is not None:
        bbox = [b.bbox_x, b.bbox_y, b.bbox_w, b.bbox_h]
    return AnswerBoxOut(
        id=b.id,
        label=b.label or "",
        points=b.points,
        bbox=bbox,
        page_index=b.page_index,
        segments=b.segments_json,
        qr_segments=b.qr_bbox_json,
    )


def _question_to_out(q: Question, db: Session | None = None) -> QuestionOut:
    question_image_id = None
    if hasattr(q, 'question_images') and q.question_images:
        question_image_id = q.question_images[0].id
    return QuestionOut(
        question_id=q.id,
        course_id=q.course_id,
        title=q.title,
        state=q.state,
        physical_page=q.physical_page,
        dpi=q.dpi,
        content=q.content,
        answer_boxes=[_box_to_out(b) for b in q.answer_boxes],
        ground_truth_boxes=[_gt_box_to_out(b, db=db) for b in q.ground_truth_boxes],
        question_image_id=question_image_id,
        page_w_px=q.page_w_px,
        page_h_px=q.page_h_px,
        page_count=q.page_count,
        derived_from=q.derived_from,
        created_at=q.created_at.isoformat() if q.created_at else "",
        finalized_at=q.finalized_at.isoformat() if q.finalized_at else None,
    )


_IMAGE_URL_RE = re.compile(r"/api/images/([0-9a-fA-F-]{36})")


def _inline_uploaded_images(node: Any, db: Session) -> Any:
    """
    Replace /api/images/<id> srcs in a doc with data: URIs.

    The renderer runs a headless browser that has no session, and image
    serving requires authentication, so a linked image would come back 401
    and render as nothing. That's not just a missing picture: an image
    that fails to load occupies no height, so every answer box below it is
    measured at the wrong position and the printed page no longer matches
    what extraction expects.

    Inlining also means rendering doesn't depend on the app being able to
    reach itself over the network, which is one less thing to get wrong
    when deployed.
    """
    if isinstance(node, list):
        return [_inline_uploaded_images(n, db) for n in node]
    if not isinstance(node, dict):
        return node

    result = dict(node)

    if result.get("type") == "image":
        attrs = dict(result.get("attrs") or {})
        src = attrs.get("src") or ""
        match = _IMAGE_URL_RE.search(src)
        if match:
            img = db.query(UploadedImage).filter(UploadedImage.id == match.group(1)).first()
            if img and img.data:
                encoded = base64.b64encode(bytes(img.data)).decode("ascii")
                attrs["src"] = f"data:{img.content_type or 'image/png'};base64,{encoded}"
            else:
                logger.warning("Question doc references missing image %s", match.group(1))
        result["attrs"] = attrs

    if isinstance(result.get("content"), list):
        result["content"] = [_inline_uploaded_images(n, db) for n in result["content"]]

    return result


def _question_to_dict(q: Question, db: Session | None = None) -> dict:
    """Plain dict for services (doc_renderer, extractor) — avoids passing
    ORM/ Pydantic objects into rendering/CV code."""
    return _question_to_out(q, db=db).model_dump()


def _get_question_or_404(question_id: str, db: Session, user: User) -> Question:
    """
    Fetch a question the given user is allowed to author.

    Every endpoint in this router is authoring work, so access means
    "teaches the course this question belongs to". Students never reach
    these routes — a question's ground-truth boxes are the answer key, so
    student-facing views need their own purpose-built response rather than
    a relaxed check here.
    """
    q = db.query(Question).filter(Question.id == question_id).first()
    if not q:
        raise HTTPException(status_code=404, detail=f"Question {question_id} not found")

    if user.role != "admin":
        course = db.query(Course).filter(Course.id == q.course_id).first()
        if course is None or course.teacher_id != user.id:
            # 404 rather than 403: a teacher poking at IDs shouldn't be able
            # to confirm another course's question exists.
            raise HTTPException(status_code=404, detail=f"Question {question_id} not found")

    return q


def _get_owned_course_or_404(course_id: str, db: Session, user: User) -> Course:
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail=f"Course {course_id} not found")
    if user.role != "admin" and course.teacher_id != user.id:
        raise HTTPException(status_code=403, detail="You don't teach this course")
    return course


def _assert_draft(q: Question):
    if q.state == "finalized":
        raise HTTPException(
            status_code=409,
            detail=f"Question {q.id} is finalized — cannot modify. Clone it to create a new draft.",
        )


def _upsert_answer_boxes(q: Question, boxes_in: list, db: Session):
    """Same upsert-by-id pattern as the old update_blocks — preserves rows
    (and their frozen bbox, if any) the client still references, adds new
    ones, deletes ones the client dropped."""
    incoming_ids = {b.id for b in boxes_in}
    existing = {b.id: b for b in q.answer_boxes}

    for old_id, old_box in existing.items():
        if old_id not in incoming_ids:
            db.delete(old_box)

    for i, b in enumerate(boxes_in):
        if b.id in existing:
            box = existing[b.id]
            box.label = b.label
            box.points = b.points
            box.order_index = i
        else:
            db.add(AnswerBox(
                id=b.id,
                question_id=q.id,
                label=b.label,
                points=b.points,
                order_index=i,
            ))


def _gt_box_to_out(b: GroundTruthBox, db: Session | None = None) -> GroundTruthBoxOut:
    question_image_id = None
    if db is not None:
        qi = db.query(QuestionImage).filter(QuestionImage.ground_truth_box_id == b.id).first()
        if qi:
            question_image_id = qi.id
    return GroundTruthBoxOut(
        id=b.id,
        label=b.label or "",
        question_id=b.question_id,
        question_image_id=question_image_id,
    )


def _extract_ground_truth_box_contents(content_doc: dict) -> dict[str, dict]:
    """Walk the Tiptap JSON and return a mapping of groundTruthBox id → its
    inner content (the sub-doc inside the box)."""
    result = {}
    if not isinstance(content_doc, dict):
        return result
    for node in content_doc.get("content", []):
        if node.get("type") == "groundTruthBox":
            box_id = node.get("attrs", {}).get("id")
            if box_id:
                result[box_id] = node.get("content")
    return result


def _question_nodes_by_gt_box_id(content_doc: dict) -> dict[str, list]:
    """Buckets each top-level doc node under the *following* groundTruthBox's
    id — mirrors the frontend's questionTextByGtBoxId (AuthorPage.jsx) and
    doc_renderer's up_to_gt_box_id segmenting. A single Question doc can
    hold multiple sub-questions (multiple groundTruthBox nodes in order),
    so a correctness check needs the specific sub-question text a given
    box actually answers, not the whole document — otherwise a check
    against a 2-part question only ever addresses the first part. Returns
    node lists suitable for extract_plain_text() (which already accepts a
    bare list, not just a wrapping doc)."""
    result: dict[str, list] = {}
    if not isinstance(content_doc, dict):
        return result
    buffer: list = []
    for node in content_doc.get("content", []) or []:
        if node.get("type") == "groundTruthBox":
            box_id = (node.get("attrs") or {}).get("id")
            if box_id:
                result[box_id] = buffer
            buffer = []
            continue
        if node.get("type") == "answerBox":
            continue
        buffer.append(node)
    return result


def _upsert_ground_truth_boxes(q: Question, boxes_in: list, db: Session, box_contents: dict | None = None):
    incoming_ids = {b.id for b in boxes_in}
    existing = {b.id: b for b in q.ground_truth_boxes}

    for old_id, old_box in existing.items():
        if old_id not in incoming_ids:
            db.delete(old_box)

    for i, b in enumerate(boxes_in):
        content = (box_contents or {}).get(b.id)
        if b.id in existing:
            box = existing[b.id]
            box.label = b.label
            box.order_index = i
            if content is not None:
                box.content = content
        else:
            db.add(GroundTruthBox(
                id=b.id,
                question_id=q.id,
                label=b.label,
                order_index=i,
                content=content,
            ))


# ── Endpoints ─────────────────────────────────────────────────────

@router.post("", response_model=QuestionOut, status_code=201)
def create_question(
    body: QuestionCreate,
    course_id: str,
    user: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """Create a draft question inside a course you teach."""
    _get_owned_course_or_404(course_id, db, user)

    q = Question(
        id=str(uuid.uuid4()),
        course_id=course_id,
        created_by=user.id,
        state="draft",
        physical_page=body.physical_page,
        content=body.content,
    )
    db.add(q)
    db.flush()  # so q.id is available for the FK below
    _upsert_answer_boxes(q, body.answer_boxes, db)

    db.commit()
    db.refresh(q)
    return _question_to_out(q, db=db)


@router.get("", response_model=list[QuestionOut])
def list_questions(
    course_id: str,
    user: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """Questions in a course you teach. Unlike Component-1, questions are
    never listed globally — they belong to exactly one course."""
    _get_owned_course_or_404(course_id, db, user)

    questions = (
        db.query(Question)
        .filter(Question.course_id == course_id)
        .order_by(Question.created_at.desc())
        .all()
    )
    return [_question_to_out(q, db=db) for q in questions]


@router.patch("/{question_id}", response_model=QuestionOut)
def update_question_meta(
    question_id: str,
    body: QuestionMetaUpdate,
    user: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """
    Rename a paper.

    Deliberately not part of the content autosave and not blocked by
    _assert_draft: the title never reaches the printed page, so renaming a
    finalized paper changes nothing a student has already been given.
    """
    q = _get_question_or_404(question_id, db, user)
    title = (body.title or "").strip()
    q.title = title or None
    db.commit()
    db.refresh(q)
    return _question_to_out(q, db=db)


@router.get("/{question_id}", response_model=QuestionOut)
def get_question(question_id: str, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    q = _get_question_or_404(question_id, db, user)
    return _question_to_out(q, db=db)


@router.put("/{question_id}/blocks", response_model=QuestionOut)
def save_content(question_id: str, body: QuestionContentUpdate, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    """
    Autosave endpoint — path kept as /blocks to match the frontend's
    existing saveQuestionContent() call; body/behavior is doc+answer_boxes
    now, not a flat block list. Draft only.
    """
    q = _get_question_or_404(question_id, db, user)
    _assert_draft(q)

    q.content = body.content
    _upsert_answer_boxes(q, body.answer_boxes, db)

    gt_box_contents = _extract_ground_truth_box_contents(body.content)
    _upsert_ground_truth_boxes(q, body.ground_truth_boxes, db, box_contents=gt_box_contents)

    db.commit()
    db.refresh(q)
    return _question_to_out(q, db=db)


@router.post("/{question_id}/images")
async def upload_image(question_id: str, image: UploadFile = File(...), user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    """Store an image the teacher inserts inline in the doc. Draft only —
    once finalized, content (and therefore images) is frozen."""
    q = _get_question_or_404(question_id, db, user)
    _assert_draft(q)

    from pathlib import Path
    from config import settings

    ext = Path(image.filename or "").suffix.lower() or ".png"
    if ext not in (".png", ".jpg", ".jpeg", ".webp"):
        raise HTTPException(status_code=400, detail=f"Unsupported image type: {ext}")

    content_type = image.content_type or "application/octet-stream"
    data = await image.read()

    db_img = UploadedImage(
        question_id=question_id,
        filename=image.filename or f"{uuid.uuid4().hex}{ext}",
        content_type=content_type,
        data=data,
    )
    db.add(db_img)
    db.commit()
    db.refresh(db_img)

    return {"url": f"{settings.public_base_url}/api/images/{db_img.id}"}


@router.post("/{question_id}/suggest-rubric")
async def suggest_rubric(question_id: str, body: RubricSuggestRequest, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    """LLM proposes point values + rubric text per answer box — the teacher
    reviews and edits in the UI; nothing here is auto-applied to the DB."""
    q = _get_question_or_404(question_id, db, user)
    if not q.answer_boxes:
        raise HTTPException(status_code=400, detail="No answer boxes to suggest a rubric for")

    from services.llm_provider import get_provider, extract_plain_text

    question_text = extract_plain_text(q.content or {})
    boxes = [{"id": b.id, "label": b.label or "", "points": b.points} for b in q.answer_boxes]

    provider = get_provider(body.provider)
    try:
        suggestions = await provider.suggest_rubric(question_text, boxes)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Rubric suggestion failed: {e}")

    return {"suggestions": suggestions}


@router.post("/{question_id}/equation-from-image")
async def equation_from_image(
    question_id: str,
    provider: str = Form(...),
    image: UploadFile = File(...),
    user: User = Depends(require_teacher), db: Session = Depends(get_db),
):
    """Transcribe an uploaded image of an equation into LaTeX so a teacher
    who doesn't know LaTeX can still author one. Returned LaTeX is never
    inserted directly — the editor shows it in an editable preview first."""
    _get_question_or_404(question_id, db, user)

    from services.llm_provider import get_provider as get_llm_provider

    content_type = image.content_type or "image/png"
    data = await image.read()
    if not data:
        raise HTTPException(status_code=400, detail="Uploaded image was empty")

    try:
        llm = get_llm_provider(provider)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        latex = await llm.equation_from_image(data, content_type)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Equation extraction failed: {e}")

    return {"latex": latex}


@router.post("/{question_id}/check-correctness")
async def check_correctness(question_id: str, body: CorrectnessCheckRequest, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    """LLM sanity-checks each of this question's own ground truth answers
    against the specific sub-question it answers — catches a teacher's own
    mistakes (wrong answer key, ambiguous wording) before students see
    them. Purely advisory: nothing here is auto-applied to the DB.

    Runs one check per ground truth box (not one combined check across all
    of them) — a single Question doc (one "paper") can hold multiple
    individual questions, and lumping every box's answer into one blob
    meant the LLM would only ever address the first one. Each box is
    paired with its own preceding question text via
    _question_nodes_by_gt_box_id, same pairing the doc already uses
    elsewhere (doc_renderer's up_to_gt_box_id, AuthorPage's ground-truth
    preview grid). Pass body.ground_truth_box_id to scope this to just
    one individual question instead of checking the whole paper."""
    q = _get_question_or_404(question_id, db, user)
    if not q.ground_truth_boxes:
        raise HTTPException(status_code=400, detail="No ground truth answer to check against")

    from services.llm_provider import get_provider, extract_plain_text, extract_image_ids

    fallback_question_text = extract_plain_text(q.content or {})
    question_nodes_by_box = _question_nodes_by_gt_box_id(q.content or {})
    all_boxes = sorted(q.ground_truth_boxes, key=lambda b: b.order_index)
    # Index within the FULL (unfiltered) paper — so a scoped single-box
    # check still reports "Question 3", not "Question 1", matching the
    # numbering the frontend's dropdown already shows for that box.
    index_by_box_id = {b.id: i for i, b in enumerate(all_boxes)}

    boxes = all_boxes
    if body.ground_truth_box_id:
        boxes = [b for b in boxes if b.id == body.ground_truth_box_id]
        if not boxes:
            raise HTTPException(status_code=404, detail="Ground truth box not found on this question")

    provider = get_provider(body.provider)

    async def _check_one(box: GroundTruthBox) -> dict:
        answer_text = extract_plain_text(box.content or {})
        image_ids = extract_image_ids(box.content or {})
        if not answer_text.strip() and not image_ids:
            return {
                "ground_truth_box_id": box.id,
                "label": box.label or "",
                "index": index_by_box_id[box.id],
                "ok": None,
                "issue": None,
                "explanation": "This ground truth box is empty — add an answer before checking.",
                "suggested_question": None,
                "suggested_answer": None,
            }

        answer_images = []
        for img_id in image_ids:
            img = db.query(UploadedImage).filter(UploadedImage.id == img_id).first()
            if img and img.data:
                answer_images.append((bytes(img.data), img.content_type or "image/png"))

        question_text = extract_plain_text(question_nodes_by_box.get(box.id, [])) or fallback_question_text

        try:
            result = await provider.check_correctness(question_text, answer_text, answer_images)
        except Exception as e:
            result = {
                "ok": None,
                "issue": None,
                "explanation": f"Check failed: {e}",
                "suggested_question": None,
                "suggested_answer": None,
            }
        return {"ground_truth_box_id": box.id, "label": box.label or "", "index": index_by_box_id[box.id], **result}

    # Sequential, not asyncio.gather — the self-hosted server is a single
    # GPU process; firing two /chat/completions requests at once broke it
    # outright ("Server disconnected without sending a response") rather
    # than just queueing. Hosted providers would tolerate concurrency fine,
    # but there's one provider per request here, so serialize for all of
    # them rather than special-casing self-hosted.
    results = [await _check_one(box) for box in boxes]
    return {"results": results}


@router.get("/{question_id}/ground-truth")
def list_ground_truth_boxes(question_id: str, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    _get_question_or_404(question_id, db, user)
    boxes = db.query(GroundTruthBox).filter(GroundTruthBox.question_id == question_id).order_by(GroundTruthBox.order_index).all()
    result = []
    for box in boxes:
        box_data = _gt_box_to_out(box, db=db).model_dump()
        img = db.query(GroundTruthImage).filter(GroundTruthImage.ground_truth_box_id == box.id).first()
        if img:
            box_data["image_id"] = img.id
        result.append(box_data)
    return result


@router.post("/{question_id}/ground-truth", response_model=list[GroundTruthBoxOut])
def upsert_ground_truth_boxes(question_id: str, body: list[GroundTruthBoxIn], user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    q = _get_question_or_404(question_id, db, user)
    _assert_draft(q)
    _upsert_ground_truth_boxes(q, body, db)
    db.commit()
    boxes = db.query(GroundTruthBox).filter(GroundTruthBox.question_id == question_id).order_by(GroundTruthBox.order_index).all()
    return [_gt_box_to_out(b, db=db) for b in boxes]


def _content_disposition(download: bool, filename: str) -> dict:
    if not download:
        return {}
    return {"Content-Disposition": f'attachment; filename="{filename}"'}


@router.get("/ground-truth-images/{image_id}")
def get_ground_truth_image(image_id: str, download: bool = False, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    img = db.query(GroundTruthImage).filter(GroundTruthImage.id == image_id).first()
    if not img:
        raise HTTPException(status_code=404, detail="Ground truth image not found")

    # These are answer-key renders, so a teacher role alone isn't enough —
    # confirm this teacher owns the course the image ultimately belongs to.
    gt_box = db.query(GroundTruthBox).filter(GroundTruthBox.id == img.ground_truth_box_id).first()
    if gt_box is None:
        raise HTTPException(status_code=404, detail="Ground truth image not found")
    _get_question_or_404(gt_box.question_id, db, user)

    if not img.data:
        logger.warning("Ground truth image %s has empty data — deleting stale record", image_id)
        db.delete(img)
        db.commit()
        raise HTTPException(status_code=404, detail="Ground truth image had no data — try regenerating")
    try:
        raw = bytes(img.data)
        headers = _content_disposition(download, f"ground-truth-{image_id[:8]}.png")
        return Response(content=raw, media_type=img.content_type or "image/png", headers=headers)
    except Exception as e:
        logger.error("Failed to serve ground truth image %s: %s", image_id, e)
        raise HTTPException(status_code=500, detail="Failed to serve ground truth image")


@router.get("/question-images/{image_id}")
def get_question_image(image_id: str, download: bool = False, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    img = db.query(QuestionImage).filter(QuestionImage.id == image_id).first()
    if not img:
        raise HTTPException(status_code=404, detail="Question image not found")

    _get_question_or_404(img.question_id, db, user)

    if not img.data:
        logger.warning("Question image %s has empty data — deleting stale record", image_id)
        db.delete(img)
        db.commit()
        raise HTTPException(status_code=404, detail="Question image had no data — try regenerating")
    try:
        raw = bytes(img.data)
        ext = "png" if (img.content_type or "").endswith("png") else "pdf"
        headers = _content_disposition(download, f"question-{image_id[:8]}.{ext}")
        return Response(content=raw, media_type=img.content_type or "application/pdf", headers=headers)
    except Exception as e:
        logger.error("Failed to serve question image %s: %s", image_id, e)
        raise HTTPException(status_code=500, detail="Failed to serve question image")


@router.get("/{question_id}/question-images")
def list_question_images(question_id: str, ground_truth_box_id: str, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    _get_question_or_404(question_id, db, user)
    img = db.query(QuestionImage).filter(
        QuestionImage.question_id == question_id,
        QuestionImage.ground_truth_box_id == ground_truth_box_id,
    ).first()
    if not img:
        raise HTTPException(status_code=404, detail="Question image not found for this ground truth box")
    return {
        "id": img.id,
        "ground_truth_box_id": img.ground_truth_box_id,
        "label": img.label,
        "content_type": img.content_type,
    }


@router.post("/{question_id}/regenerate-ground-truth")
def regenerate_ground_truth(question_id: str, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    """Regenerate ground truth images AND question segment images for an
    already-finalized question. Useful if rendering failed during the
    original finalization."""
    q = _get_question_or_404(question_id, db, user)
    if q.state != "finalized":
        raise HTTPException(status_code=400, detail="Question must be finalized to regenerate images")

    from services.doc_renderer import render_ground_truth_box_to_image, render_question_to_image

    # Regenerate question images (one per ground truth box)
    gt_box_ids = [b.id for b in q.ground_truth_boxes]
    if gt_box_ids:
        db.query(QuestionImage).filter(QuestionImage.question_id == question_id).delete(synchronize_session=False)

    for gt_box in q.ground_truth_boxes:
        try:
            segment_bytes = render_question_to_image(
                _inline_uploaded_images(q.content, db),
                canvas_w=q.page_w_px or 794,
                canvas_h=q.page_h_px or 1123,
                up_to_gt_box_id=gt_box.id,
                include_box=False,
            )
            if segment_bytes:
                db.add(QuestionImage(
                    question_id=question_id,
                    ground_truth_box_id=gt_box.id,
                    label=f"Q: {gt_box.id[:8]}",
                    data=segment_bytes,
                    content_type="image/png",
                    page_w_px=q.page_w_px,
                    page_h_px=q.page_h_px,
                ))
        except Exception as e:
            logger.warning("Failed to render question image for GT box %s: %s", gt_box.id, e)

    # Regenerate ground truth images
    if gt_box_ids:
        db.query(GroundTruthImage).filter(GroundTruthImage.ground_truth_box_id.in_(gt_box_ids)).delete(synchronize_session=False)

    for gt_box in q.ground_truth_boxes:
        if not gt_box.content and q.content:
            extracted = _extract_ground_truth_box_contents(q.content)
            if gt_box.id in extracted:
                gt_box.content = extracted[gt_box.id]

        try:
            png_bytes = render_ground_truth_box_to_image(_inline_uploaded_images(gt_box.content or {}, db))
            if png_bytes:
                db.add(GroundTruthImage(
                    ground_truth_box_id=gt_box.id,
                    data=png_bytes,
                    content_type="image/png",
                ))
        except Exception as e:
            logger.warning("Failed to render ground truth box %s: %s", gt_box.id, e)

    db.commit()
    return {"status": "ok", "regenerated_questions": len(gt_box_ids), "regenerated_ground_truths": len(gt_box_ids)}


@router.post("/{question_id}/finalize", response_model=QuestionOut)
def finalize_question(question_id: str, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    """
    Freeze a draft question. Unlike the old canvas model, this now has real
    work to do: render the doc once, measure where each answer box actually
    landed, and freeze those coordinates — they're what extraction will use
    against scanned/photographed submissions from here on.
    """
    q = _get_question_or_404(question_id, db, user)
    _assert_draft(q)

    if not q.content:
        raise HTTPException(status_code=400, detail="Cannot finalize an empty question — add some content first.")

    from services.doc_renderer import render_finalized_question, render_ground_truth_box_to_image, render_question_to_image

    question_dict = _question_to_dict(q, db=db)
    question_dict["content"] = _inline_uploaded_images(question_dict.get("content"), db)
    layout = render_finalized_question(question_dict)

    q.page_w_px = layout["page_w_px"]
    q.page_h_px = layout["page_h_px"]
    q.page_count = layout["page_count"]
    for box in q.answer_boxes:
        if box.id in layout["boxes"]:
            all_segs = layout["boxes"][box.id]
            page_index, x, y, w, h = all_segs[0]
            box.page_index = page_index
            box.bbox_x, box.bbox_y, box.bbox_w, box.bbox_h = x, y, w, h
            box.segments_json = all_segs
            box.qr_bbox_json = layout.get("qr_boxes", {}).get(box.id)
        else:
            raise HTTPException(
                status_code=500,
                detail=f"Answer box {box.id} exists in DB but was not found in rendered layout — "
                f"doc content and answer_boxes table are out of sync.",
                )

    try:
        for gt_box in q.ground_truth_boxes:
            segment_bytes = render_question_to_image(
                _inline_uploaded_images(q.content, db),
                canvas_w=q.page_w_px or 794,
                canvas_h=q.page_h_px or 1123,
                up_to_gt_box_id=gt_box.id,
                include_box=False,
            )
            if segment_bytes:
                db.add(QuestionImage(
                    question_id=question_id,
                    ground_truth_box_id=gt_box.id,
                    label=f"Q: {gt_box.id[:8]}",
                    data=segment_bytes,
                    content_type="image/png",
                    page_w_px=q.page_w_px,
                    page_h_px=q.page_h_px,
                ))
    except Exception as e:
        logger.warning("Failed to render question images for %s: %s", question_id, e)

    for gt_box in q.ground_truth_boxes:
        if not gt_box.content and q.content:
            extracted = _extract_ground_truth_box_contents(q.content)
            if gt_box.id in extracted:
                gt_box.content = extracted[gt_box.id]

        try:
            png_bytes = render_ground_truth_box_to_image(_inline_uploaded_images(gt_box.content or {}, db))
            if png_bytes:
                db.add(GroundTruthImage(
                    ground_truth_box_id=gt_box.id,
                    data=png_bytes,
                    content_type="image/png",
                ))
            else:
                logger.warning("Ground truth box %s rendered empty image — content may be empty", gt_box.id)
        except Exception as e:
            logger.warning("Failed to render ground truth box %s: %s", gt_box.id, e)

    q.state = "finalized"
    q.finalized_at = datetime.now(timezone.utc)

    pdf_record = QuestionPdf(
        question_id=question_id,
        data=layout["pdf_data"],
        page_w_px=layout["page_w_px"],
        page_h_px=layout["page_h_px"],
        page_count=layout["page_count"],
    )
    db.add(pdf_record)
    db.commit()
    db.refresh(q)
    return _question_to_out(q, db=db)


@router.get("/{question_id}/pdf")
def export_pdf(question_id: str, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    """Serve the PDF baked during finalize (stored in the database)."""
    q = _get_question_or_404(question_id, db, user)
    if q.state != "finalized":
        raise HTTPException(status_code=400, detail="Cannot export PDF — question is still a draft. Finalize it first.")

    from models import QuestionPdf
    pdf = db.query(QuestionPdf).filter(QuestionPdf.question_id == question_id).first()
    if not pdf:
        raise HTTPException(status_code=404, detail="PDF not found — try re-finalizing (clone + finalize) to regenerate it.")

    from fastapi.responses import Response
    return Response(content=pdf.data, media_type="application/pdf")


@router.post("/{question_id}/clone", response_model=QuestionOut, status_code=201)
def clone_question(question_id: str, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    """Clone a finalized question into a new draft. bbox/page dims are NOT
    copied — they're re-measured on next finalize. Image files are copied
    from the original question to the new question in the database."""
    original = _get_question_or_404(question_id, db, user)

    new_id = str(uuid.uuid4())

    orig_images = db.query(UploadedImage).filter(UploadedImage.question_id == original.id).all()
    filename_to_new_id = {}
    for orig in orig_images:
        new_img = UploadedImage(
            question_id=new_id,
            filename=orig.filename,
            content_type=orig.content_type,
            data=orig.data,
        )
        db.add(new_img)
        db.flush()
        filename_to_new_id[orig.filename] = new_img.id

    import copy
    new_content = copy.deepcopy(original.content)

    # answer_boxes.id / ground_truth_boxes.id are global primary keys, not
    # scoped per-question — reusing the original ids on the clone's rows
    # violates the UNIQUE constraint (and would make the clone's future
    # printed QR codes indistinguishable from the original's). Generate
    # fresh ids for the clone and remap every reference to them, both in
    # the DB rows and in the doc's embedded node attrs.
    answer_box_id_map = {b.id: str(uuid.uuid4()) for b in original.answer_boxes}
    gt_box_id_map = {b.id: str(uuid.uuid4()) for b in original.ground_truth_boxes}

    def _walk(node: dict):
        if not isinstance(node, dict):
            return
        t = node.get("type")
        if t == "image":
            attrs = node.get("attrs") or {}
            src = attrs.get("src", "")
            for old_filename, new_id in filename_to_new_id.items():
                if old_filename in src:
                    attrs["src"] = f"{settings.public_base_url}/api/images/{new_id}"
                    break
        elif t == "answerBox":
            attrs = node.get("attrs") or {}
            if attrs.get("id") in answer_box_id_map:
                attrs["id"] = answer_box_id_map[attrs["id"]]
        elif t == "groundTruthBox":
            attrs = node.get("attrs") or {}
            if attrs.get("id") in gt_box_id_map:
                attrs["id"] = gt_box_id_map[attrs["id"]]
        for child in node.get("content") or []:
            _walk(child)

    if new_content:
        _walk(new_content)

    new_q = Question(
        id=new_id,
        # A clone stays in the original's course; the cloner becomes its
        # author, since they're the one who now owns this draft.
        course_id=original.course_id,
        created_by=user.id,
        state="draft",
        physical_page=original.physical_page,
        dpi=original.dpi,
        content=new_content,
        derived_from=original.id,
    )
    db.add(new_q)
    db.flush()

    for i, b in enumerate(original.answer_boxes):
        db.add(AnswerBox(
            id=answer_box_id_map[b.id],
            question_id=new_q.id,
            label=b.label,
            points=b.points,
            order_index=i,
            # bbox / segments_json intentionally left None — frozen on next finalize
        ))

    for i, b in enumerate(original.ground_truth_boxes):
        gt_content = copy.deepcopy(b.content)
        if gt_content:
            _walk({"content": gt_content} if isinstance(gt_content, list) else gt_content)
        db.add(GroundTruthBox(
            id=gt_box_id_map[b.id],
            question_id=new_q.id,
            label=b.label,
            order_index=i,
            content=gt_content,
        ))

    db.commit()
    db.refresh(new_q)
    return _question_to_out(new_q, db=db)
