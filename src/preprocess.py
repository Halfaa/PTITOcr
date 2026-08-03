"""
Pre-processing module -- Phase 1 of the internship subject.

Turns a smartphone photo of a document into something closer to a scan:
locate the sheet, flatten it to a bird's eye view, even out the lighting,
denoise.

Unlike scripts/dewarp_oracle.py, this module knows NOTHING about the
deformation. The oracle inverts the exact warp using Blender's UV maps and
exists only to measure the ceiling; this module estimates everything from the
image alone, which is what a real application must do.

Pipeline
--------
    1. locate the document      contour detection on a downscaled copy
    2. perspective transform    four-point warp to a rectangle
    3. illumination correction  divide by a heavily blurred copy
    4. denoise                  edge-preserving filter
    5. binarise                 OPTIONAL, off by default -- see below

On binarisation. The subject's Phase 1 asks for it, and it was the right
call in the Tesseract era: classical OCR works on binary images. Modern VLM
recognisers (PaddleOCR-VL, HunyuanOCR) are trained on natural photographs and
usually do WORSE on binarised input, which throws away the antialiasing that
makes Vietnamese diacritics legible. It is therefore implemented but off by
default, and the benchmark can settle the question rather than assumption.

Usage:
    python src/preprocess.py --images-dir "..\\doc3D-renderer\\img\\multipage_test"
    python src/preprocess.py --images-dir ... --out ... --debug
"""

import argparse
import re
import sys
from pathlib import Path

try:
    import cv2
    import numpy as np
except ImportError:
    raise SystemExit("This module needs opencv and numpy:\n"
                     "    pip install 'opencv-python<4.12' 'numpy<2'")


# --------------------------------------------------------------------------
# 1. Locating the document
# --------------------------------------------------------------------------

def _order_corners(pts):
    """Order four points as top-left, top-right, bottom-right, bottom-left.

    Using the coordinate sum and difference is the standard trick: the
    top-left has the smallest x+y, the bottom-right the largest, and the two
    others separate on x-y.
    """
    pts = np.array(pts, dtype=np.float32).reshape(4, 2)
    ordered = np.zeros((4, 2), dtype=np.float32)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    ordered[0] = pts[np.argmin(s)]
    ordered[2] = pts[np.argmax(s)]
    ordered[1] = pts[np.argmin(d)]
    ordered[3] = pts[np.argmax(d)]
    return ordered


def _clean(mask):
    kernel = np.ones((7, 7), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=3)
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=2)


def _candidate_masks(small):
    """Several segmentations of the sheet, because no single cue works.

    Measured on our renders, comparing the sheet region (known exactly from
    Blender's UV maps) against the background:

        page 1   sheet darker, MORE saturated, MORE textured than the background
        page 4   same brightness, LESS saturated, LESS textured

    Every sign flips. Brightness, saturation and texture each work on some
    images and fail on others, because doc3D draws its backgrounds from random
    natural images. So we generate several candidates and let shape decide
    which one actually looks like a sheet of paper.

    Edges are deliberately the LAST resort: on a printed invoice the strongest
    rectangle is the table border, not the paper edge. A detector trusting it
    crops to the table and silently drops the header -- the patient name and
    date the subject asks for.
    """
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    saturation, value = hsv[:, :, 1], hsv[:, :, 2]

    mean = cv2.blur(gray.astype(np.float32), (15, 15))
    mean_sq = cv2.blur(gray.astype(np.float32) ** 2, (15, 15))
    texture = np.sqrt(np.maximum(mean_sq - mean * mean, 0))
    texture = cv2.normalize(texture, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)

    candidates = []
    for channel in (value, 255 - saturation, texture, 255 - texture):
        _, mask = cv2.threshold(channel, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        candidates.append(_clean(mask))

    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 40, 120)
    edges = cv2.dilate(edges, np.ones((5, 5), np.uint8), iterations=2)
    candidates.append(edges)
    return candidates


def _document_score(contour, image_area):
    """How much does this contour look like a sheet of paper?

    Three criteria, all necessary: it must occupy a plausible share of the
    frame, be close to convex (a sheet has no notches), and fill its own
    bounding rectangle well (a sheet is rectangular, even seen at an angle).
    """
    area = cv2.contourArea(contour)
    ratio = area / image_area
    # The upper bound matters as much as the lower one: a mask covering the
    # whole frame is convex AND rectangular, so it would score near 1 while
    # detecting nothing at all. A photographed sheet leaves margins.
    if not (0.08 <= ratio <= 0.80):
        return 0.0

    hull_area = cv2.contourArea(cv2.convexHull(contour))
    convexity = area / hull_area if hull_area > 0 else 0.0

    rect = cv2.minAreaRect(contour)
    rect_area = rect[1][0] * rect[1][1]
    rectangularity = area / rect_area if rect_area > 0 else 0.0

    # Aspect prior. A table locked onto by mistake is a WIDE STRIP (l/h of 3
    # or more); a sheet of paper is A4-ish (0.7 to 1.4 either way). Penalise
    # extreme aspect ratios instead of rejecting outright, so unusual but
    # genuine documents still stand a chance.
    w, h = rect[1]
    if min(w, h) > 0:
        aspect = max(w, h) / min(w, h)
        if aspect > 2.0:
            return convexity * rectangularity * (2.0 / aspect)

    return convexity * rectangularity


