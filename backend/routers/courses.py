import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from database import get_db
from models import (
    AnswerGrade,
    Course,
    Enrollment,
    EnrollmentRequest,
    Question,
    Submission,
    User,
)
from schemas import (
    EnrollmentRequestOut,
    LeaderboardEntry,
    LeaderboardOut,
    CourseCreate,
    CourseOut,
    CourseSummary,
    EnrolledStudent,
    JoinRequest,
)
from ratelimit import JOIN_LIMIT, limiter
from security import get_current_user, may_create_courses, require_teacher
from services.notify import notify

router = APIRouter(prefix="/courses", tags=["courses"])

# Excludes 0/O/1/I/L — these get misread when a code is copied off a slide
# or read aloud, and a join code's whole job is to be typed by hand.
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
_CODE_LENGTH = 6


def _generate_join_code(db: Session) -> str:
    for _ in range(20):
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))
        if not db.query(Course.id).filter(Course.join_code == code).first():
            return code
    raise HTTPException(
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Could not allocate a unique join code, please retry",
    )


def _student_counts(db: Session, course_ids: list[str]) -> dict[str, int]:
    if not course_ids:
        return {}
    rows = (
        db.query(Enrollment.course_id, func.count(Enrollment.id))
        .filter(Enrollment.course_id.in_(course_ids))
        .group_by(Enrollment.course_id)
        .all()
    )
    return {course_id: count for course_id, count in rows}


def _to_course_out(course: Course, student_count: int, my_role: str = "student") -> CourseOut:
    return CourseOut(
        id=course.id,
        title=course.title,
        join_code=course.join_code,
        teacher_id=course.teacher_id,
        teacher_name=course.teacher.display_name,
        archived=course.archived,
        created_at=course.created_at,
        student_count=student_count,
        my_role=my_role,
    )


def _get_course_or_404(course_id: str, db: Session) -> Course:
    course = db.query(Course).filter(Course.id == course_id).one_or_none()
    if course is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Course not found")
    return course


def _assert_can_view(course: Course, user: User, db: Session) -> None:
    if course.teacher_id == user.id or user.role == "admin":
        return
    enrolled = (
        db.query(Enrollment.id)
        .filter(Enrollment.course_id == course.id, Enrollment.student_id == user.id)
        .first()
    )
    if not enrolled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not enrolled in this course")


@router.post("", response_model=CourseOut, status_code=status.HTTP_201_CREATED)
def create_course(
    body: CourseCreate,
    user: User = Depends(may_create_courses),
    db: Session = Depends(get_db),
):
    course = Course(
        title=body.title.strip(),
        join_code=_generate_join_code(db),
        teacher_id=user.id,
    )
    db.add(course)
    db.commit()
    db.refresh(course)
    return _to_course_out(course, student_count=0, my_role="teacher")


@router.get("", response_model=list[CourseOut])
def list_my_courses(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Every course this person is part of, each labelled with how.

    Both lists, not one or the other. This used to branch on the global
    role, which meant whoever taught anything could never see a course
    they were taking — the teacher of Numerical Methods may perfectly
    well be a student of Compilers, and the enrolment was simply
    invisible to them.

    Teaching a course you are also enrolled in cannot arise: joining a
    course you teach is refused at the door.
    """
    taught = (
        db.query(Course)
        .filter(Course.teacher_id == user.id)
        .order_by(Course.created_at.desc())
        .all()
    )
    enrolled = (
        db.query(Course)
        .join(Enrollment, Enrollment.course_id == Course.id)
        .filter(Enrollment.student_id == user.id)
        .order_by(Course.created_at.desc())
        .all()
    )

    counts = _student_counts(db, [c.id for c in taught + enrolled])
    return [
        *(_to_course_out(c, counts.get(c.id, 0), "teacher") for c in taught),
        *(_to_course_out(c, counts.get(c.id, 0), "student") for c in enrolled),
    ]


@router.get("/search", response_model=list[CourseSummary])
def search_courses(
    q: str = Query(min_length=1, max_length=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Find a course by title, or by its teacher's name/email.

    Deliberately omits join_code: a student who could search up a code
    could enroll in any course without the teacher handing it out.
    """
    term = f"%{q.strip()}%"
    courses = (
        db.query(Course)
        .join(User, Course.teacher_id == User.id)
        .filter(
            Course.archived.is_(False),
            or_(
                Course.title.ilike(term),
                User.display_name.ilike(term),
                User.email.ilike(term),
            ),
        )
        .order_by(Course.title)
        .limit(50)
        .all()
    )

    counts = _student_counts(db, [c.id for c in courses])
    return [
        CourseSummary(
            id=c.id,
            title=c.title,
            teacher_name=c.teacher.display_name,
            student_count=counts.get(c.id, 0),
            my_status=_my_status(c, db, user),
        )
        for c in courses
    ]


def _my_status(course: Course, db: Session, user: User) -> str:
    """Where the person searching already stands with this course.

    Sent with the result so the button can say the right thing without a
    second request per row — otherwise a search for "physics" is one
    query plus one per course to find out which of them you are already
    in."""
    if course.teacher_id == user.id:
        return "teaching"
    enrolled = (
        db.query(Enrollment.id)
        .filter(Enrollment.course_id == course.id, Enrollment.student_id == user.id)
        .first()
    )
    if enrolled:
        return "enrolled"
    req = (
        db.query(EnrollmentRequest.status)
        .filter(
            EnrollmentRequest.course_id == course.id,
            EnrollmentRequest.student_id == user.id,
        )
        .first()
    )
    if req and req[0] in ("pending", "declined"):
        return req[0]
    return "none"


@router.post("/join", response_model=CourseOut)
@limiter.limit(JOIN_LIMIT)
def join_course(
    request: Request,
    body: JoinRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    code = body.join_code.strip().upper()
    course = db.query(Course).filter(Course.join_code == code).one_or_none()
    if course is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No course found with that join code")
    if course.archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "That course is archived")
    if course.teacher_id == user.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "You teach this course")

    already = (
        db.query(Enrollment.id)
        .filter(Enrollment.course_id == course.id, Enrollment.student_id == user.id)
        .first()
    )
    if not already:
        db.add(Enrollment(course_id=course.id, student_id=user.id))
        db.commit()

    counts = _student_counts(db, [course.id])
    return _to_course_out(course, counts.get(course.id, 0), "student")


