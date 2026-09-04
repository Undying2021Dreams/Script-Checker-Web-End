"""
Grading pipeline tests.

No real model is involved: a fake provider returns canned replies, so the
pairing, mark arithmetic, failure handling, override rules and release
gating are all verified deterministically. Only the actual model call
needs a live LLM.
"""

import pytest

from models import (
    AnswerBox,
    AnswerGrade,
    Course,
    Enrollment,
    GroundTruthBox,
    Question,
    Submission,
    CropImage,
)
from services.grading import (
    AnswerToGrade,
    grade_one,
    pair_answer_boxes_with_ground_truth,
    parse_grading_response,
)
from services.llm_provider import LLMProvider


class FakeProvider(LLMProvider):
    """Returns a scripted reply per call, or raises if told to."""

    def __init__(self, replies=None, raises=None):
        self.replies = list(replies or [])
        self.raises = raises
        self.calls = []

    async def complete(self, system_prompt, user_text, images):
        self.calls.append({"system": system_prompt, "user": user_text, "images": images})
        if self.raises:
            raise self.raises
        return self.replies.pop(0) if self.replies else "SCORE: 1\nFEEDBACK: ok"

    async def suggest_rubric(self, *a, **k): ...
    async def equation_from_image(self, *a, **k): ...
    async def check_correctness(self, *a, **k): ...


# ── Pairing ─────────────────────────────────────────────────────────

def _doc(*nodes):
    return {"type": "doc", "content": list(nodes)}


def _para(text):
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}


def _answer(box_id):
    return {"type": "answerBox", "attrs": {"id": box_id}}


def _truth(box_id):
    return {"type": "groundTruthBox", "attrs": {"id": box_id}}


def test_pairs_each_answer_box_with_the_following_model_answer():
    doc = _doc(
        _para("Q1"), _answer("a1"), _truth("g1"),
        _para("Q2"), _answer("a2"), _truth("g2"),
    )
    assert pair_answer_boxes_with_ground_truth(doc) == {"a1": "g1", "a2": "g2"}


def test_multiple_answer_boxes_share_one_model_answer():
    # A sub-question with parts (i) and (ii) marked against one answer.
    doc = _doc(_para("Q1"), _answer("a1"), _answer("a2"), _truth("g1"))
    assert pair_answer_boxes_with_ground_truth(doc) == {"a1": "g1", "a2": "g1"}


def test_trailing_answer_box_has_no_model_answer():
    doc = _doc(_para("Q1"), _answer("a1"), _truth("g1"), _para("Q2"), _answer("a2"))
    assert pair_answer_boxes_with_ground_truth(doc) == {"a1": "g1", "a2": None}


def test_pairing_survives_a_missing_document():
    assert pair_answer_boxes_with_ground_truth(None) == {}


# ── Parsing the model's reply ───────────────────────────────────────

def test_parses_a_normal_reply():
    parsed = parse_grading_response("SCORE: 3\nFEEDBACK: Good method, arithmetic slip.", 5)
    assert parsed["score"] == 3
    assert parsed["feedback"] == "Good method, arithmetic slip."
    assert not parsed["parse_error"]


def test_parses_a_decimal_mark():
    assert parse_grading_response("SCORE: 2.5\nFEEDBACK: Half credit.", 5)["score"] == 2.5


def test_unreadable_is_not_a_zero():
    parsed = parse_grading_response("SCORE: UNREADABLE\nFEEDBACK: Photo is blurred.", 5)
    assert parsed["unreadable"] is True
    assert parsed["score"] is None


@pytest.mark.parametrize("reply", [
    "I think this deserves about 4 marks",  # ignored the format
    "SCORE: banana\nFEEDBACK: hmm",
    "",
])
def test_unparseable_replies_are_flagged_not_guessed(reply):
    assert parse_grading_response(reply, 5)["parse_error"] is True


@pytest.mark.parametrize("score", ["9", "-2"])
def test_scores_outside_the_maximum_are_rejected(score):
    # A mark above the maximum is a model error, not a generous grader.
    parsed = parse_grading_response(f"SCORE: {score}\nFEEDBACK: x", 5)
    assert parsed["parse_error"] is True
    assert parsed["score"] is None