def _text_mask(small):
    """Binary mask of probable text pixels.

    Text is the one cue that survives the white-on-white failure case: when
    the sheet and the background share the same colour, no segmentation can
    tell them apart -- but the printed text is always high-contrast, and it
    is by definition ON the sheet. Morphological gradient picks up stroke
    edges; closing with a wide horizontal kernel merges characters into word
    blobs; small components (noise, background texture) are dropped.
    """
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    grad = cv2.morphologyEx(gray, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
    _, bw = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    merged = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, np.ones((1, 9), np.uint8))

    n, labels, stats, _ = cv2.connectedComponentsWithStats(merged, 8)

    # First pass: word-shaped blobs only. Printed words are WIDER than tall;
    # background texture (marble veins, carpet) produces roundish or tall
    # blobs that passed a naive size filter and contaminated the mask --
    # measured as an IoU drop from 0.82 to 0.65 before this filter existed.
    kept = []
    for i in range(1, n):
        x, y, w, h, area = stats[i]
        if area >= 20 and 3 <= h <= small.shape[0] // 15 and w >= 1.5 * h:
            kept.append(i)

    # Second pass: on one page, printed text has a consistent body height.
    # Keeping only blobs near the median height drops the stragglers that
    # happen to be word-shaped by accident.
    if len(kept) >= 5:
        median_h = float(np.median([stats[i][3] for i in kept]))
        kept = [i for i in kept
                if 0.4 * median_h <= stats[i][3] <= 2.5 * median_h]

    out = np.zeros_like(merged)
    for i in kept:
        out[labels == i] = 255
    return out


def _text_hull_contour(small, grow=0.10):
    """Contour of the convex hull of all text, grown outward.

    Used both as a detection candidate (the only one that works when sheet
    and background colours match) and as a floor for any crop: the sheet
    extends beyond its text by at least a printing margin, hence `grow`.
    """
    mask = _text_mask(small)
    points = cv2.findNonZero(mask)
    # Fewer than ~50 text pixels means the page content was not found at
    # all; a hull built on that would be meaningless.
    if points is None or len(points) < 50:
        return None, mask
    hull = cv2.convexHull(points)
    center = hull.reshape(-1, 2).mean(axis=0)
    grown = center + (hull.reshape(-1, 2) - center) * (1.0 + grow)
    grown[:, 0] = np.clip(grown[:, 0], 0, small.shape[1] - 1)
    grown[:, 1] = np.clip(grown[:, 1], 0, small.shape[0] - 1)
    return grown.astype(np.float32).reshape(-1, 1, 2), mask


def _text_outside_fraction(contour, text_mask):
    """Fraction of text pixels that a crop to `contour` would cut off."""
    total = int(np.count_nonzero(text_mask))
    if total == 0:
        return 0.0
    inside = np.zeros_like(text_mask)
    cv2.fillPoly(inside, [contour.astype(np.int32)], 255)
    kept = int(np.count_nonzero(cv2.bitwise_and(text_mask, inside)))
    return 1.0 - kept / total


