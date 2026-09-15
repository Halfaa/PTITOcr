# Document index

Eighteen documents written over the course of the internship, in the order
the questions came up. This index says which one to read for which question,
and **which ones are out of date** — because a figure that was right when it
was written may have been re-measured since.

Three states:

- **current** — the figures and conclusions still hold
- **historical** — true at its date, superseded since; kept for the record
- **closed** — an avenue explored then closed, or a candidate dropped

---

## Where to start

| document | state | for which question |
|---|---|---|
| [`../dataset/README.md`](../dataset/README.md) | current | which image sets exist, and which ground truth to score them against |
| [`resultats_teds.md`](resultats_teds.md) | current | the headline figures: which model reads our invoices best |
| [`audit_pipeline.md`](audit_pipeline.md) | current | where the production chain can fail *silently* |
| [`etat_du_projet.md`](etat_du_projet.md) | **historical** | state as of 28 July (week 1) — useful as a starting point, no longer as a status |

---

## Models: candidates, predictions, licences

| document | state | contents |
|---|---|---|
| [`etat_de_lart_modeles.md`](etat_de_lart_modeles.md) | historical | July 2026 state of the art for VN+EN models with tables. **Caveat: HunyuanOCR appears there as a candidate, it has since been dropped** (Tencent licence, excludes the EU) |
| [`chandra_ocr2.md`](chandra_ocr2.md) | current | why measure Chandra, predictions written before measuring, OpenRAIL-M licence |
| [`glm_ocr.md`](glm_ocr.md) | **in progress** | the GLM-OCR bet (0.9 B, MIT). Still not measured: the first pass failed with OOM on our handwriting images, fix applied, re-run pending |
| [`summary_paddleocr_vl.md`](summary_paddleocr_vl.md) | historical | the very first benchmark, on the 10 TabRecSet images only |
| [`summary_ppstructure.md`](summary_ppstructure.md) | historical | same for PP-StructureV3 |
| [`notes_benchmark_tabrecset.md`](notes_benchmark_tabrecset.md) | current | how the TabRecSet mini-set was chosen (10 real images) |

---

## Measurement results

| document | state | contents |
|---|---|---|
| [`resultats_teds.md`](resultats_teds.md) | current | TEDS of the models on warped multi-page invoices |
| [`resultats_pretraitement.md`](resultats_pretraitement.md) | current | Phase 1 of the brief: localisation, perspective, lighting, denoising |
| [`avec_sans_pretraitement.md`](avec_sans_pretraitement.md) | current | the comparison asked for in the meeting: does pre-processing actually help |
| [`resultats_validation.md`](resultats_validation.md) | current | arithmetic validation: catching a reading error without ground truth |
| [`degradation.md`](degradation.md) | current | at what photo quality the chain breaks (24 steps) |
| [`resultats_handwriting.md`](resultats_handwriting.md) | current | handwriting HTR benchmark VN/EN: Chandra 95.5 / 99.1%, PaddleOCR-VL 78.2 / 90.3% |
| [`degradation_handwriting.md`](degradation_handwriting.md) | current | where Chandra breaks on handwriting: noise/exposure/JPEG cost nothing, blur and resolution break it — with a capture specification |
| [`notion_handwriting_results.md`](notion_handwriting_results.md) | current | the degradation results as a slide-style summary, ready to paste into Notion |
| [`notion_deformation_3d.md`](notion_deformation_3d.md) | current | 3D deformation: −35.7 points, why it is the worst failure mode, and why the figure is a lower bound |
| [`resultats_handwriting_en.md`](resultats_handwriting_en.md) | current | short standalone summary of the above, ready to send as is |

---

## Test sets: design and limitations

| document | state | contents |
|---|---|---|
| [`jeu_de_test_diversifie.md`](jeu_de_test_diversifie.md) | current | why 6 templates and 12 invoices rather than a single template |
| [`fonds_encombres.md`](fonds_encombres.md) | current | the project's largest document (18 sections): the distractor-sheet set, and **eleven cropping attempts that all fail**. §11, §16 and §18 are the conclusions; the rest is the path that leads there |

---

## Application

| document | state | contents |
|---|---|---|
| [`application.md`](application.md) | current | the API + PWA deliverable planned for weeks 11-12 |

---

## Caveats that cut across several documents

**HunyuanOCR is dropped.** Its Tencent community licence excludes the EU,
the United Kingdom and South Korea, and Kaggle does not let you choose the
machine's region. It nevertheless appears as a candidate, or as a table
column, in a dozen documents predating that decision
(`etat_du_projet.md`, `resultats_teds.md`, `resultats_pretraitement.md`,
`etat_de_lart_modeles.md`...). The figures there remain valid — they were
genuinely measured — but the model is no longer part of the roster.

**Cropping on a cluttered scene is a closed avenue.** Eleven families of
methods, an IoU ceiling that never exceeds 0.59 against a measured
achievable 0.85. Conclusion in §11, then §16-§18 of `fonds_encombres.md`:
the sheet's edge is *invisible* in our renders (white on white, with no
depth of field), and the right answer is not a better crop but a reader that
segments by itself — which PaddleOCR-VL already does.

**Renders predating the seed fix are not matched.**
`render_mesh_multipage.py` drew camera and lighting without seeding
`random`: two renders of the same set gave different views. Fixed since
(`random.seed(zlib.crc32(...))`), but any image-for-image comparison between
two sets rendered before that fix is invalid. Detail in
`fonds_encombres.md` §3.
