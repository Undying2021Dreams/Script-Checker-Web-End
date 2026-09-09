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


def test_pairs_each_answer_box_with_the_model_answer_above_it():
    # The order the editor actually produces: the teacher writes the
    # model answer, then leaves a box under it for the student.
    doc = _doc(
        _para("Q1"), _truth("g1"), _answer("a1"),
        _para("Q2"), _truth("g2"), _answer("a2"),
    )
    assert pair_answer_boxes_with_ground_truth(doc) == {"a1": ["g1"], "a2": ["g2"]}


def test_one_box_covering_several_sub_questions_is_marked_against_all_of_them():
    # A real paper from this project: two sub-questions, each with its own
    # model answer and marking scheme, and a single box at the end for all
    # the working. Marking it against only the nearest answer would judge
    # the student's work against the wrong question.
    doc = _doc(
        _para("Q1"), _truth("g1"),
        _para("Q2"), _truth("g2"),
        _answer("a1"),
    )
    assert pair_answer_boxes_with_ground_truth(doc) == {"a1": ["g1", "g2"]}


def test_pairs_each_answer_box_with_the_model_answer_below_it():
    # The mirror convention. Which one a paper uses is read off the
    # document rather than assumed, since a teacher may lay it out either
    # way and does so consistently within one paper.
    doc = _doc(
        _para("Q1"), _answer("a1"), _truth("g1"),
        _para("Q2"), _answer("a2"), _truth("g2"),
    )
    assert pair_answer_boxes_with_ground_truth(doc) == {"a1": ["g1"], "a2": ["g2"]}


def test_multiple_answer_boxes_share_one_model_answer():
    # A sub-question with parts (i) and (ii) marked against one answer.
    doc = _doc(_para("Q1"), _answer("a1"), _answer("a2"), _truth("g1"))
    assert pair_answer_boxes_with_ground_truth(doc) == {"a1": ["g1"], "a2": ["g1"]}


def test_trailing_answer_box_has_no_model_answer():
    doc = _doc(_para("Q1"), _answer("a1"), _truth("g1"), _para("Q2"), _answer("a2"))
    assert pair_answer_boxes_with_ground_truth(doc) == {"a1": ["g1"], "a2": []}


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


# ── Blank answers ───────────────────────────────────────────────────

def _image(lines=(), bg="white", size=(900, 300)):
    """
    Build a crop with a known amount of ink on it.

    The font is Pillow's own, at an explicit size, rather than one found
    on the host. An earlier version reached for a macOS system path and
    fell back to `load_default()` when it was missing, which on Linux
    meant an ~11px bitmap font: "x = 3" then covered so few pixels that
    it fell under the blank threshold, and the case asserting a real
    answer is *not* blank passed on a developer's Mac while failing in
    CI. A test guarding a threshold has to put the same number of dark
    pixels on the page everywhere it runs.
    """
    import io
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.load_default(size=40)

    im = Image.new("RGB", size, bg)
    d = ImageDraw.Draw(im)
    for i, line in enumerate(lines):
        d.text((30, 20 + i * 70), line, fill="black", font=font)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.parametrize("description,image,expected", [
    ("pure white", _image(), True),
    ("photographed grey", _image(bg="#d8d8d8"), True),
    ("faint short answer", _image(["x = 3"]), False),
    ("full working", _image(["2x + 4 = 10", "2x = 6", "x = 3"]), False),
])
def test_blank_detection(description, image, expected):
    from services.grading import looks_blank

    assert looks_blank(image) is expected, description


@pytest.mark.asyncio
async def test_blank_answer_scores_zero_without_calling_the_model():
    """
    A blank crop must never earn marks, and the model can't be trusted to
    notice it's blank: shown the question and model answer for comparison,
    a real 7B vision model reproduced them as the student's work and
    awarded partial credit. So blankness is decided here, before any call.
    """
    provider = FakeProvider(["SCORE: 3\nFEEDBACK: nice working"])
    item = AnswerToGrade(
        answer_box_id="a1", label="a", max_score=5,
        question_text="Solve 2x+4=10", ground_truth_text="x = 3",
        crops=[(_image(), "image/png")],
    )
    result = await grade_one(provider, item)

    assert result["score"] == 0.0
    assert result["needs_manual_review"] is False  # unattempted is a real mark
    assert provider.calls == []  # and costs nothing


