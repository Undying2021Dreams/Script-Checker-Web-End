"""
Authorization tests for the ported question/submission/file routes.

Component-1 was a single-user test harness with no auth at all, so these
rules are new here and are exactly what a shared deployment gets wrong
quietly: another teacher reading your answer key, a student reading
another student's scanned work.
"""

import pytest

from models import AnswerBox, Course, CropImage, Enrollment, Question, Submission


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


def test_every_render_path_gets_images_inlined(client, course, db, monkeypatch):
    """
    Each render call must be handed inlined content, not just the PDF one.

    The renderer's browser can't authenticate, so a linked image 401s and
    the render falls back to the img tag's alt text — which is the
    original filename. That looked like "the preview shows a file name".
    Fixing only the PDF path left the question and model-answer previews
    still broken, so this asserts on all of them rather than the symptom.
    """
    from models import GroundTruthBox, UploadedImage

    q = Question(course_id=course.id, created_by=course.teacher_id, state="draft")
    db.add(q)
    db.flush()
    # id is assigned on flush, so set it explicitly — the src below is
    # built from it before anything is written.
    img = UploadedImage(id="11111111-2222-3333-4444-555555555555", question_id=q.id,
                        filename="diagram.png", content_type="image/png", data=b"PNGBYTES")
    db.add(img)

    figure = {"type": "image", "attrs": {"src": f"http://localhost:8000/api/images/{img.id}"}}
    q.content = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Sketch it."}]},
            figure,
            {"type": "answerBox", "attrs": {"id": "rb1", "label": "a", "points": 5}},
            {"type": "groundTruthBox", "attrs": {"id": "rg1", "label": "Sol"}},
        ],
    }
    db.add(GroundTruthBox(id="rg1", question_id=q.id, order_index=0, content={"type": "doc", "content": [figure]}))
    db.add(AnswerBox(id="rb1", question_id=q.id, label="a", points=5, order_index=0))
    db.commit()

    seen: dict[str, list] = {"question": [], "ground_truth": [], "pdf": []}

    def _srcs(node, out):
        if isinstance(node, list):
            for n in node:
                _srcs(n, out)
        elif isinstance(node, dict):
            if node.get("type") == "image":
                out.append((node.get("attrs") or {}).get("src", ""))
            _srcs(node.get("content") or [], out)
        return out

    def fake_question_image(content, **kwargs):
        seen["question"].extend(_srcs(content, []))
        return b"PNG"

    def fake_gt_image(content):
        seen["ground_truth"].extend(_srcs(content, []))
        return b"PNG"

    def fake_finalize(question_dict):
        seen["pdf"].extend(_srcs(question_dict.get("content"), []))
        return {"page_w_px": 794, "page_h_px": 1123, "page_count": 1,
                # boxes maps a box id to its segments, each [page, x, y, w, h]
                "boxes": {"rb1": [[0, 10, 20, 100, 50]]}, "pdf_data": b"%PDF-"}

    import services.doc_renderer as dr
    monkeypatch.setattr(dr, "render_question_to_image", fake_question_image)
    monkeypatch.setattr(dr, "render_ground_truth_box_to_image", fake_gt_image)
    monkeypatch.setattr(dr, "render_finalized_question", fake_finalize)

    res = client.as_user(course.teacher).post(f"/api/questions/{q.id}/finalize")
    assert res.status_code == 200, res.text

    for path, srcs in seen.items():
        assert srcs, f"{path} render received no images at all"
        for src in srcs:
            assert src.startswith("data:"), f"{path} render got a linked image the browser can't fetch: {src}"
