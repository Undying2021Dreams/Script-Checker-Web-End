"""
The student's Android app: grading on the phone.

Additive. Nothing here changes an existing route; the teacher's side is
untouched and learns what happened through the notification bell. Every
route needs the caller enrolled in the course (student._assert_enrolled);
the submission routes also need the caller to own the submission, and
answer 404 otherwise, as the rest of the app does for other people's work.

See Script-Checker-Web-End/addition_branch_phone.md for why these exist
and the decisions behind them, in particular that the pack carries the
answer key.
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from config import settings
from database import get_db
from models import (
    AnswerBox,
    AnswerGrade,
    Course,
    GroundTruthBox,
    GroundTruthImage,
    Question,
    Submission,
    UploadedImage,
    User,
)
from ratelimit import LLM_LIMIT, limiter
from routers.student import _assert_enrolled
from schemas import (
    AssignmentPack,
    OnDeviceBoxGrade,
    OnDeviceGradesOut,
    OnDeviceResultsIn,
    OnDeviceResultsOut,
    OnDeviceRunInfo,
    OnDeviceRunStarted,
    PackBox,
    PackMarkers,
    ReevaluationRequest,
)
from security import get_current_user
from services import on_device
from services.doc_renderer import get_marker_positions
from services.grading import pair_answer_boxes_with_ground_truth, question_nodes_by_ground_truth_box
from services.grading_runner import submission_totals
from services.llm_provider import extract_image_ids
from services.notify import notify

router = APIRouter(prefix="/student", tags=["on-device"])

PACK_VERSION = 1

# A request for a person to look again. Cheap to make, so bounded to stop
# a student flooding their teacher's bell.
REEVALUATION_LIMIT = "5/hour"

IMAGE_KINDS = ("model-answer", "question")


# ── Access ──────────────────────────────────────────────────────────

def _finalized_question_for_student(question_id: str, db: Session, user: User) -> Question:
    q = db.query(Question).filter(Question.id == question_id).first()
    if q is None or q.state != "finalized":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    _assert_enrolled(q.course_id, db, user)
    return q


def _own_submission(submission_id: str, db: Session, user: User) -> Submission:
    """The caller's own submission, in a course they are enrolled in."""
    sub = db.query(Submission).filter(Submission.id == submission_id).first()
    if sub is None or sub.student_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")
    question = db.query(Question).filter(Question.id == sub.question_id).first()
    if question is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")
    _assert_enrolled(question.course_id, db, user)
    return sub


# ── 1. The pack ─────────────────────────────────────────────────────

def _image_refs(db: Session, question: Question) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """(box id -> model-answer image refs, box id -> question figure refs),
    in the order build_grading_items attaches them."""
    pairing = pair_answer_boxes_with_ground_truth(question.content)
    nodes_by_gt = question_nodes_by_ground_truth_box(question.content)
    gt_ids_known = {b.id for b in question.ground_truth_boxes}
    uploaded = {
        img_id
        for (img_id,) in db.query(UploadedImage.id).filter(UploadedImage.question_id == question.id)
    }

    model_refs: dict[str, list[str]] = {}
    question_refs: dict[str, list[str]] = {}
    for box in question.answer_boxes:
        gt_ids = [gt_id for gt_id in pairing.get(box.id, []) if gt_id in gt_ids_known]

        refs: list[str] = []
        for gt_id in gt_ids:
            for (img_id,) in (
                db.query(GroundTruthImage.id)
                .filter(GroundTruthImage.ground_truth_box_id == gt_id)
                .order_by(GroundTruthImage.page_index)
            ):
                refs.append(f"pack/images/model-answer/{img_id}")
        model_refs[box.id] = refs

        seen: set[str] = set()
        figures: list[str] = []
        for gt_id in gt_ids:
            for img_id in extract_image_ids(nodes_by_gt.get(gt_id, [])):
                if img_id in seen or img_id not in uploaded:
                    continue
                seen.add(img_id)
                figures.append(f"pack/images/question/{img_id}")
        question_refs[box.id] = figures

    return model_refs, question_refs


