def _create_course(client, teacher, title="Numerical Methods"):
    res = client.as_user(teacher).post("/api/courses", json={"title": title})
    assert res.status_code == 201, res.text
    return res.json()


def test_teacher_creates_course_and_gets_a_join_code(client, make_user):
    teacher = make_user(role="teacher")
    course = _create_course(client, teacher)

    assert course["title"] == "Numerical Methods"
    assert course["teacher_id"] == teacher.id
    assert course["student_count"] == 0
    assert len(course["join_code"]) == 6
    # Ambiguous characters are excluded so the code survives being read aloud
    assert not set(course["join_code"]) & set("01OIL")


def test_anyone_may_start_a_course_of_their_own(client, make_user):
    """
    Creating a course makes you the teacher of that course and nothing
    else — every other permission is checked against the course itself.
    """
    student = make_user(role="student")
    res = client.as_user(student).post("/api/courses", json={"title": "Reading group"})
    assert res.status_code == 201, res.text
    assert res.json()["my_role"] == "teacher"


def test_course_creation_can_be_closed_to_configured_teachers(client, make_user, monkeypatch):
    """
    The deployment accepts any Microsoft account, so on a public URL the
    owner may want the door shut. Keys here are free-tier, which makes
    the exposure a burnt quota rather than a bill — but a stranger
    exhausting it before a demo is reason enough to keep the switch.
    """
    from config import settings

    monkeypatch.setattr(settings, "OPEN_COURSE_CREATION", False)

    student = make_user(role="student")
    assert client.as_user(student).post("/api/courses", json={"title": "Sneaky"}).status_code == 403

    teacher = make_user(role="teacher")
    assert client.as_user(teacher).post("/api/courses", json={"title": "Fine"}).status_code == 201


def test_join_codes_are_unique_across_courses(client, make_user):
    teacher = make_user(role="teacher")
    codes = {_create_course(client, teacher, f"Course {i}")["join_code"] for i in range(15)}
    assert len(codes) == 15


def test_student_joins_with_code_then_sees_the_course(client, make_user):
    teacher = make_user(role="teacher")
    student = make_user(role="student")
    course = _create_course(client, teacher)

    res = client.as_user(student).post("/api/courses/join", json={"join_code": course["join_code"]})
    assert res.status_code == 200
    assert res.json()["student_count"] == 1

    listed = client.as_user(student).get("/api/courses").json()
    assert [c["id"] for c in listed] == [course["id"]]


def test_join_code_is_case_insensitive_and_trimmed(client, make_user):
    teacher = make_user(role="teacher")
    student = make_user(role="student")
    course = _create_course(client, teacher)

    res = client.as_user(student).post(
        "/api/courses/join", json={"join_code": f"  {course['join_code'].lower()}  "}
    )
    assert res.status_code == 200


def test_joining_twice_does_not_duplicate_enrollment(client, make_user):
    teacher = make_user(role="teacher")
    student = make_user(role="student")
    course = _create_course(client, teacher)

    for _ in range(2):
        res = client.as_user(student).post(
            "/api/courses/join", json={"join_code": course["join_code"]}
        )
        assert res.status_code == 200

    assert res.json()["student_count"] == 1


def test_bad_join_code_is_rejected(client, make_user):
    student = make_user(role="student")
    res = client.as_user(student).post("/api/courses/join", json={"join_code": "ZZZZZZ"})
    assert res.status_code == 404


def test_teacher_cannot_join_own_course(client, make_user):
    teacher = make_user(role="teacher")
    course = _create_course(client, teacher)
    res = client.as_user(teacher).post("/api/courses/join", json={"join_code": course["join_code"]})
    assert res.status_code == 409


def test_teacher_only_lists_own_courses(client, make_user):
    teacher_a = make_user(role="teacher")
    teacher_b = make_user(role="teacher")
    mine = _create_course(client, teacher_a, "Mine")
    _create_course(client, teacher_b, "Theirs")

    listed = client.as_user(teacher_a).get("/api/courses").json()
    assert [c["id"] for c in listed] == [mine["id"]]


def test_outsider_cannot_view_course(client, make_user):
    teacher = make_user(role="teacher")
    outsider = make_user(role="student")
    course = _create_course(client, teacher)

    res = client.as_user(outsider).get(f"/api/courses/{course['id']}")
    assert res.status_code == 403


def test_enrolled_student_can_view_course(client, make_user):
    teacher = make_user(role="teacher")
    student = make_user(role="student")
    course = _create_course(client, teacher)
    client.as_user(student).post("/api/courses/join", json={"join_code": course["join_code"]})

    res = client.as_user(student).get(f"/api/courses/{course['id']}")
    assert res.status_code == 200


def test_only_teacher_sees_roster(client, make_user):
    teacher = make_user(role="teacher")
    student = make_user(role="student", display_name="Zoe Student")
    course = _create_course(client, teacher)
    client.as_user(student).post("/api/courses/join", json={"join_code": course["join_code"]})

    roster = client.as_user(teacher).get(f"/api/courses/{course['id']}/students").json()
    assert [s["display_name"] for s in roster] == ["Zoe Student"]

    res = client.as_user(student).get(f"/api/courses/{course['id']}/students")
    assert res.status_code == 403


