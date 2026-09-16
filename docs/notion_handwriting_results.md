# Handwriting OCR — what works, what breaks

Chandra OCR 2 · synthetic medical forms · metric = share of handwritten
fields correctly found · paired reference in every run

---

## 1. Baseline, clean pages

| model | English | Vietnamese |
|---|---|---|
| **Chandra OCR 2** (5 B) | **99.1%** | **95.5%** |
| PaddleOCR-VL (0.9 B) | 90.3% | 78.2% |

```
English      Chandra      ████████████████████████████████████████  99.1
             PaddleOCR-VL ████████████████████████████████████      90.3

Vietnamese   Chandra      ██████████████████████████████████████    95.5
             PaddleOCR-VL ███████████████████████████████           78.2
```

**Why it works** — Chandra reads a full page in one pass, keeps layout, and
handles Vietnamese diacritics. PaddleOCR-VL substitutes CJK characters when
unsure of a diacritic, which is why its Vietnamese gap is 3× its English gap.

---

## 2. Degradation — the headline

24 levels × 3 specimens, English. Reference `niveau0` = **100.0%**.

| degradation | range tested | worst score | verdict |
|---|---|---|---|
| sensor noise | 500 → 8 photons | **100.0%** | no effect |
| underexposure | −2 → −6 stops | **100.0%** | no effect |
| JPEG | quality 25 → 3 | **97.2%** | negligible |
| motion blur | 6 → 37 px | **8.5%** | breaks |
| resolution | 1241 → 364 px | **18.3%** | breaks |

```
worst score reached over the whole tested range

noise        ████████████████████████████████████████  100.0
exposure     ████████████████████████████████████████  100.0
jpeg         ███████████████████████████████████████    97.2
resolution   ███████                                    18.3
blur         ███                                         8.5
```

**Why photometry costs nothing** — noise, darkness and compression change
pixel *values*. The stroke stays where it is, and its shape is what carries
the letter.

**Why geometry breaks it** — blur and downscaling change stroke *shape*.
Cursive strokes are thin and close together; once two of them merge, no
amount of context recovers the character.

---

## 3. Motion blur

| blur | % of page width | at 200 dpi | fields found |
|---|---|---|---|
| 6 px | 0.36% | 0.8 mm | **97.2%** |
| 11 px | 0.67% | 1.4 mm | 73.2% |
| 17 px | 1.03% | 2.2 mm | 43.7% |
| 24 px | 1.45% | 3.0 mm | 15.5% |
| 37 px | 2.24% | 4.7 mm | 8.5% |

```
 6 px  ███████████████████████████████████████  97.2
11 px  █████████████████████████                73.2
17 px  ██████████████████                       43.7
24 px  ██████                                   15.5
37 px  ███                                       8.5
```

≈ **25 points lost per step** — a steep slope, not a cliff. A blurred page
degrades gradually, so a confidence signal has something to work with.

---

### What it looks like

Same page, same zone (identity block: name, date of birth, ID number).

> 📎 Drop in `demo/figures/17_paliers_manuscrit_flou.png`

| level | blur | reads as | fields found |
|---|---|---|---|
| `niveau0` | — | perfectly clean | 100.0% |
| `flou1` | 6 px | slightly soft, fully legible | **97.2%** |
| `flou2` | 11 px | visibly doubled, still readable | 73.2% |
| `flou3` | 17 px | ghosted, barely guessable | 43.7% |
| `flou5` | 37 px | strokes merged into grey | 8.5% |

The interesting one is `flou2`: **a human still reads it, the model already
loses a quarter of the fields.** That gap is the argument for a capture-time
check rather than trusting the operator's eye.

---

## 4. Resolution

| page width | approx. dpi | fields found |
|---|---|---|
| 1241 px | 150 | **100.0%** |
| 910 px | 110 | 88.7% |
| 662 px | 80 | 63.4% |
| 496 px | 60 | 45.1% |
| 364 px | 44 | 18.3% |

```
1241 px  ████████████████████████████████████████  100.0
 910 px  ███████████████████████████████████        88.7
 662 px  █████████████████████████                  63.4
 496 px  ██████████████████                         45.1
 364 px  ███████                                    18.3
```

A 25% downscale from the source costs **nothing**. The model does not need
200 dpi — it needs about half of it.

### What it looks like

> 📎 Drop in `demo/figures/18_paliers_manuscrit_resolution.png`

Thumbnails are scaled back up to a common width — which is exactly what the
model is given when it receives a downscaled photo.

---

## 4bis. How to produce the two figures

```powershell
python scripts\figure_paliers_manuscrit.py
```

Writes both strips into `demo/figures/`, each level labelled with its blur
or width **and its score**, so the picture cannot be quoted without its
number. Then drag the two PNGs into the blocks above.

---

## 5. 3D deformation

Vietnamese specimens projected on curved meshes, vs the same set read flat.

| condition | fields found |
|---|---|
| flat (30 specimens) | **95.6%** |
| warped (8 specimens) | **59.9%** |

```
flat    ██████████████████████████████████████  95.6
warped  ████████████████████████                59.9
```

**−35.7 points — the largest single drop measured.**

> ⚠️ Lower bound only: those 8 renders came out rotated 90° (texture
> orientation bug found afterwards), so the figure mixes deformation with
> orientation.

---

## 6. Capture specification

To keep **≥ 90% of fields**, on English handwriting, with Chandra:

| requirement | threshold |
|---|---|
| motion blur | < 7 px at 200 dpi — **0.4% of page width, ≈ 0.9 mm on A4** |
| resolution | ≥ **950 px across the page** (≈ 115 dpi) |
| noise · exposure · JPEG | **no constraint** within tested ranges |

→ In practice: **hold still, don't let the image be downscaled.**
Lighting is not the problem.

---

## 7. Limits of these numbers

| limit | consequence |
|---|---|
| 3 specimens per level (~141 field observations) | curve shape is solid, exact thresholds are indicative |
| English only — Vietnamese degradation not measured | **these are the optimistic figures**; VN is already 3.6 pts lower on clean pages, and diacritics are what blur destroys first |
| no printed-invoice curve measured | the "handwriting breaks earlier than print" prediction is still unverified |
| synthetic pages, handwriting fonts | not real handwriting, not real photographs — now addressed separately in [`notion_real_handwriting.md`](notion_real_handwriting.md), on 250 photographed lines of real Vietnamese handwriting |
| warped set rotated 90° | deformation figure is a lower bound |
