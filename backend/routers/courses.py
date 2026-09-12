import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from database import get_db
from models import Course, Enrollment, User
from schemas import (
    CourseCreate,
    CourseOut,
    CourseSummary,
    EnrolledStudent,
    JoinRequest,
)
from ratelimit import JOIN_LIMIT, limiter
from security import get_current_user, require_teacher

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
    user: User = Depends(require_teacher),
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
    user: User = Depends(get_current_user),  # noqa: ARG001 — sign-in required to search
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
        )
        for c in courses
    ]


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
