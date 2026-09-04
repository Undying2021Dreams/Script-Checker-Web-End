"""
Deterministic Extractor — simplified.

We no longer search for a "question region" — the teacher-authored doc IS
the ground truth question/solution text, so extraction's only job is to
crop out each answer_box on the submitted page and cross-check its QR.

A submission now targets one physical page of a (possibly multi-page)
question via `page_index` (0 for single-page questions, which covers the
common case unchanged from before).

Modalities: tablet (identity), photo (homography), scanner (affine).
"""

from __future__ import annotations

import io
import json
import logging
import uuid

import cv2
import numpy as np
from PIL import Image as PILImage

from config import settings
from services.doc_renderer import get_marker_positions, ARUCO_DICT

logger = logging.getLogger(__name__)

ARUCO_PARAMS = cv2.aruco.DetectorParameters()
ARUCO_DETECTOR = cv2.aruco.ArucoDetector(ARUCO_DICT, ARUCO_PARAMS)


def _decode_image(image_bytes: bytes) -> tuple[np.ndarray, int | None]:
    dpi = None
    try:
        pil_img = PILImage.open(io.BytesIO(image_bytes))
        if "dpi" in pil_img.info:
            dpi = int(pil_img.info["dpi"][0])
    except Exception:
        pass

    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Failed to decode image — unsupported format or corrupt file")
    return img, dpi


def _detect_aruco_markers(img: np.ndarray) -> dict[int, np.ndarray]:
    corners, ids, _ = ARUCO_DETECTOR.detectMarkers(img)
    if ids is None:
        return {}
    return {int(mid): corners[i][0].mean(axis=0) for i, mid in enumerate(ids.flatten())}


def _compute_transform(canonical_pts: np.ndarray, detected_pts: np.ndarray, modality: str):
    if modality == "tablet":
        return None, "identity"
    if modality == "photo":
        H, _ = cv2.findHomography(canonical_pts, detected_pts, cv2.RANSAC, 5.0)
        return H, "homography"
    if modality == "scanner":
        M, _ = cv2.estimateAffine2D(canonical_pts, detected_pts)
        return np.vstack([M, [0, 0, 1]]), "affine"
    raise ValueError(f"Unknown modality: {modality}")


def _transform_bbox(bbox: list[int], transform: np.ndarray | None) -> np.ndarray:
    x, y, w, h = bbox
    corners = np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], dtype=np.float64)
    if transform is None:
        return corners
    warped = cv2.perspectiveTransform(corners.reshape(-1, 1, 2), transform)
    return warped.reshape(-1, 2)


def _crop_region(img: np.ndarray, corners: np.ndarray) -> np.ndarray:
    x_min = max(0, int(corners[:, 0].min()))
    y_min = max(0, int(corners[:, 1].min()))
    x_max = min(img.shape[1], int(corners[:, 0].max()))
    y_max = min(img.shape[0], int(corners[:, 1].max()))
    if x_max <= x_min or y_max <= y_min:
        logger.warning("Degenerate crop region: (%d,%d)-(%d,%d)", x_min, y_min, x_max, y_max)
        return np.zeros((10, 10, 3), dtype=np.uint8)
    return img[y_min:y_max, x_min:x_max].copy()


def _encode_png(img: np.ndarray) -> bytes:
    success, buf = cv2.imencode(".png", img)
    if not success:
        raise ValueError("Failed to encode PNG")
    return buf.tobytes()


def _detect_qr(region: np.ndarray) -> tuple[str, np.ndarray | None]:
    """Decode a QR code in `region`, returning its text and 4 corner
    points (region-local pixel coords, shape (4,2), ordered
    top-left/top-right/bottom-right/bottom-left) if found — or ("", None)
    if not. Tries OpenCV's built-in decoder first, then falls back to
    pyzbar (the zbar library) if available and cv2 comes up empty. zbar is
    generally more robust on small/blurry/perspective-skewed codes than
    OpenCV's own decoder — exactly the failure mode a handheld phone
    photo produces for the small per-box QR codes.

    Both decoders' points are normalized to the SAME corner order before
    returning, since callers (_try_local_registration) build a homography
    from these against canonically-ordered points — cv2 returns corners
    clockwise starting top-left (TL,TR,BR,BL), but pyzbar/zbar returns
    them counter-clockwise starting top-left (TL,BL,BR,TR). Silently
    mixing the two conventions produces a transposed/flipped homography
    that still centers roughly correctly but warps a wide box into a
    tall narrow one (or vice versa) — confirmed by hand while testing
    this feature, not a hypothetical."""
    data, points, _ = cv2.QRCodeDetector().detectAndDecode(region)
    if data and points is not None:
        return data, points.reshape(-1, 2)

    try:
        from pyzbar.pyzbar import decode as pyzbar_decode
        results = pyzbar_decode(region)
        if results:
            r = results[0]
            raw = [(p.x, p.y) for p in r.polygon]
            if len(raw) == 4:
                # pyzbar order (TL,BL,BR,TR) -> cv2 order (TL,TR,BR,BL)
                raw = [raw[0], raw[3], raw[2], raw[1]]
            poly = np.array(raw, dtype=np.float64)
            return r.data.decode("utf-8"), poly
    except ImportError:
        pass

    return "", None


