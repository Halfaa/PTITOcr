"""
Evaluation TEDS des sorties OCR sur les factures multi-pages.

Repond a deux questions distinctes :

  1. Quelle est la qualite d'extraction du modele (TEDS / TEDS-Struct) ?
  2. Qu'apporte concretement l'etape de fusion multi-pages ?

Pour (2), chaque facture est evaluee DEUX fois contre la meme verite terrain
(la facture complete) :
    - "sans fusion" : on ne garde que le tableau de la 1re page, comme le
      ferait un pipeline qui ignore le probleme multi-pages ;
    - "avec fusion" : on evalue le tableau reconstitue par table_merge.
L'ecart entre les deux chiffre exactement le gain apporte par l'algorithme.

Usage :
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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
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
    """Retire les separateurs de milliers.

    Le generateur choisit au hasard, par facture, entre '2900', '2 900',
    '2.900' et '2,900'. Ce choix est une variable parasite du generateur,
    pas une difficulte de lecture : on l'annule des deux cotes pour ne pas
    penaliser un modele qui a parfaitement lu le montant.
    """
    text = str(cell).strip()
    stripped = re.sub(r"[.,\s]", "", text)
    return stripped if stripped.isdigit() else text


def normalize_rows(rows, enabled=True):
    if not enabled:
        return rows
    return [[normalize_number(c) for c in row] for row in rows]


# --------------------------------------------------------------------------
# Verite terrain
# --------------------------------------------------------------------------

def ground_truth_rows(invoice: dict) -> list:
    """Tableau logique attendu : entete + lignes de medicaments + total.

    On NE met pas les artefacts de mise en page (banniere de titre, marqueurs
    '-- Tiep trang truoc --', entetes repetes) : ce sont precisement les
    elements que la fusion doit supprimer. Les inclure reviendrait a noter
    l'algorithme sur sa capacite a reproduire une coupure de page, alors que
    l'objectif est de la faire disparaitre.
    """
    rows = [list(HEADER)]
    for i, med in enumerate(invoice["medications"], start=1):
        rows.append([
            str(i), med["name"], med["dosage_form"],
            str(med["quantity"]), str(med["unit_price"]), str(med["total_price"]),
        ])
    rows.append(["Tổng tiền:", "", "", "", "", str(invoice["total_amount"])])
    return rows


def page_groups_from_pdf(pdf_path: Path) -> list:
    """Regroupe les pages du PDF par facture.

    Une page ouvre une nouvelle facture si elle n'a pas de marqueur de
    continuation ET contient un tableau. Les pages sans tableau (debordement
    du pied de page) sont rattachees a la facture precedente.
    """
    import fitz

    doc = fitz.open(str(pdf_path))
    groups = []
    for i, page in enumerate(doc, start=1):
        text = page.get_text()
        has_table = "STT" in text
        is_continuation = "Tiếp trang trước" in text
        if has_table and not is_continuation:
            groups.append([i])
        elif groups:
            groups[-1].append(i)
    return groups


# --------------------------------------------------------------------------

def load_ocr_pages(pages_dir: Path) -> dict:
    """{numero_de_page: (table_principale | None, markdown_complet)}"""
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
    parser.add_argument("--run", required=True, help="Nom d'un run dans results/")
    parser.add_argument("--pdf", default=None)
    parser.add_argument("--gt-dir", default=None)
    parser.add_argument("--strict-numbers", action="store_true",
                        help="Ne pas neutraliser les separateurs de milliers")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    pages_dir = root / "results" / args.run / "pages"
    pdf_path = Path(args.pdf) if args.pdf else (root / DEFAULT_PDF).resolve()
    gt_dir = Path(args.gt_dir) if args.gt_dir else (root / DEFAULT_GT).resolve()
    norm = not args.strict_numbers

    groups = page_groups_from_pdf(pdf_path)
    ocr = load_ocr_pages(pages_dir)

    print(f"Run : {args.run}")
    print(f"{len(groups)} facture(s), {len(ocr)} page(s) OCR disponible(s)")
    print(f"Separateurs de milliers neutralises : {'oui' if norm else 'non'}\n")

    header = (f"{'facture':<10}{'pages':<12}{'TEDS sans':>10}{'TEDS avec':>11}"
              f"{'gain':>8}{'  Struct sans':>14}{'Struct avec':>13}")
    print(header)
    print("-" * len(header))

    totals = {"sans": [], "avec": [], "s_sans": [], "s_avec": []}

    for k, pages in enumerate(groups, start=1):
        gt_file = gt_dir / f"invoice_{k}.json"
        if not gt_file.exists():
            continue
        invoice = json.loads(gt_file.read_text(encoding="utf-8"))
        true_html = rows_to_html(normalize_rows(ground_truth_rows(invoice), norm))

        available = [(p, ocr[p][0], ocr[p][1]) for p in pages if p in ocr and ocr[p][0]]
        if not available:
            print(f"invoice_{k:<3}{str(pages):<12}{'aucune table extraite':>40}")
            continue

        # Sans fusion : seule la 1re page est vue par le pipeline
        first_html = rows_to_html(normalize_rows(available[0][1].rows, norm))

        # Avec fusion
        merged, _ = merge_table_sequence([t for _, t, _ in available],
                                         [txt for _, _, txt in available])
        merged_html = rows_to_html(normalize_rows(merged[0].rows, norm))

        scores = {
            "sans": teds(first_html, true_html),
            "avec": teds(merged_html, true_html),
            "s_sans": teds(first_html, true_html, structure_only=True),
            "s_avec": teds(merged_html, true_html, structure_only=True),
        }
        for key, value in scores.items():
            totals[key].append(value)

        gain = scores["avec"] - scores["sans"]
        print(f"invoice_{k:<3}{str(pages):<12}{scores['sans']:>10.3f}{scores['avec']:>11.3f}"
              f"{gain:>+8.3f}{scores['s_sans']:>14.3f}{scores['s_avec']:>13.3f}")

    if not totals["sans"]:
        print("\nAucune facture evaluable.")
        return

    mean = lambda xs: sum(xs) / len(xs)
    print("-" * len(header))
    print(f"{'MOYENNE':<22}{mean(totals['sans']):>10.3f}{mean(totals['avec']):>11.3f}"
          f"{mean(totals['avec']) - mean(totals['sans']):>+8.3f}"
          f"{mean(totals['s_sans']):>14.3f}{mean(totals['s_avec']):>13.3f}")

    print(f"\nTEDS         {mean(totals['avec']):.3f}  (structure + contenu)")
    print(f"TEDS-Struct  {mean(totals['s_avec']):.3f}  (structure seule)")
    ecart = mean(totals["s_avec"]) - mean(totals["avec"])
    print(f"Ecart        {ecart:.3f}  -> " + (
        "l'erreur vient surtout de la LECTURE du texte" if ecart > 0.1
        else "structure et contenu se degradent ensemble"))


if __name__ == "__main__":
    main()
