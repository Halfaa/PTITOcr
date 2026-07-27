"""
Rapport HTML de demonstration de la fusion multi-pages.

Pour une facture donnee : les images sources cote a cote, les tableaux tels
que l'OCR les sort page par page, puis le tableau unique reconstitue --
avec la charniere entre les deux pages mise en evidence.

C'est le document a montrer pour expliquer ce que fait l'algorithme : il
rend visible en un coup d'oeil ce que les scores TEDS resument en un chiffre.

Usage :
    python src/report_merge_demo.py --run multipage_hunyuan --invoice 1
    python src/report_merge_demo.py --run multipage_hunyuan --invoice 5   (3 pages)
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_check import require as _require_env
_require_env("eval")


import argparse
import base64
import json
import re

from table_merge import extract_tables, merge_table_sequence  # noqa: E402
from teds import teds, rows_to_html  # noqa: E402
from eval_teds import (GEN_DIR, DEFAULT_PDF, DEFAULT_GT, HEADER,  # noqa: E402
                       ground_truth_rows, normalize_rows, page_groups_from_pdf)

IMAGES_DIR = Path("..") / "doc3D-renderer" / "img" / "multipage_test"


def image_to_data_uri(path: Path) -> str:
    """Image embarquee en base64 : le rapport reste autonome, affichable
    partout (navigateur, Notion, pièce jointe) sans dossier annexe."""
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{data}"


def find_page_image(images_dir: Path, page_number: int):
    matches = list(images_dir.glob(f"page_{page_number}-*.png"))
    return matches[0] if matches else None


def table_html(table, highlight_from=None, marker_rows=()):
    """Rend un tableau. highlight_from = indice a partir duquel les lignes
    proviennent de la page suivante (mises en couleur)."""
    out = []
    for i, row in enumerate(table.rows):
        classes = []
        if highlight_from is not None and i >= highlight_from:
            classes.append("from-next")
        if i in marker_rows:
            classes.append("artifact")
        cls = f' class="{" ".join(classes)}"' if classes else ""
        cells = "".join(f"<td>{str(c)}</td>" for c in row)
        out.append(f"<tr{cls}>{cells}</tr>")
    return "<table>" + "".join(out) + "</table>"


CSS = """
body { font-family: -apple-system, Segoe UI, Arial, sans-serif; margin: 0;
       background: #16181c; color: #e6e6e6; line-height: 1.55; }
.wrap { max-width: 1200px; margin: 0 auto; padding: 32px 24px 64px; }
h1 { font-size: 1.7em; margin: 0 0 6px; }
h2 { font-size: 1.2em; color: #6ea8fe; margin: 40px 0 12px;
     border-bottom: 1px solid #333; padding-bottom: 8px; }
.sub { color: #9aa0a6; margin: 0 0 24px; }
.pages { display: flex; gap: 20px; flex-wrap: wrap; }
.page { flex: 1; min-width: 260px; }
.page img { width: 100%; border-radius: 6px; border: 1px solid #333; }
.page .cap { color: #9aa0a6; font-size: .85em; margin-top: 6px; text-align: center; }
table { border-collapse: collapse; width: 100%; background: #fff; color: #111;
        font-size: .8em; margin: 10px 0; }
td { border: 1px solid #bbb; padding: 4px 7px; }
tr:first-child td { background: #e8eaed; font-weight: 600; }
tr.from-next td { background: #e3f2e6; }
tr.artifact td { background: #fde8e8; font-style: italic; }
.legend { font-size: .85em; color: #9aa0a6; margin: 8px 0 0; }
.swatch { display: inline-block; width: 11px; height: 11px; border: 1px solid #999;
          vertical-align: middle; margin: 0 4px 0 12px; }
.box { background: #1e2228; border: 1px solid #333; border-radius: 6px;
       padding: 14px 18px; margin: 16px 0; }
.metrics { display: flex; gap: 28px; flex-wrap: wrap; }
.metric .val { font-size: 1.6em; font-weight: 700; color: #7ee08a; }
.metric .lab { font-size: .8em; color: #9aa0a6; }
code { background: #22262c; padding: 1px 5px; border-radius: 3px; font-size: .9em; }
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="multipage_hunyuan")
    parser.add_argument("--invoice", type=int, default=1)
    parser.add_argument("--images-dir", default=None)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    pages_dir = root / "results" / args.run / "pages"
    images_dir = Path(args.images_dir) if args.images_dir else (root / IMAGES_DIR).resolve()
    gt_dir = (root / DEFAULT_GT).resolve()

    groups = page_groups_from_pdf((root / DEFAULT_PDF).resolve())
    if args.invoice < 1 or args.invoice > len(groups):
        print(f"Facture {args.invoice} inexistante (1 a {len(groups)})")
        return
    page_numbers = groups[args.invoice - 1]

    # Sorties OCR page par page
    tables, texts, kept_pages = [], [], []
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
        kept_pages.append(n)

    if not tables:
        print("Aucun tableau extrait pour cette facture.")
        return

    merged, decisions = merge_table_sequence(tables, texts)
    merged_table = merged[0]

    invoice = json.loads((gt_dir / f"invoice_{args.invoice}.json").read_text(encoding="utf-8"))
    true_html = rows_to_html(normalize_rows(ground_truth_rows(invoice)))
    merged_html_norm = rows_to_html(normalize_rows(merged_table.rows))
    first_html_norm = rows_to_html(normalize_rows(tables[0].rows))

    score_avec = teds(merged_html_norm, true_html)
    score_sans = teds(first_html_norm, true_html)
    struct_avec = teds(merged_html_norm, true_html, structure_only=True)

    # Indice a partir duquel les lignes viennent des pages suivantes
    seam = len(tables[0].rows)

    html = [f"<!DOCTYPE html><html lang='fr'><head><meta charset='utf-8'>",
            f"<title>Fusion multi-pages — facture {args.invoice}</title>",
            f"<style>{CSS}</style></head><body><div class='wrap'>"]

    html.append(f"<h1>Fusion d'un tableau réparti sur {len(kept_pages)} pages</h1>")
    html.append(f"<p class='sub'>Facture {args.invoice} · pages {kept_pages} · "
                f"modèle <code>{args.run.replace('multipage_', '')}</code></p>")

    # --- Images sources
    html.append("<h2>1. Les images en entrée</h2>")
    html.append("<p>Photos simulées : la page est projetée sur un maillage 3D courbé "
                "avec un fond et un éclairage réalistes. Chaque page est donnée à "
                "l'OCR <strong>séparément</strong> — il ne sait pas qu'elles "
                "appartiennent à la même facture.</p>")
    html.append("<div class='pages'>")
    for n in kept_pages:
        img = find_page_image(images_dir, n)
        if img:
            html.append(f"<div class='page'><img src='{image_to_data_uri(img)}' alt='page {n}'>"
                        f"<div class='cap'>page {n}</div></div>")
    html.append("</div>")

    # --- Sorties OCR brutes
    html.append("<h2>2. Ce que l'OCR produit, page par page</h2>")
    html.append("<p>Des tableaux indépendants, chacun avec son propre en-tête. "
                "En rouge, les lignes qui ne sont pas des données et que la fusion "
                "devra supprimer : en-tête répété en tête des pages de "
                "continuation, et marqueurs de coupure quand l'OCR les capture "
                "dans le tableau.</p>")

    def artifact_rows(table, is_first_page):
        """Lignes qui ne sont pas des donnees : marqueurs de coupure, et
        entete repete des pages de continuation."""
        found = set()
        for i, row in enumerate(table.rows):
            joined = " ".join(str(c) for c in row).lower()
            if any(k in joined for k in ("tiếp trang", "xem tiếp", "tiep trang")):
                found.add(i)
        # Sur une page de continuation, la 1re ligne est l'entete repete.
        if not is_first_page and table.rows:
            found.add(0)
        return found

    def out_of_table_markers(text):
        """Marqueurs de coupure presents dans la page mais HORS du tableau."""
        plain = re.sub(r"<table.*?</table>", " ", text, flags=re.S)
        plain = re.sub(r"<[^>]+>", " ", plain)
        return [line.strip() for line in plain.split("\n")
                if "iếp trang" in line or "iep trang" in line]

    for idx, (n, t, txt) in enumerate(zip(kept_pages, tables, texts)):
        html.append(f"<div class='box'><strong>page {n}</strong> — "
                    f"{len(t.rows)} lignes extraites")
        markers = out_of_table_markers(txt)
        if markers:
            html.append("<p class='legend'>Marqueur repéré dans la page mais "
                        "<em>hors</em> du tableau : "
                        + ", ".join(f"« {m} »" for m in markers) + "</p>")
        html.append(table_html(t, marker_rows=artifact_rows(t, idx == 0)))
        html.append("</div>")

    html.append("<p class='legend'>À noter : les marqueurs textuels sont souvent "
                "extraits <em>en dehors</em> du tableau, voire perdus par l'OCR. "
                "C'est pourquoi l'algorithme ne s'y fie jamais seul et croise "
                "plusieurs signaux — voir la section suivante.</p>")

    # --- Décisions
    html.append("<h2>3. La décision de fusion</h2>")
    for i, d in enumerate(decisions):
        verdict = "FUSION" if d["decision"] else "pas de fusion"
        html.append(f"<div class='box'><strong>page {kept_pages[i]} → "
                    f"{kept_pages[i+1]} : {verdict}</strong> "
                    f"(confiance {d['confidence']})<ul>")
        html.append(f"<li>Continuité d'index : la page précédente finit à "
                    f"<code>{d['last_index_a']}</code>, la suivante commence à "
                    f"<code>{d['first_index_b']}</code></li>")
        html.append(f"<li>Similarité des en-têtes : "
                    f"<code>{d['header_similarity']:.2f}</code></li>")
        html.append(f"<li>Ligne « Tổng tiền » en fin de page précédente : "
                    f"<code>{d['table_a_ends_with_total']}</code> "
                    f"(si oui, la facture est terminée → pas de fusion)</li>")
        html.append(f"<li>Marqueur de continuation détecté : "
                    f"<code>{d['table_b_has_continuation_marker']}</code></li>")
        html.append("</ul></div>")

    # --- Résultat
    html.append("<h2>4. Le tableau reconstitué</h2>")
    html.append(f"<p>Un seul tableau, {len(merged_table.rows)} lignes. "
                f"Les en-têtes répétés et les marqueurs ont été supprimés, "
                f"la numérotation s'enchaîne sans rupture.</p>")
    html.append("<p class='legend'><span class='swatch' style='background:#fff'></span>"
                "lignes issues de la première page"
                "<span class='swatch' style='background:#e3f2e6'></span>"
                "lignes issues des pages suivantes</p>")
    html.append(table_html(merged_table, highlight_from=seam))

    # --- Scores
    expected = len(invoice["medications"]) + 2
    html.append("<h2>5. Vérification</h2>")
    html.append("<div class='box'><div class='metrics'>")
    for val, lab in [(f"{score_sans:.3f}", "TEDS sans fusion"),
                     (f"{score_avec:.3f}", "TEDS avec fusion"),
                     (f"+{score_avec - score_sans:.3f}", "gain"),
                     (f"{struct_avec:.3f}", "TEDS-Struct"),
                     (f"{len(merged_table.rows)} / {expected}", "lignes obtenues / attendues")]:
        html.append(f"<div class='metric'><div class='val'>{val}</div>"
                    f"<div class='lab'>{lab}</div></div>")
    html.append("</div></div>")
    html.append("<p class='legend'>TEDS compare l'arbre du tableau produit à celui "
                "de la vérité terrain (JSON du générateur). « Sans fusion » = ce que "
                "donnerait un pipeline qui ignore le problème multi-pages : seule la "
                "première page, donc la moitié des lignes manquantes.</p>")

    html.append("</div></body></html>")

    out = Path(args.output) if args.output else \
        root / "results" / args.run / f"demo_fusion_invoice{args.invoice}.html"
    out.write_text("".join(html), encoding="utf-8")
    print(f"{len(kept_pages)} page(s) -> 1 tableau de {len(merged_table.rows)} lignes "
          f"(attendu {expected})")
    print(f"TEDS {score_sans:.3f} -> {score_avec:.3f}")
    print(f"Rapport : {out.resolve()}")


if __name__ == "__main__":
    main()
