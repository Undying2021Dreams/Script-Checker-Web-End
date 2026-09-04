"""
doc_renderer.py — PDF rendering & multi-page answer box layout engine.

Pipeline for render_finalized_question(question_dict):
  1. Flatten the Tiptap JSON doc into top-level block HTML fragments.
  2. Unpaginated Measurement Pass (_measure): Headless-render fragments in
     Playwright to measure exact natural element heights (KaTeX equations, fonts).
  3. Multi-Page Answer Box Segmentation (_paginate):
     - Answer boxes can be of arbitrary height (no 800px cap).
     - If an answer box exceeds remaining page height, it starts on the current
       page (if space >= 80px) and splits into segments across subsequent pages.
     - Each segment is rendered as a standalone box with 4 closed dashed borders.
     - Subsequent blocks resume cleanly after the last segment.
  4. Final Render & Playwright DOM Coordinate Measurement:
     - Render multi-page HTML with ArUco corner markers and QR codes per segment.
     - Before writing PDF, evaluate DOM `getBoundingClientRect()` on Playwright
       to retrieve the EXACT pixel `[page_idx, x, y, w, h]` for every segment,
       aligning QR codes vertically and eliminating coordinate estimation drift.
  5. Export PDF with Playwright and return `measured_boxes` for DB storage.

Requires: `pip install playwright && playwright install chromium`
Uses KaTeX via CDN for equation rendering.
"""

from __future__ import annotations

import base64
import io
import logging

import cv2
import qrcode
from PIL import Image as PILImage

from config import settings

logger = logging.getLogger(__name__)

# Vendored locally (backend/static/katex, same version — 0.16.9 — as
# what used to be pulled from cdn.jsdelivr.net) and served by this same
# process via the /static mount in main.py, so PDF/image rendering works
# with zero internet access. Playwright fetches these over loopback
# (settings.public_base_url), not out to the real internet, so this
# works identically whether the machine is offline or not.
KATEX_CSS = f"{settings.public_base_url}/static/katex/katex.min.css"
KATEX_JS = f"{settings.public_base_url}/static/katex/katex.min.js"
KATEX_AUTORENDER = f"{settings.public_base_url}/static/katex/contrib/auto-render.min.js"

ARUCO_DICT_ID = getattr(cv2.aruco, settings.ARUCO_DICT, cv2.aruco.DICT_4X4_50)
ARUCO_DICT = cv2.aruco.getPredefinedDictionary(ARUCO_DICT_ID)
CORNER_MARKER_IDS = [0, 1, 2, 3]  # TL, TR, BL, BR

# The content area has to clear the ArUco marker footprint (the marker
# itself, drawn from the page edge inward) on every side, plus the QR
# gutter on the left (QR codes for answer boxes live in the left margin).
# Previously a single flat PAGE_MARGIN_PX (64) was smaller than the actual
# marker footprint (MARKER_MARGIN_PX + MARKER_SIZE_PX = 100), so the top
# few lines of content rendered underneath the marker. Fixed by deriving
# these from the marker geometry instead of a guessed constant.
_MARKER_ZONE = settings.MARKER_MARGIN_PX + settings.MARKER_SIZE_PX  # marker's own footprint from the page edge
_QR_SIZE = 72  # bumped up from 46 — at 46px the ~40-module QR payload this
                # encodes worked out to ~1 canonical px/module, i.e. right at
                # the theoretical minimum even for a lossless scan; any photo
                # blur/JPEG compression pushed it under the decodable floor.
                # Keep in sync with the `qrSize` JS literals below.
_QR_GUTTER = _QR_SIZE + 12  # QR width + breathing room before the content edge

TOP_MARGIN = _MARKER_ZONE + 12
BOTTOM_MARGIN = _MARKER_ZONE + 12
RIGHT_MARGIN = _MARKER_ZONE + 12
LEFT_MARGIN = _MARKER_ZONE + _QR_GUTTER + 10  # must also clear the QR gutter, not just the marker


