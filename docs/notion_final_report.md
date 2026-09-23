# OCR Medical documents

**Final internship report**

IMT Mines Alès · Imperato Julien
PTIT/Thinkslab · supervisor Thanh-Ha DO

July - September 2026

---

## Objective

Reading Vietnamese hospital paperwork automatically: invoices and
rehabilitation follow-up forms, photographed rather than scanned, part printed
and part handwritten. The question asked at the start was which model reads
them and what has to happen to the image before it does.

Real records cannot be published, so the project builds its own documents with
exact ground truth, measures readers against them, and ends by generating the
handwriting itself so that a reader can be trained on it.

---

## Contents

| | part | principal result | status |
|---|---|---|---|
| 1 | Corpus and method | synthetic documents, exact ground truth | measured |
| 2 | Model selection and page assembly | Chandra OCR 2 at TEDS 0.916, merging worth +0.275 | measured |
| 3 | Making the image readable | adaptive pre-processing 0.942, plus a capture specification | measured |
| 4 | Cluttered backgrounds | cropping is not solvable here, IoU ceiling 0.59 | closed |
| 5 | Handwriting | real Vietnamese, CER 6.84% zero-shot against 4.80% published | measured |
| 6 | Geometric deformation | −2.0 points on real captured paper, against −35.7 simulated | open |
| 7 | Generating medical handwriting | real handwriting costs Chandra **37.7 points** against a font | measured |
| 8 | What comes next | the remaining gap is training, not architecture | - |

Each part is a numbered list of points. Every point states what was done,
the figure obtained, and one of four states: **measured** (a number exists and
the protocol is reproducible), **partial** (one language or one subset only),
**closed** (avenue abandoned, with the reason), **open** (built, not yet
measured).

Abandoned avenues are reported inside the part they belong to rather than in
an appendix. A measured negative result is still a result: it narrows the
search space for subsequent work.

---

## Part 1. Corpus and method

### 1.1 Why synthetic documents · measured

Real Vietnamese hospital records cannot be published. The project therefore
generates its own: LaTeX invoice templates and a form (27/BV1-P3, physical
rehabilitation follow-up), rendered then photographed in 3D.

The decisive consequence is that **the ground truth is exact and free**. Every
figure in this report is a comparison against a known truth, not against a
human annotation that would itself need checking.

### 1.2 Six templates rather than one · measured

An early version used a single invoice template. A model can learn a layout
and appear to read while it is in fact recalling. Six templates and twelve
invoices, with varied column counts and header positions, remove that
possibility.

### 1.3 Official medical vocabulary, not invented terms · measured

Technique names come from the Ministry of Health nomenclature (Decision
5737/QĐ-BYT, 120 techniques). An invented but plausible Vietnamese term would
let a model "guess right" without reading, which is the exact failure mode
measured in §5.4.

### 1.4 One evaluation protocol for every run · measured

`scripts/eval_all.py`, then `src/eval_handwriting.py` and `src/eval_lignes.py`.
Runs scored by different scripts are not comparable, so the project keeps one
entry point per task type.

### 1.5 Unified corpus · measured

16 sets, 691 images, one `manifest.json`, all paths rewritten to be
archive-relative so a clone resolves them without the neighbouring
repositories.

> 📎 Drop in `demo/figures/02-model-comparison.png`

---

## Part 2. Which model reads the documents, and how pages are assembled

### 2.1 Benchmark on warped multi-page invoices · measured

| model | size | TEDS | TEDS-Struct | gap |
|---|---|---|---|---|
| HunyuanOCR-1.5 | 1 B | 0.950 | 0.973 | 0.023 |
| **Chandra OCR 2** | 5 B | **0.916** | 0.943 | 0.027 |
| PaddleOCR-VL | 0.9 B | 0.909 | 0.933 | 0.024 |
| PP-StructureV3 | - | 0.557 | 0.857 | **0.300** |

