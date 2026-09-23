"""
Being let into a course, and being told what happened.

Joining by code is unchanged and stays the quick path — a teacher who
reads a code out in class has already decided who is in the room. These
cover the other way in, and the bell that reports it.
"""

import pytest

from models import Course, Enrollment, EnrollmentRequest, Notification


@pytest.fixture
def course(db, make_user):
    teacher = make_user(role="teacher")
    course = Course(title="Numerical Methods", join_code="REQ001", teacher_id=teacher.id)
    db.add(course)
    db.commit()
    db.refresh(course)
    course.teacher = teacher
    return course


def test_a_student_asks_and_the_teacher_decides(client, course, db, make_user):
    student = make_user()

    asked = client.as_user(student).post(f"/api/courses/{course.id}/request-join")
    assert asked.status_code == 200, asked.text
    assert asked.json()["status"] == "pending"

    # The teacher is told, and sees it waiting.
    assert db.query(Notification).filter(
        Notification.user_id == course.teacher.id, Notification.kind == "join_request"
    ).count() == 1

    waiting = client.as_user(course.teacher).get(f"/api/courses/{course.id}/join-requests")
    assert [r["student_id"] for r in waiting.json()] == [student.id]

    request_id = waiting.json()[0]["id"]
    done = client.as_user(course.teacher).post(
        f"/api/courses/{course.id}/join-requests/{request_id}", params={"approve": True}
    )
    assert done.status_code == 200, done.text
    assert done.json()["status"] == "approved"

    # Enrolled, told about it, and no longer waiting.
    assert db.query(Enrollment).filter(
        Enrollment.course_id == course.id, Enrollment.student_id == student.id
    ).count() == 1
    assert db.query(Notification).filter(
        Notification.user_id == student.id, Notification.kind == "join_decision"
    ).count() == 1
    assert client.as_user(course.teacher).get(
        f"/api/courses/{course.id}/join-requests"
    ).json() == []


def test_asking_twice_does_not_make_two_requests(client, course, db, make_user):
    """Pressing the button repeatedly must not flood a teacher's list."""
    student = make_user()
    for _ in range(3):
        assert client.as_user(student).post(
            f"/api/courses/{course.id}/request-join"
        ).status_code == 200

    assert db.query(EnrollmentRequest).filter(
        EnrollmentRequest.course_id == course.id
    ).count() == 1
    assert len(client.as_user(course.teacher).get(
        f"/api/courses/{course.id}/join-requests"
    ).json()) == 1


def test_only_the_courses_teacher_sees_or_decides_requests(client, course, db, make_user):
    student = make_user()
    outsider = make_user(role="teacher")
    client.as_user(student).post(f"/api/courses/{course.id}/request-join")
    req = db.query(EnrollmentRequest).one()

    # 404, not 403: whose course this is should not be confirmable by
    # poking at ids.
    assert client.as_user(outsider).get(
        f"/api/courses/{course.id}/join-requests"
    ).status_code == 404
    assert client.as_user(student).get(
        f"/api/courses/{course.id}/join-requests"
    ).status_code == 404
    assert client.as_user(outsider).post(
        f"/api/courses/{course.id}/join-requests/{req.id}", params={"approve": True}
    ).status_code == 404
    assert db.query(Enrollment).count() == 0


def test_search_says_where_you_already_stand(client, course, db, make_user):
    """
    So the button can say the right thing without a request per row.
    """
    student = make_user()
    found = client.as_user(student).get("/api/courses/search", params={"q": "Numerical"})
    assert found.json()[0]["my_status"] == "none"

    client.as_user(student).post(f"/api/courses/{course.id}/request-join")
    found = client.as_user(student).get("/api/courses/search", params={"q": "Numerical"})
    assert found.json()[0]["my_status"] == "pending"

    db.add(Enrollment(course_id=course.id, student_id=student.id))
    db.commit()
    found = client.as_user(student).get("/api/courses/search", params={"q": "Numerical"})
    assert found.json()[0]["my_status"] == "enrolled"

    mine = client.as_user(course.teacher).get("/api/courses/search", params={"q": "Numerical"})
    assert mine.json()[0]["my_status"] == "teaching"


def test_notifications_are_your_own_and_reading_clears_the_count(client, db, make_user):
    mine = make_user()
    theirs = make_user()
    db.add_all([
        Notification(user_id=mine.id, kind="x", title="first"),
        Notification(user_id=mine.id, kind="x", title="second"),
        Notification(user_id=theirs.id, kind="x", title="not yours"),
    ])
    db.commit()

    seen = client.as_user(mine).get("/api/notifications").json()
    assert seen["unread"] == 2
    assert {i["title"] for i in seen["items"]} == {"first", "second"}

    one = seen["items"][0]["id"]
    after = client.as_user(mine).post("/api/notifications/read", params={"notification_id": one})
    assert after.json()["unread"] == 1

    assert client.as_user(mine).post("/api/notifications/read").json()["unread"] == 0
    # Someone else's is untouched.
    assert client.as_user(theirs).get("/api/notifications").json()["unread"] == 1


def test_a_person_may_correct_their_own_name_but_not_their_role(client, db, make_user):
    """
    The name arrives from Entra ID — often an initial and a surname —
    and it appears beside every mark, so people may fix it. Role and
    email are not theirs to change: either would be a way to grant
    yourself a course.
    """
    person = make_user()
    res = client.as_user(person).patch(
        "/api/me",
        json={"display_name": "Ada Lovelace", "institution": "BUET", "role": "admin"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["display_name"] == "Ada Lovelace"
    assert res.json()["institution"] == "BUET"
    # The role in the body was ignored, not applied.
    assert res.json()["role"] != "admin"

    # And it actually reached the database, rather than only the reply.
    db.expire_all()
    from models import User

    stored = db.query(User).filter(User.id == person.id).one()
    assert stored.display_name == "Ada Lovelace"
    assert stored.institution == "BUET"
    assert stored.role != "admin"

    assert client.as_user(person).patch("/api/me", json={"display_name": "  "}).status_code == 400
