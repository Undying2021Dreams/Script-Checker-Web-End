from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    display_name: str
    role: str


class CourseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class CourseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    join_code: str
    teacher_id: str
    teacher_name: str
    archived: bool
    created_at: datetime
    student_count: int


class CourseSummary(BaseModel):
    """Search results — no join_code, since that's an enrollment credential."""

    id: str
    title: str
    teacher_name: str
    student_count: int


class JoinRequest(BaseModel):
    join_code: str = Field(min_length=1, max_length=32)


class EnrolledStudent(BaseModel):
    id: str
    email: str
    display_name: str
    enrolled_at: datetime


class SubmissionSummary(BaseModel):
    id: str
    question_id: str
    student_id: str | None
    student_name: str | None
    modality: str
    created_at: datetime
    grading_status: str
    released: bool
    # None for a student whose marks haven't been released — the list must
    # not leak what the detail endpoint gates.
    earned: float | None
    max_score: int | None
    needs_review_count: int | None


class StudentAssignment(BaseModel):
    """
    A paper as a student sees it.

    Carries no document content: a Question's content holds the model
    answers inline, so the paper reaches a student only as the rendered
    PDF, which omits them.
    """

    question_id: str
    course_id: str
    total_marks: int
    page_count: int | None
    finalized_at: datetime | None
    submission_id: str | None
    submission_status: str | None
    released: bool
    # Withheld until the teacher releases the marks.
    earned: float | None
    max_score: int | None


# ── Grading ─────────────────────────────────────────────────────────

class GradeRunRequest(BaseModel):
    provider: Literal["gemini", "openai", "claude", "self_hosted"] = "self_hosted"


class GradeOverride(BaseModel):
    # None clears the override and falls back to the model's own mark.
    score: float | None = None
    feedback: str | None = None


class AnswerGradeOut(BaseModel):
    answer_box_id: str
    label: str
    order_index: int
    max_score: int
    # The mark that counts — an override if one was set, else the model's.
    score: float | None
    llm_score: float | None
    override_score: float | None
    feedback: str | None
    provider: str | None
    needs_manual_review: bool
    review_reason: str | None


class SubmissionGradesOut(BaseModel):
    submission_id: str
    question_id: str
    student_id: str | None
    grading_status: str
    grading_error: str | None
    released: bool
    earned: float
    max_score: int
    needs_review_count: int
    grades: list[AnswerGradeOut]


# ── Answer boxes ────────────────────────────────────────────────────

class AnswerBoxIn(BaseModel):
    """What the frontend sends — matches AnswerBoxNode's attrs exactly."""
    id: str
    label: str = ""
    points: int = 1


class AnswerBoxOut(AnswerBoxIn):
    # None until the question is finalized and doc_renderer has measured
    # the actual laid-out position.
    bbox: list[int] | None = None  # [x, y, w, h] in canonical px, page-local
    page_index: int | None = None  # which printed page this box starts on
    segments: list[list[int]] | None = None  # [[page_index, x, y, w, h], ...] for all segments
    # Canonical position of each segment's own printed QR code, index-
    # aligned with `segments` — extractor.py's local per-box registration
    # anchor (see extractor._try_local_registration).
    qr_segments: list[list[int] | None] | None = None


# ── Questions ───────────────────────────────────────────────────────

class QuestionCreate(BaseModel):
    physical_page: str = "A4"
    content: dict[str, Any] | None = None
    answer_boxes: list[AnswerBoxIn] = []


class QuestionContentUpdate(BaseModel):
    """Body for PUT /questions/{id}/blocks (kept path name to match the
    frontend api.js already shipped — this now saves the whole doc, not
    a flat block list)."""
    content: dict[str, Any]
    answer_boxes: list[AnswerBoxIn] = []
    ground_truth_boxes: list[GroundTruthBoxIn] = []


class QuestionOut(BaseModel):
    question_id: str
    course_id: str
    state: str
    physical_page: str
    dpi: int
    content: dict[str, Any] | None
    answer_boxes: list[AnswerBoxOut]
    ground_truth_boxes: list[GroundTruthBoxOut] = []
    question_image_id: str | None = None
    page_w_px: int | None = None
    page_h_px: int | None = None
    page_count: int | None = None
    derived_from: str | None = None
    created_at: str
    finalized_at: str | None = None

    model_config = {"from_attributes": True}


# ── LLM (repurposed — see llm_provider.py in next-part) ─────────────

class RubricSuggestRequest(BaseModel):
    provider: Literal["gemini", "openai", "claude", "self_hosted"]


class CorrectnessCheckRequest(BaseModel):
    provider: Literal["gemini", "openai", "claude", "self_hosted"]
    # None = check every individual question in the paper (all ground
    # truth boxes); set to scope the check to just one.
    ground_truth_box_id: str | None = None


# ── Submissions / Extraction ────────────────────────────────────────

class CropInfo(BaseModel):
    answer_box_id: str
    qr_check: Literal["pass", "fail", "absent"]
    warped_bbox: list[int]  # [x1, y1, x2, y2] in image pixel space
    part: int = 0
    # "local" = registered via this box's own printed QR code (tried only
    # for photo modality, more accurate when it succeeds); "global" =
    # used the whole-page homography/affine/identity transform instead
    # (scanner, tablet, or a photo where local registration wasn't usable).
    registration: Literal["local", "global"] = "global"



class PageExtractionResult(BaseModel):
    page_index: int
    markers_detected: str  # e.g. "4/4"
    transform_type: str    # "homography" | "affine" | "identity" | "none"
    crops: list[CropInfo]
    image_resolution: str | None = None
    image_dpi: int | None = None
    error: str | None = None


class ExtractionResult(BaseModel):
    submission_id: str
    question_id: str
    modality: str
    pages: list[PageExtractionResult]


# ── Extraction, grouped by answer box (not by page) ──────────────────
# ExtractionResult above mirrors how extraction physically happens — one
# photographed page at a time. This mirrors how a consumer (e.g. an LLM
# evaluation call) actually wants it: per answer box, in document order,
# with that box's own multi-page segments already sorted into part order.

class AnswerPartOut(BaseModel):
    part: int
    page_index: int | None = None
    qr_check: Literal["pass", "fail", "absent"] | None = None
    warped_bbox: list[int] | None = None
    registration: Literal["local", "global"] | None = None
    crop_url: str


class GroupedAnswerBoxOut(BaseModel):
    answer_box_id: str
    label: str
    points: int
    order_index: int
    expected_parts: int
    parts: list[AnswerPartOut]
    # True iff every expected part (0..expected_parts-1, from the box's
    # own segments_json recorded at finalize) was actually extracted —
    # false means a page is missing from this submission (never
    # photographed/uploaded, or extraction failed on it).
    complete: bool


class GroupedSubmissionOut(BaseModel):
    submission_id: str
    question_id: str
    modality: str
    answer_boxes: list[GroupedAnswerBoxOut]


class TabletStroke(BaseModel):
    points: list[list[float]]


class TabletSubmission(BaseModel):
    question_id: str
    ink_strokes: list[TabletStroke]


# ── Ground Truth ────────────────────────────────────────────────────

class GroundTruthBoxIn(BaseModel):
    id: str
    label: str = ""


class GroundTruthBoxOut(GroundTruthBoxIn):
    question_id: str | None = None
    question_image_id: str | None = None


class GroundTruthImageOut(BaseModel):
    id: str
    ground_truth_box_id: str
    content_type: str
    page_index: int | None = None
    created_at: str

    model_config = {"from_attributes": True}
