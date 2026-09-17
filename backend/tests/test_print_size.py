"""
How big the printing actually comes out.

The paper is laid out at 150 DPI so a canonical pixel is a pixel of the
scan. A CSS pixel is 1/96 inch whatever the page is, so every length
taken from the editor covered 96/150 of the paper it was meant to:
normal body text printed at 7.2pt, and answer box labels at 5.3pt. It
was legible in a PDF viewer, which is why it survived, and barely
readable on paper.

So this measures the rendered sheet rather than the stylesheet. A rule
saying `font-size:15px` tells you nothing about how large that is; only
the physical size does.
"""

import io

import numpy as np
from pdf2image import convert_from_bytes

from services.doc_renderer import LEFT_MARGIN, RIGHT_MARGIN, TOP_MARGIN, render_finalized_question


def _question(paragraphs: int = 6) -> dict:
    content = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{
                    "type": "text",
                    "text": "The quick brown fox jumps over the lazy dog and keeps running. " * 2,
                }],
            }
            for _ in range(paragraphs)
        ],
    }
    return {
        "question_id": "print-size-q",
        "content": content,
        "physical_page": "A4",
        "dpi": 150,
        "answer_boxes": [],
    }


def _text_row_heights(page_img) -> list[int]:
    """Heights, in pixels, of the bands of ink a page's text sits in.

    One band per line of type. Measured off the rasterised page, so it
    is the ink a reader would see, not what a rule claimed.
    """
    gray = np.array(page_img.convert("L"))
    # Only the content column: the corner markers and the QR codes are
    # ink too, and they are supposed to be a fixed physical size.
    band = gray[TOP_MARGIN : gray.shape[0] - TOP_MARGIN, LEFT_MARGIN : gray.shape[1] - RIGHT_MARGIN]
    inky = (band < 128).sum(axis=1) > 0

    heights, run = [], 0
    for row in inky:
        if row:
            run += 1
        elif run:
            heights.append(run)
            run = 0
    if run:
        heights.append(run)
    return heights


def test_body_text_prints_at_a_readable_size():
    result = render_finalized_question(_question())
    pages = convert_from_bytes(result["pdf_data"], dpi=150)
    heights = _text_row_heights(pages[0])

    assert heights, "the page came out with no text on it at all"

    # A line of 15px Georgia has ascenders and descenders about 15px
    # tall in editor pixels, which is 23 at 150 DPI. Before the fix
    # every line measured about 11.
    median = sorted(heights)[len(heights) // 2]
    assert 16 <= median <= 32, (
        f"body text bands are {median}px tall at 150 DPI; expected about 23. "
        f"All bands: {sorted(heights)}"
    )


def test_paper_is_a4_sized():
    """The canonical page is A4, and the PDF has to be too — a sheet
    printed at another size rescales every mark on it, including the
    fiducials extraction measures against."""
    result = render_finalized_question(_question(paragraphs=2))
    pages = convert_from_bytes(result["pdf_data"], dpi=150)
    w, h = pages[0].size
    assert abs(w - round(8.27 * 150)) <= 4, f"page is {w}px wide at 150 DPI, not A4"
    assert abs(h - round(11.69 * 150)) <= 4, f"page is {h}px tall at 150 DPI, not A4"
