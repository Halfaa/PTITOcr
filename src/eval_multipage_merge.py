"""
Evaluate the merging algorithm (table_merge.py) against ground truth.

Ground truth is extracted from the source PDF of the multi-page invoices: we
read, page by page, whether the "Tiep trang truoc" / "Xem tiep trang sau"
markers are present. By construction, a page carrying the continuation marker
is the continuation of the previous one.

This is the only honest way to put a number on the algorithm: comparing it to
the OCR output itself would mean grading it on the very data that inspired it.

Usage:
    python src/eval_multipage_merge.py --run multipage_ppstructure
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_check import require as _require_env
_require_env("eval")


import argparse
import re

from table_merge import extract_tables, is_continuation  # noqa: E402

DEFAULT_PDF = Path("..") / "synthetic_invoice_generator" / "hospital_pharmacy" / "invoices_multipage_xelatex.pdf"


def natural_sort_key(path: Path):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", path.name)]


def page_number(name: str):
    """'page_12-concave_mesh_1010001' -> 12"""
    m = re.search(r"page_(\d+)", name)
    return int(m.group(1)) if m else None


def ground_truth_continuations(pdf_path: Path) -> set:
    """Return the set of N such that page N+1 continues page N.

    Derived from the invoice grouping, itself keyed on the header block that
    LaTeX prints once per invoice. Two consecutive pages of the same group
    are a continuation.

    The first version read the continuation marker directly, which was wrong
    twice over. Practically, it only works while every template prints one:
    on the diversified test set, five invoices do not, and their genuine
    continuations were scored as "expected=no" -- the algorithm was punished
    for being right, and precision read 58 % instead of 100 %.

    And on principle, the reference must not share a failure mode with what
    it measures. The marker is one of the signals the merge algorithm uses;
    grading that algorithm with it means a template dropping the marker
    breaks the measurement and the measured thing at once, with no way to
    tell which.
    """
    from eval_teds import page_groups_from_pdf

    continuations = set()
    for group in page_groups_from_pdf(pdf_path):
        for a, b in zip(group, group[1:]):
            if b == a + 1:
                continuations.add(a)
    return continuations


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, help="Name of a run under results/")
    parser.add_argument("--pdf", default=None, help="Source PDF of the multi-page invoices")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    pages_dir = project_root / "results" / args.run / "pages"
    pdf_path = Path(args.pdf) if args.pdf else (project_root / DEFAULT_PDF).resolve()

    truth = ground_truth_continuations(pdf_path)
    print(f"Ground truth: {len(truth)} real continuation(s) -> "
          f"{sorted((n, n + 1) for n in truth)}\n")

    # Load OCR output, one main table per page
    tables, nums, texts = [], [], []
    lost = []
    for d in sorted([p for p in pages_dir.iterdir() if p.is_dir()], key=natural_sort_key):
        md_files = list(d.glob("*.md"))
        n = page_number(d.name)
        if not md_files:
            lost.append(n)
            continue
        text = md_files[0].read_text(encoding="utf-8")
        found = extract_tables(text)
        if not found:
            lost.append(n)
            continue
        tables.append(max(found, key=lambda t: len(t.rows)))
        nums.append(n)
        texts.append(text)

    if lost:
        print(f"Pages where OCR extracted NO table: {sorted(lost)}")
        print("  -> continuations involving them are out of the algorithm's "
              "reach (upstream failure, not a merging failure)\n")

    tp = fp = fn = tn = 0
    rows = []
    current_text = texts[0]
    for i in range(len(tables) - 1):
        a, b = nums[i], nums[i + 1]
        signals = is_continuation(tables[i], tables[i + 1], current_text, texts[i + 1])
        predicted = signals["decision"]
        # True only if the two pages really are consecutive
        expected = (b == a + 1) and (a in truth)

        if predicted and expected:
            tp += 1; verdict = "OK  (correct merge)"
        elif predicted and not expected:
            fp += 1; verdict = "FALSE POSITIVE"
        elif not predicted and expected:
            fn += 1; verdict = "MISSED (continuation not found)"
        else:
            tn += 1; verdict = "OK  (correctly not merged)"

        rows.append((a, b, predicted, expected, verdict, signals))
        current_text = texts[i + 1]

    for a, b, pred, exp, verdict, s in rows:
        print(f"page {a:>2} -> {b:<2}  predicted={'yes' if pred else 'no ':<3} "
              f"expected={'yes' if exp else 'no ':<3} {verdict:<32} "
              f"[hdr={s['header_similarity']:.2f} lastA={s['last_index_a']} "
              f"firstB={s['first_index_b']} total_A={s['table_a_ends_with_total']}]")

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    print(f"\nTrue positives  : {tp}")
    print(f"False positives : {fp}   (wrong merges -- the worst kind: they corrupt the data)")
    print(f"Missed          : {fn}")
    print(f"True negatives  : {tn}")
    print(f"\nPrecision {precision:.0%}   Recall {recall:.0%}   F1 {f1:.0%}")


if __name__ == "__main__":
    main()
