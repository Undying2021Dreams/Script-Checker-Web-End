"""
Photographs are flattened and relit before they are stored or marked.

A page photographed by hand is tilted and lit from one side. The four
printed corner markers say exactly where the sheet is — a scanner app
has to guess that from the edges — so the same correction is exact here
rather than estimated.

Measured on real phone photographs of a real paper: they read 99.3%
"ink" by the blank detector's own measure, because paper photographs
grey rather than white. Afterwards, 2%.
"""

import io
import uuid

import cv2
import numpy as np
import pytest
from pdf2image import convert_from_bytes

from models import Course, Enrollment


@pytest.fixture
def course(db, make_user):
    teacher = make_user(role="teacher")
    course = Course(title="Numerical Methods", join_code="SCAN01", teacher_id=teacher.id)
    db.add(course)
    db.commit()
    db.refresh(course)
    course.teacher = teacher
    return course


def _finalized_paper(client, course):
    content = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Solve for x: 2x + 4 = 10"}]},
            {"type": "answerBox", "attrs": {"id": "sbox", "label": "a", "points": 5,
                                            "minHeight": 400}},
        ],
    }
    created = client.as_user(course.teacher).post(
        "/api/questions", params={"course_id": course.id}, json={}
    ).json()
    qid = created["question_id"]
    client.as_user(course.teacher).put(
        f"/api/questions/{qid}/blocks",
        json={"content": content,
              "answer_boxes": [{"id": "sbox", "label": "a", "points": 5}],
              "ground_truth_boxes": []},
    )
    assert client.as_user(course.teacher).post(f"/api/questions/{qid}/finalize").status_code == 200
    return qid


def _photographed(client, course, qid, tilt=0.05, dim=0.45):
    """The paper's own page, tilted and lit unevenly, as JPEG bytes."""
    pdf = client.as_user(course.teacher).get(f"/api/questions/{qid}/pdf").content
    page = convert_from_bytes(pdf, dpi=200, fmt="png")[0]
    img = cv2.cvtColor(np.array(page), cv2.COLOR_RGB2BGR)

    h, w = img.shape[:2]
    d = tilt * w
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[d, d * 0.5], [w - d * 0.3, 0], [w, h - d * 0.4], [d * 0.6, h]])
    out = cv2.warpPerspective(img, cv2.getPerspectiveTransform(src, dst), (w, h),
                              borderValue=(90, 90, 90))
    ramp = np.linspace(1.0, dim, w, dtype=np.float32)[None, :, None]
    out = np.clip(out.astype(np.float32) * ramp, 0, 255).astype(np.uint8)
    return cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()


def _ink_percent(data: bytes) -> float:
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    return float((gray < 200).sum()) / gray.size * 100


def test_a_photograph_is_flattened_and_relit_before_it_is_stored(client, course, db, make_user):
    student = make_user()
    qid = _finalized_paper(client, course)
    db.add(Enrollment(course_id=course.id, student_id=student.id))
    db.commit()

    photo = _photographed(client, course, qid)
    before = _ink_percent(photo)

    res = client.as_user(student).post(
        "/api/submissions",
        # Same as the real client sends: the codes on a photographed
        # page rarely read, so the student says which page it is as they
        # take it.
        data={"question_id": qid, "modality": "photo", "page_index_hint": "0"},
        files={"image": ("page.jpg", photo, "image/jpeg")},
    )
    assert res.status_code == 200, res.text
    body = res.json()

    # Still extracts: flattening puts the markers exactly where the
    # canonical page says they are, so the transform that follows is
    # near-identity rather than absent.
    assert body["pages"][0]["markers_detected"] == "4/4", body["pages"][0]
    assert body["pages"][0]["crops"], "no crops came out of the scanned page"

    stored = client.as_user(student).get(
        f"/api/submissions/{body['submission_id']}/images/{body['pages'][0]['page_index']}"
    )
    assert stored.status_code == 200
    after = _ink_percent(stored.content)

    # The photograph came in grey — nearly every pixel below the blank
    # detector's threshold — and is stored white.
    assert before > 50, f"the test photo was supposed to be dimly lit, got {before:.1f}%"
    assert after < 25, f"the stored page is still grey: {after:.1f}% ink"

    page = cv2.imdecode(np.frombuffer(stored.content, np.uint8), cv2.IMREAD_COLOR)
    assert abs(page.shape[1] / page.shape[0] - 1240 / 1754) < 0.02, (
        f"the stored page is not A4-shaped: {page.shape[1]}x{page.shape[0]}"
    )