def test_teacher_removes_student(client, make_user):
    teacher = make_user(role="teacher")
    student = make_user(role="student")
    course = _create_course(client, teacher)
    client.as_user(student).post("/api/courses/join", json={"join_code": course["join_code"]})

    res = client.as_user(teacher).delete(f"/api/courses/{course['id']}/students/{student.id}")
    assert res.status_code == 204

    assert client.as_user(teacher).get(f"/api/courses/{course['id']}").json()["student_count"] == 0
    # And the course drops off the student's list
    assert client.as_user(student).get("/api/courses").json() == []


def test_search_finds_courses_by_title_and_teacher(client, make_user):
    teacher = make_user(role="teacher", display_name="Dr Rahman")
    student = make_user(role="student")
    _create_course(client, teacher, "Numerical Methods")
    _create_course(client, teacher, "Discrete Maths")

    by_title = client.as_user(student).get("/api/courses/search", params={"q": "numerical"}).json()
    assert [c["title"] for c in by_title] == ["Numerical Methods"]

    by_teacher = client.as_user(student).get("/api/courses/search", params={"q": "rahman"}).json()
    assert {c["title"] for c in by_teacher} == {"Numerical Methods", "Discrete Maths"}


def test_search_never_leaks_join_codes(client, make_user):
    teacher = make_user(role="teacher")
    student = make_user(role="student")
    _create_course(client, teacher, "Numerical Methods")

    results = client.as_user(student).get("/api/courses/search", params={"q": "numerical"}).json()
    assert results
    # A searchable join code would let anyone enroll in any course
    assert all("join_code" not in c for c in results)


# ── Leaderboard ─────────────────────────────────────────────────────

def _released_result(db, course, question, student, earned, out_of):
    """A released submission worth `earned` of `out_of`."""
    from models import AnswerBox, AnswerGrade, Submission
    from datetime import datetime, timezone
    import uuid

    box_id = f"lb-{uuid.uuid4().hex[:8]}"
    db.add(AnswerBox(id=box_id, question_id=question.id, label="a",
                     points=out_of, order_index=0))
    sub = Submission(question_id=question.id, student_id=student.id,
                     modality="photo", manifest={}, grading_status="graded",
                     released_at=datetime.now(timezone.utc))
    db.add(sub)
    db.flush()
    db.add(AnswerGrade(submission_id=sub.id, answer_box_id=box_id,
                       max_score=out_of, llm_score=earned))
    db.commit()
    return sub


def _course_with_results(db, make_user):
    from models import Course, Enrollment, Question

    teacher = make_user(role="teacher")
    top = make_user(role="student", display_name="Top")
    middle = make_user(role="student", display_name="Middle")

    course = Course(title="NM", join_code="LB0001", teacher_id=teacher.id)
    db.add(course)
    db.commit()
    db.add_all([
        Enrollment(course_id=course.id, student_id=top.id),
        Enrollment(course_id=course.id, student_id=middle.id),
    ])
    q = Question(course_id=course.id, created_by=teacher.id, state="finalized", content={})
    db.add(q)
    db.commit()

    _released_result(db, course, q, top, earned=9, out_of=10)
    _released_result(db, course, q, middle, earned=4, out_of=10)
    return teacher, top, middle, course, q


def test_a_student_sees_their_own_rank_but_not_their_classmates_names(client, db, make_user):
    """
    A ranking that names classmates publishes the standing of whoever is
    last, and they did not ask for that. The distribution and your own
    position carry the motivation without the exposure.
    """
    _, top, middle, course, _ = _course_with_results(db, make_user)

    body = client.as_user(middle).get(f"/api/courses/{course.id}/leaderboard").json()

    assert body["named"] is False
    assert body["my_rank"] == 2
    assert body["ranked"] == 2
    assert body["class_average"] == 6.5

    mine = [e for e in body["entries"] if e["is_me"]]
    assert len(mine) == 1 and mine[0]["display_name"] == "Middle"
    assert [e["display_name"] for e in body["entries"] if not e["is_me"]] == [None]


def test_the_teacher_sees_the_names(client, db, make_user):
    """No new exposure: a teacher can already see every mark in the course."""
    teacher, *_, course, _ = _course_with_results(db, make_user)

    body = client.as_user(teacher).get(f"/api/courses/{course.id}/leaderboard").json()

    assert body["named"] is True
    assert [e["display_name"] for e in body["entries"]] == ["Top", "Middle"]
    assert body["my_rank"] is None


def test_unreleased_marks_are_not_ranked(client, db, make_user):
    """
    A ranking built from unreleased work would leak the order of results
    before anyone had been told their own.
    """
    from models import Submission

    _, top, middle, course, _ = _course_with_results(db, make_user)
    db.query(Submission).filter(Submission.student_id == top.id).update({"released_at": None})
    db.commit()

    body = client.as_user(middle).get(f"/api/courses/{course.id}/leaderboard").json()
    assert body["ranked"] == 1
    assert body["my_rank"] == 1


def test_an_outsider_cannot_read_the_leaderboard(client, db, make_user):
    _, _, _, course, _ = _course_with_results(db, make_user)
    outsider = make_user(role="student")
    assert client.as_user(outsider).get(f"/api/courses/{course.id}/leaderboard").status_code in (403, 404)


def test_popular_courses_are_ordered_by_enrolment(client, db, make_user):
    _, _, _, course, _ = _course_with_results(db, make_user)
    from models import Course

    quiet = Course(title="Quiet", join_code="LB0002", teacher_id=course.teacher_id)
    db.add(quiet)
    db.commit()

    body = client.as_user(make_user(role="student")).get("/api/courses/popular").json()
    titles = [c["title"] for c in body]
    assert titles.index("NM") < titles.index("Quiet")