def _grabcut_contour(small, margin=0.04, iterations=3):
    """Sheet outline via GrabCut, seeded with a rectangle inset from the frame.

    This is by far the best detector here, and the reason is structural:
    GrabCut models the COLOUR DISTRIBUTIONS of foreground and background
    instead of thresholding one cue. When no single cue is consistent -- and
    measurements show brightness, saturation and texture all flip sign from
    one image to the next -- modelling the distributions is what works.

    Measured against the exact sheet masks from Blender's UV maps, over the
    17 renders:

        threshold + contours   0.44 IoU,  0/17 usable (>= 0.7)
        GrabCut                0.76 IoU, 13/17 usable

    The seed rectangle assumes the sheet does not touch the frame edges,
    which holds for a photographed document: a margin is almost always
    visible.
    """
    height, width = small.shape[:2]
    mask = np.zeros((height, width), np.uint8)
    rect = (int(width * margin), int(height * margin),
            int(width * (1 - 2 * margin)), int(height * (1 - 2 * margin)))
    try:
        cv2.grabCut(small, mask, rect, np.zeros((1, 65), np.float64),
                    np.zeros((1, 65), np.float64), iterations,
                    cv2.GC_INIT_WITH_RECT)
    except cv2.error:
        return None

    foreground = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD),
                          255, 0).astype(np.uint8)
    foreground = cv2.morphologyEx(foreground, cv2.MORPH_OPEN,
                                  np.ones((5, 5), np.uint8), iterations=2)
    contours, _ = cv2.findContours(foreground, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    return max(contours, key=cv2.contourArea) if contours else None


_RNG_SEED = 20260728


def _unnest_from_print(small, contour, small_area, min_score,
                       ksize=15, nested_ratio=2.0, attempts=4):
    """Second opinion with the printed text erased.

    GrabCut models colour distributions, and on a page carrying a lot of
    blank paper it converges on the wrong two classes: it separates INK from
    everything else instead of PAPER from background. The outline it returns
    is then the table border, and cropping to it removes the header -- the
    hospital, the patient, the date, the doctor. Measured on page 8 of the
    benchmark: IoU 0.28 against the exact sheet mask, header entirely gone.

    A median blur wide enough to swallow a character removes the ink and
    leaves the paper flat. Re-running GrabCut on that image gives a reading
    of the same photograph in which printed content cannot be a class of its
    own.

    The decision rule is the ratio of the two areas, and it says something
    checkable rather than something tuned: erasing the ink cannot move the
    edge of the sheet. So the two runs should agree. When the second one is
    much LARGER, the first was locked onto something nested inside the sheet
    -- and the measurement leaves a real gap rather than a tuned point:

        pages where the sharp run was already right   x1.00 to x1.76
        page 12 (crop stuck on the table)             x2.40
        page 8  (crop stuck on the table)             x4.51

    The threshold sits at x2.0, inside that gap. Below it we keep the sharp
    run, which is the more accurate of the two when it is not mistaken.

    Cost: one extra GrabCut pass, so detection is about twice as slow. It
    runs on the 480 px copy, so it stays well under a second per image.
    """
    area = cv2.contourArea(contour)
    if area <= 0:
        return contour

    blurred = cv2.medianBlur(small, ksize)
    for attempt in range(attempts):
        # A different seed per attempt -- see the note on determinism in
        # detect_document_quad. On the ink-free image GrabCut is bimodal: it
        # either finds the sheet or collapses onto a speck. Measured on page
        # 8, five identical calls gave areas 0.504, 0.413, 0.021, 0.021,
        # 0.021. A collapse scores 0 and is rejected below, so retrying costs
        # nothing but a pass and turns an unreliable signal into a usable one.
        cv2.setRNGSeed(_RNG_SEED + 1 + attempt)
        # One iteration, not three: this pass only has to answer "is the
        # sheet much bigger than what the sharp run returned", which is a
        # coarse question. GrabCut's cost is linear in its iteration count,
        # and the retry loop is what makes detection expensive.
        second = _grabcut_contour(blurred, iterations=1)
        if second is None or _document_score(second, small_area) < min_score:
            continue  # collapsed run: no verdict, try again
        # A plausible outline IS a verdict, whichever way it points. Much
        # larger means the sharp run was nested in the print, and we take it.
        # Comparable means there was nothing to un-nest -- retrying then
        # would only burn passes on the 15 pages out of 17 that were already
        # right, which is what made detection several times slower.
        if cv2.contourArea(second) >= nested_ratio * area:
            return second
        return contour
    return contour


def detect_document_quad(image, min_score=0.55, return_score=False,
                         return_contour=False, use_text=False):
    """Find the document's four corners, or None.

    Detection runs on a downscaled copy: it is faster, and blurring away the
    printed text is exactly what we want -- we are looking for the outline of
    the sheet, not for its content.
    """
    # Determinism. cv2.grabCut seeds its colour models with a k-means whose
    # RNG is global and unseeded, so the SAME image gives different outlines
    # from one call to the next -- measured on page 8: five identical calls
    # returned areas 0.504, 0.413, 0.021, 0.021, 0.021. Left alone, the
    # module is not reproducible and any benchmark run on it is partly
    # measuring noise. Seeding here fixes the whole chain.
    cv2.setRNGSeed(_RNG_SEED)

    height, width = image.shape[:2]
    # 480 px is a compromise: GrabCut costs roughly the square of the side,
    # and going finer does not improve the outline of a sheet.
    scale = 480.0 / max(height, width)
    small = cv2.resize(image, None, fx=scale, fy=scale) if scale < 1 else image.copy()
    small_area = small.shape[0] * small.shape[1]

    best_contour, best_score = None, 0.0
    # use_text=False by default -- MEASURED decision, not a hunch. Against
    # the exact sheet masks, every policy built on the morphological text
    # mask regressed the mean IoU (0.82 alone -> 0.79 as competing candidate
    # -> 0.72 with replacement), and the text hull beat the shape detector on
    # ZERO of the 17 pages. Root cause: on these synthetic backgrounds the
    # mask counts background speckle as text (74% of "text" outside a crop
    # whose IoU is 0.99). The idea itself is sound -- text is the only cue
    # that survives white-on-white -- but it needs a RELIABLE text source
    # (the OCR's own spotting, or a learned detector), not morphology. The
    # machinery stays, gated, ready for that source.
    text_hull, text_mask = _text_hull_contour(small) if use_text else (None, None)

    grabcut = _grabcut_contour(small)
    if grabcut is not None:
        grabcut = _unnest_from_print(small, grabcut, small_area, min_score)
        best_contour, best_score = grabcut, _document_score(grabcut, small_area)

    # Text-hull candidate: RESCUE ONLY. On images where colour-based
    # detection works, the text hull is systematically a bit worse (it hugs
    # the print, not the sheet), so letting it compete lowered the average
    # IoU. But it is the only detector that survives the white-on-white
    # case, where sheet and background colours are identical and every
    # colour-based segmentation is blind. Hence: considered only when the
    # shape detectors found nothing credible.
    if best_score < min_score and text_hull is not None:
        score = _document_score(text_hull, small_area)
        if score > best_score:
            best_contour, best_score = text_hull, score

    # Threshold-based candidates are kept as a fallback, for the cases where
    # GrabCut latches onto the background (a sheet touching the frame edge,
    # for instance). Guard: a fallback candidate much SMALLER than what
    # GrabCut found is the table-inside-the-sheet signature -- shrinking the
    # crop loses the header, so we refuse it.
    grabcut_area = cv2.contourArea(grabcut) if grabcut is not None else 0.0
    if best_score < min_score:
        for mask in _candidate_masks(small):
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                           cv2.CHAIN_APPROX_SIMPLE)
            for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:3]:
                if grabcut_area > 0 and cv2.contourArea(contour) < 0.6 * grabcut_area:
                    continue
                score = _document_score(contour, small_area)
                if score > best_score:
                    best_contour, best_score = contour, score

    # Below this, no candidate resembles a sheet: better to admit failure than
    # to crop wrongly. Cropping wrongly is not a neutral error -- a quad
    # fitted to the table border removes the header, i.e. the patient name and
    # the date.
    if best_contour is None or best_score < min_score:
        return None

    # Text-coverage constraint: a crop that cuts text is wrong by
    # definition, whatever its shape score says. If more than 2% of the text
    # pixels fall outside the winner, extend it with the text hull -- the
    # union keeps the detected sheet shape where it is right and stretches
    # it just enough to include all the content.
    if text_hull is not None:
        outside = _text_outside_fraction(best_contour, text_mask)
        if outside > 0.5:
            # The crop does not even CONTAIN the page content: the shape
            # detector is disproven by the facts, whatever its score said
            # (page_8: a carpet patch scored 0.74 while 100% of the text sat
            # elsewhere). Replace it with the text hull outright.
            best_contour = text_hull
        elif outside > 0.05:
            # Moderate leak: extend just enough to include the text. Guard:
            # if the union balloons the area, the text mask itself is
            # contaminated by background texture -- trust the shape detector.
            union = np.vstack([best_contour.reshape(-1, 2),
                               text_hull.reshape(-1, 2)]).astype(np.float32)
            union_hull = cv2.convexHull(union)
            if cv2.contourArea(union_hull) <= 1.5 * cv2.contourArea(best_contour):
                best_contour = union_hull

    peri = cv2.arcLength(best_contour, True)
    approx = cv2.approxPolyDP(best_contour, 0.02 * peri, True)
    if len(approx) == 4:
        quad = approx.reshape(4, 2).astype(np.float32)
    else:
        # A curved sheet has no true quadrilateral outline: take the minimum
        # enclosing rectangle instead.
        quad = cv2.boxPoints(cv2.minAreaRect(best_contour)).astype(np.float32)

    if scale < 1:
        quad /= scale
    quad = _order_corners(quad)
    full_contour = (best_contour.reshape(-1, 2).astype(np.float32) / scale
                    if scale < 1 else best_contour.reshape(-1, 2).astype(np.float32))
    if return_contour:
        return quad, best_score, full_contour
    return (quad, best_score) if return_score else quad