**The PP-StructureV3 gap is the informative number.** It rebuilds the grid
(0.857) but not the characters (0.557): it sees the table and misreads the
content. TEDS alone would have hidden this. The two metrics side by side
diagnose it.

### 2.2 HunyuanOCR dropped despite the best score · closed

Its Tencent community licence excludes the EU, the UK and South Korea, and
Kaggle does not allow choosing the machine's region. The measured figures
remain valid and appear in a dozen documents predating the decision, but the
model is out of the roster. **The best model is not always the usable one**,
and a licence check belongs at the start of a benchmark, not the end.

### 2.3 Multi-page merging · measured

An invoice spans several photographed pages. Merging them before scoring:

| model | first page alone | reassembled | gain |
|---|---|---|---|
| HunyuanOCR-1.5 | 0.668 | 0.950 | **+0.281** |
| **Chandra OCR 2** | 0.641 | **0.916** | **+0.275** |
| PaddleOCR-VL | 0.658 | 0.909 | **+0.251** |
| PP-StructureV3 | 0.424 | 0.557 | +0.132 |

Each invoice is scored twice against the same ground truth, the complete
invoice: once with the first page's table alone, which is what a pipeline
ignoring the problem would produce, and once with the table reassembled.

The gain is larger than any difference between models. **How pages are
assembled matters more than which reader is used.** It is also of the same
order for all four, which is the reassuring part: the merging algorithm is
not calibrated on one particular reader.

An invoice's table is cut across pages: the header repeats, a
`Tiếp trang trước` banner appears, and the logical table has to be rebuilt
from those fragments. `src/table_merge.py` does this. The evaluation measures
the reconstructed *logical* table (header, drug lines, total) rather than the
layout artifacts, which are precisely what merging must make disappear.

### 2.4 Continuation detection: recall is not the metric that matters · measured

Whether two consecutive pages belong to the same invoice, scored pair by pair
against a ground truth read from the source PDF rather than from the OCR
outputs, which had inspired the algorithm:

| model | TP | FP | misses | precision | recall | F1 |
|---|---|---|---|---|---|---|
| **Chandra OCR 2** | 8 | **0** | 0 | 100% | 100% | **100%** |
| HunyuanOCR-1.5 | 8 | **0** | 0 | 100% | 100% | **100%** |
| PP-StructureV3 | 7 | **0** | 0 | 100% | 100% | **100%** |
| PaddleOCR-VL | 7 | **0** | 1 | 100% | 88% | 93% |

One page yields no table for any model, and PP-StructureV3 loses a second one, which
is why the totals differ by a unit. It is an upstream reading failure,
not a merging failure.

**Zero false positives for all four models, and that is the number to read.**
A missed merge leaves two visibly incomplete tables. A wrong merge manufactures
one plausible table mixing two invoices, an error that survives every
downstream check.

The most discriminating signal is a restart of the `STT` column at one. It is a
**domain assumption**: valid for this invoice format, to be re-validated on any
other.

### 2.5 An audit of silent failures, and the worst bug of the project · measured

A targeted review of the production modules only, not the benchmarks. What
was being looked for was not crashes, which are visible, but code producing a
**plausible and wrong** result without raising anything.

The most serious finding inverted a decision. `confidence()` awarded 0.15 for
"no gap in the numbering", but gaps were computed over the `STT` values
actually read: when the column was not recognised, the gap list came back
empty, and the bonus was granted anyway.

| same table, with a real numbering gap | confidence |
|---|---|
| `STT` readable, the gap is seen | 0.600 |
| `STT` header unreadable (**the same table**) | **0.750** |

**Damaging the reading raised the score by 0.15.** And the bias was not
neutral: it systematically favoured the *pre-processed* variant, whose known
defect is precisely that it damages headers (§3.2). The adaptive policy was
therefore sometimes choosing a reading *because it was too degraded to be
checked*.

