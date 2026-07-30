"""
Oracle dewarping: flatten the warped pages using the EXACT deformation.

This is a MEASURING INSTRUMENT, not a production component. In real life the
deformation is unknown and has to be estimated by a model. Here we have it,
because doc3D-renderer wrote a UV map next to every rendered image: for each
pixel of the render it stores where that pixel came from in the flat page.

Purpose: establish the CEILING. If flattening perfectly only gains 0.01 TEDS,
no real dewarping model will do better and the whole avenue can be dropped
without spending weeks integrating one. If it gains 0.06, the investment is
justified -- and any model can then be judged as "captures X% of the
achievable gain", which is far more informative than a raw delta.

It also sidesteps a methodological trap: public dewarping models (DewarpNet
and successors) are trained on Doc3D, the very dataset doc3D-renderer
generates. Testing one of them here would evaluate it on its own training
distribution. The oracle measures the potential rather than a given model, so
the question does not arise.

UV convention (determined empirically, see --verify):
    channel 0 = page mask     channel 1 = V     channel 2 = U
    the V axis is flipped
The render is portrait while the source texture is landscape, hence the swap.

Usage:
    python scripts/dewarp_oracle.py --batch multipage_test
    python scripts/dewarp_oracle.py --batch multipage_test --verify
"""

import argparse
import os
from pathlib import Path

os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

try:
    import cv2
    import numpy as np
except ImportError:
    raise SystemExit(
        "This script needs opencv and numpy:\n"
        "    pip install opencv-python numpy"
    )

DOC3D = Path("..") / "doc3D-renderer"


def build_inverse_map(uv, out_h, out_w):
    """Build the remap tables that flatten the page.

    The UV map is a FORWARD mapping (render pixel -> flat position). remap()
    needs the reverse, so we scatter the source coordinates into the target
    grid, then fill the gaps.

    Gaps are unavoidable: where the 3D surface is compressed, several render
    pixels land on one flat pixel; where it is stretched, some flat pixels
    receive none. We fill those by iterative dilation, which is enough at
    this scale and avoids a scipy dependency.
    """
    mask = uv[:, :, 0] > 0.5
    # Channels swapped and V flipped -- see the module docstring.
    u = uv[:, :, 2]
    v = 1.0 - uv[:, :, 1]

    ys, xs = np.nonzero(mask)
    tx = np.clip((u[ys, xs] * (out_w - 1)).astype(np.int32), 0, out_w - 1)
    ty = np.clip((v[ys, xs] * (out_h - 1)).astype(np.int32), 0, out_h - 1)

    map_x = np.zeros((out_h, out_w), np.float32)
    map_y = np.zeros((out_h, out_w), np.float32)
    count = np.zeros((out_h, out_w), np.float32)
    np.add.at(map_x, (ty, tx), xs.astype(np.float32))
    np.add.at(map_y, (ty, tx), ys.astype(np.float32))
    np.add.at(count, (ty, tx), 1.0)

    valid = count > 0
    map_x[valid] /= count[valid]
    map_y[valid] /= count[valid]

    kernel = np.ones((3, 3), np.uint8)
    for _ in range(40):
        holes = ~valid
        if not holes.any():
            break
        grown = cv2.dilate(valid.astype(np.uint8), kernel) > 0
        newly = grown & holes
        if not newly.any():
            break
        spread_x = cv2.dilate(np.where(valid, map_x, 0), kernel)
        spread_y = cv2.dilate(np.where(valid, map_y, 0), kernel)
        map_x[newly] = spread_x[newly]
        map_y[newly] = spread_y[newly]
        valid |= newly

    return map_x, map_y, valid.mean()


def page_stem(name: str) -> str:
    """'page_1-concave_mesh_10001' -> 'page_1'"""
    return name.split("-")[0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch", default="multipage_test",
                        help="Batch name under doc3D-renderer/img/ and /uv/")
    parser.add_argument("--doc3d", default=None, help="Path to doc3D-renderer")
    parser.add_argument("--out", default=None,
                        help="Output folder (default: img/<batch>_unwarped)")
    parser.add_argument("--verify", action="store_true",
                        help="Correlate the result with the original flat page "
                             "(requires tex/<...>/) as a sanity check")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    doc3d = Path(args.doc3d) if args.doc3d else (root / DOC3D).resolve()
    img_dir = doc3d / "img" / args.batch
    uv_dir = doc3d / "uv" / args.batch
    out_dir = Path(args.out) if args.out else doc3d / "img" / f"{args.batch}_unwarped"
    tex_dir = doc3d / "tex" / "multipage"

    if not img_dir.exists():
        print(f"Folder not found: {img_dir}")
        return
    out_dir.mkdir(parents=True, exist_ok=True)

    images = sorted(img_dir.glob("*.png"))
    print(f"{len(images)} image(s) in {img_dir}")
    print(f"Output -> {out_dir}\n")

    correlations = []
    for i, img_path in enumerate(images, start=1):
        uv_path = uv_dir / f"{img_path.stem}.exr"
        if not uv_path.exists():
            print(f"[{i}/{len(images)}] {img_path.name}: no UV map, skipped")
            continue

        img = cv2.imread(str(img_path))
        uv = cv2.imread(str(uv_path), cv2.IMREAD_UNCHANGED)
        if img is None or uv is None:
            print(f"[{i}/{len(images)}] {img_path.name}: unreadable, skipped")
            continue

        # Target size: that of the original flat page when available, so the
        # result is directly comparable to it.
        flat_path = tex_dir / f"{page_stem(img_path.stem)}.png"
        if flat_path.exists():
            flat = cv2.imread(str(flat_path))
            out_h, out_w = flat.shape[:2]
        else:
            flat = None
            out_h, out_w = img.shape[:2]

        map_x, map_y, coverage = build_inverse_map(uv, out_h, out_w)
        result = cv2.remap(img, map_x, map_y, cv2.INTER_CUBIC)
        cv2.imwrite(str(out_dir / img_path.name), result)

        line = f"[{i}/{len(images)}] {img_path.name}  coverage {coverage:.1%}"
        if args.verify and flat is not None:
            a = cv2.cvtColor(result, cv2.COLOR_BGR2GRAY).astype(np.float32)
            b = cv2.cvtColor(flat, cv2.COLOR_BGR2GRAY).astype(np.float32)
            corr = float(np.corrcoef(a.ravel(), b.ravel())[0, 1])
            correlations.append(corr)
            line += f"   correlation with the flat page {corr:+.3f}"
        print(line)

    if correlations:
        mean = sum(correlations) / len(correlations)
        print(f"\nMean correlation with the original flat pages: {mean:+.3f}")
        print("A value clearly above 0 confirms the geometry is inverted "
              "correctly.\nIt will not reach 1.0: the render also carries "
              "lighting, shadows and a\nbackground that flattening does not "
              "remove.")

    print(f"\nNext step -- run the benchmark on these images:")
    print(f"    python scripts\\bench_deformed.py --model hunyuan \\")
    print(f"           --images-dir \"{out_dir}\" --output {args.batch}_unwarped_hunyuan")


if __name__ == "__main__":
    main()
