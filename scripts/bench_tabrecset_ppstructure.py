"""
Meme benchmark que run_benchmark.py, mais avec le pipeline PP-StructureV3
(detection de layout + OCR + reconnaissance de tableau en etapes separees et
specialisees) au lieu de PaddleOCR-VL (VLM unique).

A lancer APRES run_benchmark.py (pas en meme temps si CPU limite, les deux
pipelines sont lourds).

Usage :
    python run_benchmark_ppstructure.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from env_check import require as _require_env
_require_env("paddle")


import base64
import time
from pathlib import Path

from paddleocr import PPStructureV3

# Chemins resolus depuis la racine du projet (et non depuis le repertoire
# courant) : le script marche quel que soit l'endroit d'ou on le lance.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
IMAGES_DIR = PROJECT_ROOT / "data" / "tabrecset_sample" / "images"
RUN_DIR = PROJECT_ROOT / "results" / "tabrecset_ppstructure"
OUTPUT_DIR = RUN_DIR / "pages"
REPORT_PATH = RUN_DIR / "report.html"
RUN_DIR.mkdir(parents=True, exist_ok=True)


def image_to_data_uri(path: Path) -> str:
    """Encode l'image en base64 et l'embarque dans le HTML (data URI) pour que
    le rapport soit autonome et s'affiche partout (Notion, navigateur, email...)."""
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"

HTML_HEADER = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Benchmark PP-StructureV3 - 10 images</title>
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
<h1>Benchmark PP-StructureV3 — 10 images</h1>
"""

HTML_ENTRY = """
<div class="entry">
  <div class="panel left">
    <h2>{name}</h2>
    <img src="{image_uri}" alt="{name}">
  </div>
  <div class="panel right">
    <div class="meta">Temps de traitement : {elapsed:.1f}s</div>
    {content}
  </div>
</div>
"""


def main():
    images = sorted(IMAGES_DIR.glob("*.jpg")) + sorted(IMAGES_DIR.glob("*.png"))
    if not images:
        print(f"Aucune image trouvee dans {IMAGES_DIR}/")
        return

    print(f"{len(images)} images a traiter.")
    print("Chargement de la pipeline PP-StructureV3 (peut prendre du temps la 1ere fois)...")
    # enable_mkldnn=False : contourne un bug connu de PaddlePaddle 3.3.x
    # (NotImplementedError ConvertPirAttribute2RuntimeAttribute) sur inference
    # CPU via oneDNN. Legerement plus lent, mais evite le crash.
    pipeline = PPStructureV3(enable_mkldnn=False)

    html_parts = [HTML_HEADER]

    for i, image_path in enumerate(images, start=1):
        print(f"[{i}/{len(images)}] Traitement de : {image_path.name}")
        img_output_dir = OUTPUT_DIR / image_path.stem
        img_output_dir.mkdir(parents=True, exist_ok=True)

        start = time.time()
        output = pipeline.predict(str(image_path))

        for res in output:
            res.save_to_json(save_path=str(img_output_dir))
            res.save_to_markdown(save_path=str(img_output_dir))
            res.save_to_img(save_path=str(img_output_dir))

        elapsed = time.time() - start

        md_files = list(img_output_dir.glob("*.md"))
        img_files = list(img_output_dir.glob("*.jpg")) + list(img_output_dir.glob("*.png"))

        if md_files:
            md_content = max(md_files, key=lambda p: p.stat().st_mtime).read_text(encoding="utf-8")
            md_content = md_content.replace("\n\n", "<br><br>")
        else:
            md_content = "<em>Aucun contenu markdown genere.</em>"

        annotated_image_path = max(img_files, key=lambda p: p.stat().st_mtime) if img_files else image_path

        html_parts.append(
            HTML_ENTRY.format(
                name=image_path.name,
                image_uri=image_to_data_uri(annotated_image_path),
                elapsed=elapsed,
                content=md_content,
            )
        )

        print(f"  -> termine en {elapsed:.1f}s")

    html_parts.append("</body></html>")
    REPORT_PATH.write_text("".join(html_parts), encoding="utf-8")
    print(f"\nRapport genere : {REPORT_PATH.resolve()}")

    import webbrowser
    webbrowser.open(REPORT_PATH.resolve().as_uri())


if __name__ == "__main__":
    main()