@pytest.mark.asyncio
async def test_a_written_answer_still_reaches_the_model():
    provider = FakeProvider(["SCORE: 4\nFEEDBACK: good"])
    item = AnswerToGrade(
        answer_box_id="a1", label="a", max_score=5,
        question_text="Solve 2x+4=10", ground_truth_text="x = 3",
        crops=[(_image(["2x = 6", "x = 3"]), "image/png")],
    )
    result = await grade_one(provider, item)

    assert result["score"] == 4
    assert len(provider.calls) == 1


# ── Bulk grading ────────────────────────────────────────────────────

def _extra_submission(db, setup, student):
    from models import CropImage, Enrollment, Submission

    db.add(Enrollment(course_id=setup["course"].id, student_id=student.id))
    sub = Submission(
        question_id=setup["question"].id, student_id=student.id, modality="photo", manifest={},
    )
    db.add(sub)
    db.flush()
    db.add(CropImage(submission_id=sub.id, answer_box_id="a1", part=0, data=_image(["x = 3"])))
    db.commit()
    return sub


def test_bulk_grading_marks_every_submission(client, graded_setup, db, make_user, monkeypatch):
    second = _extra_submission(db, graded_setup, make_user(role="student"))
    provider = FakeProvider(["SCORE: 5\nFEEDBACK: ok"] * 10)
    monkeypatch.setattr("routers.grading.get_provider", lambda name: provider)

    res = client.as_user(graded_setup["teacher"]).post(
        f"/api/questions/{graded_setup['question'].id}/grade-all",
        json={"provider": "self_hosted"},
    )
    assert res.status_code == 200, res.text
    assert res.json() == {"queued": 2, "skipped": 0}

    for sub_id in (graded_setup["submission"].id, second.id):
        body = client.as_user(graded_setup["teacher"]).get(f"/api/submissions/{sub_id}/grades").json()
        assert body["grading_status"] == "graded", sub_id


def test_bulk_grading_skips_work_already_marked(client, graded_setup, db, make_user, monkeypatch):
    _extra_submission(db, graded_setup, make_user(role="student"))
    monkeypatch.setattr(
        "routers.grading.get_provider", lambda name: FakeProvider(["SCORE: 5\nFEEDBACK: ok"] * 10)
    )
    teacher = graded_setup["teacher"]
    qid = graded_setup["question"].id

    first = client.as_user(teacher).post(f"/api/questions/{qid}/grade-all", json={"provider": "self_hosted"})
    assert first.json()["queued"] == 2

    # A rerun shouldn't spend calls re-marking what's already done.
    again = client.as_user(teacher).post(f"/api/questions/{qid}/grade-all", json={"provider": "self_hosted"})
    assert again.json() == {"queued": 0, "skipped": 2}

    # Unless asked for explicitly.
    forced = client.as_user(teacher).post(
        f"/api/questions/{qid}/grade-all", json={"provider": "self_hosted", "include_graded": True}
    )
    assert forced.json()["queued"] == 2


def test_bulk_grading_preserves_teacher_overrides(client, graded_setup, monkeypatch):
    teacher = graded_setup["teacher"]
    sub = graded_setup["submission"]
    monkeypatch.setattr(
        "routers.grading.get_provider", lambda name: FakeProvider(["SCORE: 5\nFEEDBACK: ok"] * 10)
    )
    _grade(client, teacher, sub.id)
    client.as_user(teacher).patch(f"/api/submissions/{sub.id}/grades/a1", json={"score": 1})

    client.as_user(teacher).post(
        f"/api/questions/{graded_setup['question'].id}/grade-all",
        json={"provider": "self_hosted", "include_graded": True},
    )

    body = client.as_user(teacher).get(f"/api/submissions/{sub.id}/grades").json()
    a1 = next(g for g in body["grades"] if g["answer_box_id"] == "a1")
    assert a1["score"] == 1  # the human's decision stands through a batch run


def test_students_cannot_bulk_grade(client, graded_setup, monkeypatch):
    monkeypatch.setattr("routers.grading.get_provider", lambda name: FakeProvider([]))
    res = client.as_user(graded_setup["student"]).post(
        f"/api/questions/{graded_setup['question'].id}/grade-all",
        json={"provider": "self_hosted"},
    )
    assert res.status_code == 404


# ── Provider errors ─────────────────────────────────────────────────

