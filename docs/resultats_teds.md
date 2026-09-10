# Results — warped multi-page invoices

Three models, 8 invoices, 17 pages, identical test set.
Images produced by `synthetic_invoice_generator` then warped in 3D by
`doc3D-renderer` (Blender), to simulate photographs of documents.

Metric: **TEDS** (Tree-Edit-Distance-based Similarity, Zhong et al. 2020,
PubTabNet) — the standard table-recognition metric, so the figures are
comparable to the literature.

- **TEDS**: structure + textual content
- **TEDS-Struct**: structure alone, cell text ignored

To reproduce:

```powershell
python src\eval_teds.py           --run multipage_hunyuan
python src\eval_multipage_merge.py --run multipage_hunyuan
```

---

## 1. Comparison of the four models

Figures re-measured on 5 August under the unified protocol
(`scripts/eval_all.py`), after improvements to the evaluation (Markdown
table parsing, ground-truth corrections). The earlier values in this
document (0.928 for Hunyuan) came from an intermediate state of the
evaluation code.

| Model | Size | TEDS | TEDS-Struct | Gap | Time / page |
|---|---|---|---|---|---|
| **HunyuanOCR-1.5** | 1 B | **0.950** | **0.973** | 0.023 | ~87 s (laptop GPU) |
| Chandra OCR 2 | 5 B | 0.916 | 0.943 | 0.027 | ~81 s (Kaggle T4) |
| PaddleOCR-VL | 0.9 B | 0.909 | 0.933 | 0.024 | ~230 s (CPU) |
| PP-StructureV3 | — | 0.557 | 0.857 | **0.300** | ~60 s (CPU) |

Raw reading. With pre-processing and then the adaptive policy, the ranking
flips: Chandra 0.967 (= ceiling), Hunyuan 0.953, PaddleOCR-VL 0.951 — see
[chandra_ocr2.md](chandra_ocr2.md) for the detail and the comparability
caveats on Hunyuan's pre-processed run.

**HunyuanOCR and PaddleOCR-VL are neck and neck** (0.928 against 0.909). The
gap is real but modest, and over 8 invoices it should not be
over-interpreted.

**PP-StructureV3 falls clearly behind**, and its error profile is different:
a TEDS / TEDS-Struct gap of 0.300, against 0.020 and 0.024 for the other
two. In other words it rebuilds the grid correctly (0.857) but reads
Vietnamese characters very badly. That is exactly the distinction
TEDS-Struct exists to draw, and it steers the diagnosis: for this model the
problem is the OCR, not table detection.

---

## 2. What multi-page merging brings

Each invoice is scored **twice against the same ground truth** (the complete
invoice): once with the first page's table alone — what a pipeline ignoring
the problem would produce — and once with the table reassembled by
`table_merge`.

| Model | TEDS without merging | TEDS with merging | Gain |
|---|---|---|---|
| HunyuanOCR-1.5 | 0.668 | 0.928 | **+0.260** |
| PaddleOCR-VL | 0.658 | 0.909 | **+0.251** |
| PP-StructureV3 | 0.424 | 0.557 | +0.132 |

The gain is **of the same order for all three models**, which is
reassuring: the merging algorithm is not calibrated on one particular model.

### Per-invoice detail (HunyuanOCR-1.5)

| Invoice | Pages | TEDS without | TEDS with | Gain | Struct with |
|---|---|---|---|---|---|
| 1 | 1–2 | 0.510 | 0.902 | +0.392 | 0.983 |
| 2 | 3–4 | 0.810 | 0.945 | +0.135 | 0.965 |
| 3 | 5–6 | 0.666 | 0.971 | +0.304 | 0.972 |
| 4 | 7–8 | 0.687 | 0.964 | +0.277 | 0.971 |
| 5 | 9–11 | 0.482 | 0.968 | **+0.486** | 0.972 |
| 6 | 12–13 | 0.862 | 0.947 | +0.086 | 0.969 |
| 7 | 14–15 | 0.572 | 0.972 | +0.400 | 0.976 |
| 8 | 16–17 | 0.759 | 0.759 | 0.000 | 0.783 |
| **Mean** | | **0.668** | **0.928** | **+0.260** | **0.949** |

Invoice 5 is the most telling case: it spans three pages, and merging takes
it from 0.482 to 0.968.

Invoice 8 is the only failure: the OCR extracted **no table at all** from
page 17, so there is nothing to merge. That is an upstream detection
failure, out of the algorithm's reach.

---

## 3. Quality of continuation detection

Evaluated page-pair by page-pair, against a ground truth read directly from
the source PDF (`Tiếp trang trước` markers) — and not from the OCR outputs,
which inspired the algorithm.

| Model | TP | FP | Misses | Precision | Recall | F1 |
|---|---|---|---|---|---|---|
| HunyuanOCR-1.5 | 7 | 0 | 0 | 100% | 100% | **100%** |
| PP-StructureV3 | 7 | 0 | 0 | 100% | 100% | **100%** |
| PaddleOCR-VL | 7 | 0 | 1 | 100% | 88% | 93% |

**Zero false positives in all three cases.** That is the most important
point: merging wrongly manufactures a table that mixes two invoices, an
error far more serious than a missed merge, and far harder to spot
downstream.

---

## Limitations to own

**Sample.** 8 invoices, 17 pages, a single generator, a single layout. The
figures establish that the chain works on real OCR noise — not that it
generalises to other invoice formats.

**Domain assumption.** The algorithm assumes the STT column restarts at 1 on
each invoice. That is the most discriminating signal, and the one that
rescues cases where the OCR mangled the end of the previous table. To be
re-validated on invoices in another format.

**Ground truth = the *logical* table.** Header, drug lines, Total line — not
the layout artifacts (banner, continuation markers, repeated headers). Those
artifacts are precisely what merging has to make disappear.

**Thousands separators neutralised.** The generator picks at random between
`2900`, `2 900`, `2.900` and `2,900`: a nuisance variable of the generator,
not a reading difficulty. `--strict-numbers` disables the normalisation.

**Times are not comparable.** HunyuanOCR runs on GPU, the other two on CPU.
The ~87 s against ~230 s do not measure the models' relative efficiency.

---

## One incident worth remembering

While bringing up HunyuanOCR, the model produced **6842 characters of
gibberish** (pinyin syllables, repeated dashes) without raising a single
error, in 315 s. The cause: the image processor used the torchvision
backend, which replaces LANCZOS resampling with BICUBIC and departs from the
original model's pre-processing. Fixed by forcing `backend="pil"`
(hard-coded in `scripts/bench_deformed.py`).

Without comparison against ground truth, that run would have produced a
perfectly computed TEDS score over absurd data. It is the most concrete
argument in favour of the whole evaluation apparatus.
