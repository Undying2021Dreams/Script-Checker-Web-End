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


def test_student_cannot_create_a_course(client, make_user):
    student = make_user(role="student")
    res = client.as_user(student).post("/api/courses", json={"title": "Sneaky"})
    assert res.status_code == 403


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
