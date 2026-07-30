"""
Same benchmark as bench_tabrecset_paddleocr_vl.py and
bench_tabrecset_ppstructure.py, but with Chandra OCR 2
(datalab-to/chandra-ocr-2, a 5B-parameter VLM on a Qwen3.5 backbone) through
HuggingFace Transformers, on CPU.

Why CPU: this machine's GPU (RTX 3050 Ti, 4 GB VRAM) cannot host a 5B model,
not even in 4-bit quantisation (weights alone are ~2.5-3 GB, far too tight
once the vision encoder activations are added).

The model takes ~10 GB of RAM (bf16): close other heavy applications before
launching, and use --test to validate on a single image before running all 10
(loading + inference can take a very long time on CPU).

Usage:
    python scripts/bench_tabrecset_chandra.py --test   # first image only
    python scripts/bench_tabrecset_chandra.py          # all 10 images
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

# Paths resolved from the project root (not from the current working
# directory): the script runs from wherever it is launched.
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
<html lang="en">
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
    <div class="meta">Processing time: {elapsed:.1f}s</div>
    {content}
  </div>
</div>
"""


def load_model():
    print(f"Loading {MODEL_NAME} on CPU...")
    print("(First run: ~10 GB download from HuggingFace, then loading into RAM. Be patient.)")
    model = AutoModelForImageTextToText.from_pretrained(
        MODEL_NAME,
        dtype=torch.bfloat16,
        device_map="cpu",
    )
    model.eval()
    model.processor = AutoProcessor.from_pretrained(MODEL_NAME)
    model.processor.tokenizer.padding_side = "left"
    print("Model loaded.")
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
        help="Process only the first N images (useful given CPU slowness, ~15 min/image)",
    )
    args = parser.parse_args()

    images = sorted(IMAGES_DIR.glob("*.jpg")) + sorted(IMAGES_DIR.glob("*.png"))
    if not images:
        print(f"No image found in {IMAGES_DIR}/")
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
        print(f"[{i}/{len(images)}] Processing: {image_path.name}")
        try:
            markdown, elapsed = process_image(model, image_path)
        except Exception as e:
            print(f"  -> ECHEC : {e}")
            html_parts.append(
                HTML_ENTRY.format(
                    name=image_path.name,
                    image_uri=image_to_data_uri(image_path),
                    elapsed=0.0,
                    content=f"<em>Error during processing: {e}</em>",
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
        print(f"  -> done in {elapsed:.1f}s")

    html_parts.append("</body></html>")
    REPORT_PATH.write_text("".join(html_parts), encoding="utf-8")
    print(f"\nReport written: {REPORT_PATH.resolve()}")

    import webbrowser
    webbrowser.open(REPORT_PATH.resolve().as_uri())


if __name__ == "__main__":
    main()
