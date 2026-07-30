"""
HTML demonstration report of multi-page merging.

For a given invoice: the source images side by side, the tables as OCR emits
them page by page, then the single reconstructed table -- with the seam
between pages highlighted.

This is the document to show when explaining what the algorithm does: it
makes visible at a glance what the TEDS scores summarise as a single number.

Usage:
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
from eval_teds import (DEFAULT_PDF, DEFAULT_GT,  # noqa: E402
                       ground_truth_rows, normalize_rows, page_groups_from_pdf)

IMAGES_DIR = Path("..") / "doc3D-renderer" / "img" / "multipage_test"


def image_to_data_uri(path: Path) -> str:
    """Image embedded as base64: the report stays self-contained and can be
    opened anywhere (browser, Notion, email attachment) with no side folder."""
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{data}"


def find_page_image(images_dir: Path, page_number: int):
    matches = list(images_dir.glob(f"page_{page_number}-*.png"))
    return matches[0] if matches else None


def table_html(table, highlight_from=None, marker_rows=()):
    """Render a table. highlight_from = index from which rows come from the
    following page (shown in colour)."""
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
        print(f"No such invoice: {args.invoice} (valid range 1..{len(groups)})")
        return
    page_numbers = groups[args.invoice - 1]

    # OCR output, page by page
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
        print("No table extracted for this invoice.")
        return

    merged, decisions = merge_table_sequence(tables, texts)
    merged_table = merged[0]

    invoice = json.loads((gt_dir / f"invoice_{args.invoice}.json").read_text(encoding="utf-8"))
    true_html = rows_to_html(normalize_rows(ground_truth_rows(invoice)))
    merged_html_norm = rows_to_html(normalize_rows(merged_table.rows))
    first_html_norm = rows_to_html(normalize_rows(tables[0].rows))

    score_with = teds(merged_html_norm, true_html)
    score_without = teds(first_html_norm, true_html)
    struct_with = teds(merged_html_norm, true_html, structure_only=True)

    # Index from which rows originate from the following pages
    seam = len(tables[0].rows)

    html = [f"<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>",
            f"<title>Multi-page merging — invoice {args.invoice}</title>",
            f"<style>{CSS}</style></head><body><div class='wrap'>"]

    html.append(f"<h1>Merging a table spread over {len(kept_pages)} pages</h1>")
    html.append(f"<p class='sub'>Invoice {args.invoice} · pages {kept_pages} · "
                f"model <code>{args.run.replace('multipage_', '')}</code></p>")

    # --- Source images
    html.append("<h2>1. The input images</h2>")
    html.append("<p>Simulated photographs: the page is projected onto a curved "
                "3D mesh with a realistic background and lighting. Each page is "
                "given to the OCR <strong>separately</strong> — it has no way "
                "of knowing they belong to the same invoice.</p>")
    html.append("<div class='pages'>")
    for n in kept_pages:
        img = find_page_image(images_dir, n)
        if img:
            html.append(f"<div class='page'><img src='{image_to_data_uri(img)}' alt='page {n}'>"
                        f"<div class='cap'>page {n}</div></div>")
    html.append("</div>")

    # --- Raw OCR output
    html.append("<h2>2. What OCR produces, page by page</h2>")
    html.append("<p>Independent tables, each with its own header. In red, the "
                "rows that are not data and that merging must remove: the "
                "repeated header at the top of continuation pages, and page-break "
                "markers whenever OCR captures them inside the table.</p>")

    def artifact_rows(table, is_first_page):
        """Rows that are not data: break markers, and the repeated header of
        continuation pages."""
        found = set()
        for i, row in enumerate(table.rows):
            joined = " ".join(str(c) for c in row).lower()
            if any(k in joined for k in ("tiếp trang", "xem tiếp", "tiep trang")):
                found.add(i)
        # On a continuation page, row 0 is the repeated header.
        if not is_first_page and table.rows:
            found.add(0)
        return found

    def out_of_table_markers(text):
        """Break markers present on the page but OUTSIDE the table."""
        plain = re.sub(r"<table.*?</table>", " ", text, flags=re.S)
        plain = re.sub(r"<[^>]+>", " ", plain)
        return [line.strip() for line in plain.split("\n")
                if "iếp trang" in line or "iep trang" in line]

    for idx, (n, t, txt) in enumerate(zip(kept_pages, tables, texts)):
        html.append(f"<div class='box'><strong>page {n}</strong> — "
                    f"{len(t.rows)} rows extracted")
        markers = out_of_table_markers(txt)
        if markers:
            html.append("<p class='legend'>Marker found on the page but "
                        "<em>outside</em> the table: "
                        + ", ".join(f"“{m}”" for m in markers) + "</p>")
        html.append(table_html(t, marker_rows=artifact_rows(t, idx == 0)))
        html.append("</div>")

    html.append("<p class='legend'>Note: textual markers are often extracted "
                "<em>outside</em> the table, or lost altogether by the OCR. "
                "This is why the algorithm never relies on them alone and "
                "cross-checks several signals — see the next section.</p>")

    # --- Decisions
    html.append("<h2>3. The merging decision</h2>")
    for i, d in enumerate(decisions):
        verdict = "MERGE" if d["decision"] else "no merge"
        html.append(f"<div class='box'><strong>page {kept_pages[i]} → "
                    f"{kept_pages[i+1]}: {verdict}</strong> "
                    f"(confidence {d['confidence']})<ul>")
        html.append(f"<li>Index continuity: the previous page ends at "
                    f"<code>{d['last_index_a']}</code>, the next one starts at "
                    f"<code>{d['first_index_b']}</code></li>")
        html.append(f"<li>Header similarity: "
                    f"<code>{d['header_similarity']:.2f}</code></li>")
        html.append(f"<li>“Tổng tiền” row at the end of the previous page: "
                    f"<code>{d['table_a_ends_with_total']}</code> "
                    f"(if yes, the invoice is complete → no merge)</li>")
        html.append(f"<li>Continuation marker detected: "
                    f"<code>{d['table_b_has_continuation_marker']}</code></li>")
        html.append("</ul></div>")

    # --- Result
    html.append("<h2>4. The reconstructed table</h2>")
    html.append(f"<p>A single table, {len(merged_table.rows)} rows. Repeated "
                f"headers and markers have been removed, and the numbering "
                f"runs on without a break.</p>")
    html.append("<p class='legend'><span class='swatch' style='background:#fff'></span>"
                "rows from the first page"
                "<span class='swatch' style='background:#e3f2e6'></span>"
                "rows from the following pages</p>")
    html.append(table_html(merged_table, highlight_from=seam))

    # --- Scores
    expected = len(invoice["medications"]) + 2
    html.append("<h2>5. Verification</h2>")
    html.append("<div class='box'><div class='metrics'>")
    for val, lab in [(f"{score_without:.3f}", "TEDS without merging"),
                     (f"{score_with:.3f}", "TEDS with merging"),
                     (f"+{score_with - score_without:.3f}", "gain"),
                     (f"{struct_with:.3f}", "TEDS-Struct"),
                     (f"{len(merged_table.rows)} / {expected}", "rows produced / expected")]:
        html.append(f"<div class='metric'><div class='val'>{val}</div>"
                    f"<div class='lab'>{lab}</div></div>")
    html.append("</div></div>")
    html.append("<p class='legend'>TEDS compares the tree of the produced table "
                "with that of the ground truth (the generator's JSON). "
                "“Without merging” is what a pipeline ignoring the multi-page "
                "problem would yield: the first page only, hence half the rows "
                "missing.</p>")

    html.append("</div></body></html>")

    out = Path(args.output) if args.output else \
        root / "results" / args.run / f"demo_merge_invoice{args.invoice}.html"
    out.write_text("".join(html), encoding="utf-8")
    print(f"{len(kept_pages)} page(s) -> 1 table of {len(merged_table.rows)} rows "
          f"(expected {expected})")
    print(f"TEDS {score_without:.3f} -> {score_with:.3f}")
    print(f"Report: {out.resolve()}")


if __name__ == "__main__":
    main()