def get_marker_positions(canvas_w: int, canvas_h: int) -> dict[int, tuple[int, int]]:
    """Same corner-marker layout as the old pdf_renderer — kept identical
    so extractor.py's homography math doesn't need to change."""
    m = settings.MARKER_MARGIN_PX
    s = settings.MARKER_SIZE_PX
    half = s // 2
    return {
        0: (m + half, m + half),
        1: (canvas_w - m - half, m + half),
        2: (m + half, canvas_h - m - half),
        3: (canvas_w - m - half, canvas_h - m - half),
    }


def _b64_png(img: PILImage.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _aruco_data_uri(marker_id: int) -> str:
    arr = cv2.aruco.generateImageMarker(ARUCO_DICT, marker_id, settings.MARKER_SIZE_PX)
    return "data:image/png;base64," + _b64_png(PILImage.fromarray(arr))


def _qr_data_uri(question_id: str, answer_box_id: str, part: int = 0, order: int = 0) -> str:
    qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=5, border=2)
    # Pipe-delimited, not JSON — JSON's braces/quotes/keys are pure
    # overhead for a fiducial that has to survive a phone photo. For a
    # realistic id pair this drops the QR from version 6 (45 modules/side)
    # to version 4 (37 modules/side), meaningfully more pixels per module
    # at the same printed size. extractor._parse_qr_payload still reads
    # the old JSON format too, so any already-printed page keeps working.
    qr.add_data(f"{question_id}|{answer_box_id}|{part}|{order}")
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    return "data:image/png;base64," + _b64_png(img)


# ── Tiptap JSON -> HTML ─────────────────────────────────────────────


def _render_marks(text: str, marks: list[dict]) -> str:
    font_size = None
    for mark in marks or []:
        mt = mark.get("type")
        if mt == "bold":
            text = f"<strong>{text}</strong>"
        elif mt == "italic":
            text = f"<em>{text}</em>"
        elif mt == "fontSize":
            font_size = mark.get("attrs", {}).get("size")
    if font_size:
        text = f'<span style="font-size:{font_size}">{text}</span>'
    return text


def _render_inline(nodes: list[dict] | None) -> str:
    out = []
    for n in nodes or []:
        t = n.get("type")
        if t == "text":
            out.append(_render_marks(n.get("text", ""), n.get("marks")))
        elif t == "equation":
            latex = n.get("attrs", {}).get("latex", "")
            display = n.get("attrs", {}).get("display", False)
            delim = f"\\[{latex}\\]" if display else f"\\({latex}\\)"
            cls = "eq-block" if display else "eq-inline"
            out.append(f'<span class="{cls}">{delim}</span>')
        elif t == "hardBreak":
            out.append("<br/>")
    return "".join(out)


def _list_items_html(list_node: dict) -> str:
    items = []
    for li in list_node.get("content", []):
        # listItem -> [paragraph, ...]; grab first paragraph's inline content
        inner = ""
        for child in li.get("content", []):
            if child.get("type") == "paragraph":
                inner = _render_inline(child.get("content"))
                break
        items.append(f"<li>{inner}</li>")
    return "".join(items)


def _render_top_level(node: dict) -> dict:
    """Returns {html, atomic, answer_box_id}."""
    t = node.get("type")

    if t == "paragraph":
        inline_nodes = node.get("content") or []
        inner = _render_inline(inline_nodes) or "&nbsp;"
        has_block_eq = any(
            c.get("type") == "equation" and c.get("attrs", {}).get("display") for c in inline_nodes
        )
        return {"html": f"<p>{inner}</p>", "atomic": has_block_eq, "answer_box_id": None}

    if t == "heading":
        level = node.get("attrs", {}).get("level", 2)
        inner = _render_inline(node.get("content"))
        return {"html": f"<h{level}>{inner}</h{level}>", "atomic": False, "answer_box_id": None}

    if t in ("bulletList", "orderedList"):
        tag = "ul" if t == "bulletList" else "ol"
        return {"html": f"<{tag}>{_list_items_html(node)}</{tag}>", "atomic": False, "answer_box_id": None}

    if t == "image":
        src = node.get("attrs", {}).get("src", "")
        alt = node.get("attrs", {}).get("alt", "")
        return {"html": f'<img class="question-image" src="{src}" alt="{alt}"/>', "atomic": True, "answer_box_id": None}

    if t == "answerBox":
        attrs = node.get("attrs", {})
        label = attrs.get("label") or "answer"
        width_pct = attrs.get("widthPercent", 100)
        min_h = attrs.get("minHeight", 90)
        return {
            "html": f'<div class="answer-box-node" style="width:{width_pct}%;min-height:{min_h}px"><div class="ab-label">☐ {label}</div></div>',
            "atomic": True,
            "answer_box_id": attrs.get("id"),
            "width_percent": width_pct,
        }

    logger.warning("Unknown top-level node type %r — skipping", t)
    return {"html": "", "atomic": False, "answer_box_id": None}


