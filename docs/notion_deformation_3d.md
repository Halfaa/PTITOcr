# 3D deformation — reading a handwritten page that is not flat

Chandra OCR 2 · Vietnamese handwritten forms · same pages, read flat vs
projected onto curved meshes in Blender (HDR lighting, shadow-receiving
plane)

---

## 1. The number

| condition | pages | fields found | score |
|---|---|---|---|
| flat | 30 | **95.6%** | 97.3 |
| warped | 8 | **59.9%** | 80.8 |

```
flat    ██████████████████████████████████████  95.6
warped  ████████████████████████                59.9
```

**−35.7 points.** Larger than any photometric degradation, and comparable to
17 px of motion blur (43.7%) — deformation sits among the worst failure
modes measured on handwriting.

> ⚠️ **Read this as a lower bound, not as the cost of deformation.**
> Two reasons, both fixable, detailed in §4.

---

## 2. What deformation does that noise does not

| degradation | what it changes | Chandra |
|---|---|---|
| noise, exposure, JPEG | pixel **values** | 100% — no effect |
| blur, downscaling | stroke **thickness** | breaks progressively |
| 3D deformation | stroke **geometry and baseline** | breaks hardest |

**Why it is the worst case.** A curved page does three things at once:

1. **Baselines stop being straight** — a text line follows the curl, so row
   segmentation has to track a curve instead of a horizontal band.
2. **Scale varies inside one page** — the far side of the curl is compressed,
   so the same letter is several sizes in the same image, and the sharp zone
   is not the whole sheet.
3. **The table grid bends with it** — for a form, cell boundaries are what
   ties a value to its field. A bent grid can put the right value in the
   wrong column.

Photometric noise leaves all three intact. That is the whole explanation for
the gap between the two families.

---

## 3. What it looks like

> 📎 Drop in `doc3D-renderer/img/handwriting_vi_warped/specimen_000-concave_mesh_10001.png`
> 📎 And next to it `handwriting/generated/specimen_000/specimen_000.png` (the flat original)

The curl is cylindrical: the two edges parallel to the axis stay straight,
the two others arc. Handwriting stays visually legible to a human across
the whole page — which is exactly the point: **the model loses a third of
the fields on a page a person still reads without effort.**

To crop a tighter comparison rather than dropping full pages:

```powershell
python scripts\figure_paliers_manuscrit.py --jeu handwriting_vi_warped
```

---

## 4. Why this number is a lower bound

**The 8 renders came out rotated 90°.** A texture-orientation bug, found
after they were produced: the mesh applies its own 90° rotation, invoice
textures are stored landscape and come out upright, our portrait specimens
did not. So the figure mixes deformation with orientation, and models handle
rotation very unevenly. Fixed in `scripts/preparer_textures_manuscrit.py`
(`--rotation 90`, now the default), but the render has not been redone.

**The comparison is not paired.** 8 warped pages against 30 flat ones — part
of the gap may simply be which pages are in each set.

Both are cheap to remove:

```powershell
# 1. re-render with the corrected rotation
python scripts\preparer_textures_manuscrit.py --langue vi
cd ..\doc3D-renderer
$env:PLAN_RECEPTEUR="1"; $env:RENDER_RESOLUTION_X="1654"; $env:RENDER_RESOLUTION_Y="2339"
.\render_variants.ps1 -FolderId handwriting_vi_warped -Source tex/handwriting_vi -TexCsv tex_handwriting_vi.csv -Verifier

# 2. score the SAME pages on both sides
cd ..\MedicalRecord
$s = "specimen_000,specimen_001,specimen_002,specimen_003,specimen_004,specimen_005,specimen_006,specimen_007"
python src\eval_handwriting.py --run images-handwriting-vi_chandra --verite-dir handwriting/generated --lang vi --specimens $s
python src\eval_handwriting.py --run mages-handwriting-vi-warped_chandra --verite-dir handwriting/generated --lang vi --specimens $s
```

The second pair of lines is the honest version of the table in §1.

---

## 5. What this set also unlocks

The warped renders come with **pixel-exact UV masks** — 8 `.exr` files under
`doc3D-renderer/uv/handwriting_vi_warped/`. That is ground truth for *sheet
localisation* on handwriting, which did not exist before: until now the
cropping work had ground truth only on invoices.

It also carries the first **shadow-receiving plane** in this project. Section
16 of `fonds_encombres.md` established that the sheet edge is *straight but
invisible* — white on white, with no drop shadow to detach it. These renders
are the first where the edge physically exists.

---

## 6. Limits

| limit | consequence |
|---|---|
| 8 pages | shape of the effect is clear, the exact figure is not |
| rotated 90° | mixes deformation with orientation — lower bound |
| unpaired comparison | part of the gap may be page selection |
| Vietnamese only | no English warped set rendered yet |
| synthetic curl | one mesh family (cylindrical), not real photographed pages |