@pytest.mark.parametrize("body,expected", [
    # Anthropic / Gemini shape
    ({"error": {"message": "Your credit balance is too low"}}, "credit balance is too low"),
    # OpenAI nests the same way
    ({"error": {"message": "Incorrect API key provided"}}, "Incorrect API key"),
    # Some gateways return a bare string
    ({"error": "quota exceeded"}, "quota exceeded"),
    ({"message": "service unavailable"}, "service unavailable"),
])
def test_provider_errors_carry_the_reason(body, expected):
    """
    httpx's own raise_for_status throws away the response body, which is
    where the actual reason lives. A teacher who clicks Grade needs "credit
    balance is too low", not "400 Bad Request".
    """
    import httpx

    from services.llm_provider import _raise_for_status

    resp = httpx.Response(400, json=body, request=httpx.Request("POST", "https://x"))
    with pytest.raises(RuntimeError) as exc:
        _raise_for_status(resp, "Claude")

    assert "Claude" in str(exc.value)
    assert "400" in str(exc.value)
    assert expected in str(exc.value)


def test_non_json_provider_errors_still_say_something():
    import httpx

    from services.llm_provider import _raise_for_status

    resp = httpx.Response(502, text="<html>Bad Gateway</html>", request=httpx.Request("POST", "https://x"))
    with pytest.raises(RuntimeError, match="502"):
        _raise_for_status(resp, "OpenAI")


def test_a_successful_response_is_left_alone():
    import httpx

    from services.llm_provider import _raise_for_status

    _raise_for_status(httpx.Response(200, json={}, request=httpx.Request("POST", "https://x")), "Claude")


# ── A teacher's mark outranks the machine's ─────────────────────────

def test_regrading_leaves_a_teachers_mark_and_words_alone(client, graded_setup, monkeypatch):
    """
    Re-running the model must not quietly undo a human decision.

    The two are stored in separate columns precisely so this can hold;
    this asserts the behaviour a teacher actually depends on, which is
    that re-grading a paper they have already marked by hand changes
    nothing they wrote.
    """
    teacher = graded_setup["teacher"]
    sub = graded_setup["submission"]

    _use_fake_provider(monkeypatch, ["SCORE: 2\nFEEDBACK: model's first take"] * 2)
    _grade(client, teacher, sub.id)

    client.as_user(teacher).patch(
        f"/api/submissions/{sub.id}/grades/a1",
        json={"score": 5, "feedback": "Method is right, arithmetic slipped."},
    )

    _use_fake_provider(monkeypatch, ["SCORE: 1\nFEEDBACK: model's second take"] * 2)
    body = _grade(client, teacher, sub.id).json()

    marked = next(g for g in body["grades"] if g["answer_box_id"] == "a1")
    assert marked["override_score"] == 5
    assert marked["override_feedback"] == "Method is right, arithmetic slipped."
    assert marked["score"] == 5, "the teacher's mark is the one that counts"
    assert marked["feedback"] == "Method is right, arithmetic slipped."
    # The model's newer opinion is still recorded alongside, so a
    # disputed mark can be traced.
    assert marked["llm_score"] == 1

    untouched = next(g for g in body["grades"] if g["answer_box_id"] == "a2")
    assert untouched["score"] == 1, "a box with no override still follows the model"


def test_blank_feedback_does_not_mask_the_models(client, graded_setup, monkeypatch):
    """Clearing the note falls back to the model's rather than showing nothing."""
    teacher = graded_setup["teacher"]
    sub = graded_setup["submission"]

    _use_fake_provider(monkeypatch, ["SCORE: 2\nFEEDBACK: check your signs"] * 2)
    _grade(client, teacher, sub.id)

    client.as_user(teacher).patch(
        f"/api/submissions/{sub.id}/grades/a1", json={"score": 4, "feedback": "   "}
    )
    body = client.as_user(teacher).get(f"/api/submissions/{sub.id}/grades").json()
    marked = next(g for g in body["grades"] if g["answer_box_id"] == "a1")

    assert marked["override_feedback"] is None
    assert marked["feedback"] == "check your signs"


# ── The worked solution reaches the student, but only after release ──

def test_model_answer_is_withheld_until_marks_are_released(client, graded_setup, monkeypatch):
    teacher = graded_setup["teacher"]
    student = graded_setup["student"]
    sub = graded_setup["submission"]

    _use_fake_provider(monkeypatch, ["SCORE: 3\nFEEDBACK: ok"] * 2)
    _grade(client, teacher, sub.id)

    # While the paper is still live the model answer is the answer key.
    assert client.as_user(student).get(f"/api/submissions/{sub.id}/grades").status_code == 403

    client.as_user(teacher).post(f"/api/submissions/{sub.id}/release")

    body = client.as_user(student).get(f"/api/submissions/{sub.id}/grades").json()
    marked = next(g for g in body["grades"] if g["answer_box_id"] == "a1")
    assert marked["model_answer_text"] == "x = 3"
    assert marked["feedback"] == "ok"
