# Benchmark Summary — PaddleOCR-VL-0.9B

**Setup:** 10-image mini-dataset from TabRecSet (full-page images with tables + surrounding text/context, not pre-cropped). Single unified VLM pipeline (NaViT encoder + ERNIE-4.5-0.3B), generates table structure directly as HTML.

**Speed:** ~2316.7s total (~38.6 min), ~232s/image average. Slow — full VLM generation per image.

**Accuracy:** 8/10 tables correctly extracted with proper `<table>` structure and accurate content.

**Failures (2/10):** Both on borderless ("no-line") Chinese tables — output degraded to flat, unstructured text with no `<table>` tag. Inconsistent though: a third borderless Chinese table was extracted correctly, so this isn't a systematic borderless-table failure.

**Strengths:**
- Correctly split a complex multi-section table (election candidate list) into 4 clean sub-tables, preserving section headers separately.
- Fluent, coherent surrounding text generation (no word-merging or spacing artifacts).
- Handled colspan/merged cells well (e.g., nutrition label with merged rows).

**Weaknesses:**
- Very slow relative to a modular pipeline.
- Occasional character confusion in generated text (e.g., "g" misread as "9" in a unit context).
- Struggled on a physically overlapping/degraded photo (expected given source quality).

**Bottom line:** Best structural accuracy in this sample, especially on complex/irregular layouts, at a significant speed cost.
