"""
What a grading run is allowed to touch.

Two things put a mark beyond the machine's reach, and both are a person
having taken responsibility for it: the marks have been released to the
student, or a teacher has decided that box themselves. Each is undone by
an explicit act — withdrawing, or resetting — and by nothing else.

These are worth testing precisely because the failure is silent: a
re-mark that overwrites a teacher's judgement, or changes a grade a
student has already been given, looks exactly like a successful run.
"""

import pytest

from models import AnswerGrade, Course, Enrollment, Question, Submission
from services.grading_runner import protected_answer_box_ids


@pytest.fixture
def course(db, make_user):
    teacher = make_user(role="teacher")
    course = Course(title="Numerical Methods", join_code="PROT01", teacher_id=teacher.id)
    db.add(course)
    db.commit()
    db.refresh(course)
    course.teacher = teacher
    return course


def _paper_with_two_boxes(db, course):
    q = Question(course_id=course.id, created_by=course.teacher_id, state="finalized",
                 physical_page="A4", dpi=150)
    db.add(q)
    db.flush()
    for i, label in enumerate("ab"):
        db.add(AnswerBoxRow(q.id, f"{q.id}-{label}", label, i))
    db.commit()
    return q


def AnswerBoxRow(question_id, box_id, label, order_index):
    from models import AnswerBox

    return AnswerBox(
        id=box_id, question_id=question_id, label=label,
        order_index=order_index, points=5,
    )


def _submission_with_marks(db, q, student_id, released=False):
    from datetime import datetime, timezone

    sub = Submission(
        question_id=q.id, student_id=student_id, modality="photo",
        grading_status="graded",
        # `released` is derived from this, not stored separately.
        released_at=datetime.now(timezone.utc) if released else None,
    )
    db.add(sub)
    db.flush()
    for box in q.answer_boxes:
        db.add(AnswerGrade(submission_id=sub.id, answer_box_id=box.id,
                           max_score=5, llm_score=3, llm_feedback="machine"))
    db.commit()
    db.refresh(sub)
    return sub


def test_released_marks_are_protected_and_withdrawing_releases_them(db, course, make_user):
    student = make_user()
    q = _paper_with_two_boxes(db, course)
    sub = _submission_with_marks(db, q, student.id, released=True)

    assert protected_answer_box_ids(db, sub) == {b.id for b in q.answer_boxes}

    sub.released_at = None
    db.commit()
    assert protected_answer_box_ids(db, sub) == set()


def test_only_the_box_a_teacher_touched_is_protected(db, course, make_user):
    """
    Per box, not per script. A teacher who corrects one part of an answer
    should not thereby freeze the other three — nor should their
    correction be the only thing a rerun leaves behind.
    """
    from datetime import datetime, timezone

    student = make_user()
    q = _paper_with_two_boxes(db, course)
    sub = _submission_with_marks(db, q, student.id)
    first, second = sorted(q.answer_boxes, key=lambda b: b.order_index)

    touched = (
        db.query(AnswerGrade)
        .filter(AnswerGrade.submission_id == sub.id, AnswerGrade.answer_box_id == first.id)
        .one()
    )
    touched.override_score = 4
    touched.overridden_by = course.teacher.id
    touched.overridden_at = datetime.now(timezone.utc)
    db.commit()

    assert protected_answer_box_ids(db, sub) == {first.id}
    assert second.id not in protected_answer_box_ids(db, sub)


def test_a_note_alone_protects_a_box(db, course, client, make_user):
    """Feedback with no mark is still a teacher's decision about it."""
    student = make_user()
    q = _paper_with_two_boxes(db, course)
    sub = _submission_with_marks(db, q, student.id)
    box = sorted(q.answer_boxes, key=lambda b: b.order_index)[0]

    res = client.as_user(course.teacher).patch(
        f"/api/submissions/{sub.id}/grades/{box.id}",
        json={"score": None, "feedback": "Check your signs on line 3."},
    )
    assert res.status_code == 200, res.text
    db.expire_all()
    assert protected_answer_box_ids(db, sub) == {box.id}