def test_a_scanner_upload_is_left_exactly_as_it_arrived(client, course, db):
    """
    A flatbed scan and a PDF page are already flat and evenly lit.
    Running them through this would be a resampling pass that costs
    sharpness and buys nothing, so the modality decides.
    """
    qid = _finalized_paper(client, course)
    pdf = client.as_user(course.teacher).get(f"/api/questions/{qid}/pdf").content
    page = convert_from_bytes(pdf, dpi=200, fmt="png")[0]
    buf = io.BytesIO()
    page.save(buf, format="PNG")
    sent = buf.getvalue()

    res = client.as_user(course.teacher).post(
        "/api/submissions",
        data={"question_id": qid, "modality": "scanner"},
        files={"image": ("page.png", sent, "image/png")},
    )
    assert res.status_code == 200, res.text
    body = res.json()

    stored = client.as_user(course.teacher).get(
        f"/api/submissions/{body['submission_id']}/images/{body['pages'][0]['page_index']}"
    )
    assert stored.content == sent, "a scanner upload was rewritten"


def test_a_teacher_can_discard_a_script_and_a_student_cannot(client, course, db, make_user):
    """
    Discarding a whole script is the teacher's.

    A student can already take back a page they have not handed in.
    Letting them throw away a handed-in script would let them unsubmit
    after seeing a mark, which is the one thing handing in is for.
    """
    from models import CropImage, Submission, SubmissionImage

    student = make_user()
    qid = _finalized_paper(client, course)
    db.add(Enrollment(course_id=course.id, student_id=student.id))
    db.commit()

    photo = _photographed(client, course, qid)
    res = client.as_user(student).post(
        "/api/submissions",
        data={"question_id": qid, "modality": "photo", "page_index_hint": "0"},
        files={"image": ("page.jpg", photo, "image/jpeg")},
    )
    assert res.status_code == 200, res.text
    sub_id = res.json()["submission_id"]
    assert db.query(SubmissionImage).filter(SubmissionImage.submission_id == sub_id).count()

    # The student who sent it may not discard it.
    assert client.as_user(student).delete(f"/api/submissions/{sub_id}").status_code == 404

    # Nor may a teacher of some other course.
    outsider = make_user(role="teacher")
    assert client.as_user(outsider).delete(f"/api/submissions/{sub_id}").status_code == 404

    assert client.as_user(course.teacher).delete(f"/api/submissions/{sub_id}").status_code == 200

    # And the work goes with it rather than being left behind.
    assert db.query(Submission).filter(Submission.id == sub_id).count() == 0
    assert db.query(SubmissionImage).filter(SubmissionImage.submission_id == sub_id).count() == 0
    assert db.query(CropImage).filter(CropImage.submission_id == sub_id).count() == 0


def _multi_page_paper(client, course):
    """A finalized paper that runs to more than one sheet.

    Answer box ids are unique across the whole database, so each call
    mints its own — two of these exist side by side in one test.
    """
    tag = uuid.uuid4().hex[:8]
    boxes = [{"id": f"{tag}-a", "label": "a", "points": 5},
             {"id": f"{tag}-b", "label": "b", "points": 5}]
    content = {
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": "Question one."}]},
            *[{"type": "answerBox", "attrs": {**b, "minHeight": 1400}} for b in boxes],
        ],
    }
    qid = client.as_user(course.teacher).post(
        "/api/questions", params={"course_id": course.id}, json={}
    ).json()["question_id"]
    client.as_user(course.teacher).put(
        f"/api/questions/{qid}/blocks",
        json={"content": content, "answer_boxes": boxes, "ground_truth_boxes": []},
    )
    finalized = client.as_user(course.teacher).post(f"/api/questions/{qid}/finalize")
    assert finalized.status_code == 200, finalized.text
    pages = client.as_user(course.teacher).get(f"/api/questions/{qid}").json()["page_count"]
    assert pages > 1, f"this paper was supposed to run to several sheets, got {pages}"
    return qid, pages


