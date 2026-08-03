"""
Merging of tables split across multiple pages.

Detects when a table extracted from page N is the continuation of a table
extracted from page N-1 (same invoice, medication table overflowing) and
merges them into a single logical table.

Works on PaddleOCR-VL / PP-StructureV3 / HunyuanOCR output (tables emitted as
<table>...</table> inside the markdown).

Principle: never rely on a single signal -- far too fragile under OCR noise.
The decision combines several independent signals:

  1. explicit continuation marker ("Tiep trang truoc" / "continued"), searched
     in the WHOLE page text rather than in the table alone -- in practice OCR
     emits that marker as a separate text block.
  2. index (STT) continuity: last row of A = N, first row of B = N+1
  3. same column count + similar headers
  4. no "Total" row at the end of table A (a table that ends normally is not
     split)

A strong signal (1 or 2) is sufficient on its own. Otherwise signal 3 is
required, and signal 4 must not contradict it.

--------------------------------------------------------------------------
Robustness to real OCR noise (observed on PP-StructureV3 output):

  * the first <table> row is NOT necessarily the header: OCR often inserts a
    spurious row there ("vien 3 200"). The header is therefore *searched* by
    keyword (STT / Ten mat hang / DVT / ...) rather than assumed.
  * cells are sometimes permuted: the STT index may end up in the last
    column. We therefore inspect both the first AND the last cell.
  * amounts (2900, 24000...) must never be mistaken for indices -> capped by
    _MAX_PLAUSIBLE_INDEX.
  * text comparisons are tolerant (difflib): "so luong" / "so lugng" /
    "soluong" must all match.
"""

from dataclasses import dataclass
from difflib import SequenceMatcher
from html.parser import HTMLParser
import re
import unicodedata


@dataclass
class Table:
    rows: list  # list of rows, each row a list of cell strings
    raw_html: str = ""

    @property
    def n_cols(self):
        return max((len(r) for r in self.rows), default=0)

    @property
    def header(self):
        idx = _find_header_index(self)
        return self.rows[idx] if len(self.rows) > idx else []

    @property
    def data_rows(self):
        return self.rows[_find_header_index(self) + 1:]


class _TableHTMLParser(HTMLParser):
    """Minimal HTML parser (stdlib only, no external dependency): extracts
    every <table> from a blob of text as Table() objects."""

    def __init__(self):
        super().__init__()
        self.tables = []
        self.spans = []          # (first_line, last_line) of each <table>
        self._current_start_line = 0
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._current_table_rows = None
        self._current_row = None
        self._current_cell_text = None
        self._current_table_html = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._in_table = True
            self._current_table_rows = []
            self._current_table_html = ["<table>"]
            self._current_start_line = self.getpos()[0]
            return
        if not self._in_table:
            return
        self._current_table_html.append(self._start_tag_str(tag, attrs))
        if tag == "tr":
            self._in_row = True
            self._current_row = []
        elif tag in ("td", "th"):
            self._in_cell = True
            self._current_cell_text = []

    @staticmethod
    def _start_tag_str(tag, attrs):
        attr_str = "".join(f' {k}="{v}"' for k, v in attrs)
        return f"<{tag}{attr_str}>"

    def handle_endtag(self, tag):
        if not self._in_table:
            return
        self._current_table_html.append(f"</{tag}>")
        if tag in ("td", "th") and self._in_cell:
            text = "".join(self._current_cell_text).strip()
            self._current_row.append(text)
            self._in_cell = False
        elif tag == "tr" and self._in_row:
            self._current_table_rows.append(self._current_row)
            self._in_row = False
        elif tag == "table":
            self.tables.append(Table(rows=self._current_table_rows,
                                     raw_html="".join(self._current_table_html)))
            self.spans.append((self._current_start_line, self.getpos()[0]))
            self._in_table = False

    def handle_data(self, data):
        if self._in_cell:
            self._current_cell_text.append(data)


_MD_SEPARATOR = re.compile(r"^:?-{2,}:?$")