The fix publishes `index_available` and grants the point only when the check
could actually run. Weights are deliberately **not** renormalised over the
available signals, which would reward information loss even more. Absence of
evidence is neither proof nor fault: it earns nothing and costs nothing.

### 2.6 Three more silent failures from the same audit · measured

**The label `STT` read as `S/T`.** It is the shortest label in the table, and losing one
letter of three drops fuzzy similarity below threshold, where the same loss on
`Thành tiền` goes unnoticed. All 33 lines of one invoice came out with
`index: null`, taking skipped-line detection with them.

**The delivered JSON did not distinguish "verified" from "unverifiable".**
`numbering_gaps: []` was emitted both for a perfect numbering and for an
unreadable one. The consumer believed checked what could not be checked.

**The field `lines_to_check` could name no line at all.** Entries were identified by
`STT`. Without it the field returned `[null, null, …]`, announcing 31 lines
to review without saying which. The most useful field of the deliverable
became unusable in exactly the case where it is most needed.

The common shape of all four: **a guard that reports success when it did not
run.** That is the failure mode to look for in this kind of pipeline, and it
is invisible to tests that only check the happy path.

### 2.7 GLM-OCR never measured · open

0.9 B, MIT licence, the most permissive candidate. The first pass failed
with CUDA OOM on 1654×2339 handwriting images (no resizing in the inference
path). Fix applied (`GLM_MAX_LONG_SIDE`), re-run still pending. **This is the
main gap in the model comparison.**

---

## Part 3. Making the image readable

### 3.1 Classical localisation does not work · closed

Contour and perspective detection on the photographed sheet:

| | value |
|---|---|
| ceiling over all candidates | 0.51 IoU |
| what the selection actually retains | 0.35 |
| images with a usable crop (IoU ≥ 0.7) | **0 / 17** |

Not a tuning problem: even the *best* candidate never reaches a usable crop.

### 3.2 Pre-processing hurts on average, helps per image · measured

| policy | TEDS | invoices ≥ 0.9 |
|---|---|---|
| raw only | 0.906 | 42/48 |
| pre-processed only | 0.879 | 24/48 |
| **adaptive (per image)** | **0.942** | **44/48** |
| *ceiling (perfect hindsight choice)* | *0.945* | |

The average conceals two opposite populations: pre-processing rescues badly
lit pages and destroys clean ones (one invoice fell from 0.968 to 0.478).
**The adaptive policy reaches 0.942 against a 0.945 ceiling**, so there is almost
nothing left to gain from a better decision rule.

> 📎 Drop in `demo/figures/04-adaptive-policy.png` and
> `demo/figures/08-with-without-preprocessing.png`

### 3.3 Capture quality: what actually costs something · measured

24 degradation steps, paired against a `niveau0` reference:

| degradation | range tested | worst score |
|---|---|---|
| sensor noise | 500 → 8 photons | **100.0%** |
| underexposure | −2 → −6 stops | **100.0%** |
| JPEG | quality 25 → 3 | **97.2%** |
| motion blur | 6 → 37 px | **8.5%** |
| resolution | 1241 → 364 px | **18.3%** |

**Photometry is free, geometry is fatal.** Noise, darkness and compression
change pixel *values*. The stroke stays where it is, and its shape carries the
letter. Blur and downscaling change the stroke's *shape*, and once two strokes
merge, no amount of context recovers the character.

### 3.4 A capture specification, and a gate that enforces it · measured

To keep ≥ 90% of handwritten fields:

| requirement | threshold |
|---|---|
| motion blur | < 7 px at 200 dpi, i.e. **0.4% of page width, ≈ 0.9 mm on A4** |
| resolution | ≥ **950 px across the page** (≈ 115 dpi) |
| noise · exposure · JPEG | **no constraint** in the tested ranges |