def test_emptying_an_override_hands_the_box_back(db, course, client, make_user):
    """
    Clearing both the mark and the note is a teacher stepping back off a
    box. Without this it stayed frozen for ever once touched, even when
    nothing of theirs was left on it.
    """
    student = make_user()
    q = _paper_with_two_boxes(db, course)
    sub = _submission_with_marks(db, q, student.id)
    box = sorted(q.answer_boxes, key=lambda b: b.order_index)[0]

    client.as_user(course.teacher).patch(
        f"/api/submissions/{sub.id}/grades/{box.id}",
        json={"score": 4, "feedback": "good"},
    )
    db.expire_all()
    assert protected_answer_box_ids(db, sub) == {box.id}

    client.as_user(course.teacher).patch(
        f"/api/submissions/{sub.id}/grades/{box.id}",
        json={"score": None, "feedback": ""},
    )
    db.expire_all()
    assert protected_answer_box_ids(db, sub) == set()


def test_resetting_is_refused_while_the_marks_are_released(db, course, client, make_user):
    student = make_user()
    q = _paper_with_two_boxes(db, course)
    sub = _submission_with_marks(db, q, student.id, released=True)

    res = client.as_user(course.teacher).post(f"/api/submissions/{sub.id}/reset-marks")
    assert res.status_code == 409, res.text
    assert "withdraw" in res.json()["detail"].lower()
    assert db.query(AnswerGrade).filter(AnswerGrade.submission_id == sub.id).count() == 2


def test_resetting_a_script_clears_both_halves_of_every_mark(db, course, client, make_user):
    """
    The teacher's marks go too, and deliberately. A box a teacher has
    decided is not re-marked, so clearing only the machine's half would
    leave the script permanently half-frozen.
    """
    from datetime import datetime, timezone

    student = make_user()
    q = _paper_with_two_boxes(db, course)
    sub = _submission_with_marks(db, q, student.id)
    box = sorted(q.answer_boxes, key=lambda b: b.order_index)[0]
    g = db.query(AnswerGrade).filter(AnswerGrade.answer_box_id == box.id).one()
    g.override_score = 5
    g.overridden_at = datetime.now(timezone.utc)
    db.commit()

    res = client.as_user(course.teacher).post(f"/api/submissions/{sub.id}/reset-marks")
    assert res.status_code == 200, res.text

    assert db.query(AnswerGrade).filter(AnswerGrade.submission_id == sub.id).count() == 0
    db.refresh(sub)
    assert sub.grading_status == "ungraded"
    assert protected_answer_box_ids(db, sub) == set()


def test_resetting_a_whole_paper_leaves_released_scripts_alone(db, course, client, make_user):
    q = _paper_with_two_boxes(db, course)
    open_sub = _submission_with_marks(db, q, make_user().id)
    released = _submission_with_marks(db, q, make_user().id, released=True)

    res = client.as_user(course.teacher).post(f"/api/questions/{q.id}/reset-all-marks")
    assert res.status_code == 200, res.text
    assert res.json() == {"changed": 1, "skipped": 1}

    assert db.query(AnswerGrade).filter(AnswerGrade.submission_id == open_sub.id).count() == 0
    assert db.query(AnswerGrade).filter(AnswerGrade.submission_id == released.id).count() == 2


def test_bulk_marking_never_touches_released_work_even_when_asked(db, course, client, make_user):
    """
    "Include already graded" means redo the ones you have looked at, not
    change a grade a student has already been given.
    """
    q = _paper_with_two_boxes(db, course)
    _submission_with_marks(db, q, make_user().id, released=True)

    res = client.as_user(course.teacher).post(
        f"/api/questions/{q.id}/grade-all",
        json={"provider": "gemini", "include_graded": True},
    )
    assert res.status_code == 200, res.text
    assert res.json() == {"queued": 0, "skipped": 1}