def _split_pipe_row(line: str) -> list:
    """Split a Markdown table row into cells."""
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def _extract_markdown_tables(text: str, skip_lines: set) -> list:
    """Extract Markdown pipe tables as (first_line, Table) pairs.

    HunyuanOCR does not always answer in HTML: on some pages it renders the
    table as a Markdown pipe table instead. The content is complete and
    correct, but a parser that only looks for <table> discards it entirely --
    and, being a well-formed page with a plausible amount of text, nothing
    signals the loss. Two pages of the benchmark were being thrown away this
    way, which is also why their continuation could never be merged.

    skip_lines holds the lines already covered by an HTML <table>, so a pipe
    table nested inside HTML is not counted twice.
    """
    tables, block, start = [], [], None

    def flush():
        # A separator row (|---|---|) is Markdown syntax, not data.
        rows = [_split_pipe_row(l) for l in block
                if not all(_MD_SEPARATOR.match(c) for c in _split_pipe_row(l) if c != "")
                or not any(_split_pipe_row(l))]
        rows = [r for r in rows if any(c for c in r)]
        if len(rows) >= 2:
            width = max(len(r) for r in rows)
            html = ["<table>"]
            for row in rows:
                padded = row + [""] * (width - len(row))
                html.append("<tr>" + "".join(f"<td>{c}</td>" for c in padded) + "</tr>")
            html.append("</table>")
            tables.append((start, Table(rows=rows, raw_html="".join(html))))

    for number, line in enumerate(text.splitlines(), start=1):
        is_row = number not in skip_lines and line.count("|") >= 2 and "|" in line.strip()
        if is_row:
            if not block:
                start = number
            block.append(line)
        elif block:
            flush()
            block, start = [], None
    if block:
        flush()
    return tables


def extract_tables(markdown_or_html: str) -> list:
    """Return every Table() found in a text blob (markdown or raw HTML).

    Both notations are handled, and the tables come back in document order:
    merge_table_sequence() reasons about "the table before" and "the table
    after", so the ordering is part of the contract.
    """
    parser = _TableHTMLParser()
    parser.feed(markdown_or_html)

    skip = {n for first, last in parser.spans for n in range(first, last + 1)}
    found = [(first, table) for (first, _), table in zip(parser.spans, parser.tables)]
    found += _extract_markdown_tables(markdown_or_html, skip)
    return [table for _, table in sorted(found, key=lambda pair: pair[0])]


# --------------------------------------------------------------------------
# Normalisation / OCR-tolerant comparison
# --------------------------------------------------------------------------

# Vietnamese "đ" is a letter in its own right, not a "d" with a diacritic:
# NFKD leaves it untouched. Without this explicit mapping, "ĐVT" normalises
# to "đvt" and never matches the keyword "dvt" -- the unit column was
# silently dropped from every parsed invoice because of it.
_VN_LETTERS = str.maketrans({"đ": "d", "Đ": "d", "ð": "d", "Ð": "d"})


def _normalize(s) -> str:
    """Lowercase, strip diacritics, collapse whitespace."""
    s = str(s).lower().strip().translate(_VN_LETTERS)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s)


def _fuzzy_eq(a, b, threshold: float = 0.75) -> bool:
    """Tolerant equality: 'so luong' == 'so lugng' == 'soluong'.

    OCR routinely confuses u/g/y and swallows spaces; strict equality would
    reject headers that are in fact identical.
    """
    a, b = _normalize(a), _normalize(b)
    if not a or not b:
        return False
    if a == b or a.replace(" ", "") == b.replace(" ", ""):
        return True
    return SequenceMatcher(None, a, b).ratio() >= threshold


# Header keywords of the medication table (Vietnamese invoice).
_HEADER_KEYWORDS = [
    "stt", "ten mat hang", "dich vu", "dvt",
    "so luong", "don gia", "thanh tien",
]
# How far B's first index may sit from the one A's row count predicts. A few
# units absorb a row duplicated or dropped at the page break; tens of units
# mean a different document. Measured continuations land within [-3, 0],
# the measured false merge at +48.
_MAX_INDEX_OFFSET = 5

_CONTINUATION_KEYWORDS = ["tiep trang truoc", "suite", "continued", "tiep theo"]
_END_KEYWORDS = ["tong tien", "total", "grand total", "tong cong"]
_NEXT_PAGE_KEYWORDS = ["xem tiep trang sau", "continued on next page", "suite page suivante"]

