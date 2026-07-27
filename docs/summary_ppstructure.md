# Benchmark Summary — PP-StructureV3

**Setup:** Same 10-image TabRecSet mini-dataset as the PaddleOCR-VL run. Modular pipeline: PP-DocLayout_plus-L (layout) → PP-OCRv5 (text) → SLANeXt/SLANet_plus (table structure, with dedicated wired/wireless weights).

**Speed:** ~494.7s total (~8.2 min), ~49.5s/image average. About **4.7x faster** than PaddleOCR-VL.

**Accuracy:** Only ~5-6/10 tables correctly structured — lower than PaddleOCR-VL on this sample.

**Failures (4/10):** No `<table>` tag generated, output collapsed to flat/run-on text —
- The same 2 borderless Chinese tables PaddleOCR-VL also failed on.
- One additional borderless Chinese table PaddleOCR-VL had actually gotten right (a regression).
- A nutrition label PaddleOCR-VL extracted cleanly — here it collapsed into garbled text with visible reading-order scrambling.

**Weaknesses:**
- Zero success (0/3) on borderless Chinese tables in this sample, despite SLANeXt's dedicated wired/wireless weights — didn't resolve the hypothesis that specialized weights would help.
- Paragraph text sometimes loses spacing/merges words (e.g., "DeSarasdiet..." instead of "Does Sara's diet...").
- A complex multi-section table (election list) had header fragments corrupted into a stray merged cell — messier than PaddleOCR-VL's clean split.

**Strengths:**
- Much faster, suitable for high-volume processing.
- Slightly better digit/unit disambiguation in one case (correctly read "22.5g" where PaddleOCR-VL read "22.59").

**Bottom line:** Clear speed advantage, but less robust table detection/structure on this sample — consistent with the OmniDocBench chart showing PaddleOCR-VL ahead on Table TEDS specifically.
