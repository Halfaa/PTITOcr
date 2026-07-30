"""
Apply table_merge.py to a benchmark run: detect tables split across
consecutive pages and merge them, producing an HTML report that shows, for
each page pair, the decision taken and the signals behind it (essential in
order to judge and discuss the borderline cases).

Usage (from any directory):
    python src/merge_multipage_results.py --run multipage_ppstructure

--run is the name of a folder under results/ (see results/<run>/pages/).
The report is written to results/<run>/merge_report.html.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import argparse  # noqa: E402
import re  # noqa: E402

from table_merge import extract_tables, merge_table_sequence  # noqa: E402


def natural_sort_key(path: Path):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", path.name)]


def table_to_html(table) -> str:
    rows_html = []
    for row in table.rows:
        cells = "".join(f"<td>{c}</td>" for c in row)
        rows_html.append(f"<tr>{cells}</tr>")
    return "<table>" + "".join(rows_html) + "</table>"


HTML_HEADER = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Multi-page table merging</title>
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
<h1>Multi-page table merging — __SOURCE__</h1>
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, help="Name of a run under results/ (e.g. multipage_ppstructure)")
    parser.add_argument("--report", default=None, help="HTML report path (default: results/<run>/merge_report.html)")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    run_dir = project_root / "results" / args.run
    output_dir = run_dir / "pages"
    if not output_dir.exists():
        print(f"Folder not found: {output_dir}")
        print("Available runs:", ", ".join(sorted(p.name for p in (project_root / 'results').iterdir() if p.is_dir())))
        return

    subdirs = sorted([d for d in output_dir.iterdir() if d.is_dir()], key=natural_sort_key)
    print(f"{len(subdirs)} page(s) found in {output_dir}")

    page_tables = []  # list of (page_name, [Table, ...], full_markdown)
    for d in subdirs:
        md_files = list(d.glob("*.md"))
        if not md_files:
            print(f"  {d.name}: no .md, skipped")
            continue
        md_content = max(md_files, key=lambda p: p.stat().st_mtime).read_text(encoding="utf-8")
        tables = extract_tables(md_content)
        page_tables.append((d.name, tables, md_content))
        print(f"  {d.name}: {len(tables)} table(s) found")

    # For simplicity we assume one main table per page (the medication
    # table). If a page holds several, we keep the largest.
    main_tables, page_names, page_texts = [], [], []
    for name, tables, md_content in page_tables:
        if not tables:
            continue
        main_tables.append(max(tables, key=lambda t: len(t.rows)))
        page_names.append(name)
        # The full markdown is handed to the algorithm: OCR extracts the
        # continuation markers OUTSIDE the table.
        page_texts.append(md_content)

    merged, decisions = merge_table_sequence(main_tables, page_texts)

    # .replace rather than .format: the <style> block contains CSS braces.
    html = [HTML_HEADER.replace("__SOURCE__", args.run)]

    # Detailed report for every consecutive page pair (decision + signals)
    for i, decision in enumerate(decisions):
        page_a, page_b = page_names[i], page_names[i + 1]
        css_class = "decision-yes" if decision["decision"] else "decision-no"
        verdict = "MERGED" if decision["decision"] else "NOT merged (independent tables)"
        html.append(f"""
<div class="pair">
  <h2>{page_a} -> {page_b}</h2>
  <div class="{css_class}">{verdict} (confidence: {decision['confidence']})</div>
  <div class="signals">{decision}</div>
</div>""")

    html.append("<h1>Final tables (after merging)</h1>")
    for i, table in enumerate(merged, start=1):
        html.append(f"""
<div class="pair">
  <h2>Final table {i} ({len(table.data_rows)} data rows)</h2>
  {table_to_html(table)}
</div>""")

    html.append("</body></html>")

    report_path = Path(args.report) if args.report else run_dir / "merge_report.html"
    report_path.write_text("".join(html), encoding="utf-8")
    print(f"\n{len(main_tables)} page(s) -> {len(merged)} final table(s) after merging")
    print(f"Report: {report_path.resolve()}")


if __name__ == "__main__":
    main()