def _parse_qr_payload(data: str) -> dict | None:
    """Decode a QR's payload text into {q, b, part, order}.

    Current format is compact pipe-delimited `q|b|part|order` — doc_renderer
    switched to this from JSON because JSON's braces/quotes/keys were pure
    overhead for a fiducial that has to survive a phone photo (roughly
    halves the QR's module count at the same encoded ids). Still parses
    the old JSON format too so a page that was already printed before this
    change doesn't suddenly stop being readable."""
    if not data:
        return None
    if data.startswith("{"):
        try:
            return json.loads(data)
        except json.JSONDecodeError:
            return None
    parts = data.split("|")
    if len(parts) != 4:
        return None
    q, b, part_s, order_s = parts
    try:
        return {"q": q, "b": b, "part": int(part_s), "order": int(order_s)}
    except ValueError:
        return None


def _check_qr(img: np.ndarray, corners: np.ndarray, question_id: str, answer_box_id: str, part: int = 0, margin: int = 80) -> str:
    x_min = max(0, int(corners[:, 0].min()) - margin)
    y_min = max(0, int(corners[:, 1].min()) - margin)
    x_max = min(img.shape[1], int(corners[:, 0].max()) + margin)
    y_max = min(img.shape[0], int(corners[:, 1].max()) + margin)
    region = img[y_min:y_max, x_min:x_max]
    if region.size == 0:
        return "absent"

    data, _ = _detect_qr(region)
    if not data:
        return "absent"

    payload = _parse_qr_payload(data)
    if payload is None:
        return "fail"
    if payload.get("q") == question_id and payload.get("b") == answer_box_id:
        if "part" in payload and payload.get("part") != part:
            logger.warning("QR part mismatch for answer_box %s: expected %d, got %s", answer_box_id, part, payload.get("part"))
            return "fail"
        return "pass"
    logger.warning("QR mismatch for answer_box %s: got %s", answer_box_id, payload)
    return "fail"