def _flatten(content_doc: dict) -> list[dict]:
    return [_render_top_level(n) for n in content_doc.get("content", [])]


def _node_to_html(node: dict) -> str:
    t = node.get("type")
    if t == "paragraph":
        inner = _render_inline(node.get("content") or []) or "&nbsp;"
        return f"<p>{inner}</p>"
    if t == "heading":
        level = node.get("attrs", {}).get("level", 2)
        inner = _render_inline(node.get("content") or [])
        return f"<h{level}>{inner}</h{level}>"
    if t in ("bulletList", "orderedList"):
        tag = "ul" if t == "bulletList" else "ol"
        return f"<{tag}>{_list_items_html(node)}</{tag}>"
    if t == "image":
        src = node.get("attrs", {}).get("src", "")
        alt = node.get("attrs", {}).get("alt", "")
        return f'<img class="question-image" src="{src}" alt="{alt}"/>'
    if t == "equation":
        latex = node.get("attrs", {}).get("latex", "")
        display = node.get("attrs", {}).get("display", False)
        delim = f"\\[{latex}\\]" if display else f"\\({latex}\\)"
        cls = "eq-block" if display else "eq-inline"
        return f'<span class="{cls}">{delim}</span>'
    if t == "hardBreak":
        return "<br/>"
    if t == "text":
        return _render_marks(node.get("text", ""), node.get("marks"))
    logger.warning("Unknown ground truth node type %r — skipping", t)
    return ""


_GROUND_TRUTH_HTML_TEMPLATE = """<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="{katex_css}">
<style>
body{{margin:0;padding:24px;font-family:Georgia,'Times New Roman',serif;color:#111}}
p{{margin:0 0 10px;font-size:15px;line-height:1.5}}
h1,h2,h3{{margin:14px 0 8px}}
ul,ol{{margin:0 0 10px 22px}}
.question-image{{max-width:100%;display:block;margin:10px 0}}
.eq-block{{display:block;text-align:center;margin:10px 0}}
.eq-inline{{}}
</style></head>
<body>{content}
<script src="{katex_js}"></script>
<script src="{katex_autorender}"></script>
<script>
renderMathInElement(document.body, {{delimiters:[
  {{left:"\\\\(", right:"\\\\)", display:false}},
  {{left:"\\\\[", right:"\\\\]", display:true}}
]}});
window.__ready = true;
</script></body></html>"""


