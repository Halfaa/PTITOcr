"""
Adaptive extraction: read the page twice, keep what holds up.

Pre-processing improves table extraction and degrades header detection --
measured on both models, and no setting made the trade-off go away. Rather
than pick a side, this module reads each photograph in two variants (raw and
pre-processed) and decides per component which reading to keep.

The decision costs no ground truth, which is what makes it usable in
production. An invoice is arithmetically redundant: every line satisfies
quantity x unit_price = total, and the lines sum to the declared grand total.
An extraction that balances is very unlikely to be wrong; one that does not
has been caught. That is the same redundancy already used by
invoice_validate.py to flag lines for review -- here it is used to rank two
candidate readings.

Measured against the exact ground truth (which the policy never sees):

    PaddleOCR-VL    raw 0.909 TEDS, 22/32 fields
                    pre-processed 0.951, 14/32
                    adaptive 0.951, 24/32      ceiling 0.955

    HunyuanOCR-1.5  raw 0.950 TEDS, 25/32 fields
                    pre-processed 0.973, 25/32
                    adaptive 0.974, 28/32      ceiling 0.976

The adaptive policy beats BOTH single variants on BOTH metrics, and lands
within 0.004 of the best achievable choice.

Cost: one extra inference per page -- about 20 s on a T4. Nothing else in the
pipeline changes; the merge and the export take the chosen table as they
would any other.
"""

from dataclasses import dataclass, field
from typing import Optional

from invoice_fields import extract_fields
from invoice_parse import parse_table
from invoice_validate import check_invoice

# Fields the internship subject names explicitly. Order matters: it is the
# order in which sources are consulted, not a ranking of importance.
HEADER_FIELDS = ("hospital_name", "customer_name", "invoice_date", "doctor")


@dataclass
class Confidence:
    """How much an extraction agrees with itself, on a 0..1 scale."""

    score: float
    n_lines: int = 0
    n_consistent: int = 0
    total_ok: Optional[bool] = None
    n_gaps: int = 0
    index_available: bool = False

    def __str__(self):
        if not self.n_lines:
            return "no usable table"
        numbering = (f"{self.n_gaps} numbering gap(s)" if self.index_available
                     else "numbering unreadable")
        return (f"{self.score:.2f} "
                f"({self.n_consistent}/{self.n_lines} lines balance, "
                f"total {'ok' if self.total_ok else 'off'}, {numbering})")


# Weights. Deliberately not tuned: line consistency carries the most because
# it is an average over many independent checks, the grand total is a single
# check on the same data, and numbering continuity catches what arithmetic
# cannot -- a row the OCR dropped entirely still leaves the survivors
# balancing.
W_LINES, W_TOTAL, W_GAPS = 0.60, 0.25, 0.15


def confidence(table) -> Confidence:
    """Score an extracted table WITHOUT ground truth."""
    if table is None:
        return Confidence(0.0)
    invoice = parse_table(table)
    if not invoice.items:
        return Confidence(0.0)

    result = check_invoice(invoice)
    n = result["n_lines"]
    consistent = result["n_ok"] + result["n_corrected"]

    # Absence de preuve n'est pas preuve : un signal illisible ne rapporte
    # rien, il ne coute rien non plus. Le total suivait deja cette regle ;
    # la numerotation, non -- une colonne STT detruite valait le bonus plein
    # « aucun trou », si bien qu'abimer la lecture faisait MONTER la note
    # (0,600 -> 0,750 sur un tableau ou le trou est reel).
    #
    # On ne renormalise surtout pas les poids sur les signaux disponibles :
    # ca reviendrait a recompenser la perte d'information encore plus fort.
    score = (W_LINES * (consistent / n if n else 0.0)
             + W_TOTAL * (1.0 if result["total_ok"] else 0.0)
             + W_GAPS * (1.0 if (result["index_available"]
                                 and not result["index_gaps"]) else 0.0))

    return Confidence(score, n, consistent, result["total_ok"],
                      len(result["index_gaps"]),
                      result["index_available"])


@dataclass
class Choice:
    """What the policy kept, and why."""

    table: object = None
    table_source: str = ""
    fields: dict = field(default_factory=dict)
    field_sources: dict = field(default_factory=dict)
    confidences: dict = field(default_factory=dict)


def choose(candidates, prefer_table="preprocessed",
           field_order=("raw", "preprocessed")):
    """Pick the best table and the best value for each header field.

    `candidates` maps a source name to (table, page_texts):

        {"raw": (table_a, [md_page1, md_page2]),
         "preprocessed": (table_b, [...])}

    Two independent decisions, because the two components fail
    independently:

    TABLE -- highest confidence wins. On a tie, `prefer_table` breaks it:
    when both readings balance perfectly the arithmetic can no longer
    separate them, and falling back to the variant that is better on average
    is the honest thing to do. Measured: ties happen on half the invoices,
    and breaking them toward the pre-processed reading is worth +0.010 TEDS.

    HEADER FIELDS -- first non-empty value in `field_order`. There is no
    arithmetic to check a patient name against, so redundancy cannot rank
    these; what the measurements DO establish is that the raw image is more
    reliable for them (8/8 hospital names against 5/8). A field missing from
    the first source is taken from the second, which is where the gain comes
    from: 24/32 against 22 and 14 for the single variants.
    """
    result = Choice()

    for name, (table, _) in candidates.items():
        result.confidences[name] = confidence(table)

    best = max(result.confidences.items(),
               key=lambda kv: (kv[1].score, kv[0] == prefer_table))
    result.table_source = best[0]
    result.table = candidates[best[0]][0]

    for name in HEADER_FIELDS:
        for source in field_order:
            if source not in candidates:
                continue
            for text in candidates[source][1]:
                value = extract_fields(text).get(name)
                if value:
                    result.fields[name] = value
                    result.field_sources[name] = source
                    break
            if name in result.fields:
                break
        result.fields.setdefault(name, None)

    return result