# --------------------------------------------------------------------------
# 2. Perspective transform
# --------------------------------------------------------------------------

def expand_from_centroid(points, factor, width, height):
    """Push points outward from their centroid by `factor` (e.g. 0.08 = 8%).

    Safety margin around the detection. The rationale: when detection goes
    wrong here, it goes wrong INWARD -- it locks onto the table border, the
    sharpest rectangle of a printed invoice, and silently cuts the header
    (hospital, patient, date). A wrongly tight crop loses content forever; a
    slightly loose crop only keeps a strip of background that the OCR happily
    ignores. The two errors are not symmetric, so we bias outward.
    """
    points = np.asarray(points, dtype=np.float32)
    center = points.mean(axis=0)
    out = center + (points - center) * (1.0 + factor)
    out[:, 0] = np.clip(out[:, 0], 0, width - 1)
    out[:, 1] = np.clip(out[:, 1], 0, height - 1)
    return out


def four_point_transform(image, quad):
    """Flatten the quadrilateral into a rectangle (bird's eye view).

    The output size is derived from the quad's own side lengths rather than
    imposed: imposing a ratio would stretch documents that are not the
    expected format.
    """
    tl, tr, br, bl = quad
    # AVERAGE of opposite sides, not max. Under strong perspective the far
    # side is compressed; taking the max stretches that axis and distorts
    # the text (observed as characters twice their natural width).
    width = int((np.linalg.norm(br - bl) + np.linalg.norm(tr - tl)) / 2)
    height = int((np.linalg.norm(tr - br) + np.linalg.norm(tl - bl)) / 2)
    width, height = max(width, 10), max(height, 10)

    destination = np.array([[0, 0], [width - 1, 0],
                            [width - 1, height - 1], [0, height - 1]],
                           dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(quad, destination)
    return cv2.warpPerspective(image, matrix, (width, height),
                               flags=cv2.INTER_CUBIC)


# --------------------------------------------------------------------------
# 2b. Curved-boundary flattening (classical dewarping)
# --------------------------------------------------------------------------
# A homography maps 4 POINTS and therefore cannot represent curvature: with
# four_point_transform a bent sheet stays bent inside its rectangle. The
# dewarping literature (Jiang et al., CVPR 2022, grid regularization; and the
# boundary branches of DocScanner / D2Dewarp) converges on one idea that
# transfers to a classical setting: the sheet BOUNDARY carries most of the
# deformation, and dewarping should make it straight again.
#
# So instead of collapsing the GrabCut contour to 4 corners, we keep the four
# curved edges, resample them, and build a Coons patch -- the surface
# interpolating four boundary curves -- as a dense remap grid. Curvature that
# is visible on the boundary is flattened; purely interior bulges (which the
# boundary cannot see) are not, and THAT residual is what learned models are
# for.

def _split_contour_edges(contour, quad, samples=40):
    """Cut the closed contour into its 4 edges and resample each.

    Returns (top, right, bottom, left) as (samples, 2) arrays: top goes
    tl->tr, right tr->br, bottom bl->br, left tl->bl -- the orientation the
    Coons formula expects.
    """
    pts = contour.reshape(-1, 2).astype(np.float32)
    n = len(pts)
    if n < 8:
        return None

    # Contour index of the point closest to each ordered corner
    corner_idx = []
    for corner in quad:
        d = np.linalg.norm(pts - corner, axis=1)
        corner_idx.append(int(np.argmin(d)))

    def arc(i, j):
        """Points walking the contour from index i to index j."""
        if i <= j:
            return pts[i:j + 1]
        return np.vstack([pts[i:], pts[:j + 1]])

    def resample(curve, m):
        """Arc-length resampling to m points, then smoothing.

        The GrabCut outline is noisy at pixel level, and the Coons patch
        reproduces boundary noise faithfully across the WHOLE interior --
        which showed up as ripples running through the text. A sheet edge is
        physically smooth (paper bends, it does not wiggle), so a low-order
        polynomial fit per coordinate is the right prior: it keeps the global
        curvature and discards the segmentation noise.
        """
        if len(curve) < 2:
            return None
        seg = np.linalg.norm(np.diff(curve, axis=0), axis=1)
        t = np.concatenate([[0], np.cumsum(seg)])
        if t[-1] == 0:
            return None
        t /= t[-1]
        u = np.linspace(0, 1, m)
        x = np.interp(u, t, curve[:, 0])
        y = np.interp(u, t, curve[:, 1])
        # Degree 3 is enough for a single bend; higher degrees start to fit
        # the noise this smoothing exists to remove.
        degree = min(3, m - 1)
        x = np.polyval(np.polyfit(u, x, degree), u)
        y = np.polyval(np.polyfit(u, y, degree), u)
        return np.stack([x, y], axis=1)

    tl, tr, br, bl = range(4)
    edges = {}
    for key, (a, b) in {"top": (tl, tr), "right": (tr, br),
                        "bottom_rev": (br, bl), "left_rev": (bl, tl)}.items():
        i, j = corner_idx[a], corner_idx[b]
        forward = arc(i, j)
        backward = arc(j, i)[::-1]
        # Of the two ways around the contour, the true edge is the one that
        # does NOT pass through the remaining corners: pick the shorter arc.
        curve = forward if len(forward) <= len(backward) else backward
        edges[key] = resample(curve, samples)
        if edges[key] is None:
            return None

    top = edges["top"]
    right = edges["right"]
    bottom = edges["bottom_rev"][::-1]   # -> bl->br
    left = edges["left_rev"][::-1]       # -> tl->bl
    return top, right, bottom, left


def curved_flatten(image, contour, quad, samples=40):
    """Flatten a curved sheet using its full boundary (Coons patch).

    Coons interpolation: a point at grid position (u, v) is
        S(u,v) = (1-v)·top(u) + v·bottom(u) + (1-u)·left(v) + u·right(v)
                 - bilinear blend of the four corners
    which reproduces the four boundary curves exactly and fills the interior
    smoothly. Falls back to None if the boundary cannot be split.
    """
    edges = _split_contour_edges(contour, quad, samples)
    if edges is None:
        return None
    top, right, bottom, left = edges

    tl, tr = top[0], top[-1]
    bl, br = bottom[0], bottom[-1]
    # Average, not max -- same anti-stretch reasoning as four_point_transform.
    width = int((np.linalg.norm(tr - tl) + np.linalg.norm(br - bl)) / 2)
    height = int((np.linalg.norm(bl - tl) + np.linalg.norm(br - tr)) / 2)
    width, height = max(width, 10), max(height, 10)

    u = np.linspace(0, 1, width, dtype=np.float32)
    v = np.linspace(0, 1, height, dtype=np.float32)

    def curve_at(curve, t):
        """Evaluate a resampled curve at parameters t (vectorised)."""
        s = np.linspace(0, 1, len(curve))
        x = np.interp(t, s, curve[:, 0])
        y = np.interp(t, s, curve[:, 1])
        return np.stack([x, y], axis=-1)

    top_u = curve_at(top, u)        # (W, 2)
    bottom_u = curve_at(bottom, u)  # (W, 2)
    left_v = curve_at(left, v)      # (H, 2)
    right_v = curve_at(right, v)    # (H, 2)

    U = u[None, :, None]            # (1, W, 1)
    V = v[:, None, None]            # (H, 1, 1)

    surface = ((1 - V) * top_u[None] + V * bottom_u[None]
               + (1 - U) * left_v[:, None] + U * right_v[:, None]
               - ((1 - U) * (1 - V) * tl + U * (1 - V) * tr
                  + (1 - U) * V * bl + U * V * br))

    map_x = surface[:, :, 0].astype(np.float32)
    map_y = surface[:, :, 1].astype(np.float32)
    return cv2.remap(image, map_x, map_y, cv2.INTER_CUBIC)


# --------------------------------------------------------------------------
# 3. Illumination and noise
# --------------------------------------------------------------------------

def correct_illumination(image, kernel_ratio=0.08, strength=1.0, target=242):
    """Even out lighting by dividing by a heavily blurred copy.

    A photograph carries a slow luminance gradient -- shadow on one side,
    glare on the other. Blurring hard enough to erase the text leaves only
    that gradient; dividing by it cancels it while preserving the text.

    This matters more than it sounds here: the 3D renders keep a marked
    shading that flattening does not remove, and it is the main residual
    difference with the original flat page.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    k = int(max(gray.shape) * kernel_ratio) | 1  # must be odd
    background = cv2.GaussianBlur(gray, (k, k), 0).astype(np.float32)
    background[background < 1] = 1

    # Two precautions, both measured against Vietnamese diacritics.
    #
    # target = 242, not 255. The previous version divided with scale=255,
    # which maps the paper to pure white and clips everything just below it
    # to white as well. A diacritic is exactly that: a small, thin,
    # low-contrast mark sitting a few levels under the paper. Leaving 13
    # levels of headroom keeps it. Measured symptom: "BẠCH DƯƠNG" was coming
    # back from the OCR as "BACH DUONG".
    #
    # The gain is computed on luminance but applied to the three channels, so
    # the image stays in colour. The previous version returned GRAY2BGR,
    # silently discarding colour information that the VLM models are trained
    # on.
    gain = (target / background) ** strength
    if image.ndim == 3:
        corrected = image.astype(np.float32) * gain[:, :, None]
    else:
        corrected = image.astype(np.float32) * gain
    return np.clip(corrected, 0, 255).astype(np.uint8)


def denoise(image, strength=5):
    """Edge-preserving denoise. Bilateral rather than Gaussian: it must not
    blur the strokes of the diacritics, which is precisely what the models
    struggle to read."""
    return cv2.bilateralFilter(image, d=7, sigmaColor=strength * 10,
                               sigmaSpace=strength * 2)


def binarize(image, block_size=31, c=10):
    """Adaptive binarisation. OFF by default -- see the module docstring."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY, block_size, c)
    return cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)


