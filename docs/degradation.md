# Robustness to image quality

**Question.** At what photo quality does the chain stop working?

Today we have no idea. All our figures — 0.967 adaptive on the multi-page
set, 0.977 on the diversified one — come from Blender renders: perfect
focus, controlled lighting, lossless PNG. We know the chain works in the
lab, and strictly nothing more. It is also, before we have real
photographs, the only way to know whether 0.97 is a robust figure.

The deliverable is not one more note, it is a **specification**: each
degradation's breaking point tells us what a capture-time quality check has
to reject.

---

## 1. The protocol

Base: the 8 pages of invoices 1, 2, 6 and 7 from the `variants_warped` set,
so four **complete** invoices — TEDS is computed on the reassembled invoice,
and an orphan page would skew the measurement.

The same 8 pages at every step. The comparison is therefore **paired**: the
gap between two steps cannot come from a different sample, which is worth
far more, at equal sample size, than drawing random pages at each level.

24 batches in total — 1 reference + 23 steps — i.e. 192 pages, about 4 h 20
on a T4. Raw reading only: what we measure is the robustness of **reading**
to image quality. Doubling it for pre-processing would answer a different
question (does lighting correction make noise worse?) and deserves its own
run, once the breaking points are known.

### The five degradations

| | what it simulates | steps |
|---|---|---|
| `flou` | camera shake during the exposure | 3, 6, 9, 13, 20 px |
| `bruit` | high ISO in low light | 500 → 8 photons at saturation |
| `exposition` | underexposure then brought back up | −2 to −6 stops |
| `resolution` | resizing by a messaging app | 0.75 → 0.22 of the long side |
| `jpeg` | camera compression | quality 25, 10, 3 |

### Three physical choices that change the result

**We work in linear light.** A sensor integrates photons, not sRGB values.
Blurring or adding noise directly to a PNG's bytes mixes quantities that
have already been through gamma: the blur comes out too dark and the noise
badly distributed between shadows and highlights.

**Noise is signal-dependent.** Shot noise (Poisson, so stronger where there
is light) plus Gaussian read noise. The usual reflex — uniform Gaussian
noise — spares the white of the paper, which is precisely where noise shows.

**Underexposure destroys through quantisation.** Darkening then brightening
again is reversible to the decimal; what is not reversible is that the
sensor writes 8 bits. We darken, quantise, add read noise, then brighten.
Measured: at −6 stops only **32 grey levels out of 256** remain.

---

## 2. Two scales, because the first was badly calibrated

The first scale was thrown out after visual inspection
([figure 11](../demo/figures/11_paliers_degradation.png)). Two flaws:

Blur went from legible to illegible **between two steps** — the break was
not bracketed, so the curve would have located nothing.

Above all, **at JPEG quality 12 the text stayed perfectly legible.** Checked
afterwards by going lower: the encoder saturates at 23.8 dB PSNR, and
between q=3 and q=1 nothing moves any more. A white page with contrasted
text is exactly what JPEG compresses well. Five steps would have produced a
flat curve — 40 pages of GPU for a non-result.

Hence two corrections: JPEG drops to **three** steps, which is enough to
establish that compression alone is not the threat; and a fifth degradation
appears, **resolution**, which is what actually kills small text when a
photo travels through a messaging app.

The lesson is worth noting: a degradation scale is calibrated by looking at
the images, not by picking round numbers.

---

## 3. Predictions, written before measuring

As for Chandra and GLM-OCR, we record them before measuring.

**Resolution will be the most brutal, and the break will be sharp.** A
character in the table body is about 9 px tall in our renders. At 0.40 that
leaves 4, at 0.22 it leaves 2 — below 3 or 4 px no OCR reads anything at
all, and the fall should be a cliff rather than a slope.

**Blur will break around 9–13 px.** The order of magnitude that matters is
stroke thickness, about 2 px: a 9 px shake spreads a stroke across four
times its width. To the eye, step 3 is already borderline.

**Noise will be absorbed better than it looks.** A modern VLM is trained on
real photographs, often noisy; noise degrades measured sharpness but leaves
the table structure intact. We expect TEDS-Struct to hold well after TEDS
has fallen.

**JPEG compression will break nothing**, across the whole tested range. If
that prediction holds, it is a useful result in itself: it removes a
constraint from the capture specification.

**Underexposure will hold longer than feared**, because the pre-processing
module's lighting correction... is precisely not in the loop here. In raw
reading, the break should arrive around −5 stops, when only about forty
levels remain.

**And the most interesting prediction, because it is verifiable another
way:** degradations that preserve the table's *structure* (noise, JPEG)
should leave a large TEDS-Struct − TEDS gap, whereas those that destroy it
(resolution, heavy blur) should bring both down together. If the gap behaves
as predicted, it becomes an **indicator of the nature of the problem**,
usable without ground truth.

---

## 4. How to produce the figures

```powershell
# 1. Generate the 192 images (a few minutes)
python scripts\degrader.py --jeu variants_warped

# Check the steps before spending GPU time
python scripts\degrader.py --jeu variants_warped --calibrer

# 2. The Kaggle archive (252 MB), then Add Input -> Datasets, name "degradation"
python scripts\degrader.py --jeu variants_warped --zip

# 3. After the run: the curve
python scripts\eval_degradation.py --figure
```

`--zip` rather than `Compress-Archive`: PowerShell 5.1 writes sub-folders
with backslashes and Kaggle then rejects the archive ("contains a forbidden
character in name"). It is the project's first zip to contain sub-folders.

If uploading 252 MB is too slow, `--pages 1,2,11,12` cuts it down to two
invoices: 96 images, half the GPU time, and the curve keeps its shape even
though each point gets noisier.

`eval_degradation.py` returns, for each degradation, the TEDS step by step
and the first step below 0.70 — expressed as a **physical quantity** ("shake
becomes fatal beyond 9 px") rather than a step number, because that is the
form that carries over into a specification.