# ── Grading a single answer ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_grades_an_answer():
    provider = FakeProvider(["SCORE: 4\nFEEDBACK: Correct approach."])
    item = AnswerToGrade(
        answer_box_id="a1", label="a", max_score=5,
        question_text="Solve 2x+4=10", ground_truth_text="x = 3",
        crops=[(b"PNG", "image/png")],
    )
    result = await grade_one(provider, item)
    assert result["score"] == 4
    assert result["needs_manual_review"] is False


@pytest.mark.asyncio
async def test_answer_with_no_model_answer_is_sent_for_manual_review():
    provider = FakeProvider()
    item = AnswerToGrade(
        answer_box_id="a1", label="", max_score=5,
        question_text="Q", ground_truth_text="",
        crops=[(b"PNG", "image/png")],
        blocked_reason="No model answer is paired with this answer box",
    )
    result = await grade_one(provider, item)
    assert result["needs_manual_review"] is True
    assert result["score"] is None
    assert provider.calls == []  # never wastes a model call on it


@pytest.mark.asyncio
async def test_answer_with_no_extracted_crop_is_sent_for_manual_review():
    provider = FakeProvider()
    item = AnswerToGrade(
        answer_box_id="a1", label="", max_score=5,
        question_text="Q", ground_truth_text="x=3", crops=[],
    )
    result = await grade_one(provider, item)
    assert result["needs_manual_review"] is True
    assert provider.calls == []


@pytest.mark.asyncio
async def test_a_failing_model_call_does_not_raise():
    # One bad answer must not sink a whole class's grading run.
    provider = FakeProvider(raises=RuntimeError("connection reset"))
    item = AnswerToGrade(
        answer_box_id="a1", label="", max_score=5,
        question_text="Q", ground_truth_text="x=3", crops=[(b"PNG", "image/png")],
    )
    result = await grade_one(provider, item)
    assert result["needs_manual_review"] is True
    assert "connection reset" in result["review_reason"]


@pytest.mark.asyncio
async def test_prompt_says_which_images_are_the_model_answer():
    provider = FakeProvider(["SCORE: 1\nFEEDBACK: ok"])
    item = AnswerToGrade(
        answer_box_id="a1", label="", max_score=5,
        question_text="Q", ground_truth_text="",
        ground_truth_images=[(b"GT", "image/png")],
        crops=[(b"S1", "image/png"), (b"S2", "image/png")],
    )
    await grade_one(provider, item)
    call = provider.calls[0]
    # Model answer first, student's work after — and said so explicitly,
    # or the model could mark the answer key against itself.
    assert call["images"] == [(b"GT", "image/png"), (b"S1", "image/png"), (b"S2", "image/png")]
    assert "first 1 image(s) are the official model answer" in call["user"]


# ── End to end through the API ──────────────────────────────────────

@pytest.fixture
def graded_setup(db, make_user, client, monkeypatch):
    """A course with one finalized 2-part question and one submission."""
    teacher = make_user(role="teacher")
    student = make_user(role="student", display_name="Ada")
    course = Course(title="NM", join_code="NM0001", teacher_id=teacher.id)
    db.add(course)
    db.commit()
    db.add(Enrollment(course_id=course.id, student_id=student.id))

    content = _doc(
        _para("Solve 2x+4=10"), _answer("a1"), _truth("g1"),
        _para("Differentiate x^2"), _answer("a2"), _truth("g2"),
    )
    q = Question(course_id=course.id, created_by=teacher.id, state="finalized", content=content)
    db.add(q)
    db.flush()
    db.add(AnswerBox(id="a1", question_id=q.id, label="a", points=5, order_index=0))
    db.add(AnswerBox(id="a2", question_id=q.id, label="b", points=3, order_index=1))
    db.add(GroundTruthBox(id="g1", question_id=q.id, order_index=0, content=_doc(_para("x = 3"))))
    db.add(GroundTruthBox(id="g2", question_id=q.id, order_index=1, content=_doc(_para("2x"))))

    sub = Submission(question_id=q.id, student_id=student.id, modality="photo", manifest={})
    db.add(sub)
    db.flush()
    db.add(CropImage(submission_id=sub.id, answer_box_id="a1", part=0, data=b"CROP1"))
    db.add(CropImage(submission_id=sub.id, answer_box_id="a2", part=0, data=b"CROP2"))
    db.commit()
    db.refresh(sub)

    return {"teacher": teacher, "student": student, "course": course, "question": q, "submission": sub}