# --------------------------------------------------------------------------
# The pipeline
# --------------------------------------------------------------------------

def preprocess(image, do_illumination=True, do_denoise=True,
               min_long_side=None,
               do_binarize=False, min_score=0.55, do_crop=True,
               pad=0.16):
    """Full chain. Returns (result, info).

    `info` reports whether the document was located: a caller must be able to
    tell a genuine flattening from a fallback where the whole frame was kept.
    """
    info = {"quad_found": False, "fallback": None, "score": 0.0}

    # Policy: ALWAYS enhance, crop ONLY when confident.
    #
    # Measured on our 17 renders against the exact sheet masks from Blender's
    # UV maps, classical segmentation tops out at 0.56 IoU -- and that is the
    # ceiling over every candidate, not the score of the chosen one. Cropping
    # on such a detection is worse than not cropping: a quad fitted to the
    # table border silently removes the header. Photometric correction, on the
    # other hand, cannot lose content and helps regardless.
    # Cropping is ON, but conditional. GrabCut brought localisation from
    # 0.35 to 0.76 IoU (13/17 usable), which makes it worth doing -- yet a bad
    # crop is not a neutral error: it removes the header, i.e. the patient
    # name and date. So a candidate below min_score is refused and only the
    # photometric correction is applied, which can never lose content.
    if do_crop:
        found = detect_document_quad(image, min_score=min_score,
                                     return_contour=True)
        if found is None:
            quad, score, contour = None, 0.0, None
        else:
            quad, score, contour = found
    else:
        quad, score, contour = None, 0.0, None
        info["fallback"] = "cropping disabled (see do_crop)"
    info["score"] = round(float(score), 3)
    if quad is not None:
        height, width = image.shape[:2]
        quad = expand_from_centroid(quad, pad, width, height)
        if contour is not None:
            contour = expand_from_centroid(contour, pad, width, height)
        # Curved-boundary flattening first: unlike the homography it also
        # straightens the curvature visible on the sheet outline. Homography
        # kept as fallback when the boundary cannot be split into 4 edges.
        result = None
        if contour is not None:
            result = curved_flatten(image, contour, quad)
            info["method"] = "coons"
        if result is None:
            result = four_point_transform(image, quad)
            info["method"] = "homography"
        info["quad_found"] = True
        info["quad"] = quad.tolist()
    else:
        result = image.copy()
        info["fallback"] = ("sheet outline not reliably found -- geometry left "
                            "untouched, photometric correction still applied")

    if do_illumination:
        result = correct_illumination(result)
    if do_denoise:
        result = denoise(result)
    if do_binarize:
        result = binarize(result)

    # Resolution floor. Cropping to the sheet throws away the background and
    # with it a large share of the pixels: the outputs measured 26 % to 59 %
    # of the source area, at which scale a diacritic is one or two pixels
    # tall. Restoring that lost scale is worth it.
    #
    # But only up to the SOURCE resolution. Going beyond it invents pixels,
    # and it is not free: a VLM's cost grows faster than linearly with the
    # number of image patches. Measured with PaddleOCR-VL, a fixed 1600 px
    # floor took 790 s per image against ~230 s on the source-sized image --
    # 3.7 hours for a 17-page run, for pixels carrying no information.
    #
    # min_long_side=None therefore means "match the source", which is the
    # default. An explicit number overrides it.
    if min_long_side is None:
        min_long_side = max(image.shape[:2])
    if min_long_side:
        long_side = max(result.shape[:2])
        if long_side < min_long_side:
            factor = min_long_side / long_side
            result = cv2.resize(result, None, fx=factor, fy=factor,
                                interpolation=cv2.INTER_CUBIC)
            info["upscaled"] = round(factor, 2)

    info["output_size"] = [result.shape[1], result.shape[0]]
    return result, info