@router.post("/{course_id}/request-join", response_model=EnrollmentRequestOut)
def request_to_join(
    course_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Ask a teacher to be let into their course.

    The join code stays the quick path — a teacher who reads a code out
    in class has already decided who is in the room. This is the other
    case: a student finds the course by searching and the teacher has
    never heard of them, so somebody has to say yes.

    One row per student per course, reused if they ask again, so
    pressing the button repeatedly cannot flood a teacher's list.
    """
    course = db.query(Course).filter(Course.id == course_id).one_or_none()
    if course is None or course.archived:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such course")
    if course.teacher_id == user.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "You teach this course")

    already = (
        db.query(Enrollment.id)
        .filter(Enrollment.course_id == course_id, Enrollment.student_id == user.id)
        .first()
    )
    if already:
        raise HTTPException(status.HTTP_409_CONFLICT, "You are already in this course")

    req = (
        db.query(EnrollmentRequest)
        .filter(
            EnrollmentRequest.course_id == course_id,
            EnrollmentRequest.student_id == user.id,
        )
        .one_or_none()
    )
    if req is None:
        req = EnrollmentRequest(course_id=course_id, student_id=user.id)
        db.add(req)
    else:
        # Asking again after a decline is allowed — people do get added
        # late — but it is the same row, so the teacher sees one entry.
        req.status = "pending"
        req.decided_at = None
        req.decided_by = None

    notify(
        db,
        course.teacher_id,
        kind="join_request",
        title=f"{user.display_name} asked to join {course.title}",
        body=user.email,
        link=f"/courses/{course_id}",
    )
    db.commit()
    db.refresh(req)
    return _request_out(req, course, user)


@router.get("/{course_id}/join-requests", response_model=list[EnrollmentRequestOut])
def list_join_requests(
    course_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Who is waiting to be let in. The teacher's own course only."""
    course = _teacher_course_or_404(course_id, db, user)
    rows = (
        db.query(EnrollmentRequest, User)
        .join(User, EnrollmentRequest.student_id == User.id)
        .filter(
            EnrollmentRequest.course_id == course_id,
            EnrollmentRequest.status == "pending",
        )
        .order_by(EnrollmentRequest.created_at.asc())
        .all()
    )
    return [_request_out(req, course, student) for req, student in rows]


@router.post("/{course_id}/join-requests/{request_id}", response_model=EnrollmentRequestOut)
def decide_join_request(
    course_id: str,
    request_id: str,
    approve: bool,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Let a student in, or turn them down. Either way they are told."""
    course = _teacher_course_or_404(course_id, db, user)
    req = (
        db.query(EnrollmentRequest)
        .filter(EnrollmentRequest.id == request_id, EnrollmentRequest.course_id == course_id)
        .one_or_none()
    )
    if req is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such request")

    student = db.query(User).filter(User.id == req.student_id).one()

    req.status = "approved" if approve else "declined"
    req.decided_at = datetime.now(timezone.utc)
    req.decided_by = user.id

    if approve:
        exists = (
            db.query(Enrollment.id)
            .filter(Enrollment.course_id == course_id, Enrollment.student_id == req.student_id)
            .first()
        )
        if not exists:
            db.add(Enrollment(course_id=course_id, student_id=req.student_id))

    notify(
        db,
        req.student_id,
        kind="join_decision",
        title=(
            f"You were added to {course.title}"
            if approve
            else f"Your request to join {course.title} was declined"
        ),
        link=f"/courses/{course_id}" if approve else "/",
    )
    db.commit()
    db.refresh(req)
    return _request_out(req, course, student)


def _teacher_course_or_404(course_id: str, db: Session, user: User) -> Course:
    course = db.query(Course).filter(Course.id == course_id).one_or_none()
    if course is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such course")
    if user.role != "admin" and course.teacher_id != user.id:
        # 404 rather than 403: whose course this is should not be
        # confirmable by poking at ids.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such course")
    return course


def _request_out(req: EnrollmentRequest, course: Course, student: User) -> EnrollmentRequestOut:
    return EnrollmentRequestOut(
        id=req.id,
        course_id=course.id,
        course_title=course.title,
        student_id=student.id,
        student_name=student.display_name,
        student_email=student.email,
        status=req.status,
        created_at=req.created_at,
    )


@router.get("/popular", response_model=list[CourseSummary])
def popular_courses(
    limit: int = Query(6, ge=1, le=24),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),  # noqa: ARG001 — sign-in required
):
    """
    The busiest courses, for somebody who has arrived with no join code
    and nothing to search for yet.

    Enrolment counts only. Nothing here is derived from anyone's marks.
    """
    rows = (
        db.query(Course, func.count(Enrollment.id).label("students"))
        .outerjoin(Enrollment, Enrollment.course_id == Course.id)
        .filter(Course.archived.is_(False))
        .group_by(Course.id)
        .order_by(func.count(Enrollment.id).desc(), Course.title)
        .limit(limit)
        .all()
    )
    return [
        CourseSummary(
            id=c.id,
            title=c.title,
            teacher_name=c.teacher.display_name,
            student_count=students,
        )
        for c, students in rows
    ]


@router.get("/{course_id}/leaderboard", response_model=LeaderboardOut)
def course_leaderboard(
    course_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    How the course is doing, and where the person asking stands in it.

    Two rules decide what this may say.

    Only released marks count. An unreleased mark is not the student's
    to see, and a ranking built from unreleased work would leak the
    order of results before anyone had been told their own.

    Names appear only for the teacher, who can already see every mark, so
    this shows them nothing new. For a student the table is anonymous
    apart from their own row: a ranking that names classmates publishes
    the standing of whoever is last, and they did not ask for that.
    """
    course = _get_course_or_404(course_id, db)
    _assert_can_view(course, user, db)
    is_teacher = course.teacher_id == user.id or user.role == "admin"

    rows = (
        db.query(
            Submission.student_id,
            func.coalesce(
                func.sum(func.coalesce(AnswerGrade.override_score, AnswerGrade.llm_score)), 0.0
            ).label("earned"),
            func.coalesce(func.sum(AnswerGrade.max_score), 0.0).label("out_of"),
        )
        .join(Question, Question.id == Submission.question_id)
        .join(AnswerGrade, AnswerGrade.submission_id == Submission.id)
        .filter(
            Question.course_id == course_id,
            Submission.released_at.isnot(None),
            Submission.student_id.isnot(None),
        )
        .group_by(Submission.student_id)
        .all()
    )

    names = {
        u.id: u.display_name
        for u in db.query(User).filter(User.id.in_([r.student_id for r in rows])).all()
    } if rows else {}

    ordered = sorted(rows, key=lambda r: (-float(r.earned), names.get(r.student_id, "")))

    entries: list[LeaderboardEntry] = []
    my_rank = None
    for i, r in enumerate(ordered, start=1):
        mine = r.student_id == user.id
        if mine:
            my_rank = i
        entries.append(
            LeaderboardEntry(
                rank=i,
                display_name=names.get(r.student_id) if (is_teacher or mine) else None,
                earned=float(r.earned),
                max_score=float(r.out_of),
                is_me=mine,
            )
        )

    average = (
        round(sum(e.earned for e in entries) / len(entries), 2) if entries else None
    )
    return LeaderboardOut(
        entries=entries,
        my_rank=my_rank,
        ranked=len(entries),
        class_average=average,
        named=is_teacher,
    )


@router.get("/{course_id}", response_model=CourseOut)
def get_course(
    course_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    course = _get_course_or_404(course_id, db)
    _assert_can_view(course, user, db)
    counts = _student_counts(db, [course.id])
    return _to_course_out(
        course,
        counts.get(course.id, 0),
        "teacher" if course.teacher_id == user.id else "student",
    )


@router.get("/{course_id}/students", response_model=list[EnrolledStudent])
def list_students(
    course_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    course = _get_course_or_404(course_id, db)
    if course.teacher_id != user.id and user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the course's teacher can see the roster")

    rows = (
        db.query(User, Enrollment.enrolled_at)
        .join(Enrollment, Enrollment.student_id == User.id)
        .filter(Enrollment.course_id == course.id)
        .order_by(User.display_name)
        .all()
    )
    return [
        EnrolledStudent(
            id=student.id,
            email=student.email,
            display_name=student.display_name,
            enrolled_at=enrolled_at,
        )
        for student, enrolled_at in rows
    ]


@router.delete("/{course_id}/students/{student_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_student(
    course_id: str,
    student_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    course = _get_course_or_404(course_id, db)
    if course.teacher_id != user.id and user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the course's teacher can remove students")

    enrollment = (
        db.query(Enrollment)
        .filter(Enrollment.course_id == course.id, Enrollment.student_id == student_id)
        .one_or_none()
    )
    if enrollment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That student isn't enrolled")

    db.delete(enrollment)
    db.commit()
