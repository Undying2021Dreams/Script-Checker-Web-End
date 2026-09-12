"""
SQLAlchemy ORM models.

Schema changes are managed with Alembic (see alembic/versions/) — there is
no create_all()-on-startup or hand-rolled migration code here, unlike
Component-1.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    String,
    Integer,
    Float,
    Boolean,
    DateTime,
    ForeignKey,
    Enum as SAEnum,
    JSON,
    LargeBinary,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    """
    A signed-in person. Identity comes from Microsoft Entra ID — there is no
    local password. `azure_oid` is Entra ID's immutable per-user object ID
    (the `oid` claim), which is what we key off of; `email` is display/lookup
    only and can legitimately change on the Microsoft side.
    """

    __tablename__ = "users"

    id = Column(String, primary_key=True, default=_uuid)
    azure_oid = Column(String, unique=True, nullable=False, index=True)
    email = Column(String, nullable=False, index=True)
    display_name = Column(String, nullable=False)
    role = Column(SAEnum("teacher", "student", "admin", name="user_role"), nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    last_login_at = Column(DateTime, nullable=True)

    courses_taught = relationship("Course", back_populates="teacher")
    enrollments = relationship("Enrollment", back_populates="student", cascade="all, delete-orphan")


class Course(Base):
    __tablename__ = "courses"

    id = Column(String, primary_key=True, default=_uuid)
    title = Column(String, nullable=False)
    # Short, human-typeable code a student enters to self-enroll (e.g. "CS101-F26").
    join_code = Column(String, unique=True, nullable=False, index=True)
    teacher_id = Column(String, ForeignKey("users.id"), nullable=False)
    archived = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)

    teacher = relationship("User", back_populates="courses_taught")
    enrollments = relationship("Enrollment", back_populates="course", cascade="all, delete-orphan")
    questions = relationship("Question", back_populates="course", cascade="all, delete-orphan")


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("course_id", "student_id", name="uq_enrollment_course_student"),)

    id = Column(String, primary_key=True, default=_uuid)
    course_id = Column(String, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    student_id = Column(String, ForeignKey("users.id"), nullable=False)
    enrolled_at = Column(DateTime, default=_utcnow, nullable=False)

    course = relationship("Course", back_populates="enrollments")
    student = relationship("User", back_populates="enrollments")


class Question(Base):
    __tablename__ = "questions"

    id = Column(String, primary_key=True, default=_uuid)
    course_id = Column(String, ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    # Metadata, not printed content — so it stays editable after finalizing.
    title = Column(String, nullable=True)
    state = Column(SAEnum("draft", "finalized", name="question_state"), default="draft", nullable=False)
    physical_page = Column(String, nullable=False, default="A4")
    dpi = Column(Integer, nullable=False, default=150)

    # The whole question body as a Tiptap/ProseMirror JSON document.
    content = Column(JSON, nullable=True)

    # Frozen page dimensions in canonical px — populated by doc_renderer at
    # finalize time (None while draft, since layout isn't known until it's
    # actually rendered).
    page_w_px = Column(Integer, nullable=True)
    page_h_px = Column(Integer, nullable=True)
    page_count = Column(Integer, nullable=True)

    derived_from = Column(String, ForeignKey("questions.id"), nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)
    finalized_at = Column(DateTime, nullable=True)

    course = relationship("Course", back_populates="questions")
    answer_boxes = relationship(
        "AnswerBox",
        back_populates="question",
        cascade="all, delete-orphan",
        order_by="AnswerBox.order_index",
    )
    ground_truth_boxes = relationship(
        "GroundTruthBox",
        back_populates="question",
        cascade="all, delete-orphan",
        order_by="GroundTruthBox.order_index",
    )
    question_images = relationship(
        "QuestionImage",
        back_populates="question",
        cascade="all, delete-orphan",
        order_by="QuestionImage.created_at",
    )


class AnswerBox(Base):
    """
    One row per <answerBox> node embedded in the question's Tiptap doc.

    `id` is NOT auto-generated here — it's assigned client-side when the
    node is inserted in the editor and passed through as-is, so the same id
    threads through: editor node -> this row -> QR payload on the printed
    page -> extraction manifest -> grading.

    bbox_* stay NULL while the question is a draft. doc_renderer fills
    them in at finalize time from the actual rendered layout.
    """

    __tablename__ = "answer_boxes"

    id = Column(String, primary_key=True)
    question_id = Column(String, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    label = Column(String, nullable=True)
    # Null means "not decided yet", which is different from a part worth
    # nothing. Marks come from the marking scheme the teacher writes into
    # the model answer; when that scheme states no figure this stays
    # unset and says so, rather than quietly standing at one mark and
    # marking a ten-mark scheme out of one.
    points = Column(Integer, nullable=True)
    order_index = Column(Integer, nullable=False, default=0)

    # Which printed page this box landed on (0-indexed) — set at finalize,
    # since pagination is a consequence of layout, not something authored.
    page_index = Column(Integer, nullable=True)
    bbox_x = Column(Integer, nullable=True)
    bbox_y = Column(Integer, nullable=True)
    bbox_w = Column(Integer, nullable=True)
    bbox_h = Column(Integer, nullable=True)
    segments_json = Column(JSON, nullable=True)

    # Canonical position of each segment's own printed QR code — parallel
    # array to segments_json (same index = same segment). Lets extractor.py
    # register this specific box using its own nearby QR as a local
    # fiducial instead of only the whole-page homography from the 4
    # far-away corner markers.
    qr_bbox_json = Column(JSON, nullable=True)

    question = relationship("Question", back_populates="answer_boxes")


class Submission(Base):
    __tablename__ = "submissions"

    id = Column(String, primary_key=True, default=_uuid)
    question_id = Column(String, ForeignKey("questions.id"), nullable=False)
    student_id = Column(String, ForeignKey("users.id"), nullable=True)
    modality = Column(SAEnum("tablet", "photo", "scanner", name="submission_modality"), nullable=False)
    original_image_path = Column(String, nullable=True)
    image_width = Column(Integer, nullable=True)
    image_height = Column(Integer, nullable=True)
    image_dpi = Column(Integer, nullable=True)
    manifest = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)

    grading_status = Column(
        SAEnum("ungraded", "queued", "grading", "graded", "failed", name="grading_status"),
        nullable=False,
        default="ungraded",
    )
    grading_error = Column(String, nullable=True)
    graded_at = Column(DateTime, nullable=True)

    # Auto-generated marks stay invisible to the student until a teacher
    # has reviewed them and released the submission deliberately.
    released_at = Column(DateTime, nullable=True)

    question = relationship("Question")
    student = relationship("User", foreign_keys=[student_id])
    grades = relationship("AnswerGrade", back_populates="submission", cascade="all, delete-orphan")


class AnswerGrade(Base):
    """
    One mark per answer box per submission.

    `llm_score` and `override_score` are kept apart on purpose: when a
    student disputes a mark, the record has to show both what the model
    proposed and what the teacher decided. Collapsing them into a single
    column would erase that distinction the first time anyone edits a
    score. `score` (the property below) is what actually counts.
    """

    __tablename__ = "answer_grades"
    __table_args__ = (
        UniqueConstraint("submission_id", "answer_box_id", name="uq_grade_submission_box"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    submission_id = Column(String, ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False)
    answer_box_id = Column(String, ForeignKey("answer_boxes.id", ondelete="CASCADE"), nullable=False)

    max_score = Column(Integer, nullable=False)
    llm_score = Column(Float, nullable=True)
    llm_feedback = Column(String, nullable=True)
    provider = Column(String, nullable=True)
    raw_response = Column(String, nullable=True)

    override_score = Column(Float, nullable=True)
    override_feedback = Column(String, nullable=True)
    overridden_by = Column(String, ForeignKey("users.id"), nullable=True)
    overridden_at = Column(DateTime, nullable=True)

    # Set when the box couldn't be marked automatically — no ground truth
    # to compare against, no extracted crop, or the model call failed.
    # Distinct from a score of 0, which is a real mark.
    needs_manual_review = Column(Boolean, nullable=False, default=False)
    review_reason = Column(String, nullable=True)

    created_at = Column(DateTime, default=_utcnow, nullable=False)

    submission = relationship("Submission", back_populates="grades")
    answer_box = relationship("AnswerBox")

    @property
    def score(self) -> float | None:
        """The mark that counts — a teacher's override wins over the model."""
        return self.override_score if self.override_score is not None else self.llm_score


