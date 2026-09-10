# Arithmetic validation — results

An invoice is massively redundant, and that redundancy is exploitable
**without ground truth**:

```
quantity x unit_price = line_total      (one constraint per line)
sum of line totals = Tổng tiền          (one global constraint)
```

That is what sets this measurement apart from TEDS: TEDS says *how good* the
extraction is, but assumes the answer is known. Arithmetic validation works
in production, on invoices whose contents nobody knows.

To reproduce:

```powershell
python src\eval_validation.py --run multipage_hunyuan
```

---

## 1. Detecting numeric errors

Over 8 invoices. "Flagged" = line handed back to a human reviewer.

| Model | Lines | Wrong | Detected | Recall | False alarms |
|---|---|---|---|---|---|
| **HunyuanOCR-1.5** | 215 | 12 | 12 | **100%** | **0** |
| PaddleOCR-VL | 215 | 4 | 2 | 50% | 0 |
| PP-StructureV3 | 185 | 127 | 95 | 75% | 0 |

**No false alarms, with any of the three models.** Every flagged line was
genuinely wrong. That is what makes the mechanism usable: the reviewer does
not waste time on correct lines, so they will keep trusting the signal.

**The actionable result**: with HunyuanOCR, out of 215 lines, **12 need
review — 6% — and they contain 100% of the numeric errors**. We move from
"TEDS 0.928, so roughly 7% of cells are wrong somewhere" to "here are the
twelve lines to check".

---

## 2. Automatic correction

When only one of the three values is missing, it can be deduced from the
other two.

| Model | Corrections | Exact | Rate |
|---|---|---|---|
| PaddleOCR-VL | 68 | 66 | **97%** |
| PP-StructureV3 | 35 | 3 | **9%** |
| HunyuanOCR-1.5 | 0 | — | — |

This table carries the most important lesson, and it is counter-intuitive.

**PaddleOCR-VL frequently loses the unit-price column**, but keeps quantity
and total right: deduction recovers the value in 97% of cases. Its 70 wrong
lines drop to 4 that way. Automatic correction is a considerable gain here,
almost free.

**With PP-StructureV3, the same mechanism is a trap**: its outputs are so
degraded that the two remaining values are often wrong too. A third wrong
value then gets deduced — and, worse, the line becomes arithmetically
consistent, so **it stops being flagged**. Correction turns a visible error
into an invisible one.

**Design consequence**: never correct automatically without conditioning the
correction on the document's overall quality. A threshold on the invoice's
share of consistent lines would be enough to disable correction when the
model falls apart.

---

## 3. What arithmetic cannot see

| Model | Lines with a misread name |
|---|---|
| HunyuanOCR-1.5 | 12 / 215 (6%) |
| PaddleOCR-VL | 15 / 215 (7%) |
| PP-StructureV3 | 76 / 185 (41%) |

Examples: "Xetoprofen 250mg" for *Ketoprofen*, "Anoxicillin 500mg" for
*Amoxicillin*, "Effectivitan 500mg" for *Efferalgan*.

These errors are out of arithmetic's reach **by construction**, not through
some implementation gap: nothing in the invoice reveals that "Xetoprofen"
should have read "Ketoprofen". All three numbers on the line can be
perfectly correct.

Catching them would require an outside source of information — a **drug
dictionary**, with fuzzy matching on names. That is a distinct and
complementary avenue: arithmetic covers the numbers, a dictionary would
cover the labels. Together they would cover most of an invoice's content.

---

## What this changes for the conclusion

Before, we could say: "extraction reaches 0.928 TEDS". That is a good score,
but it does not say whether the remaining 7% of errors are findable — and on
medical invoices, that is precisely the question that decides usability.

Now we can say: **numeric errors are entirely detectable without ground
truth, at the cost of reviewing 6% of the lines, and with no false alarms at
all.** What remains are label errors, which call for a dictionary.

## Limitations

Same sample as the rest: 8 invoices, a single template. Validation also
assumes the invoice really does have the three columns quantity / unit price
/ total — true for this format, to be checked elsewhere.

PaddleOCR-VL's 97% exact-correction rate rests on one particular failure
mode (losing a whole column). Nothing guarantees it recurs on other
documents.
