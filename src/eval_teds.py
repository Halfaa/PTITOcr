"""
TEDS evaluation of OCR output on multi-page invoices.

Answers two distinct questions:

  1. How good is the model's extraction (TEDS / TEDS-Struct)?
  2. What does the multi-page merging step actually bring?

For (2), every invoice is scored TWICE against the same ground truth (the
complete invoice):
    - "without merging": only the first page's table is kept, as a pipeline
      ignoring the multi-page problem would do;
    - "with merging": the table reconstructed by table_merge is scored.
The gap between the two quantifies exactly what the algorithm contributes.

Usage:
    python src/eval_teds.py --run multipage_ppstructure
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_check import require as _require_env
_require_env("eval")


import argparse
import json
import re

from table_merge import extract_tables, merge_table_sequence  # noqa: E402
from teds import teds, rows_to_html  # noqa: E402

GEN_DIR = Path("..") / "synthetic_invoice_generator" / "hospital_pharmacy"
DEFAULT_PDF = GEN_DIR / "invoices_multipage_xelatex.pdf"
DEFAULT_GT = GEN_DIR / "ground_truth_labels_multipage"

HEADER = ["STT", "Tên mặt hàng/Dịch vụ", "ĐVT", "Số lượng", "Đơn giá", "Thành tiền"]


def natural_sort_key(path: Path):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", path.name)]


def page_number(name: str):
    m = re.search(r"page_(\d+)", name)
    return int(m.group(1)) if m else None


def normalize_number(cell: str) -> str:
    """Strip thousand separators.

    The generator picks at random, per invoice, between '2900', '2 900',
    '2.900' and '2,900'. That choice is a nuisance variable of the generator,
    not a reading difficulty: we cancel it on both sides so as not to
    penalise a model that read the amount perfectly.
    """
    text = str(cell).strip()
    stripped = re.sub(r"[.,\s]", "", text)
    return stripped if stripped.isdigit() else text


def normalize_rows(rows, enabled=True):
    if not enabled:
        return rows
    return [[normalize_number(c) for c in row] for row in rows]


# --------------------------------------------------------------------------
# Ground truth
# --------------------------------------------------------------------------

def ground_truth_rows(invoice: dict) -> list:
    """The expected logical table: header + medication rows + total.

    Layout artefacts (title banner, '-- Tiep trang truoc --' markers,
    repeated headers) are deliberately excluded: they are precisely what the
    merging step must remove. Including them would grade the algorithm on its
    ability to reproduce a page break, when the goal is to make it disappear.
    """
    rows = [list(HEADER)]
    for i, med in enumerate(invoice["medications"], start=1):
        rows.append([
            str(i), med["name"], med["dosage_form"],
            str(med["quantity"]), str(med["unit_price"]), str(med["total_price"]),
        ])
    rows.append(["Tổng tiền:", "", "", "", "", str(invoice["total_amount"])])
    return rows


# A line printed once per invoice, in the header block only -- never on a
# continuation page. It is the most reliable "a new invoice starts here"
# marker available in the PDF.
_INVOICE_HEADER = "Điện thoại: 02"


def page_groups_from_pdf(pdf_path: Path) -> list:
    """Group the PDF pages by invoice.

    A page opens a new invoice when it carries the header block, which
    LaTeX prints once per invoice and never repeats on a continuation page.

    Why not the continuation marker. The first version keyed on the absence
    of "Tiếp trang trước" -- which works only as long as EVERY template
    prints it. The diversified test set deliberately includes invoices that
    do not, and on those the marker-based grouping silently merged distinct
    invoices into one group. Worse, it would have graded the merge algorithm
    using one of the very signals that algorithm relies on: the ground truth
    must not share a failure mode with what it measures.

    The header rule falls back to the old behaviour when no header is
    recognised, so existing runs keep their grouping.
    """
    import fitz

    doc = fitz.open(str(pdf_path))
    pages = [page.get_text() for page in doc]

    if not any(_INVOICE_HEADER in text for text in pages):
        return _groups_from_continuation_marker(pages)

    groups = []
    for i, text in enumerate(pages, start=1):
        if _INVOICE_HEADER in text:
            groups.append([i])
        elif groups:
            groups[-1].append(i)
    return groups


def _groups_from_continuation_marker(pages) -> list:
    """Fallback: a page without a continuation marker opens an invoice."""
    groups = []
    for i, text in enumerate(pages, start=1):
        has_table = "STT" in text
        is_continuation = "Tiếp trang trước" in text
        if has_table and not is_continuation:
            groups.append([i])
        elif groups:
            groups[-1].append(i)
    return groups


# --------------------------------------------------------------------------

def load_ocr_pages(pages_dir: Path) -> dict:
    """{page_number: (main_table | None, full_markdown)}"""
    pages = {}
    for d in sorted([p for p in pages_dir.iterdir() if p.is_dir()], key=natural_sort_key):
        n = page_number(d.name)
        md_files = list(d.glob("*.md"))
        if n is None or not md_files:
            continue
        text = md_files[0].read_text(encoding="utf-8")
        found = extract_tables(text)
        table = max(found, key=lambda t: len(t.rows)) if found else None
        pages[n] = (table, text)
    return pages


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, help="Name of a run under results/")
    parser.add_argument("--pdf", default=None)
    parser.add_argument("--gt-dir", default=None)
    parser.add_argument("--strict-numbers", action="store_true",
                        help="Do not neutralise thousand separators")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    pages_dir = root / "results" / args.run / "pages"
    pdf_path = Path(args.pdf) if args.pdf else (root / DEFAULT_PDF).resolve()
    gt_dir = Path(args.gt_dir) if args.gt_dir else (root / DEFAULT_GT).resolve()
    norm = not args.strict_numbers

    groups = page_groups_from_pdf(pdf_path)
    ocr = load_ocr_pages(pages_dir)

    print(f"Run: {args.run}")
    print(f"{len(groups)} invoice(s), {len(ocr)} OCR page(s) available")
    print(f"Thousand separators neutralised: {'yes' if norm else 'no'}\n")

    header = (f"{'invoice':<10}{'pages':<12}{'TEDS w/o':>10}{'TEDS with':>11}"
              f"{'gain':>8}{'  Struct w/o':>14}{'Struct with':>13}")
    print(header)
    print("-" * len(header))

    totals = {"without": [], "with": [], "s_without": [], "s_with": []}

    for k, pages in enumerate(groups, start=1):
        gt_file = gt_dir / f"invoice_{k}.json"
        if not gt_file.exists():
            continue
        invoice = json.loads(gt_file.read_text(encoding="utf-8"))
        true_html = rows_to_html(normalize_rows(ground_truth_rows(invoice), norm))

        available = [(p, ocr[p][0], ocr[p][1]) for p in pages if p in ocr and ocr[p][0]]
        if not available:
            print(f"invoice_{k:<3}{str(pages):<12}{'no table extracted':>40}")
            continue

        # Without merging: the pipeline only ever sees the first page
        first_html = rows_to_html(normalize_rows(available[0][1].rows, norm))

        # With merging
        merged, _ = merge_table_sequence([t for _, t, _ in available],
                                         [txt for _, _, txt in available])
        merged_html = rows_to_html(normalize_rows(merged[0].rows, norm))

        scores = {
            "without": teds(first_html, true_html),
            "with": teds(merged_html, true_html),
            "s_without": teds(first_html, true_html, structure_only=True),
            "s_with": teds(merged_html, true_html, structure_only=True),
        }
        for key, value in scores.items():
            totals[key].append(value)

        gain = scores["with"] - scores["without"]
        print(f"invoice_{k:<3}{str(pages):<12}{scores['without']:>10.3f}{scores['with']:>11.3f}"
              f"{gain:>+8.3f}{scores['s_without']:>14.3f}{scores['s_with']:>13.3f}")

    if not totals["without"]:
        print("\nNo invoice could be scored.")
        return

    mean = lambda xs: sum(xs) / len(xs)
    print("-" * len(header))
    print(f"{'MEAN':<22}{mean(totals['without']):>10.3f}{mean(totals['with']):>11.3f}"
          f"{mean(totals['with']) - mean(totals['without']):>+8.3f}"
          f"{mean(totals['s_without']):>14.3f}{mean(totals['s_with']):>13.3f}")

    print(f"\nTEDS         {mean(totals['with']):.3f}  (structure + content)")
    print(f"TEDS-Struct  {mean(totals['s_with']):.3f}  (structure only)")
    gap = mean(totals["s_with"]) - mean(totals["with"])
    print(f"Gap          {gap:.3f}  -> " + (
        "errors come mostly from READING the text" if gap > 0.1
        else "structure and content degrade together"))


if __name__ == "__main__":
    main()