def _use_fake_provider(monkeypatch, replies):
    provider = FakeProvider(replies)
    monkeypatch.setattr("routers.grading.get_provider", lambda name: provider)
    return provider


def _grade(client, teacher, submission_id):
    """Trigger grading, then read the result the way a real client polls.

    The POST returns as soon as the run is queued, so its own body is the
    "queued" state, not the marks.
    """
    started = client.as_user(teacher).post(
        f"/api/submissions/{submission_id}/grade", json={"provider": "self_hosted"}
    )
    assert started.status_code == 200, started.text
    assert started.json()["grading_status"] in ("queued", "grading", "graded")
    return client.as_user(teacher).get(f"/api/submissions/{submission_id}/grades")


def test_teacher_grades_a_submission(client, graded_setup, monkeypatch):
    _use_fake_provider(monkeypatch, [
        "SCORE: 5\nFEEDBACK: Correct.",
        "SCORE: 2\nFEEDBACK: Partly right.",
    ])
    sub = graded_setup["submission"]

    res = _grade(client, graded_setup["teacher"], sub.id)
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["grading_status"] == "graded"
    assert body["earned"] == 7  # 5 + 2
    assert body["max_score"] == 8  # 5 + 3
    assert [g["label"] for g in body["grades"]] == ["a", "b"]
    assert body["released"] is False


def test_students_cannot_trigger_grading(client, graded_setup, monkeypatch):
    _use_fake_provider(monkeypatch, [])
    res = client.as_user(graded_setup["student"]).post(
        f"/api/submissions/{graded_setup['submission'].id}/grade", json={"provider": "self_hosted"}
    )
    # Grading costs real money per call, so it's the teacher's alone.
    assert res.status_code == 404


def test_student_cannot_see_marks_before_release(client, graded_setup, monkeypatch):
    _use_fake_provider(monkeypatch, ["SCORE: 5\nFEEDBACK: ok", "SCORE: 3\nFEEDBACK: ok"])
    sub = graded_setup["submission"]
    teacher, student = graded_setup["teacher"], graded_setup["student"]

    _grade(client, teacher, sub.id)

    # An unreviewed machine mark isn't a grade yet.
    assert client.as_user(student).get(f"/api/submissions/{sub.id}/grades").status_code == 403

    client.as_user(teacher).post(f"/api/submissions/{sub.id}/release")

    res = client.as_user(student).get(f"/api/submissions/{sub.id}/grades")
    assert res.status_code == 200
    assert res.json()["earned"] == 8


def test_teacher_override_wins_and_keeps_the_model_score(client, graded_setup, monkeypatch, db):
    _use_fake_provider(monkeypatch, ["SCORE: 5\nFEEDBACK: ok", "SCORE: 3\nFEEDBACK: ok"])
    sub = graded_setup["submission"]
    teacher = graded_setup["teacher"]

    _grade(client, teacher, sub.id)

    res = client.as_user(teacher).patch(
        f"/api/submissions/{sub.id}/grades/a1",
        json={"score": 2, "feedback": "Method was wrong."},
    )
    assert res.status_code == 200
    body = res.json()

    a1 = next(g for g in body["grades"] if g["answer_box_id"] == "a1")
    assert a1["score"] == 2           # the override is what counts
    assert a1["llm_score"] == 5       # but the model's mark is still on record
    assert a1["override_score"] == 2
    assert a1["feedback"] == "Method was wrong."
    assert body["earned"] == 5        # 2 + 3


def test_override_outside_the_maximum_is_rejected(client, graded_setup, monkeypatch):
    _use_fake_provider(monkeypatch, ["SCORE: 5\nFEEDBACK: ok", "SCORE: 3\nFEEDBACK: ok"])
    sub = graded_setup["submission"]
    teacher = graded_setup["teacher"]
    _grade(client, teacher, sub.id)

    res = client.as_user(teacher).patch(f"/api/submissions/{sub.id}/grades/a1", json={"score": 99})
    assert res.status_code == 400


