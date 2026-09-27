"""
Grading on the student's phone (routers/on_device.py).

The phone posts marks it worked out itself, so these tests are about
what the server lets it do: who may start and post, that every box is
accounted for, that nothing a teacher decided is touched, that a run
cannot hang for ever, and that the teacher hears about it. A fake
provider stands in for the self-hosted fallback model.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from config import settings
from models import (
    AnswerBox,
    AnswerGrade,
    Course,
    CropImage,
    Enrollment,
    GroundTruthBox,
    GroundTruthImage,
    Notification,
    Question,
    Submission,
    UploadedImage,
)
from ratelimit import limiter
from services import on_device
from services.grading_runner import build_grading_items
from tests.test_grading import FakeProvider


@pytest.fixture(autouse=True)
def _reset_limits():
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture(autouse=True)
def _no_fallback_url(monkeypatch):
    # Whatever the developer's .env says, fallback is off unless a test
    # turns it on.
    monkeypatch.setattr(settings, "SELF_HOSTED_LLM_URL", "")


def _para(text):
    return {"type": "paragraph", "content": [{"type": "text", "text": text}]}


@pytest.fixture
def paper(db, make_user):
    """A finalized two-part paper and a handed-in script by Ada."""
    teacher = make_user(role="teacher")
    student = make_user(role="student", display_name="Ada")
    classmate = make_user(role="student", display_name="Bob")
    outsider = make_user(role="student")

    course = Course(title="NM", join_code="DEV001", teacher_id=teacher.id)
    db.add(course)
    db.commit()
    db.add(Enrollment(course_id=course.id, student_id=student.id))
    db.add(Enrollment(course_id=course.id, student_id=classmate.id))

    q = Question(
        course_id=course.id, created_by=teacher.id, state="finalized", title="Algebra quiz",
        page_w_px=1240, page_h_px=1754, page_count=1, dpi=150,
    )
    db.add(q)
    db.flush()

    figure = UploadedImage(question_id=q.id, filename="fig.png", content_type="image/png", data=b"FIG")
    db.add(figure)
    db.flush()
    q.content = {"type": "doc", "content": [
        _para("Solve 2x+4=10"),
        {"type": "image", "attrs": {"src": f"/api/images/{figure.id}"}},
        {"type": "answerBox", "attrs": {"id": "a1"}},
        {"type": "groundTruthBox", "attrs": {"id": "g1"}},
        _para("Differentiate x^2"),
        {"type": "answerBox", "attrs": {"id": "a2"}},
        {"type": "groundTruthBox", "attrs": {"id": "g2"}},
    ]}
    db.add(AnswerBox(id="a1", question_id=q.id, label="a", points=5, order_index=0,
                     page_index=0, bbox_x=100, bbox_y=200, bbox_w=800, bbox_h=300,
                     segments_json=[[0, 100, 200, 800, 300]]))
    db.add(AnswerBox(id="a2", question_id=q.id, label="b", points=3, order_index=1,
                     page_index=0, bbox_x=100, bbox_y=700, bbox_w=800, bbox_h=300,
                     segments_json=[[0, 100, 700, 800, 300]]))
    db.add(GroundTruthBox(id="g1", question_id=q.id, order_index=0,
                          content={"type": "doc", "content": [_para("x = 3")]}))
    db.add(GroundTruthBox(id="g2", question_id=q.id, order_index=1,
                          content={"type": "doc", "content": [_para("2x")]}))
    db.flush()
    gt_image = GroundTruthImage(ground_truth_box_id="g1", data=b"GTIMG", page_index=0)
    db.add(gt_image)

    sub = Submission(
        question_id=q.id, student_id=student.id, modality="photo", manifest={"pages": [{}]},
        submitted_at=datetime.now(timezone.utc),
    )
    db.add(sub)
    db.flush()
    # The server's own crops, which fallback marks from.
    db.add(CropImage(submission_id=sub.id, answer_box_id="a1", part=0, data=b"CROP1"))
    db.add(CropImage(submission_id=sub.id, answer_box_id="a2", part=0, data=b"CROP2"))
    db.commit()
    db.refresh(sub)

    return {
        "teacher": teacher, "student": student, "classmate": classmate, "outsider": outsider,
        "course": course, "question": q, "submission": sub, "figure": figure, "gt_image": gt_image,
    }


def _start(client, user, sid):
    return client.as_user(user).post(f"/api/student/submissions/{sid}/on-device/start")


def _results(a1=("scored", 4.0), a2=("scored", 2.0)):
    out = []
    for box_id, (outcome, score) in (("a1", a1), ("a2", a2)):
        if outcome is None:
            continue
        out.append({
            "answer_box_id": box_id, "outcome": outcome, "score": score,
            "feedback": f"phone says {box_id}", "confidence": 80,
            "raw_response": f"TRANSCRIPT: ...\nSCORE: {score}\nFEEDBACK: phone says {box_id}\nCONFIDENCE: 80",
        })
    return out


def _post(client, user, sid, token, results=None, fallback=(), use_fallback=True):
    return client.as_user(user).post(
        f"/api/student/submissions/{sid}/on-device/results",
        json={
            "run_token": token,
            "use_fallback": use_fallback,
            "fallback_box_ids": list(fallback),
            "results": _results() if results is None else results,
        },
    )


def _run(client, paper, **kwargs):
    started = _start(client, paper["student"], paper["submission"].id)
    assert started.status_code == 200, started.text
    token = started.json()["run_token"]
    return token, _post(client, paper["student"], paper["submission"].id, token, **kwargs)


def _rows(db, sid):
    db.expire_all()
    return {g.answer_box_id: g for g in db.query(AnswerGrade).filter(AnswerGrade.submission_id == sid)}


def _sub(db, sid):
    db.expire_all()
    return db.query(Submission).filter(Submission.id == sid).first()


def _age_run(db, sid, minutes):
    sub = _sub(db, sid)
    sub.on_device_started_at = on_device.utcnow() - timedelta(minutes=minutes)
    db.commit()


# ── The pack ────────────────────────────────────────────────────────

def test_pack_matches_what_the_server_grader_would_use(client, paper, db):
    res = client.as_user(paper["student"]).get(f"/api/student/assignments/{paper['question'].id}/pack")
    assert res.status_code == 200, res.text
    pack = res.json()

    items = {i.answer_box_id: i for i in build_grading_items(db, paper["submission"])}
    assert [b["id"] for b in pack["boxes"]] == ["a1", "a2"]
    for box in pack["boxes"]:
        item = items[box["id"]]
        assert box["question_text"] == item.question_text
        assert box["model_answer_text"] == item.ground_truth_text
        assert box["blocked_reason"] == item.blocked_reason
        assert box["points"] == item.max_score

    a1 = pack["boxes"][0]
    # The answer key travels with the pack, on purpose.
    assert a1["model_answer_text"] == "x = 3"
    assert a1["segments"] == [[0, 100, 200, 800, 300]]
    assert a1["bbox"] == [100, 200, 800, 300]
    # Relative references only, never an absolute URL.
    assert a1["model_answer_images"] == [f"pack/images/model-answer/{paper['gt_image'].id}"]
    assert a1["question_images"] == [f"pack/images/question/{paper['figure'].id}"]
    assert "http" not in res.text

    assert pack["markers"]["aruco_dict"] == "DICT_4X4_50"
    assert pack["markers"]["centres"]["0"] == [70, 70]
    assert pack["markers"]["centres"]["3"] == [1170, 1684]


def test_pack_images_are_served_relative_to_the_pack(client, paper):
    base = f"/api/student/assignments/{paper['question'].id}/"
    ok = client.as_user(paper["student"]).get(base + f"pack/images/model-answer/{paper['gt_image'].id}")
    assert ok.status_code == 200 and ok.content == b"GTIMG"
    fig = client.as_user(paper["student"]).get(base + f"pack/images/question/{paper['figure'].id}")
    assert fig.status_code == 200 and fig.content == b"FIG"
    wrong_kind = client.as_user(paper["student"]).get(base + f"pack/images/question/{paper['gt_image'].id}")
    assert wrong_kind.status_code == 404


def test_draft_papers_have_no_pack(client, paper, db):
    paper["question"].state = "draft"
    db.commit()
    res = client.as_user(paper["student"]).get(f"/api/student/assignments/{paper['question'].id}/pack")
    assert res.status_code == 404


# ── Who may do what ─────────────────────────────────────────────────

def test_not_enrolled(client, paper, db):
    qid, sid = paper["question"].id, paper["submission"].id
    assert client.as_user(paper["outsider"]).get(f"/api/student/assignments/{qid}/pack").status_code == 404
    assert client.as_user(paper["outsider"]).get(
        f"/api/student/assignments/{qid}/pack/images/question/{paper['figure'].id}"
    ).status_code == 404

    # Ada's own script, after she has left the course.
    db.query(Enrollment).filter(Enrollment.student_id == paper["student"].id).delete()
    db.commit()
    assert _start(client, paper["student"], sid).status_code == 404
    assert client.as_user(paper["student"]).get(f"/api/student/submissions/{sid}/grades").status_code == 404


def test_another_students_submission(client, paper):
    sid = paper["submission"].id
    bob = paper["classmate"]
    assert _start(client, bob, sid).status_code == 404
    assert _post(client, bob, sid, "anything").status_code == 404
    assert client.as_user(bob).get(f"/api/student/submissions/{sid}/grades").status_code == 404
    assert client.as_user(bob).post(
        f"/api/student/submissions/{sid}/re-evaluation", json={}
    ).status_code == 404
    # Nor may the teacher use the student's routes on it.
    assert _start(client, paper["teacher"], sid).status_code == 404


def test_not_handed_in(client, paper, db):
    sub = _sub(db, paper["submission"].id)
    sub.submitted_at = None
    db.commit()
    assert _start(client, paper["student"], sub.id).status_code == 409


def test_released(client, paper, db):
    sub = _sub(db, paper["submission"].id)
    sub.grading_status = "graded"
    sub.released_at = datetime.now(timezone.utc)
    db.commit()
    assert _start(client, paper["student"], sub.id).status_code == 409


def test_already_graded(client, paper, db):
    _, res = _run(client, paper)
    assert res.status_code == 201
    assert _start(client, paper["student"], paper["submission"].id).status_code == 409


@pytest.mark.parametrize("state", ["queued", "grading"])
def test_teacher_started_run_in_progress(client, paper, db, state):
    sub = _sub(db, paper["submission"].id)
    sub.grading_status = state  # no on_device_started_at: a server run
    db.commit()
    res = _start(client, paper["student"], sub.id)
    assert res.status_code == 409
    assert _sub(db, sub.id).grading_status == state


# ── Posting results ─────────────────────────────────────────────────

def test_a_run_saves_every_box_as_on_device(client, paper, db):
    token, res = _run(client, paper, results=_results(a2=("blank", None)))
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["grading_status"] == "graded"
    assert body["provisional"] is True
    assert body["fallback"] == "none"
    assert body["earned"] == 4.0 and body["max_score"] == 8

    rows = _rows(db, paper["submission"].id)
    assert rows["a1"].provider == "on_device" and rows["a1"].llm_score == 4.0
    assert rows["a1"].max_score == 5
    assert "CONFIDENCE: 80" in rows["a1"].raw_response
    assert rows["a2"].llm_score == 0.0
    assert rows["a2"].llm_feedback == "Nothing was written in this answer box."

    sub = _sub(db, paper["submission"].id)
    assert sub.graded_at is not None and sub.on_device_started_at is None


def test_needs_review_is_saved_with_its_reason(client, paper, db):
    results = _results(a2=("needs_review", None))
    results[1]["review_reason"] = "UNREADABLE on the phone"
    _, res = _run(client, paper, results=results)
    assert res.status_code == 201
    row = _rows(db, paper["submission"].id)["a2"]
    assert row.needs_manual_review is True
    assert row.review_reason == "UNREADABLE on the phone"
    assert row.llm_score is None


def test_overridden_box_skipped(client, paper, db):
    sid = paper["submission"].id
    db.add(AnswerGrade(
        submission_id=sid, answer_box_id="a2", max_score=3, llm_score=1.0, provider="gemini",
        override_score=3.0, overridden_at=datetime.now(timezone.utc),
    ))
    db.commit()

    started = _start(client, paper["student"], sid).json()
    assert started["eligible_box_ids"] == ["a1"]
    assert started["protected_box_ids"] == ["a2"]

    # Posting a result for the protected box too is harmless: it's ignored.
    res = _post(client, paper["student"], sid, started["run_token"])
    assert res.status_code == 201, res.text

    rows = _rows(db, sid)
    assert rows["a1"].provider == "on_device"
    assert rows["a2"].provider == "gemini"
    assert rows["a2"].override_score == 3.0 and rows["a2"].llm_score == 1.0


def test_missing_eligible_box(client, paper, db):
    _, res = _run(client, paper, results=_results(a2=(None, None)))
    assert res.status_code == 400
    assert res.json()["detail"]["missing_box_ids"] == ["a2"]
    assert _rows(db, paper["submission"].id) == {}
    assert _sub(db, paper["submission"].id).grading_status == "grading"


@pytest.mark.parametrize("score", [3.5, -1.0, None])
def test_score_out_of_range(client, paper, db, score):
    _, res = _run(client, paper, results=_results(a2=("scored", score)))
    assert res.status_code == 400
    assert _rows(db, paper["submission"].id) == {}


def test_unknown_or_duplicate_boxes_are_refused(client, paper):
    token = _start(client, paper["student"], paper["submission"].id).json()["run_token"]
    sid = paper["submission"].id
    extra = _results() + [{**_results()[0], "answer_box_id": "nope"}]
    assert _post(client, paper["student"], sid, token, results=extra).status_code == 400
    dup = _results() + [_results()[0]]
    assert _post(client, paper["student"], sid, token, results=dup).status_code == 400
    assert _post(client, paper["student"], sid, token, fallback=["nope"]).status_code == 400


def test_idempotent_re_post(client, paper, db):
    token, first = _run(client, paper)
    assert first.status_code == 201
    sid = paper["submission"].id

    again = _post(client, paper["student"], sid, token, results=_results(a1=("scored", 1.0)))
    assert again.status_code == 200
    assert again.json()["earned"] == first.json()["earned"]
    assert _rows(db, sid)["a1"].llm_score == 4.0
    notes = db.query(Notification).filter(Notification.kind == "graded_on_device").count()
    assert notes == 1


def test_superseded_token(client, paper):
    sid = paper["submission"].id
    old = _start(client, paper["student"], sid).json()["run_token"]
    new = _start(client, paper["student"], sid).json()["run_token"]  # resume
    assert old != new
    assert _post(client, paper["student"], sid, old).status_code == 409
    assert _post(client, paper["student"], sid, new).status_code == 201


def test_expired_token(client, paper, db):
    sid = paper["submission"].id
    token = _start(client, paper["student"], sid).json()["run_token"]
    _age_run(db, sid, settings.ON_DEVICE_LEASE_MINUTES + 1)

    res = _post(client, paper["student"], sid, token)
    assert res.status_code == 409
    sub = _sub(db, sid)
    assert sub.grading_status == "failed"
    assert sub.grading_error == on_device.LEASE_EXPIRED_ERROR
    assert _rows(db, sid) == {}


# ── The lease ───────────────────────────────────────────────────────

def test_sweeper_expires_an_old_run_and_the_teacher_can_grade(client, paper, db, monkeypatch):
    sid = paper["submission"].id
    _start(client, paper["student"], sid)
    _age_run(db, sid, settings.ON_DEVICE_LEASE_MINUTES + 1)

    assert on_device.expire_stale_runs(db) == 1
    sub = _sub(db, sid)
    assert sub.grading_status == "failed"
    assert sub.grading_error == on_device.LEASE_EXPIRED_ERROR
    assert sub.on_device_run_token is None and sub.on_device_started_at is None

    provider = FakeProvider(["SCORE: 5\nFEEDBACK: Correct.", "SCORE: 1\nFEEDBACK: Partly."])
    monkeypatch.setattr("routers.grading.get_provider", lambda name: provider)
    res = client.as_user(paper["teacher"]).post(
        f"/api/submissions/{sid}/grade", json={"provider": "self_hosted"}
    )
    assert res.status_code == 200, res.text
    grades = client.as_user(paper["teacher"]).get(f"/api/submissions/{sid}/grades").json()
    assert grades["grading_status"] == "graded"
    assert grades["earned"] == 6


def test_sweeper_leaves_a_live_run_alone(client, paper, db):
    _start(client, paper["student"], paper["submission"].id)
    assert on_device.expire_stale_runs(db) == 0
    assert _sub(db, paper["submission"].id).grading_status == "grading"


def test_restart_after_expiry(client, paper, db):
    sid = paper["submission"].id
    old = _start(client, paper["student"], sid).json()["run_token"]
    _age_run(db, sid, settings.ON_DEVICE_LEASE_MINUTES + 1)
    on_device.expire_stale_runs(db)

    restarted = _start(client, paper["student"], sid)
    assert restarted.status_code == 200
    new = restarted.json()["run_token"]
    assert new != old
    assert _post(client, paper["student"], sid, old).status_code == 409
    assert _post(client, paper["student"], sid, new).status_code == 201
    assert _sub(db, sid).grading_status == "graded"


def test_a_lost_fallback_expires_too(client, paper, db, monkeypatch):
    """A server restart mid-fallback leaves the run posted but pending."""
    monkeypatch.setattr(settings, "SELF_HOSTED_LLM_URL", "http://fallback.invalid/v1")
    monkeypatch.setattr(on_device, "run_fallback", _never_runs)
    sid = paper["submission"].id
    _run(client, paper, fallback=["a2"])
    _age_run(db, sid, settings.ON_DEVICE_LEASE_MINUTES + 1)

    assert on_device.expire_stale_runs(db) == 1
    sub = _sub(db, sid)
    assert sub.grading_status == "failed"
    row = _rows(db, sid)["a2"]
    assert row.needs_manual_review is True
    assert row.review_reason == on_device.REMARK_DID_NOT_FINISH


async def _never_runs(*args, **kwargs):
    return None


# ── Fallback ────────────────────────────────────────────────────────

def test_fallback_with_url_unset(client, paper, db):
    _, res = _run(client, paper, fallback=["a2"])
    assert res.status_code == 201
    body = res.json()
    assert body["grading_status"] == "graded"
    assert body["fallback"] == "unavailable"
    assert "unavailable" in body["fallback_message"]

    row = _rows(db, paper["submission"].id)["a2"]
    assert row.needs_manual_review is True
    assert row.review_reason == "Fallback unavailable"
    assert row.llm_score is None
    assert db.query(Notification).filter(Notification.kind == "graded_on_device").count() == 1


def test_fallback_turned_off_in_the_app(client, paper, db, monkeypatch):
    monkeypatch.setattr(settings, "SELF_HOSTED_LLM_URL", "http://fallback.invalid/v1")
    _, res = _run(client, paper, fallback=["a2"], use_fallback=False)
    assert res.json()["fallback"] == "unavailable"
    assert _rows(db, paper["submission"].id)["a2"].review_reason == "Fallback unavailable"


def test_fallback_success(client, paper, db, monkeypatch):
    """Stays "grading" until the re-mark is done, then "graded"."""
    monkeypatch.setattr(settings, "SELF_HOSTED_LLM_URL", "http://fallback.invalid/v1")
    provider = FakeProvider(["SCORE: 3\nFEEDBACK: Server says full marks."])
    monkeypatch.setattr("services.on_device.get_provider", lambda name: provider)

    scheduled = []

    async def _hold(*args):
        scheduled.append(args)

    real_fallback = on_device.run_fallback
    monkeypatch.setattr(on_device, "run_fallback", _hold)
    sid = paper["submission"].id

    _, res = _run(client, paper, fallback=["a2"])
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["grading_status"] == "grading"
    assert body["fallback"] == "scheduled"
    assert body["pending_fallback_count"] == 1
    assert [b["pending_fallback"] for b in body["boxes"]] == [False, True]

    mine = client.as_user(paper["student"]).get(f"/api/student/submissions/{sid}/grades").json()
    assert mine["grading_status"] == "grading"
    assert db.query(Notification).filter(Notification.kind == "graded_on_device").count() == 0

    # Now let the re-mark finish.
    asyncio.run(real_fallback(*scheduled[0]))

    assert len(provider.calls) == 1  # only the flagged box
    assert provider.calls[0]["images"][-1] == (b"CROP2", "image/png")  # the server's crop
    rows = _rows(db, sid)
    assert rows["a1"].provider == "on_device" and rows["a1"].llm_score == 4.0
    assert rows["a2"].provider == "self_hosted" and rows["a2"].llm_score == 3.0
    assert rows["a2"].review_reason is None

    sub = _sub(db, sid)
    assert sub.grading_status == "graded" and sub.graded_at is not None
    assert db.query(Notification).filter(Notification.kind == "graded_on_device").count() == 1

    mine = client.as_user(paper["student"]).get(f"/api/student/submissions/{sid}/grades").json()
    assert mine["grading_status"] == "graded"
    assert mine["pending_fallback_count"] == 0
    assert mine["earned"] == 7.0


def test_fallback_runs_in_the_background(client, paper, db, monkeypatch):
    monkeypatch.setattr(settings, "SELF_HOSTED_LLM_URL", "http://fallback.invalid/v1")
    provider = FakeProvider(["SCORE: 1\nFEEDBACK: Server."])
    monkeypatch.setattr("services.on_device.get_provider", lambda name: provider)

    _, res = _run(client, paper, fallback=["a2"])
    assert res.json()["grading_status"] == "grading"  # the response predates the re-mark
    assert _sub(db, paper["submission"].id).grading_status == "graded"
    assert _rows(db, paper["submission"].id)["a2"].provider == "self_hosted"


def test_a_superseded_fallback_writes_nothing(client, paper, db, monkeypatch):
    monkeypatch.setattr(settings, "SELF_HOSTED_LLM_URL", "http://fallback.invalid/v1")
    provider = FakeProvider(["SCORE: 3\nFEEDBACK: late"])
    monkeypatch.setattr("services.on_device.get_provider", lambda name: provider)
    scheduled = []

    async def _hold(*args):
        scheduled.append(args)

    real_fallback = on_device.run_fallback
    monkeypatch.setattr(on_device, "run_fallback", _hold)
    sid = paper["submission"].id
    _run(client, paper, fallback=["a2"])

    # The teacher resets the marks while the re-mark is out.
    sub = _sub(db, sid)
    sub.grading_status = "failed"
    sub.on_device_started_at = None
    db.commit()

    asyncio.run(real_fallback(*scheduled[0]))
    assert provider.calls == []
    assert _rows(db, sid)["a2"].provider == "on_device"


# ── Telling the teacher ─────────────────────────────────────────────

def test_completion_notification(client, paper, db):
    _run(client, paper)
    note = db.query(Notification).filter(Notification.kind == "graded_on_device").one()
    assert note.user_id == paper["teacher"].id
    assert "Ada" in note.title and "Algebra quiz" in note.title
    assert note.link == f"/submissions/{paper['submission'].id}"
    assert note.body.startswith("6 of 8")


def test_reevaluation_notification(client, paper, db):
    sid = paper["submission"].id
    url = f"/api/student/submissions/{sid}/re-evaluation"

    early = client.as_user(paper["student"]).post(url, json={"message": "please"})
    assert early.status_code == 409  # nothing graded yet

    _run(client, paper)
    res = client.as_user(paper["student"]).post(
        url, json={"answer_box_ids": ["a2"], "message": "I wrote 2x on the second line."}
    )
    assert res.status_code == 200, res.text
    assert res.json()["notified"] is True

    note = db.query(Notification).filter(Notification.kind == "reevaluation_requested").one()
    assert note.user_id == paper["teacher"].id
    assert note.link == f"/submissions/{sid}"
    assert "Ada" in note.title
    assert "b" in note.body and "2x on the second line" in note.body

    too_long = client.as_user(paper["student"]).post(url, json={"message": "x" * 1001})
    assert too_long.status_code == 422
    unknown = client.as_user(paper["student"]).post(url, json={"answer_box_ids": ["zz"]})
    assert unknown.status_code == 400


def test_reevaluation_is_rate_limited(client, paper):
    _run(client, paper)
    url = f"/api/student/submissions/{paper['submission'].id}/re-evaluation"
    statuses = [client.as_user(paper["student"]).post(url, json={}).status_code for _ in range(7)]
    assert statuses[:5] == [200] * 5
    assert 429 in statuses


# ── What each side sees ─────────────────────────────────────────────

def test_teacher_sees_on_device_marks(client, paper):
    _run(client, paper)
    res = client.as_user(paper["teacher"]).get(f"/api/submissions/{paper['submission'].id}/grades")
    assert res.status_code == 200
    body = res.json()
    assert body["grading_status"] == "graded"
    assert {g["provider"] for g in body["grades"]} == {"on_device"}


def test_existing_student_routes_stay_release_only(client, paper):
    _run(client, paper)
    sid = paper["submission"].id

    mine = client.as_user(paper["student"]).get(f"/api/student/submissions/{sid}/grades").json()
    assert mine["provisional"] is True and mine["earned"] == 6.0

    listed = client.as_user(paper["student"]).get(
        "/api/student/assignments", params={"course_id": paper["course"].id}
    ).json()[0]
    assert listed["submission_status"] == "graded"
    assert listed["earned"] is None and listed["max_score"] is None

    official = client.as_user(paper["student"]).get(f"/api/submissions/{sid}/grades")
    assert official.status_code == 403

    client.as_user(paper["teacher"]).post(f"/api/submissions/{sid}/release")
    mine = client.as_user(paper["student"]).get(f"/api/student/submissions/{sid}/grades").json()
    assert mine["provisional"] is False and mine["released"] is True
