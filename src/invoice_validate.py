"""
Arithmetic validation of extracted invoices.

An invoice is massively redundant, and that redundancy is exploitable
WITHOUT ground truth -- which is what makes it usable in production, where a
TEDS score is not:

    quantity x unit_price = line_total       (one constraint per line)
    sum of line totals = Tong tien           (one global constraint)

Two distinct uses:

  * DETECTION: a line that does not add up contains at least one wrong cell.
    Only those lines are handed to a human reviewer, instead of making them
    re-read the whole invoice.

  * CORRECTION: if two values out of three are right, the third one follows.
    But you still need to know WHICH one is wrong -- the equation alone does
    not say. We therefore only correct when exactly one value is missing, and
    merely flag when all three are present but inconsistent.

This module is not only a measurement tool: it is the piece that would make a
TEDS of 0.93 usable in a real application.
"""

from dataclasses import dataclass


@dataclass
class LineCheck:
    item: object
    status: str          # "ok" | "inconsistent" | "incomplete" | "corrected"
    detail: str = ""
    corrected_field: str = None
    corrected_value: int = None

    @property
    def is_suspect(self):
        return self.status in ("inconsistent", "incomplete")


def check_line(item) -> LineCheck:
    """Check quantity x unit_price = total on a single line."""
    q, up, tot = item.quantity, item.unit_price, item.total
    present = [v is not None for v in (q, up, tot)]

    if all(present):
        if q * up == tot:
            return LineCheck(item, "ok")
        return LineCheck(
            item, "inconsistent",
            f"{q} x {up} = {q * up}, but the line says {tot}")

    # Exactly one value missing: it follows from the other two.
    if sum(present) == 2:
        if tot is None:
            return LineCheck(item, "corrected", f"total inferred: {q} x {up}",
                             "total", q * up)
        if up is None and q:
            if tot % q == 0:
                return LineCheck(item, "corrected",
                                 f"unit price inferred: {tot} / {q}",
                                 "unit_price", tot // q)
            return LineCheck(item, "inconsistent",
                             f"{tot} is not divisible by {q}")
        if q is None and up:
            if tot % up == 0:
                return LineCheck(item, "corrected",
                                 f"quantity inferred: {tot} / {up}",
                                 "quantity", tot // up)
            return LineCheck(item, "inconsistent",
                             f"{tot} is not divisible by {up}")

    return LineCheck(item, "incomplete",
                     "too many missing values to verify")


def check_invoice(invoice) -> dict:
    """Check every line, then the grand total."""
    checks = [check_line(it) for it in invoice.items]

    # Grand total: use corrected values where available
    line_totals = []
    for c in checks:
        value = c.corrected_value if c.corrected_field == "total" else c.item.total
        if value is not None:
            line_totals.append(value)

    computed = sum(line_totals) if line_totals else None
    declared = invoice.grand_total
    if computed is not None and declared is not None:
        total_ok = computed == declared
        total_detail = (f"sum of lines = {computed}, "
                        f"Tong tien read = {declared}")
    else:
        total_ok = None
        total_detail = "grand total missing or unreadable"

    # Numbering continuity: a gap flags a row lost by OCR, which no
    # arithmetic check can recover.
    indices = [it.index for it in invoice.items if it.index is not None]
    gaps = []
    for a, b in zip(indices, indices[1:]):
        if b != a + 1:
            gaps.append((a, b))

    # "Aucun trou" et "on ne peut pas savoir" ne sont PAS la meme chose, et
    # les confondre a une consequence mesurable.
    #
    # Quand l'OCR abime l'en-tete au point que la colonne STT n'est plus
    # reconnue, `indices` est vide, `gaps` aussi -- et tout le monde en aval
    # lit "numerotation continue". Mesure sur un tableau construit a la main,
    # avec un trou reel : STT lisible -> confiance 0,600 ; le MEME tableau
    # avec l'en-tete STT illisible -> 0,750. Abimer la lecture faisait monter
    # la note. La politique adaptative s'en trouvait biaisee en faveur de la
    # variante qui detruit l'en-tete, c'est-a-dire exactement le defaut connu
    # du pretraitement.
    #
    # Il faut deux indices lisibles au minimum : avec un seul, il n'existe
    # aucune paire consecutive a examiner, donc aucune preuve de continuite.
    index_available = len(indices) >= 2

    return {
        "checks": checks,
        "n_lines": len(checks),
        "n_ok": sum(1 for c in checks if c.status == "ok"),
        "n_suspect": sum(1 for c in checks if c.is_suspect),
        "n_corrected": sum(1 for c in checks if c.status == "corrected"),
        "total_ok": total_ok,
        "total_detail": total_detail,
        "index_gaps": gaps,
        "index_available": index_available,
        "n_indices_read": len(indices),
    }


def suspect_lines(result):
    """The lines that need human review."""
    return [c for c in result["checks"] if c.is_suspect]