def test_regrading_does_not_undo_a_teachers_override(client, graded_setup, monkeypatch, db):
    _use_fake_provider(monkeypatch, ["SCORE: 5\nFEEDBACK: ok", "SCORE: 3\nFEEDBACK: ok"])
    sub = graded_setup["submission"]
    teacher = graded_setup["teacher"]
    _grade(client, teacher, sub.id)
    client.as_user(teacher).patch(f"/api/submissions/{sub.id}/grades/a1", json={"score": 1})

    _use_fake_provider(monkeypatch, ["SCORE: 4\nFEEDBACK: changed", "SCORE: 3\nFEEDBACK: ok"])
    body = _grade(client, teacher, sub.id).json()

    a1 = next(g for g in body["grades"] if g["answer_box_id"] == "a1")
    assert a1["llm_score"] == 4   # the model's fresh mark is recorded
    assert a1["score"] == 1       # the human's decision still stands


def test_release_requires_grading_first(client, graded_setup):
    res = client.as_user(graded_setup["teacher"]).post(
        f"/api/submissions/{graded_setup['submission'].id}/release"
    )
    assert res.status_code == 409


def test_unreadable_answer_is_flagged_rather_than_scored_zero(client, graded_setup, monkeypatch):
    _use_fake_provider(monkeypatch, [
        "SCORE: UNREADABLE\nFEEDBACK: The photo is too blurred to read.",
        "SCORE: 3\nFEEDBACK: ok",
    ])
    sub = graded_setup["submission"]
    body = _grade(client, graded_setup["teacher"], sub.id).json()

    a1 = next(g for g in body["grades"] if g["answer_box_id"] == "a1")
    assert a1["score"] is None            # not zero — nobody has marked it
    assert a1["needs_manual_review"] is True
    assert body["needs_review_count"] == 1
    assert body["earned"] == 3            # only the mark that exists counts


def test_gradebook_shows_each_student_against_each_question(client, graded_setup, monkeypatch):
    _use_fake_provider(monkeypatch, ["SCORE: 5\nFEEDBACK: ok", "SCORE: 3\nFEEDBACK: ok"])
    sub = graded_setup["submission"]
    teacher = graded_setup["teacher"]
    _grade(client, teacher, sub.id)

    res = client.as_user(teacher).get(f"/api/courses/{graded_setup['course'].id}/gradebook")
    assert res.status_code == 200
    book = res.json()

    assert len(book["rows"]) == 1
    row = book["rows"][0]
    assert row["display_name"] == "Ada"
    assert row["cells"][0]["earned"] == 8
    assert row["cells"][0]["max"] == 8


def test_students_cannot_read_the_gradebook(client, graded_setup):
    res = client.as_user(graded_setup["student"]).get(
        f"/api/courses/{graded_setup['course'].id}/gradebook"
    )
    assert res.status_code == 403


def test_submission_list_hides_marks_from_students_until_released(client, graded_setup, monkeypatch):
    _use_fake_provider(monkeypatch, ["SCORE: 5\nFEEDBACK: ok", "SCORE: 3\nFEEDBACK: ok"])
    sub = graded_setup["submission"]
    teacher, student = graded_setup["teacher"], graded_setup["student"]
    question_id = graded_setup["question"].id
    _grade(client, teacher, sub.id)

    # The list view must not leak what the detail view gates.
    listed = client.as_user(student).get("/api/submissions", params={"question_id": question_id}).json()
    assert len(listed) == 1
    assert listed[0]["earned"] is None
    assert listed[0]["max_score"] is None
    assert listed[0]["needs_review_count"] is None

    client.as_user(teacher).post(f"/api/submissions/{sub.id}/release")

    listed = client.as_user(student).get("/api/submissions", params={"question_id": question_id}).json()
    assert listed[0]["earned"] == 8


def test_teacher_sees_all_submissions_student_sees_only_their_own(client, graded_setup, db, make_user):
    from models import Enrollment, Submission

    question_id = graded_setup["question"].id
    other = make_user(role="student")
    db.add(Enrollment(course_id=graded_setup["course"].id, student_id=other.id))
    db.add(Submission(question_id=question_id, student_id=other.id, modality="photo", manifest={}))
    db.commit()

    teacher_view = client.as_user(graded_setup["teacher"]).get(
        "/api/submissions", params={"question_id": question_id}
    ).json()
    assert len(teacher_view) == 2

    student_view = client.as_user(graded_setup["student"]).get(
        "/api/submissions", params={"question_id": question_id}
    ).json()
    assert [s["id"] for s in student_view] == [graded_setup["submission"].id]