# A plausible STT index stays small. Without this cap, a misplaced amount
# (2900, 24000...) would be mistaken for a row number.
_MAX_PLAUSIBLE_INDEX = 200


def _row_contains_any(row, keywords) -> bool:
    joined = _normalize(" ".join(str(c) for c in row))
    return any(kw in joined for kw in keywords)


def _text_contains_any(text: str, keywords) -> bool:
    """Search keywords in free text (the full markdown of one page).
    HTML tags are stripped first to avoid false positives."""
    if not text:
        return False
    plain = _normalize(re.sub(r"<[^>]+>", " ", text))
    return any(kw in plain for kw in keywords)


# --------------------------------------------------------------------------
# Header row detection
# --------------------------------------------------------------------------

def _header_score(row) -> int:
    """How many header keywords appear in this row."""
    if not row:
        return 0
    return sum(1 for kw in _HEADER_KEYWORDS
               if any(_fuzzy_eq(kw, cell) for cell in row))


def _find_header_index(table: "Table", search_depth: int = 4) -> int:
    """Index of the REAL header row.

    OCR frequently inserts a spurious row before the header (a fragment of
    page text captured inside the table), and the continuation marker may
    also occupy row 0. So we look among the first few rows for the one that
    looks most like a header.
    """
    rows = table.rows
    if not rows:
        return 0

    best_idx, best_score = 0, 0
    for i, row in enumerate(rows[:search_depth]):
        score = _header_score(row)
        if score > best_score:
            best_idx, best_score = i, score

    if best_score >= 2:
        return best_idx

    # Fallback: at the very least, skip a continuation-marker row.
    if _row_contains_any(rows[0], _CONTINUATION_KEYWORDS) and len(rows) > 1:
        return 1
    return 0


def _header_similarity(h1, h2) -> float:
    """0.0 to 1.0. SET-based comparison (not column by column) because OCR
    sometimes permutes columns: two identical headers may show up in a
    different order."""
    if not h1 or not h2:
        return 0.0
    matches = sum(1 for c in h1 if any(_fuzzy_eq(c, d) for d in h2))
    return matches / len(h1)


# --------------------------------------------------------------------------
# Index (STT) column detection
# --------------------------------------------------------------------------

def _numeric_index(cell):
    cell = str(cell).strip()
    if not cell.isdigit():
        return None
    value = int(cell)
    return value if 0 < value <= _MAX_PLAUSIBLE_INDEX else None


def _row_index_candidates(row):
    """Values that could be this row's STT index.

    We look at the first AND the last cell: OCR sometimes shifts the STT
    column to the end of the row (observed on PP-StructureV3 output)."""
    if not row:
        return []
    cells = [row[0]] if len(row) == 1 else [row[0], row[-1]]
    return [v for v in (_numeric_index(c) for c in cells) if v is not None]


def _index_sequence(table: "Table"):
    """Sequence of STT indices across data rows (missing values skipped).

    When a row offers two candidates (index in first and in last position),
    we keep the one that continues the sequence built so far."""
    seq = []
    for row in table.data_rows:
        candidates = _row_index_candidates(row)
        if not candidates:
            continue
        previous = seq[-1] if seq else None
        if previous is not None and previous + 1 in candidates:
            seq.append(previous + 1)
        else:
            seq.append(candidates[0])
    return seq


def _last_data_index(table: "Table"):
    """Largest index in the table -- not the last one in the sequence: a
    single noisy row at the end (permuted cells, quantity read in place of
    the STT) would otherwise wreck the signal entirely."""
    seq = _index_sequence(table)
    return max(seq) if seq else None


def _first_data_index(table: "Table"):
    """First index encountered -- here we deliberately keep the raw first
    value: it is what tells us whether the table *restarts at 1* (new
    invoice) or resumes mid-numbering (continuation)."""
    seq = _index_sequence(table)
    return seq[0] if seq else None


# --------------------------------------------------------------------------
# Decision
# --------------------------------------------------------------------------

