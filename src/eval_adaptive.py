"""
Measure the adaptive policy against each single variant.

The policy in adaptive.py decides without ground truth. This script gives it
the same two readings a production pipeline would have, lets it choose, and
only THEN opens the ground truth to score what it chose. The ceiling -- the
score a perfect chooser would reach -- is reported alongside, because the gap
to it is what says whether the decision rule is the weak link or the
candidates are.

Usage:
    python src/eval_adaptive.py --raw multipage_paddleocr_vl \\
                               --preprocessed multipage_preproc3_paddleocr
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_check import require as _require_env

_require_env("eval")

import argparse  # noqa: E402
import glob  # noqa: E402
import json  # noqa: E402
import statistics as st  # noqa: E402

import eval_teds as E  # noqa: E402
from adaptive import HEADER_FIELDS, choose  # noqa: E402
from eval_fields import compare  # noqa: E402
from invoice_fields import extract_fields  # noqa: E402
from teds import teds  # noqa: E402


def run_pages(run):
    return {int(f.parent.name.split("-")[0].replace("page_", "")):
            f.read_text(encoding="utf-8")
            for f in (Path("results") / run / "pages").glob("*/*.md")}


def merged_table(pages, group):
    tables, texts = [], []
    for page in group:
        if page in pages:
            for table in E.extract_tables(pages[page]):
                tables.append(table)
                texts.append(pages[page])
    if not tables:
        return None
    merged, _ = E.merge_table_sequence(tables, texts)
    return merged[0]


def expected(gt, name):
    if name == "doctor":
        return f"{gt['doctor']['title']} {gt['doctor']['name']}"
    return gt[name]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw", required=True)
    parser.add_argument("--preprocessed", required=True)
    parser.add_argument("--detail", action="store_true")
    parser.add_argument("--pdf", default=None,
                        help="PDF source, pour le decoupage en factures. "
                             "Defaut : le jeu multi-pages.")
    parser.add_argument("--gt-dir", default=None,
                        help="Dossier des JSON de verite terrain.")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    pdf = Path(args.pdf).resolve() if args.pdf else (root / E.DEFAULT_PDF).resolve()
    gt_dir = Path(args.gt_dir).resolve() if args.gt_dir else (root / E.DEFAULT_GT).resolve()
    groups = E.page_groups_from_pdf(pdf)
    truths = [json.loads(Path(f).read_text(encoding="utf-8"))
              for f in sorted(glob.glob(str(gt_dir / "*.json")),
                              key=lambda f: int("".join(c for c in Path(f).stem if c.isdigit()) or 0))]

    pages = {"raw": run_pages(args.raw),
             "preprocessed": run_pages(args.preprocessed)}

    print(f"raw          : {args.raw}")
    print(f"preprocessed : {args.preprocessed}\n")
    print(f"{'invoice':<9}{'conf raw':>10}{'conf pre':>10}{'kept':>14}"
          f"{'TEDS raw':>10}{'TEDS pre':>10}{'TEDS kept':>11}   note")

    teds_scores = {"raw": [], "preprocessed": [], "adaptive": []}
    fields_ok = {"raw": 0, "preprocessed": 0, "adaptive": 0}

    for i, (group, gt) in enumerate(zip(groups, truths), 1):
        true_html = E.rows_to_html(E.normalize_rows(E.ground_truth_rows(gt), True))

        candidates = {
            name: (merged_table(src, group),
                   [src[p] for p in group if p in src])
            for name, src in pages.items()
        }

        picked = choose(candidates)

        def score(table):
            if table is None:
                return 0.0
            return teds(true_html, E.rows_to_html(E.normalize_rows(table.rows, True)))

        s = {name: score(table) for name, (table, _) in candidates.items()}
        s_kept = s[picked.table_source]
        best = max(s.values())
        note = "" if abs(s_kept - best) < 1e-9 else f"missed {best - s_kept:+.3f}"

        teds_scores["raw"].append(s["raw"])
        teds_scores["preprocessed"].append(s["preprocessed"])
        teds_scores["adaptive"].append(s_kept)

        for name in HEADER_FIELDS:
            if picked.fields.get(name) and compare(
                    picked.fields[name], expected(gt, name)) in ("exact", "lenient"):
                fields_ok["adaptive"] += 1
            for source, src in pages.items():
                value = next((x for x in (extract_fields(src[p]).get(name)
                                          for p in group if p in src) if x), None)
                if value and compare(value, expected(gt, name)) in ("exact", "lenient"):
                    fields_ok[source] += 1

        print(f"  {i:<7}{picked.confidences['raw'].score:>10.2f}"
              f"{picked.confidences['preprocessed'].score:>10.2f}"
              f"{picked.table_source:>14}"
              f"{s['raw']:>10.3f}{s['preprocessed']:>10.3f}{s_kept:>11.3f}   {note}")

        if args.detail:
            for name in HEADER_FIELDS:
                print(f"        {name:<15}{str(picked.fields.get(name))[:34]:<36}"
                      f"[{picked.field_sources.get(name, '-')}]")

    n_fields = len(groups) * len(HEADER_FIELDS)
    print("\n" + "-" * 96)
    for name in ("raw", "preprocessed", "adaptive"):
        print(f"  {name:<14}TEDS {st.mean(teds_scores[name]):.3f}"
              f"    fields {fields_ok[name]}/{n_fields}")
    ceiling = st.mean(max(a, b) for a, b in
                      zip(teds_scores["raw"], teds_scores["preprocessed"]))
    print(f"\n  ceiling (perfect choice, hindsight only): {ceiling:.3f}")
    print("\nA small gap to the ceiling means the decision rule is close to the "
          "best\nachievable with these two candidates; a large one would mean the "
          "rule is\nthe weak link rather than the readings.")


if __name__ == "__main__":
    main()
