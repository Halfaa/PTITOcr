"""
Applique table_merge.py aux resultats d'un benchmark (dossier output_* genere
par benchmark_deformed/run_benchmark_deformed.py) : detecte les tableaux
coupes entre pages consecutives et les fusionne, avec un rapport HTML
montrant, pour chaque paire de pages, la decision prise et les signaux qui
l'ont motivee (essentiel pour pouvoir juger/discuter les cas limites).

Usage (depuis n'importe quel dossier) :
    python src/merge_multipage_results.py --run multipage_ppstructure

--run est le nom d'un dossier de results/ (cf. results/<run>/pages/).
Le rapport est ecrit dans results/<run>/merge_report.html.
"""

import argparse
import re
from pathlib import Path

from table_merge import extract_tables, merge_table_sequence


def natural_sort_key(path: Path):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", path.name)]


def table_to_html(table) -> str:
    rows_html = []
    for row in table.rows:
        cells = "".join(f"<td>{c}</td>" for c in row)
        rows_html.append(f"<tr>{cells}</tr>")
    return "<table>" + "".join(rows_html) + "</table>"


HTML_HEADER = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Fusion tableaux multi-pages</title>
<style>
  body { font-family: Arial, sans-serif; margin: 0; background: #1e1e1e; color: #eee; }
  h1 { padding: 20px; margin: 0; border-bottom: 2px solid #444; }
  .pair { border-bottom: 4px solid #444; padding: 20px; }
  .pair h2 { color: #4da3ff; }
  .decision-yes { color: #4dff88; font-weight: bold; }
  .decision-no { color: #ff6666; font-weight: bold; }
  .signals { background: #2a2a2a; padding: 10px; border-radius: 4px; font-family: monospace; font-size: 0.85em; margin: 10px 0; }
  .cols { display: flex; gap: 20px; }
  .cols > div { flex: 1; }
  table { border-collapse: collapse; margin: 8px 0; width: 100%; background: #fff; color: #000; font-size: 0.85em; }
  table, th, td { border: 1px solid #999; }
  td { padding: 4px 8px; }
</style>
</head>
<body>
<h1>Fusion des tableaux multi-pages — __SOURCE__</h1>
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, help="Nom d'un run dans results/ (ex: multipage_ppstructure)")
    parser.add_argument("--report", default=None, help="Chemin du rapport HTML (defaut: results/<run>/merge_report.html)")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    run_dir = project_root / "results" / args.run
    output_dir = run_dir / "pages"
    if not output_dir.exists():
        print(f"Dossier introuvable : {output_dir}")
        print("Runs disponibles :", ", ".join(sorted(p.name for p in (project_root / 'results').iterdir() if p.is_dir())))
        return

    subdirs = sorted([d for d in output_dir.iterdir() if d.is_dir()], key=natural_sort_key)
    print(f"{len(subdirs)} page(s) trouvee(s) dans {output_dir}")

    page_tables = []  # liste de (nom_page, [Table, ...], markdown_complet)
    for d in subdirs:
        md_files = list(d.glob("*.md"))
        if not md_files:
            print(f"  {d.name} : pas de .md, ignore")
            continue
        md_content = max(md_files, key=lambda p: p.stat().st_mtime).read_text(encoding="utf-8")
        tables = extract_tables(md_content)
        page_tables.append((d.name, tables, md_content))
        print(f"  {d.name} : {len(tables)} table(s) trouvee(s)")

    # Pour simplifier, on suppose 1 table principale par page (le tableau de
    # medicaments). Si une page en contient plusieurs, on prend la plus grande.
    main_tables, page_names, page_texts = [], [], []
    for name, tables, md_content in page_tables:
        if not tables:
            continue
        main_tables.append(max(tables, key=lambda t: len(t.rows)))
        page_names.append(name)
        # Le markdown complet est transmis a l'algo : les marqueurs de
        # continuation sont extraits par l'OCR HORS du tableau.
        page_texts.append(md_content)

    merged, decisions = merge_table_sequence(main_tables, page_texts)

    # .replace et non .format : le bloc <style> contient des accolades CSS.
    html = [HTML_HEADER.replace("__SOURCE__", args.run)]

    # Rapport detaille pour chaque paire de pages consecutives (decision + signaux)
    for i, decision in enumerate(decisions):
        page_a, page_b = page_names[i], page_names[i + 1]
        css_class = "decision-yes" if decision["decision"] else "decision-no"
        verdict = "FUSIONNE" if decision["decision"] else "PAS fusionne (tables independantes)"
        html.append(f"""
<div class="pair">
  <h2>{page_a} -> {page_b}</h2>
  <div class="{css_class}">{verdict} (confiance : {decision['confidence']})</div>
  <div class="signals">{decision}</div>
</div>""")

    html.append("<h1>Tables finales (apres fusion)</h1>")
    for i, table in enumerate(merged, start=1):
        html.append(f"""
<div class="pair">
  <h2>Table finale {i} ({len(table.data_rows)} lignes de donnees)</h2>
  {table_to_html(table)}
</div>""")

    html.append("</body></html>")

    report_path = Path(args.report) if args.report else run_dir / "merge_report.html"
    report_path.write_text("".join(html), encoding="utf-8")
    print(f"\n{len(main_tables)} page(s) -> {len(merged)} table(s) finale(s) apres fusion")
    print(f"Rapport : {report_path.resolve()}")


if __name__ == "__main__":
    main()