Implemented in `src/qualite_capture.py`, with Laplacian-variance landmarks
calibrated against measured field recall. The interesting step is `flou2`
(11 px): **a human still reads the page, the model already loses a quarter of
the fields.** That gap is the argument for a machine check at capture time
rather than trusting the operator's eye.

> 📎 Drop in `demo/figures/17_paliers_manuscrit_flou.png`

### 3.5 Content-based cropping · closed

Cropping to the largest detected table box, then scoring end to end. Abandoned:
on documents whose background resembles the document, the crop removed the
header of nearly every sheet. Losing the header costs more than the crop gains.

---

## Part 4. Cluttered backgrounds

### 4.1 The set · measured

Invoice pages photographed on a desk among distractor sheets. This is the realistic
case, and the one where every localisation method collapses.

| | ceiling | obtained | IoU ≥ 0.7 |
|---|---|---|---|
| clean background (25 pages) | 0.86 | **0.84** | **22/25** |
| cluttered background (20 pages) | 0.51 | **0.37** | **0/20** |

### 4.2 Eleven attempts, seven method families, all failing · closed

Contours, corners, saliency, depth, line detection, colour segmentation and
combinations. IoU ceiling never above 0.59 against a measured achievable 0.85.

The explanation came last and is the useful part: **the sheet's edge is
invisible in our renders**: white paper on white paper, with no depth of
field. The methods were not bad. The information was absent.

Two consequences. First, the right answer is not a better crop but a reader
that segments by itself, which PaddleOCR-VL already does. Second, the test
set itself was unrealistic: a real photograph has depth of field, which
separates the sheet from the background. Re-rendering it remains open.

### 4.3 Reading cost of clutter · measured

| | cluttered | clean |
|---|---|---|
| Chandra, TEDS with merging | **0.604** | 0.944 |
| TEDS-Struct | 0.714 | 0.983 |

> 📎 Drop in `demo/figures/13_plafond_fonds_encombres.png` and
> `demo/figures/16_bord_invisible.png`

---

## Part 5. Handwriting

### 5.1 Synthetic specimens · measured

30 VN + 30 EN generated forms, scored on the proportion of handwritten fields
correctly found:

| model | English | Vietnamese |
|---|---|---|
| **Chandra OCR 2** (5 B) | **99.1%** | **95.5%** |
| PaddleOCR-VL (0.9 B) | 90.3% | 78.2% |

PaddleOCR-VL's Vietnamese gap is three times its English gap: it substitutes
CJK characters when unsure of a diacritic.

### 5.2 A bug worth 18 points · measured

Chandra's Vietnamese score was 77.7% until HTML line-break tags inside table
cells were stripped before scoring, as in a date cell reading 15h00 then 12/07
on two lines. The model was reading
correctly. The *scorer* was wrong. Corrected: **95.5%**.

The lesson generalises: before concluding that a model reads badly, check that
the scorer reads the model correctly.

### 5.3 Real Vietnamese handwriting · measured

250 photographed lines, real handwriting (`vn_handwritten_images` / Cinnamon).
This closes the biggest caveat of every earlier handwriting figure, which came
from LaTeX pages rendered with handwriting *fonts*.

| | CER | WER |
|---|---|---|
| **Chandra OCR 2**, zero-shot | **6.84%** | 19.01% |
| CRNN trained on this dataset (published) | 4.80% | 15.66% |

Two points behind a specialist trained on this exact data, with no training at
all.

Three normalisations separate the error types:

| measurement | CER | what it removes |
|---|---|---|
| raw | 6.84% | - |
| tone placement canonicalised | 6.51% | −0.33 · `hoà` vs `hòa` |
| diacritics stripped | 4.99% | −1.52 more · accent errors |
| ↳ remainder | **4.99%** | **wrong letters** |

**Three quarters of the errors are letters, not accents**, the opposite of
PaddleOCR-VL on invoices.

*Caveat to state with the number:* the public archive has no train/test split,
so the CRNN's 4.80% was measured on a different partition. The order of
magnitude is informative. A few tenths are not.

