# Handwriting HTR Benchmark — Chandra vs. PaddleOCR-VL

Comparison on two synthetic handwritten medical forms — a Vietnamese
rehabilitation record and an English periodic health examination record —
30 specimens per language, scored field by field against exact ground
truth.

| set | Chandra OCR 2 (5 B) | PaddleOCR-VL (0.9 B) |
|---|---|---|
| VN | **95.5%** (score 97.2) | 78.2% (score 84.8) |
| EN | **99.1%** (score 99.7) | 90.3% (score 97.5) |

Chandra clearly leads on both languages, consistent with the edge it
already showed on the clean-background invoice benchmark. The gap is wider
in Vietnamese: diacritics remain the hard part for both models, but
PaddleOCR-VL suffers visibly more from them.

## How the score is computed

For the score, I just compare the data extracted by the model against the
clean ground truth data, field by field, and check if each value shows up
in what the model read.
