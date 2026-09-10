# Handwriting HTR benchmark — VN / EN (26 August)

The natural follow-up to the invoice pipeline: can handwriting be read on
the same medical forms, in both languages of the internship? Two synthetic
generators (`handwriting/` for the Vietnamese PHCN page 9, `handwriting_en/`
for pages 1-2 of the English record), 30 specimens per language, exact
field-level ground truth (`*_verite.json`).

---

## 1. Models tested, and why these

Research done before running anything: three candidates, chosen to span the
size/licence range already established on the invoice benchmark.

| model | size | licence | status |
|---|---|---|---|
| Chandra OCR 2 | 5 B | Apache 2.0 (code) / modified OpenRAIL-M (weights) | measured |
| PaddleOCR-VL | 0.9 B | Apache 2.0 | measured |
| GLM-OCR | 0.9 B | MIT | pending (see §4) |
| HunyuanOCR-1.5 | 1 B | Tencent (excludes EU/UK/South Korea) | **dropped** |

GLM and HunyuanOCR share the same environment (recent `transformers`), so
the same Kaggle notebook. **HunyuanOCR is dropped**: its licence excludes
the EU and Kaggle does not let you choose the machine's region — decided
without even running it, since the gap already measured between Chandra and
PaddleOCR-VL on this set does not justify working around that constraint.

---

## 2. Measurement protocol

Unlike the invoice pipeline, there is no per-model structured field
extractor — each model returns a free-form transcription of the whole page,
with its own layout conventions. `src/eval_handwriting.py` therefore asks a
more modest question: **does the expected text appear somewhere in the
transcription**, exactly or approximately? Three signals (exact / lenient /
local similarity score), detailed in the script's docstring.

Numeric or very short fields (`"5"`, `"X"`): matched on a word boundary, to
avoid a lone digit "matching" by chance on a page dense with dates and phone
numbers.

---

## 3. Results (26 August)

30 specimens per set, handwritten fields only (the VN `khoa` field is
printed, not handwritten; the EN `sex` field is a checkbox, not text — both
excluded from this table, counted separately by the script).

| set | Chandra OCR 2 (5 B) | PaddleOCR-VL (0.9 B) |
|---|---|---|
| VN | **95.5%** (score 97.2) | 78.2% (score 84.8) |
| EN | **99.1%** (score 99.7) | 90.3% (score 97.5) |

Chandra clearly leads on both languages, consistent with the edge it already
showed on clean-background invoices (see `resultats_teds.md`). The gap is
wider in Vietnamese: diacritics remain the hard part for both models, but
PaddleOCR-VL suffers visibly more from them.

### What Chandra still misses (VN, 4.5%)

Checked in detail: genuine near-misses, not a measurement artifact — scores
66 to 79, on long descriptions partially misread (`mo_ta`, `ky_thuat`) and a
few proper names or department names (`so_y_te`). Nothing to fix on the
scoring side here.

---

## 4. Two bugs found while processing these results

### GLM-OCR: systematic OOM, 30/30 on both languages

The exact same CUDA error on every specimen: an attempt to allocate
23.43 GiB. Cause: our specimens are 1654x2339 px (~200 dpi), while GLM had
so far only run on the invoice images, 900x1200 — 3.6x fewer pixels.
`_glm_predict` (in `scripts/bench_deformed.py`) passed the raw image path to
the processor with no resizing; GLM-OCR has no built-in tiling or
downsampling on the vision-encoder side, unlike Chandra and Hunyuan, which
handle our images unchanged.

**Fixed**: resize to a 1200 px long side before the call
(`GLM_MAX_LONG_SIDE`), through a temporary copy, since the processor only
accepts a file path in the message, not an image object. The Kaggle notebook
still needs re-running (task #31) — since the previous runs produced no `.md`
at all, resuming starts from zero with nothing to clean up.

### `eval_handwriting.py`: Chandra's HTML tags were breaking the score

Chandra renders tables as raw HTML inside the Markdown, with a `<br/>`
between two lines of the same cell — typically the `ngay_gio` field
("15h00<br/>12/07"), while the ground truth expects a space
("15h00 12/07"). The normaliser stripped no tags at all: a correctly read
field counted as missed. Found by manually inspecting Chandra's first VN
score (77.7%), where *almost every* `ngay_gio` field in every specimen came
out as missed — too regular a pattern to be a genuine reading error.

**Fixed** with `_sans_html()`, which strips every tag (not just `<br/>`:
PaddleOCR-VL wraps each cell in `<td style='...'>`, Chandra sometimes adds
`<i>...</i>` — harmless today but potentially not tomorrow). Measured
effect: Chandra VN goes from **77.7% to 95.5%**. PaddleOCR-VL barely moves
(78.2% → 78.2%), since it did not use `<br/>` inside its cells — this was a
genuine artifact of Chandra's rendering, not a general flaw in the method.

---

## 5. Two qualitative observations, on the worst specimen of each language

Visual inspection of PaddleOCR-VL's HTML report (image and transcription
side by side), on the worst-scoring specimen of each set.

### VN — CJK hallucinations, not a legibility problem

`specimen_005` (single font, Playwrite VN): the handwriting is perfectly
legible to the eye, which rules out an explanation based on letter shape.
Yet PaddleOCR-VL inserts **Chinese and Korean characters** in places,
instead of the expected text: "liệt nửa người trái" becomes
"liết n**其一** người trái", "Đồng ý" becomes "Đông **너**". When the model
is unsure about a Vietnamese diacritic, it appears to fall back on a CJK
token rather than a wrong Latin letter — consistent with the reservation
already noted for GLM-OCR (Vietnamese is outside its official languages),
but observed here on PaddleOCR-VL.

### EN — a clear, measurable font effect

Score by font, across the 30 EN specimens (PaddleOCR-VL):

| font | n | average |
|---|---|---|
| homemade_apple | 3 | **79.6%** |
| reenie_beanie | 6 | 88.9% |
| patrick_hand | 7 | 91.4% |
| shadows_into_light | 6 | 91.5% |
| caveat | 3 | 91.7% |
| sacramento | 4 | 92.4% |
| alex_brush | 1 | 92.6% |

Homemade Apple ("irregular, very realistic" by its own description in
`handwriting_en/README.md`) clearly trails the other six, consistently
across all three of its occurrences (71%, 83%, 85%). On the worst case
(`specimen_019`), this font's **cursive capital T** is visibly ambiguous:
"Thang" → "Zhang", "Tran" (address) → "Iran", "Tran" (signature) → "Jan" —
three different readings of the same letter on the same page. A genuine
visual ambiguity in the glyph, not a one-directional systematic confusion.

Worth checking once Chandra and GLM are available on these same specimens:
if Homemade Apple remains the weak point across all three models, that
points to the font rather than to any one model.

---

## 6. Remaining work

- Re-run GLM-OCR (task #31) after the resizing fix.
- Complete the three-model table, VN and EN.
- Check whether the Homemade Apple effect and the CJK hallucinations
  reproduce on Chandra and GLM, or are specific to PaddleOCR-VL.