### 5.4 The failure mode is invention, not misreading · measured

The worst lines replace words with **other real Vietnamese words**:

| written | read as |
|---|---|
| Quận **Hà Đông, Hà Nội** | Quận **Hồ Chí Minh, Hồ Chí Minh** |
| Xã **Lình Huỳnh**, Huyện **Hòn Đất** | Xã **Vĩnh Thụy**, Huyện **Hòa Hát** |

Quantified against the dataset's own lexicon, on 439 word substitutions:

| | count | share |
|---|---|---|
| lands on a real word | 300 | 68.3% |
| ↳ within 2 characters of the truth | 232 | 77.3% of those |
| ↳ **further than 2 characters** | **68** | **22.7% of those** |

The first number alone proves nothing: Vietnamese is dense, so one wrong
accent lands on a real word by chance. **Distance is what discriminates.**
68 substitutions, **15.5% of all of them**, cannot be produced by the pixels.

And they are not random. The furthest ones swap a word for another **from the
same semantic slot**: `tổ → phường` and `lương → huyện` (administrative units),
`dương → nguyễn` (surnames). Category-consistent substitution is the signature
of a language model filling a gap it cannot see.

**Why this matters more than the CER.** A CRNN decodes frame by frame through
a CTC head and cannot swap in a different city. Chandra generates
autoregressively and falls back on the most probable continuation. For patient
names, dosages and amounts, **fluent fiction is more dangerous than garbage**,
because garbage is detectable.

**What follows for the pipeline.** A reading cannot be presented as verified
on the strength of a low error rate, because the errors that remain are
exactly the ones that look right. Two consequences, neither of which is a
better reader. Numeric fields carry their own redundancy, so totals, sums and
line numbering can be checked against each other and the inconsistent lines
handed to a human. Non-numeric fields carry none, so a name or a diagnosis can
only be reported **as read**, never as confirmed. And since §3.4 shows the
model losing a quarter of the fields on a page a human still finds legible,
the check that costs least is the one made at capture time, before the
document is read at all.

---

## Part 6. Geometric deformation

### 6.1 Blender renders · partial

Vietnamese specimens projected onto curved meshes: flat 95.6% → warped 59.9%,
a **−35.7 point** drop. Reported at the time as the worst failure mode
measured, with an explicit caveat: those eight renders came out rotated 90°,
so the figure mixed deformation with orientation.

### 6.2 Real captured deformations, and a contradiction · open

UVDoc (SIGGRAPH Asia 2023, MIT) publishes photographs of real bent sheets with
the exact `uvmap` linking every pixel to its position on the flat page.
Geometry being decoupled from content, our documents can be projected onto
**real** paper deformation, with the shadows, lens blur and sensor noise of the
capture.

That yields two images of each document, one deformed and one flat. The flat
one is not a reconstruction: it is what a **perfect** dewarping would return,
so the gap between them is the **ceiling** of what geometric correction can
recover.

First measurement, 26 paired specimens:

| | fields read |
|---|---|
| flat | 95.4% |
| deformed | 93.4% |

**−2.0 points, against −35.7 from the Blender renders.** If confirmed, this
reverses the conclusion: with a ceiling that low, **adding a dewarping stage
to the pipeline would not be worth it**.

Not yet publishable. 4 of 30 pages failed with CUDA OOM, and deformed images
ranged 1462–1874 px against a fixed 1654 px for the reference, so part of the
2 points may be resolution rather than deformation. A corrected set (1400 px
on both sides, normalised on **document** width) is built and awaiting a re-run.

> 📎 Drop in `demo/figures/19_uvdoc_oracle.png`

The two images above are the same document. Left: our form projected onto a
**real photographed** bent sheet. The curl, the cast shadow and the lighting
falloff come from the capture, not from a simulation. Right: the flat texture,
which is by construction what a perfect dewarping would return. The whole
method is in that pair. The measurement is simply the reading score of one
against the other.

