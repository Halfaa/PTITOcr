"""
Compare models on HEADER FIELD extraction (patient, date, doctor...).

Why a separate evaluation: TEDS scores the table and nothing else. It says
strictly nothing about the patient name, the invoice date or the prescribing
doctor -- which are exactly the entities the internship subject names. A
model can score 0.93 TEDS and still lose every field that identifies whose
invoice this is.

Scoring is deliberately lenient on diacritics: "BuiHaiSu Tù" for "Bùi Hải Sư
Tử" is a reading defect, not a lost field. We therefore report two levels:

    exact      the string matches after whitespace normalisation
    lenient    it matches once diacritics are stripped and spaces removed

The gap between the two is itself informative: it isolates diacritic damage
from outright field loss.

Usage:
    python src/eval_fields.py
    python src/eval_fields.py --runs multipage_hunyuan multipage_paddleocr_vl
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_check import require as _require_env
_require_env("eval")


import argparse
import json
import re

from table_merge import extract_tables  # noqa: E402
from invoice_fields import extract_fields, _deaccent_keep_length  # noqa: E402
from eval_teds import DEFAULT_PDF, DEFAULT_GT, page_groups_from_pdf  # noqa: E402

# Field in our JSON -> how to read the expected value out of the ground truth
GROUND_TRUTH = {
    "hospital_name": lambda gt: gt["hospital_name"],
    "customer_name": lambda gt: gt["customer_name"],
    "invoice_date": lambda gt: gt["invoice_date"],
    "doctor": lambda gt: f"{gt['doctor']['title']} {gt['doctor']['name']}",
}

DEFAULT_RUNS = ["multipage_hunyuan", "multipage_paddleocr_vl", "multipage_ppstructure"]


def _squash(s: str) -> str:
    """Lowercase, no diacritics, no spaces or punctuation -- the lenient key."""
    return re.sub(r"[^a-z0-9]", "", _deaccent_keep_length(str(s)))


def _as_date(s):
    """(day, month, year) or None.

    The generator renders the same date three ways at random: '25/03/2010',
    '25-03-2010' and 'Ngày 25 tháng 3 năm 2010'. Comparing strings would
    count a correctly read date as an error, so we compare the numbers.
    """
    numbers = [int(n) for n in re.findall(r"\d+", str(s))]
    if len(numbers) != 3:
        return None
    day, month, year = numbers
    if not (1 <= day <= 31 and 1 <= month <= 12 and year > 1000):
        return None
    return day, month, year


# Honorifics that open a doctor's name in these invoices.
_TITLES = ["ths.bs ck1", "ths.bs.", "ths.bs", "bs.ck1", "bs ck1", "bs.", "bs",
           "bac si", "bac sy", "bacsi", "bacsy"]


def _drop_title(value):
    """Remove a leading honorific from a doctor's name.

    The ground truth stores the doctor as {title, name} and the evaluation
    compares against "title name". But in the document, "Bac si" is BOTH the
    honorific AND the field label ("Bac si ke don:"), so an extractor that
    correctly strips the label also strips the title -- and a perfectly read
    name was being scored wrong.

    The title is not identifying information: two doctors are told apart by
    their names, not by their degrees. So recovering the name alone counts as
    recovering the field. The 'exact' column still demands the full string
    character for character, which is where reading the title correctly is
    rewarded -- the two tiers keep saying different things.
    """
    s = re.sub(r"\s+", " ", str(value)).strip()
    flat = _deaccent_keep_length(s)
    for title in _TITLES:
        if flat.startswith(title):
            return s[len(title):].strip(" .:-")
    return s


def compare(found, expected):
    """-> 'exact' | 'lenient' | 'wrong' | 'missing'"""
    if not found:
        return "missing"
    a = re.sub(r"\s+", " ", str(found)).strip().lower()
    b = re.sub(r"\s+", " ", str(expected)).strip().lower()
    if a == b:
        return "exact"
    if _squash(found) == _squash(expected):
        return "lenient"
    found_date, expected_date = _as_date(found), _as_date(expected)
    if found_date and found_date == expected_date:
        return "lenient"
    if _squash(_drop_title(found)) == _squash(_drop_title(expected)):
        return "lenient"
    return "wrong"


def first_page_text(pages_dir: Path, page_numbers):
    for n in page_numbers:
        dirs = list(pages_dir.glob(f"page_{n}-*"))
        if not dirs:
            continue
        md = list(dirs[0].glob("*.md"))
        if md:
            return md[0].read_text(encoding="utf-8")
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", nargs="+", default=DEFAULT_RUNS)
    parser.add_argument("--detail", action="store_true",
                        help="List every mismatch")
    parser.add_argument("--pdf", default=None,
                        help="PDF source, pour le decoupage en factures. "
                             "Defaut : le jeu multi-pages.")
    parser.add_argument("--gt-dir", default=None,
                        help="Dossier des JSON de verite terrain.")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    gt_dir = Path(args.gt_dir).resolve() if args.gt_dir else (root / DEFAULT_GT).resolve()
    pdf = Path(args.pdf).resolve() if args.pdf else (root / DEFAULT_PDF).resolve()
    groups = page_groups_from_pdf(pdf)

    fields = list(GROUND_TRUTH)
    header = f"{'run':<26}" + "".join(f"{f.split('_')[0]:>16}" for f in fields) + f"{'overall':>10}"
    print(header)
    print("-" * len(header))

    mismatches = []
    for run in args.runs:
        pages_dir = root / "results" / run / "pages"
        if not pages_dir.exists():
            print(f"{run:<26} (run not found)")
            continue

        tally = {f: {"exact": 0, "lenient": 0, "wrong": 0, "missing": 0} for f in fields}
        n = 0
        for k, page_numbers in enumerate(groups, start=1):
            gt_file = gt_dir / f"invoice_{k}.json"
            text = first_page_text(pages_dir, page_numbers)
            if not gt_file.exists() or text is None:
                continue
            gt = json.loads(gt_file.read_text(encoding="utf-8"))
            got = extract_fields(text)
            n += 1
            for f in fields:
                verdict = compare(got.get(f), GROUND_TRUTH[f](gt))
                tally[f][verdict] += 1
                if verdict in ("wrong", "missing"):
                    mismatches.append((run, k, f, got.get(f), GROUND_TRUTH[f](gt)))

        cells = ""
        total_ok = 0
        for f in fields:
            ok = tally[f]["exact"] + tally[f]["lenient"]
            total_ok += ok
            cells += f"{ok}/{n} ({tally[f]['exact']}x)".rjust(16)
        overall = total_ok / (n * len(fields)) if n else 0
        print(f"{run:<26}{cells}{overall:>9.0%}")

    print("\nReading: 'ok/total (N exact)'. ok = field recovered, tolerating "
          "\ndiacritic damage; N exact = recovered character for character.")

    if args.detail and mismatches:
        print("\nFields lost or wrong:")
        for run, k, f, got, exp in mismatches:
            short = run.replace("multipage_", "")
            print(f"  {short:<14} invoice {k}  {f:<14} got={str(got)[:28]!r:<30} "
                  f"expected={str(exp)[:28]!r}")


if __name__ == "__main__":
    main()