def render_question_to_image(
    content_doc: dict | None,
    canvas_w: int = 794,
    canvas_h: int = 1123,
    up_to_gt_box_id: str | None = None,
    include_box: bool = False,
) -> bytes | None:
    """Render the question content to a PNG screenshot.

    Args:
        content_doc: Tiptap JSON document
        canvas_w: viewport width
        canvas_h: unused — kept for call-site compatibility. Height is
            determined by the content itself via a full-page screenshot.
        up_to_gt_box_id: if set, only render content up to and including this
            ground truth box id. Stops after the box if include_box=False.
        include_box: if True and up_to_gt_box_id is set, include the ground
            truth box itself in the rendered image.

    Returns:
        PNG bytes or None if nothing to render.
    """
    if not content_doc or not content_doc.get("content"):
        return None

    nodes = content_doc.get("content", [])
    html_parts = []
    found = up_to_gt_box_id is None

    for node in nodes:
        t = node.get("type")
        if t == "groundTruthBox":
            box_id = node.get("attrs", {}).get("id", "")
            if up_to_gt_box_id and box_id == up_to_gt_box_id:
                if include_box:
                    html_parts.append(_node_to_html(node))
                found = True
                break
            if up_to_gt_box_id:
                # This is a *different* question's ground truth box — it
                # marks the end of that question's segment. Whatever we've
                # accumulated so far belongs to it, not to the box we're
                # looking for, so drop it and start collecting fresh.
                html_parts = []
                continue
        elif t == "answerBox":
            continue
        else:
            html_parts.append(_node_to_html(node))

    if not found:
        # up_to_gt_box_id was passed but never matched a node in the doc —
        # the doc and the ground-truth-box row are out of sync. Render
        # nothing rather than silently returning an unrelated segment.
        return None

    content_html = "".join(html_parts)
    if not content_html.strip():
        return None

    html = f"""<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="{KATEX_CSS}">
<style>
body{{margin:0;padding:32px;font-family:Georgia,'Times New Roman',serif;color:#111;background:#fff}}
p{{margin:0 0 12px;font-size:16px;line-height:1.6}}
h1,h2,h3{{margin:18px 0 10px}}
ul,ol{{margin:0 0 12px 24px}}
.question-image{{max-width:100%;display:block;margin:12px 0;border-radius:4px}}
.eq-block{{display:block;text-align:center;margin:14px 0}}
.eq-inline{{}}
</style></head>
<body>{content_html}
<script src="{KATEX_JS}"></script>
<script src="{KATEX_AUTORENDER}"></script>
<script>
renderMathInElement(document.body, {{delimiters:[
  {{left:"\\\\(", right:"\\\\)", display:false}},
  {{left:"\\\\[", right:"\\\\]", display:true}}
]}});
window.__ready = true;
</script></body></html>"""

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            viewport={"width": canvas_w, "height": 800},
            device_scale_factor=settings.LLM_IMAGE_SCALE_FACTOR,
        )
        page.set_content(html, wait_until="load")
        page.wait_for_function("window.__ready === true", timeout=15000)
        png_bytes = page.screenshot(full_page=True, type="png")
        browser.close()

    return png_bytes


def render_ground_truth_box_to_image(content_doc: dict | list | None) -> bytes | None:
    if not content_doc:
        return None

    if isinstance(content_doc, list):
        nodes = content_doc
    elif isinstance(content_doc, dict):
        nodes = content_doc.get("content") or []
    else:
        return None

    html_parts = []
    for node in nodes:
        html_parts.append(_node_to_html(node))
    content_html = "".join(html_parts)

    if not content_html.strip():
        return None

    html = _GROUND_TRUTH_HTML_TEMPLATE.format(
        katex_css=KATEX_CSS,
        katex_js=KATEX_JS,
        katex_autorender=KATEX_AUTORENDER,
        content=content_html,
    )

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            viewport={"width": 900, "height": 800},
            device_scale_factor=settings.LLM_IMAGE_SCALE_FACTOR,
        )
        page.set_content(html, wait_until="load")
        page.wait_for_function("window.__ready === true", timeout=15000)
        png_bytes = page.screenshot(full_page=True, type="png")
        browser.close()

    return png_bytes


# ── Measurement pass ─────────────────────────────────────────────────

_MEASURE_CSS = """
body{margin:0}
.measure{font-family:Georgia,'Times New Roman',serif}
.measure p{margin:0 0 10px;font-size:15px;line-height:1.5;color:#111}
.measure h1,.measure h2,.measure h3{margin:14px 0 8px}
.measure ul,.measure ol{margin:0 0 10px 22px}
.measure .answer-box-node{border:2px dashed #999;border-radius:6px;min-height:90px;margin:0 0 10px 0;padding:8px;box-sizing:border-box}
.measure .ab-label{font-size:11px;font-weight:bold;color:#888}
.measure .question-image{max-width:100%;display:block;margin:10px 0}
"""