def is_continuation(table_a: Table, table_b: Table,
                    page_text_a: str = "", page_text_b: str = "",
                    min_header_similarity: float = 0.6) -> dict:
    """
    Decide whether table_b continues table_a. Returns a dict holding the
    decision AND every individual signal -- useful for debugging and, in a
    research context, essential to be able to explain why a merge did (or
    did not) happen.

    page_text_a / page_text_b: full markdown of the corresponding pages.
    The "continued on next page" / "continued from previous page" markers are
    almost always extracted OUTSIDE the table -- looking for them only in
    table rows misses them systematically.
    """
    signals = {}

    signals["same_col_count"] = table_a.n_cols == table_b.n_cols and table_a.n_cols > 0

    a_rows = table_a.data_rows
    signals["table_a_ends_with_total"] = (
        (bool(a_rows) and _row_contains_any(a_rows[-1], _END_KEYWORDS))
        or _text_contains_any(page_text_a, _END_KEYWORDS)
    )
    signals["table_a_has_next_page_marker"] = (
        (bool(a_rows) and _row_contains_any(a_rows[-1], _NEXT_PAGE_KEYWORDS))
        or _text_contains_any(page_text_a, _NEXT_PAGE_KEYWORDS)
    )
    signals["table_b_has_continuation_marker"] = (
        (bool(table_b.rows) and _row_contains_any(table_b.rows[0], _CONTINUATION_KEYWORDS))
        or _text_contains_any(page_text_b, _CONTINUATION_KEYWORDS)
    )

    signals["header_similarity"] = _header_similarity(table_a.header, table_b.header)

    last_idx_a = _last_data_index(table_a)
    first_idx_a = _first_data_index(table_a)
    first_idx_b = _first_data_index(table_b)
    signals["last_index_a"] = last_idx_a
    signals["first_index_b"] = first_idx_b
    signals["index_continuity"] = (
        last_idx_a is not None and first_idx_b is not None and first_idx_b == last_idx_a + 1
    )
    # Tolerance: OCR sometimes drops a whole row at the page boundary. A gap
    # of 1 to 3 is still compatible with a continuation, whereas going
    # backwards is not.
    signals["index_near_continuity"] = (
        last_idx_a is not None and first_idx_b is not None
        and 0 < first_idx_b - last_idx_a <= 3
    )
    # Disqualifier: if table_b restarts at 1 it is almost certainly a NEW
    # table (new invoice), even when the headers match -- every invoice from
    # this generator shares the same column template, so header similarity
    # alone can never tell "continuation" from "another identical-looking
    # invoice" apart.
    signals["table_b_restarts_at_1"] = first_idx_b == 1
    # Mirror image of the above: if B starts at an index > 1, its numbering
    # comes from somewhere. This is the signal that rescues the cases where
    # OCR mangled the end of table A -- +1 continuity is then unverifiable,
    # but "B starts at 20" still speaks for itself.
    #
    # It must stay a RESCUE, though. Unqualified, "B starts above 1" also
    # describes two distinct invoices in a document numbered continuously.
    # Measured on the warped test set: OCR lost page 16 entirely, so the
    # algorithm compared page 15 (ending at 21) with page 17 (starting at
    # 70) -- a jump of 49 -- and merged two different invoices.
    #
    # The check compares B's first index with the one A's SIZE predicts, not
    # with the last index actually read in A. That distinction is the whole
    # point: when the OCR mangles the end of A its last index is wrong, but
    # the number of rows survives. Measured on the three real cases:
    #
    #     A ends read at 7,  B starts at 17   raw +10   predicted -1   continuation
    #     A ends read at 12, B starts at 20   raw  +8   predicted -1   continuation
    #     A ends read at 21, B starts at 70   raw +49   predicted +48  two invoices
    #
    # The raw gap mixes the three together; the predicted one separates them
    # cleanly. Falls back to firing when A's numbering is unreadable, since
    # that is the situation this signal exists to rescue.
    _predicted_next = (first_idx_a + len(table_a.data_rows)
                       if first_idx_a is not None else None)
    _offset = (first_idx_b - _predicted_next
               if (first_idx_b is not None and _predicted_next is not None) else None)
    signals["index_offset"] = _offset
    signals["table_b_starts_mid_numbering"] = (
        first_idx_b is not None and first_idx_b > 1
        and (_offset is None or abs(_offset) <= _MAX_INDEX_OFFSET)
    )
    # "Same table" guard: requiring a strictly identical column count is too
    # harsh, OCR regularly adds or loses a column from one page to the next.
    # A sufficiently similar header does the job just as well.
    signals["compatible_shape"] = signals["same_col_count"] or signals["header_similarity"] >= 0.5

    strong_signal = (
        signals["table_b_has_continuation_marker"]
        or signals["index_continuity"]
        or (signals["index_near_continuity"] and signals["compatible_shape"])
        or (signals["table_b_starts_mid_numbering"]
            and signals["compatible_shape"]
            and not signals["table_a_ends_with_total"])
    )
    weak_signal = (
        signals["same_col_count"]
        and signals["header_similarity"] >= min_header_similarity
        and not signals["table_a_ends_with_total"]
        and (signals["table_a_has_next_page_marker"] or last_idx_a is None or first_idx_b is None)
        and not signals["table_b_restarts_at_1"]
    )

    # Two vetoes, and both say the same thing: the document itself states
    # that the previous table is finished.
    #
    #   restarting at 1     a new numbering is a new document
    #   ending on a total   "Tong tien" closes an invoice; the template only
    #                       prints it on the last page, so anything after it
    #                       belongs to something else
    #
    # The total was already one term among several in strong_signal, but
    # index_continuity fired on its own and overrode it. That is only safe
    # while the STT restarts at 1 in every invoice -- the assumption of our
    # single template. On a format numbering continuously across invoices,
    # invoice N ending at 32 and invoice N+1 starting at 33 looked exactly
    # like a continuation, and two distinct invoices were merged into one.
    # A wrong merge is the worst failure available here: it fabricates a
    # table mixing two documents, and nothing downstream can detect it.
    #
    # A continuation marker on B overrides both vetoes, because it is the
    # document asserting the continuation explicitly rather than us
    # inferring it.
    closed_by_document = (signals["table_b_restarts_at_1"]
                          or signals["table_a_ends_with_total"])
    disqualified = closed_by_document and not signals["table_b_has_continuation_marker"]
    signals["decision"] = bool(strong_signal or weak_signal) and not disqualified
    signals["confidence"] = "strong" if strong_signal else ("weak" if weak_signal else "none")
    return signals