def test_a_student_cannot_read_a_crop_until_their_marks_are_released(
    db, course, client, make_user
):
    """
    This endpoint asked only that you were signed in — any account could
    read any student's handwriting by guessing at ids.
    """
    from models import CropImage

    student = make_user()
    other = make_user()
    q = _paper_with_two_boxes(db, course)
    db.add(Enrollment(course_id=course.id, student_id=student.id))
    sub = _submission_with_marks(db, q, student.id)
    box = sorted(q.answer_boxes, key=lambda b: b.order_index)[0]
    db.add(CropImage(submission_id=sub.id, answer_box_id=box.id, part=0,
                     data=b"\x89PNG\r\n\x1a\n", content_type="image/png"))
    db.commit()

    url = f"/api/submissions/{sub.id}/crops/{box.id}"

    # A classmate: never.
    assert client.as_user(other).get(url).status_code == 404
    # Its author, before release: not yet.
    assert client.as_user(student).get(url).status_code == 404
    # Their teacher: always.
    assert client.as_user(course.teacher).get(url).status_code == 200

    sub.released_at = __import__('datetime').datetime.now(__import__('datetime').timezone.utc)
    db.commit()
    assert client.as_user(student).get(url).status_code == 200


def _doc(*nodes):
    return {"type": "doc", "content": list(nodes)}


def _para(*inline):
    return {"type": "paragraph", "content": list(inline)}


def test_a_written_comment_is_stored_as_a_document_and_as_words(db, course, client, make_user):
    """
    Both forms, from one request.

    The document is what the teacher composed; the flattened text is
    what everything else reads — the merged `feedback` a student's
    client falls back to, and anything handed back to a model. The
    server does the flattening so the two cannot disagree, and an
    equation survives it as $…$ rather than disappearing, because an
    equation node carries its LaTeX in attributes and has no text
    content to walk.
    """
    student = make_user()
    q = _paper_with_two_boxes(db, course)
    sub = _submission_with_marks(db, q, student.id)
    box = sorted(q.answer_boxes, key=lambda b: b.order_index)[0]

    doc = _doc(
        _para(
            {"type": "text", "text": "Method is right, but "},
            {"type": "equation", "attrs": {"latex": "x = -4", "display": False}},
            {"type": "text", "text": " does not satisfy the second equation."},
        )
    )
    res = client.as_user(course.teacher).patch(
        f"/api/submissions/{sub.id}/grades/{box.id}",
        json={"score": 3, "feedback_doc": doc},
    )
    assert res.status_code == 200, res.text

    grade = (
        db.query(AnswerGrade)
        .filter(AnswerGrade.submission_id == sub.id, AnswerGrade.answer_box_id == box.id)
        .one()
    )
    assert grade.override_feedback_doc == doc
    assert "Method is right" in grade.override_feedback
    assert "$x = -4$" in grade.override_feedback, grade.override_feedback

    # And it reaches a client both ways round.
    out = next(g for g in res.json()["grades"] if g["answer_box_id"] == box.id)
    assert out["override_feedback_doc"] == doc
    assert out["feedback"] == grade.override_feedback


def test_an_emptied_editor_is_not_a_comment(db, course, client, make_user):
    """
    An editor with its text deleted still holds a paragraph. Stored as a
    comment, it would mark the box as decided by a teacher who wrote
    nothing on it — and freeze it from ever being marked again.
    """
    student = make_user()
    q = _paper_with_two_boxes(db, course)
    sub = _submission_with_marks(db, q, student.id)
    box = sorted(q.answer_boxes, key=lambda b: b.order_index)[0]

    res = client.as_user(course.teacher).patch(
        f"/api/submissions/{sub.id}/grades/{box.id}",
        json={"score": None, "feedback_doc": _doc(_para())},
    )
    assert res.status_code == 200, res.text

    grade = (
        db.query(AnswerGrade)
        .filter(AnswerGrade.submission_id == sub.id, AnswerGrade.answer_box_id == box.id)
        .one()
    )
    assert grade.override_feedback_doc is None
    assert grade.override_feedback is None
    db.expire_all()
    assert protected_answer_box_ids(db, sub) == set()
