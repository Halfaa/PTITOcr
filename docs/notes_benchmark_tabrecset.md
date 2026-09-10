# Benchmark mini-dataset — table recognition

10 images taken from TabRecSet (full pages, with text/context around the
table, not pre-cropped tables), selected for their diversity: language,
border style, content type, and amount of surrounding text.

| # | File | Language | Border style | Content | Surrounding context |
|---|---------|--------|----------------|---------|------------------|
| 1 | `2istedsc.jpg` | EN | bordered | Textbook page (announcements + exercises) | A lot (2 exercises below the table) |
| 2 | `3046887202.jpg` | EN | borderless | Invoice/receipt (real photograph) | A lot (header, footer, payment) |
| 3 | `9558143260.jpg` | EN | bordered | List of election candidates, multi-section | A lot (title + several sub-tables) |
| 4 | `685642856.jpg` | EN | bordered | Lab worksheet (questions + table) | A lot (questions 1-3 before the table) |
| 5 | `table_spider_00416.jpg` | EN/FR | bordered | Nutrition label (product packaging) | Medium (bilingual text around it) |
| 6 | `7786418899_yjc.jpg` | ZH | bordered | Chemistry exam question + multiple choice | A lot (statement + choices) |
| 7 | `0_08ef...yf.jpg` | ZH | bordered | Maths exercise + questions | A lot |
| 8 | `7841115378_yf.jpg` | ZH | borderless | Maths exercise + multiple choice | A lot |
| 9 | `3876967706_ljh.jpg` | ZH | borderless | Workbook page (answers 20-30) | A lot (text-dense page) |
| 10 | `26_059a...hl.jpg` | ZH | borderless | Maths exam question, table with blanks | A lot |

## Structure

- `images/` — the 10 source images (full pages)
- `td_annotation/` — **detection** ground truth (localisation polygon of the table(s) in the page), LabelMe format
- `tsr_tcr_annotation/` — **structure + content** ground truth (cells, text), LabelMe format

Each annotation file carries the same base name as its image (`<name>.json`).

## Intended use

For each model under test (PaddleOCR-VL, PP-StructureV3, Chandra OCR, ...):
1. Run the model over the images in `images/`
2. Compare its detection against the polygon in `td_annotation/` (table localisation)
3. Compare its extracted structure/content against the cells in `tsr_tcr_annotation/`

Full source: TabRecSet (CurveTabSet), https://github.com/MaxKinny/TabRecSet