def _measure(blocks: list[dict], content_w: int) -> list[dict]:
    from playwright.sync_api import sync_playwright

    fragments = "".join(f'<div data-idx="{i}">{b["html"]}</div>' for i, b in enumerate(blocks))
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="{KATEX_CSS}">
<style>{_MEASURE_CSS} .measure{{width:{content_w}px}}</style></head>
<body><div class="measure">{fragments}</div>
<script src="{KATEX_JS}"></script>
<script src="{KATEX_AUTORENDER}"></script>
<script>
renderMathInElement(document.body, {{delimiters:[
  {{left:"\\\\(", right:"\\\\)", display:false}},
  {{left:"\\\\[", right:"\\\\]", display:true}}
]}});
window.__ready = true;
</script></body></html>"""

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": content_w, "height": 400})
        page.set_content(html, wait_until="load")
        page.wait_for_function("window.__ready === true", timeout=15000)
        rects = page.eval_on_selector_all(
            ".measure > div",
            "els => els.map(e => { const r = e.getBoundingClientRect(); return {top: r.top, height: r.height}; })",
        )
        browser.close()
    return rects


# ── Pagination simulation ────────────────────────────────────────────

def _paginate(blocks: list[dict], rects: list[dict], usable_h: float):
    """
    Simulate multi-page layout based on measured block heights and tops.
    Answer boxes are split into segments across pages to maximize usable space.
    """
    MIN_ANSWER_BOX_SPACE = 80.0  # px — min remaining height on page to start a segment

    page_of_block: list[int] = []
    answer_layout: dict = {}
    current_page = 0
    page_start_y = 0.0

    for i, (b, r) in enumerate(zip(blocks, rects)):
        natural_top = r["top"]
        h = r["height"]
        bid = b.get("answer_box_id")
        offset_y = natural_top - page_start_y

        if bid:
            remaining_space = usable_h - offset_y

            if h <= usable_h and remaining_space < MIN_ANSWER_BOX_SPACE and offset_y > 0:
                current_page += 1
                page_start_y = natural_top
                offset_y = 0.0
                remaining_space = usable_h

            segments = []
            remaining_h = h
            seg_page = current_page
            seg_y = offset_y

            while remaining_h > 0:
                avail = max(0.0, usable_h - seg_y)
                if avail < 20.0 and remaining_h > 20.0:
                    seg_page += 1
                    seg_y = 0.0
                    avail = usable_h

                seg_h = min(remaining_h, avail)
                segments.append((seg_page, seg_y, seg_h))
                remaining_h -= seg_h
                if remaining_h > 0:
                    seg_page += 1
                    seg_y = 0.0

            answer_layout[bid] = {
                "segments": segments,
                "width_percent": b.get("width_percent", 100),
                "total_h": h,
                "order": i,
            }
            page_of_block.append(current_page)

            last_page, last_y, last_seg_h = segments[-1]
            current_page = last_page
            next_natural_top = natural_top + h
            target_next_offset = last_y + last_seg_h
            if target_next_offset >= usable_h:
                current_page += 1
                page_start_y = next_natural_top
            else:
                page_start_y = next_natural_top - target_next_offset

        elif b.get("atomic"):
            if offset_y + h > usable_h and offset_y > 0:
                current_page += 1
                page_start_y = natural_top
                offset_y = 0.0
            page_of_block.append(current_page)
            if offset_y + h >= usable_h:
                current_page += 1
                page_start_y = natural_top + h

        else:
            if offset_y + h > usable_h and offset_y > 0:
                current_page += 1
                page_start_y = natural_top
                offset_y = 0.0
            page_of_block.append(current_page)
            if offset_y + h >= usable_h:
                current_page += 1
                page_start_y = natural_top + h

    max_page = max(page_of_block) if page_of_block else 0
    for info in answer_layout.values():
        for seg in info["segments"]:
            max_page = max(max_page, seg[0])

    return page_of_block, answer_layout, max_page + 1


# ── Final render + print ─────────────────────────────────────────────

_PRINT_CSS_TEMPLATE = """
@page {{ size: {W}px {H}px; margin: 0; }}
body{{margin:0}}
.doc-page{{position:relative;width:{W}px;height:{H}px;box-sizing:border-box;overflow:hidden;background:#fff}}
.doc-page + .doc-page{{break-before:page}}
.content{{position:absolute;left:{L}px;top:{T}px;width:{CW}px;font-family:Georgia,'Times New Roman',serif}}
.content p{{margin:0 0 10px;font-size:15px;line-height:1.5;color:#111}}
.content h1,.content h2,.content h3{{margin:14px 0 8px}}
.content ul,.content ol{{margin:0 0 10px 22px}}
.answer-box-node{{border:2px dashed #999;border-radius:6px;margin:0 0 10px 0;padding:8px;box-sizing:border-box;background:#fff}}
.ab-label{{font-size:11px;font-weight:bold;color:#888}}
.question-image{{max-width:100%;display:block;margin:10px 0}}
.marker-img,.qr-img{{position:absolute}}
"""


def render_finalized_question(question: dict) -> dict:
    """
    Args: question dict (from questions._question_to_dict) with keys
      question_id, content (tiptap json), physical_page, dpi.
    Returns: {page_w_px, page_h_px, page_count,
      boxes: {id: [[page_index,x,y,w,h], ...]},
      qr_boxes: {id: [[page_index,x,y,w,h] | null, ...]} — canonical
        position of each segment's own printed QR code, index-aligned
        with boxes[id]. Used by extractor.py as a local per-box fiducial
        for registration (see extractor._try_local_registration) — much
        less prone to lens-distortion/paper-curl drift than the single
        whole-page homography for boxes far from the 4 corner markers.
      pdf_data: bytes}
    """
    from playwright.sync_api import sync_playwright

    q_id = question["question_id"]
    dpi = question.get("dpi") or settings.DEFAULT_DPI
    canvas_w = round(8.27 * dpi)
    canvas_h = round(11.69 * dpi)
    content_w = canvas_w - LEFT_MARGIN - RIGHT_MARGIN
    usable_h = canvas_h - TOP_MARGIN - BOTTOM_MARGIN

    blocks = _flatten(question.get("content") or {"content": []})
    if not blocks:
        raise ValueError("Question has no content to render")

    rects = _measure(blocks, content_w)
    page_of_block, answer_layout, page_count = _paginate(blocks, rects, usable_h)

    marker_uris = {mid: _aruco_data_uri(mid) for mid in CORNER_MARKER_IDS}
    marker_positions = get_marker_positions(canvas_w, canvas_h)
    marker_size = settings.MARKER_SIZE_PX

    def markers_html():
        imgs = []
        for mid, (cx, cy) in marker_positions.items():
            x, y = cx - marker_size // 2, cy - marker_size // 2
            imgs.append(f'<img class="marker-img" style="left:{x}px;top:{y}px;width:{marker_size}px;height:{marker_size}px" src="{marker_uris[mid]}"/>')
        return "".join(imgs)

    from collections import defaultdict
    page_fragments: dict[int, list[str]] = defaultdict(list)
    page_qrs: dict[int, list[str]] = defaultdict(list)

    for i, b in enumerate(blocks):
        bid = b.get("answer_box_id")
        pg = page_of_block[i]

        if bid and bid in answer_layout:
            info = answer_layout[bid]
            segs = info["segments"]
            n_segs = len(segs)
            order_idx = info.get("order", i)

            ab_label = "answer"
            for node in (question.get("content") or {}).get("content", []):
                if node.get("type") == "answerBox" and node.get("attrs", {}).get("id") == bid:
                    ab_label = node.get("attrs", {}).get("label") or "answer"
                    break

            for seg_num, (seg_page, seg_top, seg_h) in enumerate(segs):
                label_text = f"\u2610 {ab_label}" if seg_num == 0 else f"\u2610 {ab_label} \u2014 part {seg_num + 1} of {n_segs}"
                box_html = (
                    f'<div class="answer-box-node answer-box-segment" '
                    f'data-box-id="{bid}" data-part-idx="{seg_num}" data-page-idx="{seg_page}" '
                    f'style="width:{info["width_percent"]}%;height:{seg_h:.0f}px;'
                    f'min-height:unset;margin:0 0 10px 0;box-sizing:border-box;">'
                    f'<div class="ab-label">{label_text}</div>'
                    f'</div>'
                )
                page_fragments[seg_page].append(box_html)

                qr_x = LEFT_MARGIN - _QR_SIZE - 10
                qr_y = TOP_MARGIN + seg_top + seg_h / 2 - _QR_SIZE / 2
                page_qrs[seg_page].append(
                    f'<img class="qr-img" data-box-id="{bid}" data-part-idx="{seg_num}" '
                    f'style="left:{qr_x}px;top:{qr_y:.0f}px;'
                    f'width:{_QR_SIZE}px;height:{_QR_SIZE}px" src="{_qr_data_uri(q_id, bid, part=seg_num, order=order_idx)}"/>'
                )
        else:
            page_fragments[pg].append(b["html"])

    pages_html = []
    for pg_idx in range(page_count):
        content_html = "".join(page_fragments.get(pg_idx, []))
        overlays = [markers_html()] + page_qrs.get(pg_idx, [])
        pages_html.append(f'<div class="doc-page">{"".join(overlays)}<div class="content">{content_html}</div></div>')

    css = _PRINT_CSS_TEMPLATE.format(W=canvas_w, H=canvas_h, L=LEFT_MARGIN, T=TOP_MARGIN, CW=content_w)
    final_html = f"""<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="{KATEX_CSS}">
<style>{css}</style></head>
<body>{"".join(pages_html)}
<script src="{KATEX_JS}"></script>
<script src="{KATEX_AUTORENDER}"></script>
<script>
renderMathInElement(document.body, {{delimiters:[
  {{left:"\\\\(", right:"\\\\)", display:false}},
  {{left:"\\\\[", right:"\\\\]", display:true}}
]}});
window.__ready = true;
</script></body></html>"""

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": canvas_w, "height": canvas_h})
        page.set_content(final_html, wait_until="load")
        page.wait_for_function("window.__ready === true", timeout=15000)

        measured = page.evaluate("""() => {
            const boxes = {};
            const qrBoxes = {};
            document.querySelectorAll('.answer-box-segment').forEach(el => {
                const bid = el.getAttribute('data-box-id');
                const partIdx = el.getAttribute('data-part-idx');
                const pageIdx = parseInt(el.getAttribute('data-page-idx'), 10);
                const docPage = el.closest('.doc-page');
                if (!docPage) return;
                const elRect = el.getBoundingClientRect();
                const pageRect = docPage.getBoundingClientRect();
                const relX = Math.round(elRect.left - pageRect.left);
                const relY = Math.round(elRect.top - pageRect.top);
                const relW = Math.round(elRect.width);
                const relH = Math.round(elRect.height);

                if (!boxes[bid]) boxes[bid] = [];
                if (!qrBoxes[bid]) qrBoxes[bid] = [];
                boxes[bid].push([pageIdx, relX, relY, relW, relH]);

                // Record this segment's own QR code's final canonical
                // position too — extraction uses it as a local fiducial to
                // register just this box, which is far less prone to
                // lens-distortion/paper-curl drift than the single
                // whole-page homography for boxes far from the page's 4
                // corner markers. Push null (not undefined) on a miss so
                // qrBoxes[bid] always stays index-aligned with boxes[bid].
                const qrImg = docPage.querySelector(`.qr-img[data-box-id="${bid}"][data-part-idx="${partIdx}"]`);
                if (qrImg) {
                    const qrSize = 72;  // must match _QR_SIZE in doc_renderer.py
                    qrImg.style.top = Math.round(relY + relH / 2 - qrSize / 2) + 'px';
                    const qrRect = qrImg.getBoundingClientRect();
                    qrBoxes[bid].push([
                        pageIdx,
                        Math.round(qrRect.left - pageRect.left),
                        Math.round(qrRect.top - pageRect.top),
                        Math.round(qrRect.width),
                        Math.round(qrRect.height),
                    ]);
                } else {
                    qrBoxes[bid].push(null);
                }
            });
            return { boxes, qrBoxes };
        }""")
        measured_boxes = measured["boxes"]
        measured_qr_boxes = measured["qrBoxes"]

        pdf_bytes = page.pdf(
            format="A4",
            width=f"{canvas_w}px",
            height=f"{canvas_h}px",
            print_background=True,
            margin={"top": "0", "bottom": "0", "left": "0", "right": "0"},
        )
        browser.close()

    boxes = measured_boxes
    logger.info("Rendered %s (%d pages, %d answer boxes)", q_id, page_count, len(boxes))

    return {
        "page_w_px": canvas_w,
        "page_h_px": canvas_h,
        "page_count": page_count,
        "boxes": boxes,
        "qr_boxes": measured_qr_boxes,
        "pdf_data": pdf_bytes,
    }


