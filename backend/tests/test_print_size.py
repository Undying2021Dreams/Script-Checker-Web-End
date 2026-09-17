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


def _paper_with_box_pushed_down(
    filler_lines: int, width_percent: int = 50, min_height: int = 1200
) -> dict:
    """A tall answer box preceded by enough text to start it near the
    bottom of a page — the case where it has to be split."""
    para = {"type": "paragraph", "content": [{"type": "text", "text": "Filler line. " * 6}]}
    return {
        "question_id": "split-q",
        "physical_page": "A4",
        "dpi": 150,
        "answer_boxes": [],
        "content": {
            "type": "doc",
            "content": [
                *[dict(para) for _ in range(filler_lines)],
                {
                    "type": "answerBox",
                    "attrs": {"id": "tall", "label": "a", "minHeight": min_height,
                              "widthPercent": width_percent},
                },
            ],
        },
    }


def test_a_split_answer_box_never_leaves_a_strip_too_small_to_write_in():
    """
    A box taller than the room left on the page is cut into strips. They
    used to be allowed down to 20 canonical pixels — two millimetres of
    paper, printed with a label on it and useless to write in.

    The sweep is the point: the bug only appeared at the few filler
    counts that happened to land the box near a page boundary, which is
    why a single fixed case would not have caught it. At 24 lines the
    last strip came out 34px tall, and a whole page existed to carry it.
    """
    # A fixed physical size, not the module's own constant: asserting a
    # strip is at least MIN_SEGMENT_H tall when MIN_SEGMENT_H is what
    # produced it proves nothing, and passed at the old 20px.
    smallest_usable_inches = 1.2

    worst = None
    for filler in range(14, 32):
        layout = render_finalized_question(_paper_with_box_pushed_down(filler))
        for page_index, _x, _y, _w, height in layout["boxes"]["tall"]:
            if worst is None or height < worst[0]:
                worst = (height, filler, page_index)

    assert worst is not None
    height, filler, page_index = worst
    assert height / 150 >= smallest_usable_inches, (
        f"a strip {height / 150:.2f} inch tall was printed on page "
        f"{page_index + 1} with {filler} lines of text above the box"
    )


def test_a_box_that_splits_across_pages_is_printed_full_width():
    """A 50% box that fits on one page stays 50%. The same box, pushed
    down far enough to need a second page, is widened to the full
    column — a narrow strip continuing overleaf reads as a different
    box rather than the rest of the same one."""
    fits = render_finalized_question(
        _paper_with_box_pushed_down(2, width_percent=50, min_height=400)
    )
    assert len(fits["boxes"]["tall"]) == 1, "expected this one not to split"
    narrow_w = fits["boxes"]["tall"][0][3]

    splits = render_finalized_question(_paper_with_box_pushed_down(24, width_percent=50))
    assert len(splits["boxes"]["tall"]) > 1, "expected this one to split"
    widths = {seg[3] for seg in splits["boxes"]["tall"]}

    assert len(widths) == 1, f"the strips came out different widths: {sorted(widths)}"
    assert widths.pop() > narrow_w * 1.8, (
        f"a split box printed {narrow_w}px wide — the same as when it fits on one page"
    )