> 📎 Drop in `demo/figures/05-deformation-cost.png`

---

## Part 7. Generating medical handwriting

### 7.1 Model choice, decided on published evidence · measured

WriteViT (UIT / VNU-HCM, 2025, MIT) over ScrabbleGAN, on their VNOnDB figures:

| model | FID (lower is better) |
|---|---|
| **WriteViT** | **6.18** |
| HWT | 9.85 |
| HiGAN | 11.26 |
| ScrabbleGAN | 19.23 |

ScrabbleGAN is the GAN one cites by reflex for handwriting synthesis, and it
is the **worst** on Vietnamese, with "frequent omissions or distortions of accent
marks". Choosing by reflex would have produced Vietnamese without accents.

### 7.2 Why a medical corpus, measured rather than assumed · measured

323 medical words extracted from the Ministry nomenclature and the generated
ground truths:

| compared against | medical words absent |
|---|---|
| a general Vietnamese dictionary | **10%** |
| what the real dataset actually contains | **59%** |

The domain gap is **not** a matter of rare words. The vocabulary is ordinary
Vietnamese. It is that 59% of it **never appears in the training data**, which
contains only addresses. That is what generation has to supply.

*Two corrections were needed before this number was trustworthy.* English
specimens had been included, filling a Vietnamese lexicon with `Hypertension`
and American first names. And the first comparison used a dictionary rather
than the actual training corpus.

### 7.3 Style transfer works, digits do not · measured

Preview plate, three writers, the same hard words. Vietnamese words are formed,
diacritics present, and the three handwriting styles are clearly distinct.

But `1972` renders as `Mth`, `thol`, `1t8B`. And `15` renders as `Mfg`, `lb`, `1B`.

Root cause, measured on VNOnDB (368,217 characters):

| | share |
|---|---|
| words containing a digit | **2.83%** |
| uppercase accented letters | **0.38%**, only 20 distinct forms of ~67 |
| alphabet characters never seen at all | **51 of 197** |

Not a raw-frequency problem, since `1` appears 1,073 times. A **proportion**
problem: drowned at 2.83%, the generator learns cursive and ignores digits,
which have neither ligature nor shared baseline.

This also invalidated an earlier idea of mine. I had measured what the
*lexicon* covered, when the binding constraint is what the *generator has
seen*. Asking for `Ế` from a model that never encountered it returns something
else, silently. The check now filters the lexicon by training frequency.

**For medical records, whether dosages, durations, dates or room numbers,
digits are the most critical field on the page.** The published FID figures say nothing
about them.

### 7.4 Fine-tuning on digits · open

VNOnDB rebalanced from **2.83% to 30.9%** digit-bearing words: all digit words
kept, the rest subsampled, with no duplication, since repeating an image teaches
the image rather than the digit. Training resumes from the authors' checkpoint
at a reduced learning rate.

One constraint had to be respected: `author_idx` is assigned by dictionary
enumeration order, and the checkpoint's writer-classification head was trained
on those indices. All 106 writers are kept in their original order, including
the five with no digit words.

The measurement is a **before/after plate on the same words and writers**. The
real risk is not that fine-tuning fails, but that it fixes digits while
breaking cursive. Catastrophic forgetting is the standard failure mode of
fine-tuning on a skewed distribution. The plate carries both.

### 7.5 Training the generator on the real dataset · closed

Considered, then abandoned for a methodological reason rather than a technical
one. Line-to-word segmentation reached only **14%** yield, and more
decisively, **the real dataset has no train/test split**. The 250 lines used to
measure Chandra at 6.84% are drawn from the whole set. Training a generator on
it would place them in the training data, making any downstream CRNN figure
uninterpretable.

The real dataset is the project's **measurement instrument**. It is the only
place with both a published reference (4.80%) and a measured zero-shot figure
(6.84%). Contaminating it would cost more than 3,000 extra words could return.

