"""
Authorization tests for the ported question/submission/file routes.

Component-1 was a single-user test harness with no auth at all, so these
rules are new here and are exactly what a shared deployment gets wrong
quietly: another teacher reading your answer key, a student reading
another student's scanned work.
"""

import pytest

from models import Course, CropImage, Enrollment, Question, Submission


@pytest.fixture
def course(db, make_user):
    teacher = make_user(role="teacher")
    course = Course(title="Numerical Methods", join_code="ABC123", teacher_id=teacher.id)
    db.add(course)
    db.commit()
    db.refresh(course)
    course.teacher = teacher  # convenience for tests
    return course


@pytest.fixture
def question(db, course):
    q = Question(course_id=course.id, created_by=course.teacher_id, state="finalized")
    db.add(q)
    db.commit()
    db.refresh(q)
    return q


def _enrol(db, course, student):
    db.add(Enrollment(course_id=course.id, student_id=student.id))
    db.commit()


def test_teacher_creates_question_in_own_course(client, course, db):
    res = client.as_user(course.teacher).post(
        "/api/questions", params={"course_id": course.id}, json={}
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["course_id"] == course.id
    assert body["state"] == "draft"


def test_teacher_cannot_create_question_in_another_teachers_course(client, course, make_user):
    other = make_user(role="teacher")
    res = client.as_user(other).post("/api/questions", params={"course_id": course.id}, json={})
    assert res.status_code == 403


def test_student_cannot_create_questions(client, course, make_user, db):
    student = make_user(role="student")
    _enrol(db, course, student)
    res = client.as_user(student).post("/api/questions", params={"course_id": course.id}, json={})
    assert res.status_code == 403


def test_questions_are_listed_per_course_not_globally(client, course, make_user, db):
    other_teacher = make_user(role="teacher")
    other_course = Course(title="Other", join_code="ZZZ999", teacher_id=other_teacher.id)
    db.add(other_course)
    db.commit()

    mine = client.as_user(course.teacher).post(
        "/api/questions", params={"course_id": course.id}, json={}
    ).json()
    client.as_user(other_teacher).post(
        "/api/questions", params={"course_id": other_course.id}, json={}
    )

    listed = client.as_user(course.teacher).get(
        "/api/questions", params={"course_id": course.id}
    ).json()
    assert [q["question_id"] for q in listed] == [mine["question_id"]]


def test_another_teacher_cannot_read_your_question(client, question, make_user):
    other = make_user(role="teacher")
    res = client.as_user(other).get(f"/api/questions/{question.id}")
    # 404 not 403 — an outsider shouldn't be able to confirm the id exists
    assert res.status_code == 404


def test_enrolled_student_cannot_reach_authoring_routes(client, course, question, make_user, db):
    student = make_user(role="student")
    _enrol(db, course, student)

    # Authoring is teacher work, and QuestionOut carries ground-truth boxes
    # (the answer key), so students must not reach it at all.
    assert client.as_user(student).get(f"/api/questions/{question.id}").status_code == 403
    assert client.as_user(student).post(f"/api/questions/{question.id}/finalize").status_code == 403


def test_enrolled_student_may_submit_but_outsider_may_not(client, course, question, make_user, db):
    student = make_user(role="student")
    outsider = make_user(role="student")
    _enrol(db, course, student)

    # A file has to be attached or request validation (422) short-circuits
    # before the authorization check ever runs. The bytes aren't a real
    # image, but extraction reports that in the page result rather than
    # raising, so the enrolled student still gets a 200 while the outsider
    # is refused outright.
    def _submit(as_user):
        return client.as_user(as_user).post(
            "/api/submissions",
            data={"question_id": question.id, "modality": "photo"},
            files={"image": ("page.png", b"not-an-image", "image/png")},
        )

    assert _submit(student).status_code == 200
    assert _submit(outsider).status_code == 404


def test_student_cannot_read_another_students_submission(client, course, question, make_user, db):
    mine = make_user(role="student")
    theirs = make_user(role="student")
    _enrol(db, course, mine)
    _enrol(db, course, theirs)

    sub = Submission(question_id=question.id, student_id=theirs.id, modality="photo", manifest={})
    db.add(sub)
    db.commit()

    assert client.as_user(mine).get(f"/api/submissions/{sub.id}").status_code == 404
    assert client.as_user(theirs).get(f"/api/submissions/{sub.id}").status_code == 200


def test_teacher_can_read_their_courses_submissions(client, course, question, make_user, db):
    student = make_user(role="student")
    _enrol(db, course, student)
    sub = Submission(question_id=question.id, student_id=student.id, modality="photo", manifest={})
    db.add(sub)
    db.commit()

    assert client.as_user(course.teacher).get(f"/api/submissions/{sub.id}").status_code == 200


def test_crops_are_not_readable_by_other_students(client, course, question, make_user, db):
    owner = make_user(role="student")
    snooper = make_user(role="student")
    _enrol(db, course, owner)
    _enrol(db, course, snooper)

    sub = Submission(question_id=question.id, student_id=owner.id, modality="photo", manifest={})
    db.add(sub)
    db.flush()
    db.add(CropImage(submission_id=sub.id, answer_box_id="box-1", part=0, data=b"PNGDATA"))
    db.commit()

    url = f"/api/crops/{sub.id}/box-1"
    assert client.as_user(snooper).get(url).status_code == 404
    assert client.as_user(owner).get(url).status_code == 200
    assert client.as_user(course.teacher).get(url).status_code == 200


def test_uploaded_images_are_inlined_for_rendering(db, course):
    """
    The renderer's headless browser has no session, and image serving
    requires auth, so a linked image would 401 and vanish from the
    printed paper. Inlining as data: URIs is what keeps figures on the
    page — and keeps rendering independent of the app reaching itself.
    """
    from models import UploadedImage
    from routers.questions import _inline_uploaded_images

    q = Question(course_id=course.id, created_by=course.teacher_id, state="draft")
    db.add(q)
    db.flush()
    img = UploadedImage(question_id=q.id, filename="fig.png", content_type="image/png", data=b"PNGBYTES")
    db.add(img)
    db.commit()

    doc = {
        "type": "doc",
        "content": [
            {"type": "image", "attrs": {"src": f"http://localhost:8000/api/images/{img.id}"}},
            {"type": "paragraph", "content": [{"type": "text", "text": "hi"}]},
        ],
    }
    inlined = _inline_uploaded_images(doc, db)

    src = inlined["content"][0]["attrs"]["src"]
    assert src.startswith("data:image/png;base64,")
    assert "/api/images/" not in src
    # Everything else is left alone.
    assert inlined["content"][1] == doc["content"][1]


def test_inlining_leaves_external_images_alone(db, course):
    from routers.questions import _inline_uploaded_images

    doc = {"type": "doc", "content": [{"type": "image", "attrs": {"src": "https://example.com/x.png"}}]}
    assert _inline_uploaded_images(doc, db)["content"][0]["attrs"]["src"] == "https://example.com/x.png"
