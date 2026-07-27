"""
Reconstruit benchmark_report.html a partir des resultats DEJA generes dans
output/ (sans refaire tourner PaddleOCR-VL), avec les images embarquees en
base64 cette fois (pour que ca s'affiche bien dans Notion, pas seulement en
local).

Usage :
    python rebuild_report.py
"""

import base64
from pathlib import Path

OUTPUT_DIR = Path("output")
REPORT_PATH = Path("benchmark_report.html")

HTML_HEADER = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Benchmark PaddleOCR-VL - 10 images</title>
<style>
  body { font-family: Arial, sans-serif; margin: 0; background: #1e1e1e; color: #eee; }
  h1 { padding: 20px; margin: 0; border-bottom: 2px solid #444; }
  .entry { display: flex; border-bottom: 4px solid #444; }
  .entry .panel { flex: 1; overflow: auto; padding: 20px; box-sizing: border-box; }
  .entry .left { border-right: 2px solid #444; text-align: center; }
  .entry .left img { max-width: 100%; height: auto; }
  .entry h2 { color: #4da3ff; margin-top: 0; }
  .meta { color: #999; font-size: 0.85em; margin-bottom: 12px; }
  table { border-collapse: collapse; margin: 12px 0; width: 100%; background: #fff; color: #000; }
  table, th, td { border: 1px solid #999; }
  td { padding: 6px 10px; text-align: center; }
</style>
</head>
<body>
<h1>Benchmark PaddleOCR-VL — 10 images</h1>
"""

HTML_ENTRY = """
<div class="entry">
  <div class="panel left">
    <h2>{name}</h2>
    <img src="{image_uri}" alt="{name}">
  </div>
  <div class="panel right">
    {content}
  </div>
</div>
"""


def image_to_data_uri(path: Path) -> str:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


def main():
    subdirs = sorted(p for p in OUTPUT_DIR.iterdir() if p.is_dir())
    if not subdirs:
        print(f"Aucun sous-dossier trouve dans {OUTPUT_DIR}/")
        return

    html_parts = [HTML_HEADER]

    for d in subdirs:
        md_files = list(d.glob("*.md"))
        img_files = list(d.glob("*.jpg")) + list(d.glob("*.png"))
        if not md_files or not img_files:
            print(f"Ignoré (incomplet) : {d.name}")
            continue

        md_content = max(md_files, key=lambda p: p.stat().st_mtime).read_text(encoding="utf-8")
        md_content = md_content.replace("\n\n", "<br><br>")
        annotated_image_path = max(img_files, key=lambda p: p.stat().st_mtime)

        html_parts.append(
            HTML_ENTRY.format(
                name=d.name,
                image_uri=image_to_data_uri(annotated_image_path),
                content=md_content,
            )
        )
        print(f"Ajouté : {d.name}")

    html_parts.append("</body></html>")
    REPORT_PATH.write_text("".join(html_parts), encoding="utf-8")
    print(f"\nRapport reconstruit : {REPORT_PATH.resolve()}")


if __name__ == "__main__":
    main()