*The segmentation filter is worth recording:* a split was accepted only if the
fragment count matched the label's word count **and** fragment widths tracked
character counts. Of the splits with the right count, 132 of 300 had the cuts
in the wrong places, an accent detached as a word while two words merged. The
naive version accepted all of them.

### 7.6 Filling the real form with generated handwriting · measured

The deliverable is not a pile of word images. It is the **actual PHCN form**
(27/BV1-P3), filled with handwriting produced by the GAN, with its exact
ground truth beside it.

The implementation is deliberately small. Every handwritten field of the
existing generator goes through one function, `hw()`. Replacing it is enough:
instead of wrapping text in a handwriting font, it emits **one image per
word**, separated by real LaTeX spaces.

That last detail is what makes it work. A single image per field could not be
broken across lines, and the description column of the table is narrow: its
text runs onto two or three lines. With one word per image and ordinary spaces
between them, **LaTeX keeps doing the line breaking**, the column widths and
the alignment. Nothing else in the template changes.

**One writer per document.** A real sheet is filled in by one person. Mixing
styles within a page would produce a document that cannot exist.

**The ground truth is paired.** Each generated document reuses the ground
truth of its font-rendered twin, so the two carry identical content in an
identical layout, and only the handwriting differs. That is the only way to
attribute a difference in reading score to the handwriting itself.

> 📎 Drop in `demo/figures/20_document_gan.png`

### 7.7 What the digits cost, and what would fix them · measured

Digits are written in the **handwriting font**, not by the GAN. They account
for **141 of the 397 distinct words** of the corpus, 36%: dates, durations,
room and bed numbers, ages.

The fine-tuning of §7.4 did not recover them. Raising their share of the
training data from 2.83% to 30.9% left `1972` and `15` as shapeless strokes on
the control plate, before and after. The cursive survived intact, so this is
not catastrophic forgetting: it is a failure to learn.

Two reasons, and they point at different fixes.

**Volume, not proportion.** Rebalancing changed the ratio, not the quantity:
VNOnDB holds 1,892 word images containing a digit, and the rarest appear barely
more than a hundred times each (`8` 110, `6` 128, `9` 126). **More data is the
cheapest lever**, digits being trivial to collect next to cursive Vietnamese.

**Structure.** The model learns joined writing: ligatures, a shared baseline,
transitions between letters. Digits have none of that. They are isolated
shapes, closer to printing than to cursive, and a model trained entirely on
connected script has little reason to represent them well.

The pragmatic answer, applied here, is to write them with the font. The
document stays coherent, and the fallback rate is printed for every document.

### 7.8 What the generated documents cost Chandra · measured

The 20 generated documents were read by Chandra and scored against the same
metric, the same ground truth and the same 20 specimens as their
font-rendered twins. Only the handwriting differs.

| | handwritten fields read | mean field score |
|---|---|---|
| **font** (PlaywriteVN) | **95.3%** | 97.2 |
| **GAN**, real writer styles | **57.6%** | 84.7 |

**A drop of 37.7 points**, the largest single effect measured in the project.

**The font specimens were far too easy.** A font redraws each letter
identically everywhere, a real writer never does. The 95.5% of §5.1, the
thresholds of §3.3 and the capture specification of §3.4 all rest on that
material. They are not wrong, but they describe a best case real handwriting
does not reach.

**The model is not blind, it is imprecise.** The mean field score stays at
**84.7** out of 100: Chandra recovers most characters and misses exact
equality.

Where the loss concentrates, over the failing fields:

| field | mean score when failed |
|---|---|
| `xac_nhan` (one word, often a single `X`) | 42 |
| `mo_ta` (long free-text description) | 51 |
| `ky_thuat` (technique name) | 62 |
| `ngay_gio` (date and time) | 73 |
| `bs_chi_dinh` (doctor name) | 73 |

