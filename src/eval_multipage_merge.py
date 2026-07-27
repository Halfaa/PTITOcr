"""
Evalue l'algorithme de fusion (table_merge.py) contre une verite terrain.

La verite terrain est extraite du PDF source des factures multi-pages : on y
lit directement, page par page, la presence des marqueurs "Tiep trang truoc"
/ "Xem tiep trang sau". Une page portant le marqueur de continuation est, par
construction, la suite de la page precedente.

C'est la seule facon honnete de chiffrer l'algo : le comparer aux sorties OCR
elles-memes reviendrait a le juger sur les donnees qui l'ont inspire.

Usage :
    python src/eval_multipage_merge.py --run multipage_ppstructure
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_check import require as _require_env
_require_env("eval")


import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from table_merge import extract_tables, is_continuation  # noqa: E402

DEFAULT_PDF = Path("..") / "synthetic_invoice_generator" / "hospital_pharmacy" / "invoices_multipage_xelatex.pdf"


def natural_sort_key(path: Path):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", path.name)]


def page_number(name: str):
    """'page_12-concave_mesh_1010001' -> 12"""
    m = re.search(r"page_(\d+)", name)
    return int(m.group(1)) if m else None


def ground_truth_continuations(pdf_path: Path) -> set:
    """Retourne l'ensemble des N tels que la page N+1 continue la page N."""
    import fitz  # PyMuPDF

    doc = fitz.open(str(pdf_path))
    continuations = set()
    for i, page in enumerate(doc, start=1):
        if "Tiếp trang trước" in page.get_text():
            continuations.add(i - 1)
    return continuations


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, help="Nom d'un run dans results/")
    parser.add_argument("--pdf", default=None, help="PDF source des factures multi-pages")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    pages_dir = project_root / "results" / args.run / "pages"
    pdf_path = Path(args.pdf) if args.pdf else (project_root / DEFAULT_PDF).resolve()

    truth = ground_truth_continuations(pdf_path)
    print(f"Verite terrain : {len(truth)} continuation(s) reelle(s) -> "
          f"{sorted((n, n + 1) for n in truth)}\n")

    # Chargement des sorties OCR, une table principale par page
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
        print(f"Pages ou l'OCR n'a extrait AUCUN tableau : {sorted(lost)}")
        print("  -> les continuations qui les impliquent sont hors de portee "
              "de l'algo (echec en amont, pas un echec de la fusion)\n")

    tp = fp = fn = tn = 0
    rows = []
    current_text = texts[0]
    for i in range(len(tables) - 1):
        a, b = nums[i], nums[i + 1]
        signals = is_continuation(tables[i], tables[i + 1], current_text, texts[i + 1])
        predicted = signals["decision"]
        # Verite : uniquement si les deux pages sont bien consecutives
        expected = (b == a + 1) and (a in truth)

        if predicted and expected:
            tp += 1; verdict = "OK  (fusion correcte)"
        elif predicted and not expected:
            fp += 1; verdict = "FAUX POSITIF"
        elif not predicted and expected:
            fn += 1; verdict = "RATE (continuation manquee)"
        else:
            tn += 1; verdict = "OK  (non-fusion correcte)"

        rows.append((a, b, predicted, expected, verdict, signals))
        current_text = texts[i + 1]

    for a, b, pred, exp, verdict, s in rows:
        print(f"page {a:>2} -> {b:<2}  predit={'oui' if pred else 'non'}  "
              f"attendu={'oui' if exp else 'non'}  {verdict:<28} "
              f"[hdr={s['header_similarity']:.2f} lastA={s['last_index_a']} "
              f"firstB={s['first_index_b']} total_A={s['table_a_ends_with_total']}]")

    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    print(f"\nVrais positifs  : {tp}")
    print(f"Faux positifs   : {fp}   (fusions a tort -- le plus grave : elles corrompent les donnees)")
    print(f"Rates           : {fn}")
    print(f"Vrais negatifs  : {tn}")
    print(f"\nPrecision {precision:.0%}   Rappel {recall:.0%}   F1 {f1:.0%}")


if __name__ == "__main__":
    main()