def _try_local_registration(
    img: np.ndarray,
    canonical_qr_bbox: tuple[int, int, int, int] | None,
    canonical_box_bbox: list[int],
    global_transform: np.ndarray | None,
    question_id: str,
    answer_box_id: str,
    part: int,
) -> tuple[np.ndarray, str] | None:
    """
    Register ONE answer box using its own printed QR code as a local
    4-point homography anchor, instead of relying only on the single
    whole-page homography computed from the 4 far-away corner markers.

    Why this helps: a homography is only exact for a perfectly flat,
    distortion-free plane. A real phone photo has some lens distortion
    and the paper itself may have a slight curl, so a single homography
    fit from 4 page-corner markers accumulates more error the further an
    answer box is from those corners. The QR code already printed in the
    margin right next to this specific box is a second, LOCAL fiducial —
    using it directly (rather than only for identity verification, as
    _check_qr does) gets a registration that's accurate right where it
    matters for this box, independent of how far it sits from the page
    corners.

    Returns (local_homography, qr_check="pass") on success. Returns None
    if local registration isn't usable, in which case the caller should
    fall back to the existing whole-page transform — this function is
    intentionally conservative about when to trust itself:
      - no canonical QR position recorded for this segment (e.g. a
        question finalized before this feature existed)
      - no global transform to search around
      - the QR wasn't found / didn't decode in the search window (e.g.
        occluded, blurry, too small in a wide shot)
      - the decoded payload doesn't match this exact box+part (could be
        a neighboring box's QR caught in the search window)
      - local and global registration disagree by more than one box's
        width/height — treated as a sign the "detection" above was
        spurious rather than trusting a confidently-wrong crop
    """
    if canonical_qr_bbox is None or global_transform is None:
        return None

    qx, qy, qw, qh = canonical_qr_bbox
    canonical_qr_corners = np.array(
        [[qx, qy], [qx + qw, qy], [qx + qw, qy + qh], [qx, qy + qh]], dtype=np.float64
    )

    # The global homography is only used to guess roughly WHERE this
    # box's QR probably landed in the photo — a coarse search window, not
    # the final registration.
    approx = cv2.perspectiveTransform(
        canonical_qr_corners.reshape(-1, 1, 2), global_transform
    ).reshape(-1, 2)
    margin = 60
    x_min = max(0, int(approx[:, 0].min()) - margin)
    y_min = max(0, int(approx[:, 1].min()) - margin)
    x_max = min(img.shape[1], int(approx[:, 0].max()) + margin)
    y_max = min(img.shape[0], int(approx[:, 1].max()) + margin)
    region = img[y_min:y_max, x_min:x_max]
    if region.size == 0:
        return None

    data, points = _detect_qr(region)
    if not data or points is None:
        return None

    payload = _parse_qr_payload(data)
    if payload is None:
        return None
    if (
        payload.get("q") != question_id
        or payload.get("b") != answer_box_id
        or payload.get("part", 0) != part
    ):
        return None

    detected_qr_corners = points + np.array([x_min, y_min], dtype=np.float64)
    local_H = cv2.getPerspectiveTransform(
        canonical_qr_corners.astype(np.float32), detected_qr_corners.astype(np.float32)
    )
    if local_H is None:
        return None

    # Sanity check against the global homography before trusting this.
    # Two checks, not one — a center-only check isn't enough: for a
    # roughly-square QR, a corner-ORDER bug (e.g. two decoders numbering
    # corners in opposite winding order) can produce a homography that
    # still centers in roughly the right place but rotates/transposes
    # the box's shape entirely (a 934x150 box coming out ~136x843) —
    # exactly the failure mode caught here while building this feature,
    # not a hypothetical.
    bx, by, bw, bh = canonical_box_bbox
    box_corners = np.array(
        [[bx, by], [bx + bw, by], [bx + bw, by + bh], [bx, by + bh]], dtype=np.float64
    ).reshape(-1, 1, 2)
    global_box = cv2.perspectiveTransform(box_corners, global_transform).reshape(-1, 2)
    local_box = cv2.perspectiveTransform(box_corners, local_H).reshape(-1, 2)

    def _quad_size(c: np.ndarray) -> tuple[float, float]:
        tl, tr, br, bl = c
        width = (np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) / 2
        height = (np.linalg.norm(bl - tl) + np.linalg.norm(br - tr)) / 2
        return width, height

    global_w, global_h = _quad_size(global_box)
    local_w, local_h = _quad_size(local_box)
    if global_w <= 0 or global_h <= 0 or local_w <= 0 or local_h <= 0:
        return None
    # Shape/orientation check: a correct local registration should
    # reproduce roughly the same box proportions as the global one (some
    # perspective skew is expected, a near-90-degree effective rotation
    # is not) — reject if either dimension is off by more than 2x.
    if not (0.5 <= local_w / global_w <= 2.0) or not (0.5 <= local_h / global_h <= 2.0):
        logger.warning(
            "Local QR registration for answer_box %s produced an implausible box shape "
            "(local %.0fx%.0f vs global %.0fx%.0f) — likely a corner-order mismatch, "
            "falling back to page-level registration.",
            answer_box_id, local_w, local_h, global_w, global_h,
        )
        return None
    # Position check: a fixed pixel tolerance, not one scaled by the
    # box's own size (a wide box would otherwise tolerate an absurd
    # amount of drift) — generous enough to allow local registration to
    # legitimately correct real global-homography drift, not so generous
    # it stops meaning anything.
    global_center = global_box.mean(axis=0)
    local_center = local_box.mean(axis=0)
    max_drift = 120.0
    if np.linalg.norm(global_center - local_center) > max_drift:
        logger.warning(
            "Local QR registration for answer_box %s diverged from global homography "
            "by more than %.0f px — falling back to page-level registration.",
            answer_box_id, max_drift,
        )
        return None

    return local_H, "pass"


def get_page_segments(question: dict, page_index: int) -> list[tuple[dict, int, list[int]]]:
    """Which (answer_box, part_index, canonical_bbox) entries land on a
    given physical page. Shared between extract_page (to know what to
    crop) and submissions.py (to know exactly which stored crops to clear
    before writing a resubmitted page, so retaking a page's photo can't
    leave stale crops behind from a worse earlier attempt)."""
    page_segments = []
    for box in question.get("answer_boxes", []):
        segs = box.get("segments") or []
        if segs:
            for part_idx, seg in enumerate(segs):
                if seg[0] == page_index:
                    page_segments.append((box, part_idx, seg[1:]))
        elif box.get("page_index") == page_index and box.get("bbox"):
            page_segments.append((box, 0, box["bbox"]))
    return page_segments


