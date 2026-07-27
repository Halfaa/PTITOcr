"""
Meme benchmark que run_benchmark.py (PaddleOCR-VL) et run_benchmark_ppstructure.py
(PP-StructureV3), mais avec Chandra OCR 2 (datalab-to/chandra-ocr-2, VLM 5B
parametres, base Qwen3.5) via HuggingFace Transformers, en CPU.

Pourquoi le CPU : le GPU de ce PC (RTX 3050 Ti, 4 Go de VRAM) est insuffisant
pour charger un modele 5B, meme en quantization 4-bit (poids seuls ~2.5-3 Go,
trop juste une fois les activations de l'encodeur visuel ajoutees).

Le modele pese ~10 Go en RAM (bf16) : ferme les autres applications lourdes
avant de lancer, et utilise --test pour valider sur 1 image avant les 10
(chargement + inference peuvent prendre tres longtemps sur CPU).

Usage :
    python run_benchmark_chandra.py --test   # 1ere image seulement (validation)
    python run_benchmark_chandra.py          # les 10 images du benchmark
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from env_check import require as _require_env
_require_env("paddle")


import argparse
import base64
import time
from pathlib import Path

import torch
from PIL import Image
from transformers import AutoModelForImageTextToText, AutoProcessor

from chandra.model.hf import generate_hf
from chandra.model.schema import BatchInputItem
from chandra.output import parse_markdown

# Chemins resolus depuis la racine du projet (et non depuis le repertoire
# courant) : le script marche quel que soit l'endroit d'ou on le lance.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
IMAGES_DIR = PROJECT_ROOT / "data" / "tabrecset_sample" / "images"
RUN_DIR = PROJECT_ROOT / "results" / "tabrecset_chandra"
OUTPUT_DIR = RUN_DIR / "pages"
REPORT_PATH = RUN_DIR / "report.html"
RUN_DIR.mkdir(parents=True, exist_ok=True)
MODEL_NAME = "datalab-to/chandra-ocr-2"


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
<title>Benchmark Chandra OCR 2 - CPU</title>
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
<h1>Benchmark Chandra OCR 2 — CPU</h1>
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


def load_model():
    print(f"Chargement de {MODEL_NAME} sur CPU...")
    print("(1er lancement : telechargement ~10 Go depuis HuggingFace, puis chargement en RAM. Patience.)")
    model = AutoModelForImageTextToText.from_pretrained(
        MODEL_NAME,
        dtype=torch.bfloat16,
        device_map="cpu",
    )
    model.eval()
    model.processor = AutoProcessor.from_pretrained(MODEL_NAME)
    model.processor.tokenizer.padding_side = "left"
    print("Modele charge.")
    return model


def process_image(model, image_path: Path):
    img = Image.open(image_path)
    start = time.time()
    batch = [BatchInputItem(image=img, prompt_type="ocr_layout")]
    result = generate_hf(batch, model)[0]
    markdown = parse_markdown(result.raw)
    elapsed = time.time() - start
    return markdown, elapsed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--test", action="store_true",
        help="Traite seulement la 1ere image pour valider que ca marche avant de lancer les 10",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Traite seulement les N premieres images (utile vu la lenteur sur CPU, ~15 min/image)",
    )
    args = parser.parse_args()

    images = sorted(IMAGES_DIR.glob("*.jpg")) + sorted(IMAGES_DIR.glob("*.png"))
    if not images:
        print(f"Aucune image trouvee dans {IMAGES_DIR}/")
        return
    if args.test:
        images = images[:1]
        print("Mode test : 1 seule image. Relance sans --test pour traiter les 10.")
    elif args.limit:
        images = images[:args.limit]
        print(f"Limite a {len(images)} image(s).")

    print(f"{len(images)} image(s) a traiter.")
    model = load_model()

    OUTPUT_DIR.mkdir(exist_ok=True)
    html_parts = [HTML_HEADER]

    for i, image_path in enumerate(images, start=1):
        print(f"[{i}/{len(images)}] Traitement de : {image_path.name}")
        try:
            markdown, elapsed = process_image(model, image_path)
        except Exception as e:
            print(f"  -> ECHEC : {e}")
            html_parts.append(
                HTML_ENTRY.format(
                    name=image_path.name,
                    image_uri=image_to_data_uri(image_path),
                    elapsed=0.0,
                    content=f"<em>Erreur lors du traitement : {e}</em>",
                )
            )
            continue

        img_output_dir = OUTPUT_DIR / image_path.stem
        img_output_dir.mkdir(parents=True, exist_ok=True)
        (img_output_dir / f"{image_path.stem}.md").write_text(markdown, encoding="utf-8")

        html_content = markdown.replace("\n\n", "<br><br>")
        html_parts.append(
            HTML_ENTRY.format(
                name=image_path.name,
                image_uri=image_to_data_uri(image_path),
                elapsed=elapsed,
                content=html_content,
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