def merge_tables(table_a: Table, table_b: Table, decision: dict = None) -> Table:
    """Append table_b to table_a, dropping the continuation marker row and
    the repeated header, keeping a single header."""
    merged_rows = list(table_a.rows)

    # If A's last row is a "see next page" marker (rather than actual data),
    # drop it from the merge.
    if merged_rows and _row_contains_any(merged_rows[-1], _NEXT_PAGE_KEYWORDS):
        merged_rows = merged_rows[:-1]

    # From table_b we keep only data rows: everything before its header
    # (OCR noise, continuation marker) and the header itself are artefacts of
    # the page break.
    merged_rows.extend(table_b.data_rows)
    return Table(rows=merged_rows)


def merge_table_sequence(tables: list, page_texts: list = None,
                         min_header_similarity: float = 0.6):
    """
    Take a list of Table() (one per page, in order) and return the merged
    list: each element is either a table that continues nowhere, or the
    result of merging several consecutive pages. Also returns the detail of
    every decision taken.

    page_texts: full markdown of each page, same order as `tables` (optional
    but strongly recommended, see is_continuation).
    """
    if not tables:
        return [], []

    texts = list(page_texts) if page_texts else [""] * len(tables)
    merged = [tables[0]]
    # Text of the last page of the current group: that is the one carrying
    # any "continued on next page" marker.
    current_text = texts[0]
    decisions = []

    for t, text in zip(tables[1:], texts[1:]):
        decision = is_continuation(merged[-1], t, current_text, text, min_header_similarity)
        decisions.append(decision)
        if decision["decision"]:
            merged[-1] = merge_tables(merged[-1], t, decision)
        else:
            merged.append(t)
        current_text = text

    return merged, decisions
