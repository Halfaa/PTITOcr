"""
OCR benchmark on the warped / photo-realistic images produced by
doc3D-renderer (single-page OR multi-page invoices).

Usage (from any directory):
    python scripts/bench_deformed.py --model paddleocr-vl --images-dir "..\\doc3D-renderer\\img\\multipage_test" --limit 6  --output multipage_paddleocr_vl
    python scripts/bench_deformed.py --model ppstructure  --images-dir "..\\doc3D-renderer\\img\\batch1"        --limit 14 --output batch1_ppstructure

Everything is written under results/<--output>/:
    results/<name>/pages/<image_name>/   raw model output
    results/<name>/report.html           visual report (rewritten after each image)

--limit: useful for batch1 (100 images) given PaddleOCR-VL's processing time
(~230s/image, so all 100 would take ~6h) -- unnecessary for multipage_test
(17 images only).

Images are sorted in "natural" order (page_2 before page_10) rather than
strict alphabetical order, so that consecutive pages of the same multi-page
invoice appear one after another in the report.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from env_check import require as _require_env
# The environment check happens inside main(), once --model is known:
# PaddleOCR and HunyuanOCR live in two incompatible virtualenvs.


import argparse
import base64
import re
import time
from pathlib import Path


def natural_sort_key(path: Path):
    """Sort 'page_2' before 'page_10' (unlike plain alphabetical order)."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", path.name)]


def image_to_data_uri(path: Path) -> str:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


