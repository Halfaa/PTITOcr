"""
From HTML table to typed fields.

The merged table produced by table_merge is still raw text: rows of cells.
Any downstream use -- and arithmetic validation in particular -- needs typed
objects:

    LineItem(index=1, name="Hydrocortisone 1%", unit="tuýp",
             quantity=1, unit_price=2900, total=2900)

Three real difficulties, systematically underestimated:

  1. column order is not guaranteed (OCR sometimes permutes it);
  2. numbers arrive in several formats: 2900, 2 900, 2.900, 2,900;
  3. some rows are not data: header, Total row, page-break markers.

Columns are therefore identified by their *content* rather than by their
position, reusing the header keywords already used by table_merge.
"""

from dataclasses import dataclass
import re

from table_merge import _fuzzy_eq, _normalize, _find_header_index  # noqa


# Keywords per column. Order within each list is irrelevant: we look for the
# best fuzzy match, which absorbs OCR noise ("so lugng" / "soluong" /
# "Số lượng").
COLUMN_KEYWORDS = {
    "index": ["stt", "so tt"],
    "name": ["ten mat hang/dich vu", "ten mat hang", "dich vu", "ten"],
    "unit": ["dvt", "don vi tinh"],
    "quantity": ["so luong", "sl"],
    "unit_price": ["don gia", "gia"],
    "total": ["thanh tien", "tong"],
}

# A row whose cells contain any of these closes the table.
TOTAL_KEYWORDS = ["tong tien", "tong cong", "total"]


@dataclass
class LineItem:
    index: int = None
    name: str = ""
    unit: str = ""
    quantity: int = None
    unit_price: int = None
    total: int = None
    raw: list = None       # original row, so we can trace back to the source

    def __repr__(self):
        return (f"LineItem({self.index}, {self.name!r}, q={self.quantity}, "
                f"up={self.unit_price}, tot={self.total})")


@dataclass
class Invoice:
    items: list
    grand_total: int = None
    columns: dict = None   # {field: column index} as detected


def parse_number(cell):
    """'2 900' / '2.900' / '2,900' / '2900' -> 2900. None if unreadable.

    Thousand separators vary from one invoice to the next (and sometimes
    within a single invoice, depending on what OCR read): we strip them all
    rather than trying to guess the convention.
    """
    if cell is None:
        return None
    digits = re.sub(r"[^\d]", "", str(cell))
    return int(digits) if digits else None


def detect_columns(header_row) -> dict:
    """Map each field to a column index by fuzzy-matching the label -- not by
    position, which OCR does not guarantee."""
    mapping = {}
    used = set()
    for field, keywords in COLUMN_KEYWORDS.items():
        best_idx, best_score = None, 0.0
        for i, cell in enumerate(header_row):
            if i in used:
                continue
            for kw in keywords:
                if _fuzzy_eq(kw, cell, threshold=0.7):
                    # A longer matching label is a more specific match
                    score = len(kw)
                    if score > best_score:
                        best_idx, best_score = i, score
        if best_idx is not None:
            mapping[field] = best_idx
            used.add(best_idx)
    return mapping


def _is_total_row(row) -> bool:
    joined = _normalize(" ".join(str(c) for c in row))
    return any(kw in joined for kw in TOTAL_KEYWORDS)


def parse_table(table) -> Invoice:
    """Table (merged or not) -> Invoice with typed line items."""
    header_idx = _find_header_index(table)
    header = table.rows[header_idx] if len(table.rows) > header_idx else []
    columns = detect_columns(header)

    def cell(row, field):
        i = columns.get(field)
        return row[i] if i is not None and i < len(row) else None

    items, grand_total = [], None

    for row in table.rows[header_idx + 1:]:
        if not row:
            continue
        if _is_total_row(row):
            # The grand total is the largest number on that row: the other
            # cells are empty or hold the label.
            numbers = [parse_number(c) for c in row]
            numbers = [n for n in numbers if n is not None]
            if numbers:
                grand_total = max(numbers)
            continue

        idx = parse_number(cell(row, "index"))
        qty = parse_number(cell(row, "quantity"))
        up = parse_number(cell(row, "unit_price"))
        tot = parse_number(cell(row, "total"))
        name = str(cell(row, "name") or "").strip()

        # A row with neither a name nor any amount is not a data row
        if not name and qty is None and up is None and tot is None:
            continue

        items.append(LineItem(
            index=idx, name=name,
            unit=str(cell(row, "unit") or "").strip(),
            quantity=qty, unit_price=up, total=tot, raw=list(row),
        ))

    return Invoice(items=items, grand_total=grand_total, columns=columns)