def debug_view(original, quad, result):
    """Side-by-side view: detected outline on the left, result on the right.
    Looking at what the module actually did is the fastest way to spot a
    detection that latched onto the background instead of the sheet."""
    left = original.copy()
    if quad is not None:
        pts = np.array(quad, dtype=np.int32).reshape(-1, 1, 2)
        cv2.polylines(left, [pts], True, (0, 220, 0), 3)
        for x, y in np.array(quad, dtype=int):
            cv2.circle(left, (x, y), 8, (0, 0, 255), -1)

    height = 700
    def fit(img):
        s = height / img.shape[0]
        return cv2.resize(img, (int(img.shape[1] * s), height))

    left, right = fit(left), fit(result)
    gap = np.full((height, 20, 3), 40, np.uint8)
    return np.hstack([left, gap, right])


_DEBUG_HTML_HEADER = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Pre-processing debug - {folder}</title>
<style>
 body {{ font-family: Arial, sans-serif; margin:0; background:#1e1e1e; color:#eee; }}
 h1 {{ padding:18px 24px; margin:0; border-bottom:2px solid #444; font-size:1.2em; }}
 .sum {{ padding:14px 24px; color:#bbb; border-bottom:1px solid #333; font-size:.9em; }}
 .row {{ border-bottom:3px solid #444; padding:14px 24px; }}
 .row h2 {{ color:#4da3ff; font-size:1em; margin:0 0 6px; }}
 .meta {{ color:#999; font-size:.85em; margin-bottom:10px; }}
 .meta b {{ color:#ddd; font-weight:normal; }}
 .warn {{ color:#ffb454; }}
 img {{ max-width:100%; height:auto; display:block; }}
</style></head><body>
<h1>Pre-processing — {folder}</h1>
<div class="sum">Left: detected sheet outline drawn on the source. Right: the
image actually sent to the OCR model. A green quadrilateral hugging the
background instead of the paper is the failure to look for.<br>{summary}</div>
"""

_DEBUG_HTML_ROW = """<div class="row"><h2>{name}</h2>
<div class="meta">{meta}</div><img src="data:image/jpeg;base64,{b64}" alt="{name}"></div>
"""


def _debug_row(name, view, info, source_shape):
    """One row of the debug report: the side-by-side view plus what was done."""
    import base64
    ok, buf = cv2.imencode(".jpg", view, [int(cv2.IMWRITE_JPEG_QUALITY), 82])
    b64 = base64.b64encode(buf).decode("ascii") if ok else ""

    src_px = source_shape[0] * source_shape[1]
    out_w, out_h = info["output_size"]
    up = info.get("upscaled")
    # Pixels kept BEFORE upscaling: upscaling adds no information, so
    # counting it here would hide exactly what we want to watch.
    kept = (out_w * out_h) / (up * up if up else 1) / src_px

    bits = [f"<b>{source_shape[1]}x{source_shape[0]}</b> -> <b>{out_w}x{out_h}</b>"]
    bits.append(f"method: <b>{info.get('method', 'none')}</b>")
    if info["quad_found"]:
        bits.append(f"score: <b>{info['score']}</b>")
    else:
        bits.append('<span class="warn">outline not found — geometry untouched</span>')
    bits.append(f"pixels kept: <b>{kept:.0%}</b>")
    if up:
        bits.append(f"upscaled: <b>x{up}</b>")
    # 20%, not 25%. The threshold exists to catch a crop stuck on the table
    # frame, which measured 14% and 15% of the source. A correct crop of a
    # sheet that simply sits small in the frame reaches 24% (page 1, IoU
    # 0.86), and flagging it would only teach the reader to ignore the
    # warning.
    if kept < 0.20:
        bits.append('<span class="warn">&lt;20% of the source pixels — '
                    'check the crop did not clip the header</span>')
    return _DEBUG_HTML_ROW.format(name=name, meta=" &nbsp;·&nbsp; ".join(bits), b64=b64)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--images-dir", required=True)
    parser.add_argument("--out", default=None,
                        help="Output folder (default: <images-dir>_preprocessed)")
    parser.add_argument("--min-long-side", type=int, default=None,
                        help="Upscale the crop so its long side reaches this "
                             "value. Default: the source image's long side -- "
                             "cropping costs 40-70%% of the pixels and diacritics "
                             "do not survive it, but going beyond the source "
                             "invents pixels and costs OCR time. 0 disables.")
    parser.add_argument("--no-illumination", action="store_true")
    parser.add_argument("--no-denoise", action="store_true")
    parser.add_argument("--binarize", action="store_true",
                        help="Add adaptive binarisation (usually hurts VLM OCR)")
    parser.add_argument("--pad", type=float, default=0.16,
                        help="Safety margin around the detected sheet "
                             "(fraction of its size; 0.08 = 8%%)")
    parser.add_argument("--no-crop", action="store_true",
                        help="Skip geometric cropping, enhance only")
    parser.add_argument("--min-score", type=float, default=0.55,
                        help="Confidence below which the image is not cropped")
    parser.add_argument("--debug", action="store_true",
                        help="Also write a side-by-side view per image")
    args = parser.parse_args()

    images_dir = Path(args.images_dir)
    out_dir = Path(args.out) if args.out else \
        images_dir.parent / f"{images_dir.name}_preprocessed"
    out_dir.mkdir(parents=True, exist_ok=True)
    debug_dir = out_dir / "_debug"
    if args.debug:
        debug_dir.mkdir(exist_ok=True)

    # "Natural" order: page_2 before page_10, so consecutive pages of the
    # same invoice sit next to each other in the debug report.
    def natural_key(path):
        return [int(tok) if tok.isdigit() else tok.lower()
                for tok in re.split(r"(\d+)", path.name)]

    images = sorted(list(images_dir.glob("*.png")) + list(images_dir.glob("*.jpg")),
                    key=natural_key)
    if not images:
        print(f"No image found in {images_dir}")
        return

    print(f"{len(images)} image(s) in {images_dir}")
    print(f"Output -> {out_dir}\n")

    n_found, debug_rows = 0, []
    for i, path in enumerate(images, start=1):
        image = cv2.imread(str(path))
        if image is None:
            print(f"[{i}/{len(images)}] {path.name}: unreadable")
            continue

        result, info = preprocess(
            image,
            do_illumination=not args.no_illumination,
            min_long_side=args.min_long_side,
            do_denoise=not args.no_denoise,
            do_binarize=args.binarize,
            min_score=args.min_score,
            do_crop=not args.no_crop,
            pad=args.pad,
        )
        cv2.imwrite(str(out_dir / path.name), result)
        n_found += info["quad_found"]

        if args.debug:
            view = debug_view(image, info.get("quad"), result)
            cv2.imwrite(str(debug_dir / path.name), view)
            debug_rows.append(_debug_row(path.name, view, info, image.shape))

        status = (f"cropped (score {info['score']})" if info["quad_found"]
                  else "enhanced only")
        print(f"[{i}/{len(images)}] {path.name}  {image.shape[1]}x{image.shape[0]}"
              f" -> {info['output_size'][0]}x{info['output_size'][1]}   {status}")

    if not args.no_crop:
        print(f"\nDocument located on {n_found}/{len(images)} images "
              f"({n_found / len(images):.0%})")
    else:
        print("\nPhotometric correction only (cropping disabled -- use --crop "
              "to enable).")
    if args.debug:
        summary = (f"{n_found}/{len(images)} sheets located · "
                   f"generated by: <code>{' '.join(sys.argv)}</code>")
        report = debug_dir / "report.html"
        report.write_text(_DEBUG_HTML_HEADER.format(folder=out_dir.name, summary=summary)
                          + "".join(debug_rows) + "</body></html>", encoding="utf-8")
        print(f"Side-by-side views: {debug_dir}")
        print(f"Single-file report: {report}")
    print("\nNext step -- run the benchmark on these images:")
    print(f'    python scripts\\bench_deformed.py --model hunyuan \\')
    print(f'           --images-dir "{out_dir}" --output <run_name>')


if __name__ == "__main__":
    main()
