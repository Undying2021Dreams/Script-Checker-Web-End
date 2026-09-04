"""
The student's side of a course.

The rule these exist to protect: a Question's `content` holds the model
answers inline as groundTruthBox nodes, so anything student-facing that
returned document content would hand over the answer key.
"""

import pytest

from models import (
    AnswerBox, Course, CropImage, Enrollment, GroundTruthBox, Question, QuestionPdf,
    Submission,
)


@pytest.fixture
def setup(db, make_user):
    teacher = make_user(role="teacher")
    student = make_user(role="student", display_name="Ada")
    outsider = make_user(role="student")

    course = Course(title="NM", join_code="STU001", teacher_id=teacher.id)
    db.add(course)
    db.commit()
    db.add(Enrollment(course_id=course.id, student_id=student.id))

    content = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Solve 2x+4=10"}]},
            {"type": "answerBox", "attrs": {"id": "sb1", "label": "a", "points": 5}},
            {
                "type": "groundTruthBox",
                "attrs": {"id": "sg1", "label": "Sol"},
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "x = 3"}]}],
            },
        ],
    }
    finalized = Question(
        course_id=course.id, created_by=teacher.id, state="finalized", content=content, page_count=1
    )
    draft = Question(course_id=course.id, created_by=teacher.id, state="draft", content=content)
    db.add_all([finalized, draft])
    db.flush()
    db.add(AnswerBox(id="sb1", question_id=finalized.id, label="a", points=5, order_index=0))
    db.add(GroundTruthBox(id="sg1", question_id=finalized.id, order_index=0))
    db.add(QuestionPdf(question_id=finalized.id, data=b"%PDF-fake"))
    db.commit()

    return {
        "teacher": teacher, "student": student, "outsider": outsider,
        "course": course, "question": finalized, "draft": draft,
    }


def test_student_sees_finalized_assignments_with_marks_available(client, setup):
    res = client.as_user(setup["student"]).get(
        "/api/student/assignments", params={"course_id": setup["course"].id}
    )
    assert res.status_code == 200
    body = res.json()

    assert len(body) == 1  # the draft isn't set yet, so it isn't listed
    assert body[0]["question_id"] == setup["question"].id
    assert body[0]["total_marks"] == 5
    assert body[0]["submission_id"] is None


def test_assignment_list_never_carries_document_content(client, setup):
    """The doc holds the model answers inline, so it must not appear here."""
    res = client.as_user(setup["student"]).get(
        "/api/student/assignments", params={"course_id": setup["course"].id}
    )
    raw = res.text
    assert "content" not in res.json()[0]
    assert "ground_truth" not in raw
    assert "x = 3" not in raw  # the actual answer


def test_outsider_cannot_list_a_courses_assignments(client, setup):
    res = client.as_user(setup["outsider"]).get(
        "/api/student/assignments", params={"course_id": setup["course"].id}
    )
    assert res.status_code == 404


def test_student_can_download_the_paper(client, setup):
    res = client.as_user(setup["student"]).get(
        f"/api/student/assignments/{setup['question'].id}/pdf"
    )
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert res.content.startswith(b"%PDF-")


def test_outsider_cannot_download_the_paper(client, setup):
    res = client.as_user(setup["outsider"]).get(
        f"/api/student/assignments/{setup['question'].id}/pdf"
    )
    assert res.status_code == 404


def test_draft_papers_are_not_downloadable(client, setup):
    # A draft is a teacher's work in progress with no printable paper.
    res = client.as_user(setup["student"]).get(
        f"/api/student/assignments/{setup['draft'].id}/pdf"
    )
    assert res.status_code == 404


def test_marks_stay_hidden_until_released(client, setup, db, make_user, monkeypatch):
    from tests.test_grading import FakeProvider

    sub = Submission(
        question_id=setup["question"].id, student_id=setup["student"].id,
        modality="photo", manifest={},
    )
    db.add(sub)
    db.flush()
    # Without an extracted crop the grader correctly refuses to mark and
    # flags for review instead, so there'd be no mark to hide or release.
    db.add(CropImage(submission_id=sub.id, answer_box_id="sb1", part=0, data=b"CROP"))
    db.commit()

    provider = FakeProvider(["SCORE: 4\nFEEDBACK: ok"])
    monkeypatch.setattr("routers.grading.get_provider", lambda name: provider)
    client.as_user(setup["teacher"]).post(
        f"/api/submissions/{sub.id}/grade", json={"provider": "self_hosted"}
    )

    def _assignment():
        return client.as_user(setup["student"]).get(
            "/api/student/assignments", params={"course_id": setup["course"].id}
        ).json()[0]

    before = _assignment()
    assert before["submission_id"] == sub.id
    # The student is told it's being marked, but not what the mark is.
    assert before["submission_status"] == "graded"
    assert before["released"] is False
    assert before["earned"] is None
    assert before["max_score"] is None

    client.as_user(setup["teacher"]).post(f"/api/submissions/{sub.id}/release")

    after = _assignment()
    assert after["released"] is True
    assert after["earned"] == 4


def test_a_students_list_shows_only_their_own_submission(client, setup, db, make_user):
    other = make_user(role="student")
    db.add(Enrollment(course_id=setup["course"].id, student_id=other.id))
    db.add(Submission(
        question_id=setup["question"].id, student_id=other.id, modality="photo", manifest={},
    ))
    db.commit()

    mine = client.as_user(setup["student"]).get(
        "/api/student/assignments", params={"course_id": setup["course"].id}
    ).json()[0]
    assert mine["submission_id"] is None  # the other student's doesn't leak in