**Very short fields fail hardest**: no context to resolve an ambiguous stroke,
and one wrong character loses the field. Long descriptions fail next, since a
single error anywhere is enough. What holds up best are the rigidly formatted
fields, where the expected shape constrains the reading.

*A caveat that cuts the other way:* 14% of the word occurrences on these
pages are digits, written
with the font (§7.7) and therefore read under the easy regime. **The true cost
is larger than 37.7 points, not smaller.**

> 📎 Drop in `demo/figures/21_lecture_documents_gan.png`

**The failure mode is the one of §5.4, now on our own documents.** Third line
of the figure: the form records a note about elbow flexion, Chandra returns an
order for a lumbar spine radiography. Nothing on the page mentions an X-ray.
It did not misread those words, it replaced them with a plausible medical
sentence.

Same mechanism in smaller doses elsewhere: `Trần Thị Bảy` becomes
`Trần Thị Bảo`, a physiotherapist becomes `Bác sĩ Nguyễn Văn`, a moxibustion
treatment becomes generic `chăm sóc`.

**Every one of these reads as a valid entry in a medical record**, and none
would be caught from the output alone.

---

## Part 8. What comes next

The generator works. What it does not yet do is a matter of training, not of
architecture, and that is the useful thing to say at the end of this work.

### 8.1 Train the generator longer, and on more digits

The fine-tuning of §7.4 was deliberately short: 30 epochs at a reduced
learning rate, on 6,132 rebalanced samples. It was meant to answer one
question, does raising the share of digits help, and it answered no at that
scale.

**But the evidence points at an undertrained model rather than an incapable
one.** The cursive came through the fine-tuning untouched, so nothing was
saturated or destroyed and there was capacity left. And the absolute volume of
digit data stayed tiny: 1,892 word images in total, with the rarest digits
seen barely more than a hundred times each (`8` 110, `6` 128, `9` 126). A
model cannot learn to draw convincingly from a hundred examples.

Three levers, in order of cost:

| lever | why it should help |
|---|---|
| **more epochs** | 30 is short for a GAN, the published checkpoint was trained for 200 |
| **more digit data** | digits are trivial to collect or synthesise next to cursive Vietnamese |
| **a digit-specific loss or curriculum** | the recogniser already scores content, and weighting numeric samples would push the generator where it is weak |

None of these requires changing the model. That is the argument for expecting
improvement: **the ceiling reached so far is a training ceiling.**

### 8.2 Train a CRNN on the generated set

This is the experiment the whole generation effort exists for, and the one
step still missing. The protocol is already fixed: the same CRNN trained in
three conditions, real only, synthetic only, real plus synthetic, and scored
with `src/eval_lignes.py`.

Two reference points are already in hand and make the result readable
immediately: a **CRNN published at CER 4.80%** on the real dataset, and
**Chandra at 6.84% zero-shot**. A small model trained partly on generated
handwriting, placed against those two, answers the question the supervisor
asked at the start of this phase.

---

## Sources

### This work

- **Repository** · [github.com/Halfaa/PTITOcr](https://github.com/Halfaa/PTITOcr)
  Every figure in this report is reproducible from it: the generators, the
  evaluation scripts, the Kaggle notebooks and the dataset manifest.

### External

- WriteViT: [arXiv 2505.13235](https://arxiv.org/abs/2505.13235) · [repository](https://github.com/hnam-1765/WriteViT) (MIT)
- ScrabbleGAN: [CVPR 2020](https://arxiv.org/abs/2003.10557)
- UVDoc: [SIGGRAPH Asia 2023](https://igl.ethz.ch/projects/uvdoc/) · [dataset code](https://github.com/tanguymagne/UVDoc-Dataset) (MIT)
- Handwritten text generation for HTR: [systematic review, 2025](https://arxiv.org/abs/2507.06275)
- Ministry of Health rehabilitation nomenclature: Decision 5737/QĐ-BYT, 22/12/2017
