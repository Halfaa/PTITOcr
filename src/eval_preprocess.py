"""
Measure the document-localisation step of the pre-processing module.

We can score it exactly, which is unusual: doc3D-renderer writes a UV map
next to every render, and its first channel is the sheet mask. So we have
pixel-perfect ground truth for "where is the paper", and we can compute the
IoU of the detected quadrilateral against it.

Two numbers are reported, and the gap between them is the diagnostic:

    ceiling   best IoU over EVERY candidate segmentation
    achieved  IoU of the one the scoring function actually picks

A low ceiling means the segmentations themselves never contain the sheet --
no amount of better selection would help, and the approach must change. A
high ceiling with a low achieved value means the selection is at fault.

Usage:
    python src/eval_preprocess.py
    python src/eval_preprocess.py --batch multipage_test
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

try:
    import cv2
    import numpy as np
except ImportError:
    raise SystemExit("This script needs opencv and numpy:\n"
                     "    pip install 'opencv-python<4.12' 'numpy<2'")

from preprocess import (_candidate_masks, _document_score,  # noqa: E402
                        _grabcut_contour, detect_document_quad)

DOC3D = Path("..") / "doc3D-renderer"


def quad_iou(quad, truth):
    """IoU between the filled quadrilateral and the true sheet mask."""
    if quad is None:
        return 0.0
    pred = np.zeros(truth.shape, np.uint8)
    cv2.fillPoly(pred, [np.asarray(quad, dtype=np.int32)], 1)
    pred = pred.astype(bool)
    union = (pred | truth).sum()
    return float((pred & truth).sum() / union) if union else 0.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", default="multipage_test")
    parser.add_argument("--doc3d", default=None)
    parser.add_argument("--min-score", type=float, default=0.55)
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    doc3d = Path(args.doc3d) if args.doc3d else (root / DOC3D).resolve()
    img_dir, uv_dir = doc3d / "img" / args.batch, doc3d / "uv" / args.batch

    images = sorted(img_dir.glob("*.png"))
    if not images:
        print(f"No image in {img_dir}")
        return

    print(f"{'page':<10}{'ceiling':>9}{'achieved':>10}{'cropped':>10}")
    print("-" * 39)

    ceilings, achieved, n_cropped = [], [], 0
    for path in images:
        uv_path = uv_dir / f"{path.stem}.exr"
        if not uv_path.exists():
            continue
        image = cv2.imread(str(path))
        uv = cv2.imread(str(uv_path), cv2.IMREAD_UNCHANGED)
        truth = uv[:, :, 0] > 0.5

        # Ceiling: the best any selector could do with these candidates
        scale = 480.0 / max(image.shape[:2])
        small = cv2.resize(image, None, fx=scale, fy=scale)
        small_area = small.shape[0] * small.shape[1]
        best = 0.0
        grabcut = _grabcut_contour(small)
        if grabcut is not None:
            best = quad_iou(cv2.boxPoints(cv2.minAreaRect(grabcut)) / scale, truth)
        for mask in _candidate_masks(small):
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                           cv2.CHAIN_APPROX_SIMPLE)
            for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:3]:
                if _document_score(contour, small_area) <= 0:
                    continue
                quad = cv2.boxPoints(cv2.minAreaRect(contour)) / scale
                best = max(best, quad_iou(quad, truth))

        found = detect_document_quad(image, min_score=args.min_score,
                                     return_score=True)
        quad = found[0] if isinstance(found, tuple) else None
        got = quad_iou(quad, truth)
        n_cropped += quad is not None

        ceilings.append(best)
        achieved.append(got)
        print(f"{path.stem.split('-')[0]:<10}{best:>9.2f}{got:>10.2f}"
              f"{'yes' if quad is not None else 'no':>10}")

    print("-" * 39)
    print(f"{'mean':<10}{np.mean(ceilings):>9.2f}{np.mean(achieved):>10.2f}"
          f"{f'{n_cropped}/{len(achieved)}':>10}")

    print(f"\nIoU >= 0.7 (usable crop): {sum(v >= 0.7 for v in achieved)}/{len(achieved)}")
    print("\nHow to read this. The ceiling is what the candidate segmentations "
          "\ncontain at best. If it is low, the cues themselves fail to isolate "
          "\nthe sheet and no better selector would help -- the approach has to "
          "\nchange, typically to a learned segmentation.")


if __name__ == "__main__":
    main()