class UploadedImage(Base):
    __tablename__ = "uploaded_images"

    id = Column(String, primary_key=True, default=_uuid)
    question_id = Column(String, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    filename = Column(String, nullable=False)
    content_type = Column(String, nullable=True)
    data = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)


class SubmissionImage(Base):
    __tablename__ = "submission_images"

    id = Column(String, primary_key=True, default=_uuid)
    submission_id = Column(String, ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False)
    page_index = Column(Integer, nullable=False, default=0)
    content_type = Column(String, nullable=True)
    data = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime, default=_utcnow, nullable=False)


class CropImage(Base):
    __tablename__ = "crop_images"

    id = Column(String, primary_key=True, default=_uuid)
    submission_id = Column(String, ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False)
    answer_box_id = Column(String, nullable=False)
    part = Column(Integer, nullable=False, default=0)
    content_type = Column(String, nullable=False, default="image/png")
    data = Column(LargeBinary, nullable=False)
    qr_check = Column(String, nullable=True)
    warped_bbox = Column(JSON, nullable=True)
    # "local" | "global" — which homography registered this crop.
    registration = Column(String, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)


class QuestionPdf(Base):
    __tablename__ = "question_pdfs"

    id = Column(String, primary_key=True, default=_uuid)
    question_id = Column(String, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False, unique=True)
    data = Column(LargeBinary, nullable=False)
    page_w_px = Column(Integer, nullable=True)
    page_h_px = Column(Integer, nullable=True)
    page_count = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)


class GroundTruthBox(Base):
    __tablename__ = "ground_truth_boxes"

    id = Column(String, primary_key=True, default=_uuid)
    question_id = Column(String, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    label = Column(String, nullable=True)
    order_index = Column(Integer, nullable=False, default=0)
    content = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)

    question = relationship("Question")
    images = relationship(
        "GroundTruthImage",
        back_populates="ground_truth_box",
        cascade="all, delete-orphan",
        order_by="GroundTruthImage.page_index",
    )


class GroundTruthImage(Base):
    __tablename__ = "ground_truth_images"

    id = Column(String, primary_key=True, default=_uuid)
    ground_truth_box_id = Column(String, ForeignKey("ground_truth_boxes.id", ondelete="CASCADE"), nullable=False)
    data = Column(LargeBinary, nullable=False)
    content_type = Column(String, nullable=False, default="image/png")
    page_index = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)

    ground_truth_box = relationship("GroundTruthBox", back_populates="images")


class QuestionImage(Base):
    __tablename__ = "question_images"

    id = Column(String, primary_key=True, default=_uuid)
    question_id = Column(String, ForeignKey("questions.id", ondelete="CASCADE"), nullable=False)
    ground_truth_box_id = Column(String, nullable=True)
    label = Column(String, nullable=True)
    data = Column(LargeBinary, nullable=False)
    content_type = Column(String, nullable=False, default="application/pdf")
    page_w_px = Column(Integer, nullable=True)
    page_h_px = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=_utcnow, nullable=False)

    question = relationship("Question")