def extract_page(
    question: dict,
    image_bytes: bytes | None,
    modality: str,
    page_index: int = 0,
    ink_strokes: list | None = None,
    submission_id: str | None = None,
) -> dict:
    """
    Extract answer-box crops for ONE physical page. Returns a page-scoped
    dict: {page_index, markers_detected, transform_type, crops,
    image_resolution, image_dpi, [error]} — the caller (submissions router)
    assembles these into the full multi-page ExtractionResult.
    """
    submission_id = submission_id or str(uuid.uuid4())
    q_id = question["question_id"]
    canvas_w, canvas_h = question["page_w_px"], question["page_h_px"]
    page_segments = get_page_segments(question, page_index)

    if not page_segments:
        return {
            "page_index": page_index,
            "markers_detected": "N/A",
            "transform_type": "none",
            "crops": [],
            "image_resolution": None,
            "image_dpi": None,
            "error": f"No answer boxes found on page {page_index} for question {q_id}.",
        }

    if modality == "tablet":
        result = _extract_tablet(question, page_segments, ink_strokes, submission_id)
        result["page_index"] = page_index
        return result

    if image_bytes is None:
        raise ValueError("image_bytes required for photo/scanner modality")

    img, detected_dpi = _decode_image(image_bytes)
    img_h, img_w = img.shape[:2]

    detected_markers = _detect_aruco_markers(img)
    n_detected = len([mid for mid in detected_markers if mid in (0, 1, 2, 3)])

    if n_detected < 4:
        return {
            "page_index": page_index,
            "markers_detected": f"{n_detected}/4",
            "transform_type": "none",
            "crops": [],
            "image_resolution": f"{img_w}x{img_h}",
            "image_dpi": detected_dpi,
            "error": f"Only {n_detected}/4 ArUco markers detected on page {page_index}. Flag for manual review.",
        }

    canonical_pos = get_marker_positions(canvas_w, canvas_h)
    src_pts = np.array([canonical_pos[i] for i in range(4)], dtype=np.float64)
    dst_pts = np.array([detected_markers[i] for i in range(4)], dtype=np.float64)
    transform, transform_type = _compute_transform(src_pts, dst_pts, modality)

    crops = []
    for box, part_idx, bbox in page_segments:
        canonical_qr_bbox = None
        qr_segs = box.get("qr_segments") or []
        if part_idx < len(qr_segs) and qr_segs[part_idx]:
            qr_page_index, qx, qy, qw, qh = qr_segs[part_idx]
            if qr_page_index == page_index:
                canonical_qr_bbox = (qx, qy, qw, qh)

        local = None
        if modality == "photo" and settings.USE_LOCAL_QR_REGISTRATION:
            # Scanner scans are already near-planar (no lens distortion
            # to correct for) so local QR registration adds risk for no
            # real benefit there — only attempted for handheld photos.
            # Gated behind a feature flag, default off — see config.py's
            # USE_LOCAL_QR_REGISTRATION docstring for why.
            local = _try_local_registration(
                img, canonical_qr_bbox, bbox, transform, q_id, box["id"], part_idx,
            )

        if local is not None:
            local_transform, qr_check = local
            warped = _transform_bbox(bbox, local_transform)
            registration = "local"
        else:
            warped = _transform_bbox(bbox, transform)
            qr_check = _check_qr(img, warped, q_id, box["id"], part=part_idx)
            registration = "global"

        crop_img = _crop_region(img, warped)
        x_min, y_min = int(warped[:, 0].min()), int(warped[:, 1].min())
        x_max, y_max = int(warped[:, 0].max()), int(warped[:, 1].max())

        crops.append({
            "answer_box_id": box["id"],
            "part": part_idx,
            "data": _encode_png(crop_img),
            "content_type": "image/png",
            "qr_check": qr_check,
            "warped_bbox": [x_min, y_min, x_max, y_max],
            "registration": registration,
        })

    return {
        "page_index": page_index,
        "markers_detected": f"{n_detected}/4",
        "transform_type": transform_type,
        "crops": crops,
        "image_resolution": f"{img_w}x{img_h}",
        "image_dpi": detected_dpi,
    }


def _extract_tablet(question: dict, page_segments: list[tuple], ink_strokes: list | None, submission_id: str) -> dict:
    canvas_w, canvas_h = question["page_w_px"], question["page_h_px"]

    canvas_img = np.ones((canvas_h, canvas_w, 3), dtype=np.uint8) * 255
    for stroke in ink_strokes or []:
        points = stroke.get("points", [])
        if len(points) < 2:
            continue
        pts = np.array(points, dtype=np.int32)
        cv2.polylines(canvas_img, [pts], isClosed=False, color=(0, 0, 0), thickness=2)

    crops = []
    for box, part_idx, bbox in page_segments:
        x, y, w, h = bbox
        x2, y2 = min(x + w, canvas_w), min(y + h, canvas_h)
        crop_img = canvas_img[y:y2, x:x2].copy()
        crops.append({
            "answer_box_id": box["id"],
            "part": part_idx,
            "data": _encode_png(crop_img),
            "content_type": "image/png",
            "qr_check": "absent",
            "warped_bbox": [x, y, x2, y2],
        })

    return {
        "markers_detected": "N/A",
        "transform_type": "identity",
        "crops": crops,
        "image_resolution": f"{canvas_w}x{canvas_h}",
        "image_dpi": None,
    }