@router.get("/assignments/{question_id}/pack", response_model=AssignmentPack)
def get_assignment_pack(
    question_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Everything the phone needs to crop and mark a paper by itself.

    **This includes the answer key, on purpose.** Each box carries its
    model answer text and image references, so an enrolled student holds
    the answers before they write theirs. That is an accepted risk for
    the capstone demo and wrong for a real exam; it is recorded in
    addition_branch_phone.md (sections 2 and 9). Every other student
    route still withholds the answer key.

    Finalized papers only. Question text, model answer text, maximum and
    blocked reason come from build_grading_items itself, so the phone
    marks against exactly what a server run would. Image references are
    relative to this pack's URL ("pack/images/<kind>/<id>"); the app
    resolves them against its own base URL, never PUBLIC_BASE_URL.
    """
    q = _finalized_question_for_student(question_id, db, user)

    items = on_device.pack_items(db, q)
    model_refs, question_refs = _image_refs(db, q)

    boxes = []
    for box in sorted(q.answer_boxes, key=lambda b: b.order_index):
        item = items.get(box.id)
        bbox = None
        if None not in (box.bbox_x, box.bbox_y, box.bbox_w, box.bbox_h):
            bbox = [box.bbox_x, box.bbox_y, box.bbox_w, box.bbox_h]
        boxes.append(
            PackBox(
                id=box.id,
                label=box.label,
                points=box.points,
                order_index=box.order_index,
                page_index=box.page_index,
                bbox=bbox,
                segments=box.segments_json,
                question_text=item.question_text if item else "",
                model_answer_text=item.ground_truth_text if item else "",
                model_answer_images=model_refs.get(box.id, []),
                question_images=question_refs.get(box.id, []),
                blocked_reason=item.blocked_reason if item else None,
            )
        )

    centres = {}
    if q.page_w_px and q.page_h_px:
        centres = {str(k): list(v) for k, v in get_marker_positions(q.page_w_px, q.page_h_px).items()}

    return AssignmentPack(
        pack_version=PACK_VERSION,
        question_id=q.id,
        course_id=q.course_id,
        title=q.title,
        page_w_px=q.page_w_px,
        page_h_px=q.page_h_px,
        page_count=q.page_count,
        dpi=q.dpi,
        markers=PackMarkers(
            aruco_dict=settings.ARUCO_DICT,
            marker_size_px=settings.MARKER_SIZE_PX,
            marker_margin_px=settings.MARKER_MARGIN_PX,
            centres=centres,
        ),
        boxes=boxes,
    )


# ── 2. Pack images ──────────────────────────────────────────────────

@router.get("/assignments/{question_id}/pack/images/{kind}/{image_id}")
def get_pack_image(
    question_id: str,
    kind: str,
    image_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """A model-answer image or question figure named by the pack. It must
    belong to this paper."""
    q = _finalized_question_for_student(question_id, db, user)

    if kind == "model-answer":
        img = (
            db.query(GroundTruthImage)
            .join(GroundTruthBox, GroundTruthBox.id == GroundTruthImage.ground_truth_box_id)
            .filter(GroundTruthImage.id == image_id, GroundTruthBox.question_id == q.id)
            .first()
        )
    elif kind == "question":
        img = (
            db.query(UploadedImage)
            .filter(UploadedImage.id == image_id, UploadedImage.question_id == q.id)
            .first()
        )
    else:
        img = None

    if img is None or not img.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Image not found")
    return Response(content=bytes(img.data), media_type=img.content_type or "image/png")


# ── 5. My grades (used by 4 as well) ────────────────────────────────

def _grades_payload(db: Session, sub: Submission) -> OnDeviceGradesOut:
    boxes = (
        db.query(AnswerBox)
        .filter(AnswerBox.question_id == sub.question_id)
        .order_by(AnswerBox.order_index)
        .all()
    )
    rows = {
        g.answer_box_id: g
        for g in db.query(AnswerGrade).filter(AnswerGrade.submission_id == sub.id).all()
    }
    totals = submission_totals(db, sub.id)

    out_boxes = []
    for box in boxes:
        g = rows.get(box.id)
        out_boxes.append(
            OnDeviceBoxGrade(
                answer_box_id=box.id,
                label=box.label,
                order_index=box.order_index,
                max_score=g.max_score if g else box.points,
                score=g.score if g else None,
                feedback=(g.override_feedback or g.llm_feedback) if g else None,
                provider=g.provider if g else None,
                needs_manual_review=bool(g and g.needs_manual_review),
                review_reason=g.review_reason if g else None,
                pending_fallback=bool(g and on_device.is_pending(g, sub)),
            )
        )

    released = sub.released_at is not None
    return OnDeviceGradesOut(
        submission_id=sub.id,
        question_id=sub.question_id,
        grading_status=sub.grading_status,
        grading_error=sub.grading_error,
        released=released,
        provisional=not released,
        earned=totals["earned"],
        max_score=totals["max"],
        graded_count=totals["graded_count"],
        needs_review_count=totals["needs_review_count"],
        pending_fallback_count=sum(1 for b in out_boxes if b.pending_fallback),
        run=OnDeviceRunInfo(
            started_at=sub.on_device_started_at,
            posted_at=sub.on_device_posted_at,
            lease_expires_at=on_device.lease_expires_at(sub),
        ),
        boxes=out_boxes,
    )


@router.get("/submissions/{submission_id}/grades", response_model=OnDeviceGradesOut)
def get_my_grades(
    submission_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    The student's own marks, **provisional until released**.

    A deliberate exception to the rule that a student sees no mark before
    release: the phone produced these marks in front of them, so hiding
    them would hide nothing. `provisional` stays true until the teacher
    releases; only released marks are official. Every existing student
    route is still release-only.
    """
    sub = _own_submission(submission_id, db, user)
    on_device.expire_stale_runs(db, submission_id=sub.id)
    db.refresh(sub)
    return _grades_payload(db, sub)


# ── 3. Start ────────────────────────────────────────────────────────

@router.post("/submissions/{submission_id}/on-device/start", response_model=OnDeviceRunStarted)
@limiter.limit(LLM_LIMIT)
def start_on_device_run(
    request: Request,
    submission_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Begin (or resume) grading on the phone.

    Needs the script handed in. Allowed when nothing is running, after a
    failed or expired run, or over the student's own unposted run, which
    it replaces with a new token. Refused (409) once released or graded
    (ask for re-evaluation instead), while a teacher-started server run
    is queued or grading, and while the server is re-marking this run's
    flagged boxes.
    """
    sub = _own_submission(submission_id, db, user)
    on_device.expire_stale_runs(db, submission_id=sub.id)
    db.refresh(sub)

    if sub.submitted_at is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Hand this in before grading it")
    if sub.released:
        raise HTTPException(status.HTTP_409_CONFLICT, "These marks have already been released")
    if sub.grading_status == "graded":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This has already been graded. Ask for re-evaluation instead",
        )
    if sub.grading_status == "queued" or (
        sub.grading_status == "grading" and sub.on_device_started_at is None
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, "Your teacher is grading this on the website")
    if sub.grading_status == "grading" and sub.on_device_posted_at is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The server is still re-marking some answers from this run",
        )

    token = on_device.start_run(db, sub)
    eligible, protected = on_device.eligible_box_ids(db, sub)
    return OnDeviceRunStarted(
        run_token=token,
        started_at=sub.on_device_started_at,
        lease_expires_at=on_device.lease_expires_at(sub),
        eligible_box_ids=eligible,
        protected_box_ids=protected,
    )


# ── 4. Results ──────────────────────────────────────────────────────

def _fallback_state(db: Session, sub: Submission, payload: OnDeviceGradesOut) -> tuple[str, str | None]:
    if payload.pending_fallback_count:
        return "scheduled", (
            f"The server is re-marking {payload.pending_fallback_count} answer(s). "
            "They fill in when ready."
        )
    if any(b.review_reason == on_device.FALLBACK_UNAVAILABLE for b in payload.boxes):
        return "unavailable", (
            "Server re-marking is unavailable, so the flagged answers were sent "
            "to your teacher for review."
        )
    if any(b.provider == on_device.PROVIDER_FALLBACK for b in payload.boxes):
        return "completed", None
    return "none", None


def _results_payload(db: Session, sub: Submission) -> OnDeviceResultsOut:
    payload = _grades_payload(db, sub)
    fallback, message = _fallback_state(db, sub, payload)
    return OnDeviceResultsOut(**payload.model_dump(), fallback=fallback, fallback_message=message)


def _bad_request(message: str, **extra) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, {"message": message, **extra})


@router.post(
    "/submissions/{submission_id}/on-device/results",
    response_model=OnDeviceResultsOut,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(LLM_LIMIT)
def post_on_device_results(
    request: Request,
    submission_id: str,
    body: OnDeviceResultsIn,
    background: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Save the phone's marks for every eligible box, in one call.

    Needs the live token from start (409 if superseded or expired).
    Posting again with the same token changes nothing and returns the
    current marks with 200. The server works out the eligible boxes
    itself (every box minus released or teacher-decided ones) and
    refuses a post that leaves any out (400, `missing_box_ids`). Results
    for protected boxes are ignored. A score must lie in 0..points; the
    server never clamps.

    Boxes in `fallback_box_ids` are re-marked by the server's
    self-hosted model in the background when the app allows it and
    SELF_HOSTED_LLM_URL is set; the paper stays "grading" until that
    finishes. Otherwise they go to teacher review with reason
    "Fallback unavailable". The teacher is notified when the paper is
    graded.
    """
    sub = _own_submission(submission_id, db, user)
    on_device.expire_stale_runs(db, submission_id=sub.id)
    db.refresh(sub)

    if not sub.on_device_run_token or body.run_token != sub.on_device_run_token:
        raise HTTPException(status.HTTP_409_CONFLICT, "This grading run was superseded or has expired")
    if sub.on_device_posted_at is not None:
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content=_results_payload(db, sub).model_dump(mode="json"),
        )
    if not on_device.is_phone_run_active(sub):
        raise HTTPException(status.HTTP_409_CONFLICT, "This grading run is no longer active")
    if on_device.utcnow() >= on_device.lease_expires_at(sub):
        raise HTTPException(status.HTTP_409_CONFLICT, "This grading run has expired")

    boxes = {b.id: b for b in db.query(AnswerBox).filter(AnswerBox.question_id == sub.question_id)}
    eligible, protected = on_device.eligible_box_ids(db, sub)
    eligible_set, protected_set = set(eligible), set(protected)

    posted_ids = [r.answer_box_id for r in body.results]
    unknown = sorted({i for i in posted_ids if i not in boxes})
    if unknown:
        raise _bad_request("Unknown answer boxes", unknown_box_ids=unknown)
    duplicates = sorted({i for i in posted_ids if posted_ids.count(i) > 1})
    if duplicates:
        raise _bad_request("Answer boxes posted more than once", duplicate_box_ids=duplicates)

    results = {r.answer_box_id: r for r in body.results if r.answer_box_id in eligible_set}
    missing = [i for i in eligible if i not in results]
    if missing:
        raise _bad_request("Every eligible answer box needs a result", missing_box_ids=missing)

    for box_id, r in results.items():
        points = boxes[box_id].points
        if r.outcome != "scored" or points is None:
            continue  # a box with no marks set is blocked and saved for review
        if r.score is None or not (0 <= r.score <= points):
            raise _bad_request(
                f"Score for {box_id} must be between 0 and {points}",
                answer_box_id=box_id,
            )

    fallback_ids = set(body.fallback_box_ids)
    stray = sorted(fallback_ids - eligible_set - protected_set)
    if stray:
        raise _bad_request("Fallback boxes must be eligible answer boxes", unknown_box_ids=stray)
    fallback_ids -= protected_set

    fallback_available = body.use_fallback and bool(settings.SELF_HOSTED_LLM_URL)
    pending = on_device.save_results(db, sub, results, fallback_ids, fallback_available)

    if pending:
        db.commit()
        background.add_task(on_device.run_fallback, sub.id, sub.on_device_run_token, pending)
    else:
        on_device.finish_run(db, sub)
        db.commit()

    db.refresh(sub)
    return _results_payload(db, sub)


# ── 6. Re-evaluation ────────────────────────────────────────────────

@router.post("/submissions/{submission_id}/re-evaluation")
@limiter.limit(REEVALUATION_LIMIT)
def request_reevaluation(
    request: Request,
    submission_id: str,
    body: ReevaluationRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Ask the teacher to look at the marks again. Only once graded
    (provisional or released). Tells the teacher through the bell; no new
    table.
    """
    sub = _own_submission(submission_id, db, user)
    if sub.grading_status != "graded":
        raise HTTPException(status.HTTP_409_CONFLICT, "Wait until this has been graded")

    question = db.query(Question).filter(Question.id == sub.question_id).first()
    course = db.query(Course).filter(Course.id == question.course_id).first()

    labels: list[str] = []
    if body.answer_box_ids:
        boxes = {
            b.id: b for b in db.query(AnswerBox).filter(AnswerBox.question_id == sub.question_id)
        }
        unknown = sorted(set(body.answer_box_ids) - set(boxes))
        if unknown:
            raise _bad_request("Unknown answer boxes", unknown_box_ids=unknown)
        labels = [boxes[i].label or i for i in dict.fromkeys(body.answer_box_ids)]

    paper = question.title or "Untitled paper"
    parts = [f"Parts: {', '.join(labels)}"] if labels else []
    if body.message and body.message.strip():
        parts.append(body.message.strip())

    note = notify(
        db,
        course.teacher_id if course and course.teacher_id != user.id else None,
        kind="reevaluation_requested",
        title=f"{user.display_name} asks for re-evaluation: {paper}",
        body="\n".join(parts) or None,
        link=f"/submissions/{sub.id}",
    )
    db.commit()
    return {"submission_id": sub.id, "notified": note is not None}