HTML_HEADER = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Benchmark {model_title} - {dataset_name}</title>
<style>
  body {{ font-family: Arial, sans-serif; margin: 0; background: #1e1e1e; color: #eee; }}
  h1 {{ padding: 20px; margin: 0; border-bottom: 2px solid #444; }}
  .entry {{ display: flex; border-bottom: 4px solid #444; }}
  .entry .panel {{ flex: 1; overflow: auto; padding: 20px; box-sizing: border-box; }}
  .entry .left {{ border-right: 2px solid #444; text-align: center; }}
  .entry .left img {{ max-width: 100%; height: auto; }}
  .entry h2 {{ color: #4da3ff; margin-top: 0; }}
  .meta {{ color: #999; font-size: 0.85em; margin-bottom: 12px; }}
  table {{ border-collapse: collapse; margin: 12px 0; width: 100%; background: #fff; color: #000; }}
  table, th, td {{ border: 1px solid #999; }}
  td {{ padding: 6px 10px; text-align: center; }}
</style>
</head>
<body>
<h1>Benchmark {model_title} — {dataset_name} (doc3D-renderer warped images)</h1>
"""

HTML_ENTRY = """
<div class="entry">
  <div class="panel left">
    <h2>{name}</h2>
    <img src="{image_uri}" alt="{name}">
  </div>
  <div class="panel right">
    <div class="meta">{meta}</div>
    {content}
  </div>
</div>
"""


HUNYUAN_MODEL_ID = "tencent/HunyuanOCR"
# Prompts live in src/hunyuan_prompts.py -- single source of truth, so the
# benchmark and the smoke test cannot silently drift apart.
from hunyuan_prompts import ALL as HUNYUAN_PROMPTS  # noqa: E402


def _load_hunyuan():
    """Load HunyuanOCR-1.5 on GPU.

    backend="pil" is MANDATORY: with the torchvision backend (< 0.27),
    LANCZOS resampling is silently replaced by BICUBIC and the model emits
    gibberish -- observed in practice, not a theoretical precaution.
    """
    import torch
    from transformers import AutoProcessor

    processor = AutoProcessor.from_pretrained(HUNYUAN_MODEL_ID, backend="pil",
                                              trust_remote_code=True)
    try:
        from transformers import HunYuanVLForConditionalGeneration as ModelClass
    except ImportError:
        from transformers import AutoModelForCausalLM as ModelClass

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = ModelClass.from_pretrained(
        HUNYUAN_MODEL_ID, attn_implementation="eager",
        dtype=torch.bfloat16 if device == "cuda" else torch.float32,
        device_map=device, trust_remote_code=True,
    )
    print(f"  HunyuanOCR loaded on {device}")
    return processor, model


def _hunyuan_predict(processor, model, image_path: Path,
                     prompt_key: str = "document") -> str:
    import torch
    from PIL import Image

    image = Image.open(image_path).convert("RGB")
    messages = [
        {"role": "system", "content": ""},
        {"role": "user", "content": [
            {"type": "image", "image": str(image_path)},
            {"type": "text", "text": HUNYUAN_PROMPTS[prompt_key]},
        ]},
    ]
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = processor(text=[text], images=image, padding=True, return_tensors="pt")
    inputs = inputs.to(next(model.parameters()).device)
    with torch.no_grad():
        generated = model.generate(**inputs, max_new_tokens=4096, do_sample=False,
                                   repetition_penalty=1.08)
    trimmed = [out[len(inp):] for inp, out in zip(inputs["input_ids"], generated)]
    return processor.batch_decode(trimmed, skip_special_tokens=True,
                                  clean_up_tokenization_spaces=False)[0]


CHANDRA_MODEL_ID = "datalab-to/chandra-ocr-2"


def _load_chandra():
    """Load Chandra OCR 2 on CPU.

    CPU is not a choice: 5B parameters do not fit in 4 GB of VRAM, not even
    quantised to 4 bits once the vision encoder activations are counted. It
    takes ~10 GB of RAM in bf16 and runs at roughly 15 min per image, so a
    17-page run is an overnight job.
    """
    import torch
    from transformers import AutoModelForImageTextToText, AutoProcessor

    print(f"Loading {CHANDRA_MODEL_ID} on CPU (~10 GB in RAM, be patient)...")
    model = AutoModelForImageTextToText.from_pretrained(
        CHANDRA_MODEL_ID, dtype=torch.bfloat16, device_map="cpu")
    model.eval()
    model.processor = AutoProcessor.from_pretrained(CHANDRA_MODEL_ID)
    model.processor.tokenizer.padding_side = "left"
    print("  Chandra loaded.")
    return model


def _chandra_predict(model, image_path: Path) -> str:
    from PIL import Image
    from chandra.model.hf import generate_hf
    from chandra.model.schema import BatchInputItem
    from chandra.output import parse_markdown

    batch = [BatchInputItem(image=Image.open(image_path), prompt_type="ocr_layout")]
    return parse_markdown(generate_hf(batch, model)[0].raw)


def already_processed(img_output_dir: Path) -> bool:
    """Detect output from a previous run (lets us resume without redoing work)."""
    return img_output_dir.exists() and any(img_output_dir.glob("*.md"))


def build_entry(image_path: Path, img_output_dir: Path, meta: str) -> str:
    md_files = list(img_output_dir.glob("*.md"))
    img_files = list(img_output_dir.glob("*.jpg")) + list(img_output_dir.glob("*.png"))

    md_content = (max(md_files, key=lambda p: p.stat().st_mtime).read_text(encoding="utf-8").replace("\n\n", "<br><br>")
                  if md_files else "<em>No markdown content generated.</em>")
    annotated_image_path = max(img_files, key=lambda p: p.stat().st_mtime) if img_files else image_path

    return HTML_ENTRY.format(
        name=image_path.name,
        image_uri=image_to_data_uri(annotated_image_path),
        meta=meta,
        content=md_content,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=["paddleocr-vl", "ppstructure", "hunyuan", "chandra"], required=True)
    parser.add_argument("--images-dir", required=True, help="Folder holding the warped images (e.g. doc3D-renderer/img/multipage_test)")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N images")
    parser.add_argument("--output", default=None, help="Run name. Defaults to folder name + model.")
    parser.add_argument("--prompt", default="document", choices=sorted(HUNYUAN_PROMPTS),
                        help="HunyuanOCR prompt (ignored by the other models). "
                             "document_full also keeps headers and footers.")
    args = parser.parse_args()

    _require_env({"hunyuan": "hunyuan", "chandra": "chandra"}.get(args.model, "paddle"))

    images_dir = Path(args.images_dir)
    dataset_name = images_dir.name

    # Paths resolved from the project root -> the script works from any
    # working directory, and every run lands under results/.
    project_root = Path(__file__).resolve().parent.parent
    run_name = args.output or f"{images_dir.name}_{args.model}"
    run_dir = project_root / "results" / run_name
    output_root = run_dir / "pages"
    report_path = run_dir / "report.html"
    output_root.mkdir(parents=True, exist_ok=True)

    images = sorted(images_dir.glob("*.png"), key=natural_sort_key) + sorted(images_dir.glob("*.jpg"), key=natural_sort_key)
    if args.limit:
        images = images[: args.limit]
    if not images:
        print(f"No image found in {images_dir}")
        return

    print(f"{len(images)} image(s) to process with {args.model}.")

    n_already_done = sum(already_processed(output_root / p.stem) for p in images)
    if n_already_done:
        print(f"{n_already_done} image(s) already done in a previous run -> reused without re-inference.")

    # Only load the (large) model if at least one image still needs processing.
    pipeline = None
    model_title = {"paddleocr-vl": "PaddleOCR-VL", "ppstructure": "PP-StructureV3",
                   "hunyuan": "HunyuanOCR-1.5", "chandra": "Chandra OCR 2"}[args.model]

    def build_pipeline():
        """Load the model. Called ONCE, outside the per-image try/except.

        Loading used to happen lazily inside that try, so a failure to build
        the pipeline was retried on every image -- and paddlex answers a
        second import attempt with "PDX has already been initialized",
        which is not the fault at all but the echo of the first one. Sixteen
        misleading tracebacks then buried the single real error.

        Building here means the run dies immediately, on the true exception.
        """
        if args.model == "paddleocr-vl":
            from paddleocr import PaddleOCRVL
            print("Loading PaddleOCR-VL...")
            return PaddleOCRVL(pipeline_version="v1")
        if args.model == "ppstructure":
            from paddleocr import PPStructureV3
            print("Loading PP-StructureV3...")
            # enable_mkldnn=False: works around the PaddlePaddle 3.3.x oneDNN/PIR bug on CPU
            return PPStructureV3(enable_mkldnn=False)
        if args.model == "hunyuan":
            print("Loading HunyuanOCR-1.5...")
            return _load_hunyuan()
        return _load_chandra()

    def get_pipeline():
        nonlocal pipeline
        if pipeline is None:
            pipeline = build_pipeline()
        return pipeline

    def process(image_path: Path, img_output_dir: Path):
        """Run the model and write a .md into img_output_dir.

        PaddleOCR exposes result objects that know how to serialise
        themselves; HunyuanOCR returns raw text, which we write ourselves."""
        if args.model in ("hunyuan", "chandra"):
            if args.model == "hunyuan":
                processor, model = get_pipeline()
                text = _hunyuan_predict(processor, model, image_path, args.prompt)
            else:
                text = _chandra_predict(get_pipeline(), image_path)
            (img_output_dir / f"{image_path.stem}.md").write_text(text, encoding="utf-8")
            return
        for res in get_pipeline().predict(str(image_path)):
            res.save_to_json(save_path=str(img_output_dir))
            res.save_to_markdown(save_path=str(img_output_dir))
            res.save_to_img(save_path=str(img_output_dir))

    def flush_report(entries):
        """Rewrite the whole report to disk -> at most one image is lost if the script is interrupted."""
        html = [HTML_HEADER.format(model_title=model_title, dataset_name=dataset_name)]
        html.extend(entries)
        html.append("</body></html>")
        report_path.write_text("".join(html), encoding="utf-8")

    # Load before the loop, so a broken environment fails in one clear
    # traceback instead of one per image. Skipped when every page is already
    # done, which keeps a pure "rebuild the report" run cheap.
    if n_already_done < len(images):
        pipeline = build_pipeline()

    entries = []
    for i, image_path in enumerate(images, start=1):
        img_output_dir = output_root / image_path.stem

        if already_processed(img_output_dir):
            print(f"[{i}/{len(images)}] {image_path.name} -> already done, reusing existing output")
            entries.append(build_entry(image_path, img_output_dir, meta="Reused from a previous run (not reprocessed)"))
            flush_report(entries)
            continue

        print(f"[{i}/{len(images)}] {image_path.name}")
        img_output_dir.mkdir(parents=True, exist_ok=True)

        start = time.time()
        try:
            process(image_path, img_output_dir)
        except Exception as e:
            # Full traceback on the FIRST failure: when pipeline creation is
            # what breaks, every image fails identically and the one-line
            # message ("a dependency error occurred") names neither the
            # missing package nor the real exception.
            print(f"  -> FAILED: {e}")
            if not entries or all("Error during processing" in x for x in entries):
                import traceback
                print("--- full traceback (first failure) ---")
                traceback.print_exc()
                print("--- end traceback ---")
            entries.append(HTML_ENTRY.format(
                name=image_path.name, image_uri=image_to_data_uri(image_path),
                meta="Error during processing", content=f"<em>Error: {e}</em>",
            ))
            flush_report(entries)
            continue
        elapsed = time.time() - start

        entries.append(build_entry(image_path, img_output_dir, meta=f"Processing time: {elapsed:.1f}s"))
        flush_report(entries)
        print(f"  -> done in {elapsed:.1f}s (report updated: {len(entries)}/{len(images)})")

    print(f"\nReport written: {report_path.resolve()}")

    import webbrowser
    webbrowser.open(report_path.resolve().as_uri())


if __name__ == "__main__":
    main()