def test_a_whole_pdf_is_accepted_without_being_told_any_page_numbers(client, course, db, make_user):
    """
    A PDF is the whole script in one file. Every page carries the codes
    that say which page it is, so there is nothing to ask the student —
    which is the difference from a photograph, where those codes rarely
    survive.
    """
    student = make_user()
    qid, page_count = _multi_page_paper(client, course)
    db.add(Enrollment(course_id=course.id, student_id=student.id))
    db.commit()

    pdf = client.as_user(course.teacher).get(f"/api/questions/{qid}/pdf").content
    res = client.as_user(student).post(
        "/api/submissions",
        data={"question_id": qid, "modality": "scanner"},
        files={"image": ("script.pdf", pdf, "application/pdf")},
    )
    assert res.status_code == 200, res.text
    assert sorted(p["page_index"] for p in res.json()["pages"]) == list(range(page_count))


def test_a_pdf_of_the_wrong_paper_is_refused_by_name(client, course, db, make_user):
    from services import extractor

    if not extractor._zbar_available():
        pytest.skip("no zbar here, so no page can say which paper it belongs to")

    student = make_user()
    mine, _ = _multi_page_paper(client, course)
    theirs, _ = _multi_page_paper(client, course)
    db.add(Enrollment(course_id=course.id, student_id=student.id))
    db.commit()

    other_pdf = client.as_user(course.teacher).get(f"/api/questions/{theirs}/pdf").content
    res = client.as_user(student).post(
        "/api/submissions",
        data={"question_id": mine, "modality": "scanner"},
        files={"image": ("script.pdf", other_pdf, "application/pdf")},
    )
    assert res.status_code == 422, res.text
    assert "different" in res.json()["detail"].lower(), res.json()

    # And nothing of it was kept.
    from models import Submission
    assert db.query(Submission).filter(Submission.student_id == student.id).count() == 0


def test_a_pdf_longer_than_the_paper_is_refused_rather_than_trimmed(client, course, db, make_user):
    """
    The extra pages used to be dropped silently. A document with a cover
    sheet in front of it then shifted by one and lost its last answer
    off the end, with nothing said about it.
    """
    student = make_user()
    qid, page_count = _multi_page_paper(client, course)
    db.add(Enrollment(course_id=course.id, student_id=student.id))
    db.commit()

    pdf = client.as_user(course.teacher).get(f"/api/questions/{qid}/pdf").content
    pages = [p.convert("RGB") for p in convert_from_bytes(pdf, dpi=120, fmt="png")]
    assert len(pages) == page_count

    # One sheet more than the paper has, as a cover page would make it.
    # Built with Pillow rather than a PDF library, because this is the
    # only place in the project that would need one.
    longer = io.BytesIO()
    pages[0].save(longer, format="PDF", save_all=True, append_images=pages)

    res = client.as_user(student).post(
        "/api/submissions",
        data={"question_id": qid, "modality": "scanner"},
        files={"image": ("script.pdf", longer.getvalue(), "application/pdf")},
    )
    assert res.status_code == 422, res.text
    assert "pages" in res.json()["detail"].lower(), res.json()


def test_an_oversized_pdf_page_is_rasterised_down_rather_than_whole():
    """
    What this endpoint costs is driven by pixels, not by pages.

    A PDF written by a phone scanner app often declares a page far
    larger than A4, because it sizes the page to the photograph.
    Rendered at a flat 300 DPI that gave 5000x7000 images, and every
    stage afterwards is per-pixel: a five page document took 46 seconds
    on a laptop against nine once this was capped, with identical crops
    out the other end.
    """
    from PIL import Image

    from routers.submissions import _MAX_PAGE_LONG_EDGE_PX, _pdf_page_dpi

    def pdf_of(width_px, height_px):
        # Pillow writes the page at 72 points per inch of the image, so
        # a large image becomes a large page — exactly the shape of the
        # problem.
        buf = io.BytesIO()
        Image.new("RGB", (width_px, height_px), "white").save(buf, format="PDF")
        return buf.getvalue()

    a4_at_150 = pdf_of(1240, 1754)
    huge = pdf_of(3000, 4000)

    assert _pdf_page_dpi(a4_at_150) * (1754 / 72) <= _MAX_PAGE_LONG_EDGE_PX + 1
    assert _pdf_page_dpi(huge) * (4000 / 72) <= _MAX_PAGE_LONG_EDGE_PX + 1
    assert _pdf_page_dpi(huge) < _pdf_page_dpi(a4_at_150), (
        "a larger page should be rendered at a lower DPI, not the same one"
    )
    # Something unreadable must not stop an upload; it falls back.
    assert _pdf_page_dpi(b"not a pdf at all") > 0
