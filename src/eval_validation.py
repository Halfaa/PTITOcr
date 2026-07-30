"""
Measure how effective arithmetic validation is.

Question asked: *without ground truth*, what fraction of the genuinely wrong
lines does arithmetic validation manage to flag?

This is the question that decides whether a TEDS of 0.93 is usable. A global
score does not say whether the remaining errors are detectable; here we
measure it directly.

Protocol. For every extracted line:
  - GROUND TRUTH says whether it is correct, by comparing it to the
    generator's JSON (matched by STT index, see match_ground_truth);
  - VALIDATION says whether it is suspect, using only the invoice's internal
    arithmetic.
We cross the two.

Usage:
    python src/eval_validation.py --run multipage_hunyuan
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_check import require as _require_env
_require_env("eval")


import argparse
import json

from difflib import SequenceMatcher  # noqa: E402
from table_merge import extract_tables, merge_table_sequence, _normalize  # noqa: E402
from invoice_parse import parse_table  # noqa: E402
from invoice_validate import check_invoice  # noqa: E402
from eval_teds import DEFAULT_PDF, DEFAULT_GT, page_groups_from_pdf  # noqa: E402


def match_ground_truth(item, gt_items):
    """Find the corresponding ground-truth line.

    Matching is done BY INDEX (STT), not by name: the same medication can
    appear several times on one invoice with different quantities, and a
    name-based match would then pick the wrong occurrence -- manufacturing
    errors that do not exist.

    Fall back to the name only when the index is unreadable.
    """
    if item.index is not None and 1 <= item.index <= len(gt_items):
        return gt_items[item.index - 1]

    target = _normalize(item.name)
    best, best_ratio = None, 0.0
    for med in gt_items:
        ratio = SequenceMatcher(None, target, _normalize(med["name"])).ratio()
        if ratio > best_ratio:
            best, best_ratio = med, ratio
    return best if best_ratio >= 0.6 else None


def corrected_values(check):
    """The line's values AFTER automatic correction has been applied.

    Grading the raw values would be unfair: when validation infers a missing
    unit price, that inferred value is what the pipeline would deliver. So
    that is the value to confront with ground truth.
    """
    item = check.item
    values = {"quantity": item.quantity,
              "unit_price": item.unit_price,
              "total": item.total}
    if check.corrected_field:
        values[check.corrected_field] = check.corrected_value
    return values


def line_is_truly_correct(check, gt_items):
    """Ground truth: are the three numeric values of the line right?
    (the name may be slightly misread without that being a data error)"""
    med = match_ground_truth(check.item, gt_items)
    if med is None:
        return False, "no matching ground-truth line"
    v = corrected_values(check)
    errors = []
    if v["quantity"] != med["quantity"]:
        errors.append(f"qty {v['quantity']}!={med['quantity']}")
    if v["unit_price"] != med["unit_price"]:
        errors.append(f"up {v['unit_price']}!={med['unit_price']}")
    if v["total"] != med["total_price"]:
        errors.append(f"tot {v['total']}!={med['total_price']}")
    return (not errors), ", ".join(errors)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="multipage_hunyuan")
    parser.add_argument("--verbose", action="store_true",
                        help="Detail every misclassified line")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    pages_dir = root / "results" / args.run / "pages"
    gt_dir = (root / DEFAULT_GT).resolve()
    groups = page_groups_from_pdf((root / DEFAULT_PDF).resolve())

    print(f"Run: {args.run}\n")
    head = (f"{'invoice':<10}{'lines':>7}{'right':>8}{'wrong':>9}"
            f"{'flagged':>11}{'detected':>11}{'total OK':>10}")
    print(head)
    print("-" * len(head))

    # Confusion matrix at LINE level
    tp = fp = fn = tn = 0
    n_corr_total = n_corr_right = 0
    missed_examples = []
    # NAME errors are out of reach of arithmetic by construction: counted
    # separately so as not to overstate what validation covers.
    n_name_errors = 0
    name_examples = []

    for k, page_numbers in enumerate(groups, start=1):
        gt_file = gt_dir / f"invoice_{k}.json"
        if not gt_file.exists():
            continue
        gt_items = json.loads(gt_file.read_text(encoding="utf-8"))["medications"]

        tables, texts = [], []
        for n in page_numbers:
            dirs = list(pages_dir.glob(f"page_{n}-*"))
            if not dirs:
                continue
            md = list(dirs[0].glob("*.md"))
            if not md:
                continue
            text = md[0].read_text(encoding="utf-8")
            found = extract_tables(text)
            if not found:
                continue
            tables.append(max(found, key=lambda t: len(t.rows)))
            texts.append(text)
        if not tables:
            print(f"invoice_{k:<3}{'no table extracted':>50}")
            continue

        merged, _ = merge_table_sequence(tables, texts)
        invoice = parse_table(merged[0])
        result = check_invoice(invoice)

        n_true_wrong = 0
        for check in result["checks"]:
            # Name error, counted separately: arithmetic cannot see it, no
            # matter how well the checker is implemented.
            med = match_ground_truth(check.item, gt_items)
            if med and _normalize(check.item.name) != _normalize(med["name"]):
                n_name_errors += 1
                if len(name_examples) < 6:
                    name_examples.append((k, check.item.name, med["name"]))

            truly_ok, why = line_is_truly_correct(check, gt_items)

            # "Flagged" = needs human review. An automatically corrected line
            # is NOT part of that: the pipeline delivers it repaired. Whether
            # the repair was right is measured separately.
            flagged = check.is_suspect
            if check.status == "corrected":
                n_corr_total += 1
                if truly_ok:
                    n_corr_right += 1

            if not truly_ok:
                n_true_wrong += 1
                if flagged:
                    tp += 1
                else:
                    fn += 1
                    if len(missed_examples) < 8:
                        missed_examples.append(
                            (k, check.item.index, check.item.name, why))
            else:
                if flagged:
                    fp += 1
                else:
                    tn += 1

        detected = sum(1 for c in result["checks"]
                       if c.is_suspect and not line_is_truly_correct(c, gt_items)[0])
        total_flag = {True: "yes", False: "NO", None: "?"}[result["total_ok"]]
        print(f"invoice_{k:<3}{result['n_lines']:>7}"
              f"{result['n_lines'] - n_true_wrong:>8}{n_true_wrong:>9}"
              f"{result['n_suspect']:>11}{detected:>11}{total_flag:>10}")

    print("-" * len(head))

    total_wrong = tp + fn
    recall = tp / total_wrong if total_wrong else 0.0
    precision = tp / (tp + fp) if (tp + fp) else 0.0

    print(f"\nGenuinely wrong lines          : {total_wrong}")
    print(f"  flagged by validation        : {tp}  ({recall:.0%})")
    print(f"  slipped through the net      : {fn}")
    print(f"Correct lines flagged wrongly  : {fp}")
    if n_corr_total:
        print(f"\nAutomatic corrections          : {n_corr_total}")
        print(f"  of which exact                : {n_corr_right}  "
              f"({n_corr_right / n_corr_total:.0%})")

    print(f"\nRecall {recall:.0%}   Precision {precision:.0%}")

    if missed_examples:
        print("\nExamples of UNDETECTED errors "
              "(the line adds up but is still wrong):")
        for inv, idx, name, why in missed_examples:
            print(f"  invoice {inv}, line {idx} -- {str(name)[:32]:<32} {why}")

    total_lines = tp + fp + fn + tn
    print(f"\n--- What arithmetic CANNOT see ---")
    print(f"Lines with a misread NAME      : {n_name_errors} / {total_lines} "
          f"({n_name_errors / total_lines:.0%})")
    if name_examples:
        for inv, read, expected in name_examples:
            print(f"  invoice {inv}: '{read}'  instead of  '{expected}'")

    print("\nHow to read this. Recall covers NUMERIC errors: quantity, unit "
          "\nprice, total. Validation catches them because the three values "
          "\ncontradict each other."
          "\n"
          "\nNAME errors are invisible to arithmetic by construction, not "
          "\nthrough any shortcoming of the implementation: nothing in the "
          "\ninvoice reveals that 'Xetoprofen' should have read 'Ketoprofen'. "
          "\nCatching those would need a medication dictionary -- a separate "
          "\nand complementary avenue.")


if __name__ == "__main__":
    main()
