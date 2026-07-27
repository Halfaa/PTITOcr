"""
Benchmark OCR sur les images deformees/photo-realistes produites par
doc3D-renderer (factures standard OU factures multi-pages).

Usage (depuis n'importe quel dossier) :
    python scripts/bench_deformed.py --model paddleocr-vl --images-dir "..\\doc3D-renderer\\img\\multipage_test" --limit 6  --output multipage_paddleocr_vl
    python scripts/bench_deformed.py --model ppstructure  --images-dir "..\\doc3D-renderer\\img\\batch1"        --limit 14 --output batch1_ppstructure

Tout est ecrit dans results/<--output>/ :
    results/<nom>/pages/<nom_image>/   sorties brutes du modele
    results/<nom>/report.html          rapport visuel (reecrit apres chaque image)

--limit : utile pour batch1 (100 images) vu le temps de traitement de
PaddleOCR-VL (~230s/image, donc les 100 prendraient ~6h) -- pas necessaire
pour multipage_test (17 images seulement).

Les images sont triees par ordre "naturel" (page_2 avant page_10) plutot
qu'alphabetique strict, pour que les pages consecutives d'une meme facture
multi-pages apparaissent l'une apres l'autre dans le rapport.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from env_check import require as _require_env
# La verification d'environnement est faite dans main(), une fois --model
# connu : PaddleOCR et HunyuanOCR vivent dans deux venv incompatibles.


import argparse
import base64
import re
import time
from pathlib import Path


def natural_sort_key(path: Path):
    """Trie 'page_2' avant 'page_10' (contrairement au tri alphabetique pur)."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", path.name)]


def image_to_data_uri(path: Path) -> str:
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"


HTML_HEADER = """<!DOCTYPE html>
<html lang="fr">
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
<h1>Benchmark {model_title} — {dataset_name} (images deformees doc3D-renderer)</h1>
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
HUNYUAN_PROMPT = ("提取文档图片中正文的所有信息用markdown格式表示，其中页眉、页脚部分忽略，"
                  "表格用html格式表达，文档中公式用latex格式表示，按照阅读顺序组织进行解析。")


def _load_hunyuan():
    """Charge HunyuanOCR-1.5 sur GPU.

    backend="pil" est IMPERATIF : avec le backend torchvision (< 0.27), le
    reechantillonnage LANCZOS est remplace par BICUBIC et le modele produit
    du charabia -- constate en pratique, pas une precaution theorique.
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
    print(f"  HunyuanOCR charge sur {device}")
    return processor, model


def _hunyuan_predict(processor, model, image_path: Path) -> str:
    import torch
    from PIL import Image

    image = Image.open(image_path).convert("RGB")
    messages = [
        {"role": "system", "content": ""},
        {"role": "user", "content": [
            {"type": "image", "image": str(image_path)},
            {"type": "text", "text": HUNYUAN_PROMPT},
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


def already_processed(img_output_dir: Path) -> bool:
    """Detecte un resultat d'un run precedent (permet de reprendre sans retraiter)."""
    return img_output_dir.exists() and any(img_output_dir.glob("*.md"))


def build_entry(image_path: Path, img_output_dir: Path, meta: str) -> str:
    md_files = list(img_output_dir.glob("*.md"))
    img_files = list(img_output_dir.glob("*.jpg")) + list(img_output_dir.glob("*.png"))

    md_content = (max(md_files, key=lambda p: p.stat().st_mtime).read_text(encoding="utf-8").replace("\n\n", "<br><br>")
                  if md_files else "<em>Aucun contenu markdown genere.</em>")
    annotated_image_path = max(img_files, key=lambda p: p.stat().st_mtime) if img_files else image_path

    return HTML_ENTRY.format(
        name=image_path.name,
        image_uri=image_to_data_uri(annotated_image_path),
        meta=meta,
        content=md_content,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=["paddleocr-vl", "ppstructure", "hunyuan"], required=True)
    parser.add_argument("--images-dir", required=True, help="Dossier contenant les images deformees (ex: doc3D-renderer/img/multipage_test)")
    parser.add_argument("--limit", type=int, default=None, help="Ne traiter que les N premieres images")
    parser.add_argument("--output", default=None, help="Nom du rapport (sans extension). Par defaut derive du dossier + modele.")
    args = parser.parse_args()

    _require_env("hunyuan" if args.model == "hunyuan" else "paddle")

    images_dir = Path(args.images_dir)
    dataset_name = images_dir.name

    # Chemins resolus depuis la racine du projet -> le script marche quel que
    # soit le repertoire courant, et tous les runs atterrissent dans results/.
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
        print(f"Aucune image trouvee dans {images_dir}")
        return

    print(f"{len(images)} image(s) a traiter avec {args.model}.")

    n_already_done = sum(already_processed(output_root / p.stem) for p in images)
    if n_already_done:
        print(f"{n_already_done} image(s) deja traitee(s) lors d'un run precedent -> reprises sans reinference.")

    # On ne charge le (gros) modele que si au moins une image reste a traiter.
    pipeline = None
    model_title = {"paddleocr-vl": "PaddleOCR-VL", "ppstructure": "PP-StructureV3",
                   "hunyuan": "HunyuanOCR-1.5"}[args.model]

    def get_pipeline():
        nonlocal pipeline
        if pipeline is None:
            if args.model == "paddleocr-vl":
                from paddleocr import PaddleOCRVL
                print("Chargement de PaddleOCR-VL...")
                pipeline = PaddleOCRVL(pipeline_version="v1")
            elif args.model == "ppstructure":
                from paddleocr import PPStructureV3
                print("Chargement de PP-StructureV3...")
                # enable_mkldnn=False : contourne le bug PaddlePaddle 3.3.x oneDNN/PIR sur CPU
                pipeline = PPStructureV3(enable_mkldnn=False)
            else:
                print("Chargement de HunyuanOCR-1.5...")
                pipeline = _load_hunyuan()
        return pipeline

    def process(image_path: Path, img_output_dir: Path):
        """Lance le modele et ecrit un .md dans img_output_dir.

        PaddleOCR expose des objets resultat qui savent se serialiser ;
        HunyuanOCR rend du texte brut, qu'on ecrit nous-memes."""
        if args.model == "hunyuan":
            processor, model = get_pipeline()
            text = _hunyuan_predict(processor, model, image_path)
            (img_output_dir / f"{image_path.stem}.md").write_text(text, encoding="utf-8")
            return
        for res in get_pipeline().predict(str(image_path)):
            res.save_to_json(save_path=str(img_output_dir))
            res.save_to_markdown(save_path=str(img_output_dir))
            res.save_to_img(save_path=str(img_output_dir))

    def flush_report(entries):
        """Reecrit le rapport complet sur disque -> jamais plus de 1 image de perte si on arrete le script."""
        html = [HTML_HEADER.format(model_title=model_title, dataset_name=dataset_name)]
        html.extend(entries)
        html.append("</body></html>")
        report_path.write_text("".join(html), encoding="utf-8")

    entries = []
    for i, image_path in enumerate(images, start=1):
        img_output_dir = output_root / image_path.stem

        if already_processed(img_output_dir):
            print(f"[{i}/{len(images)}] {image_path.name} -> deja fait, reutilise le resultat existant")
            entries.append(build_entry(image_path, img_output_dir, meta="Repris d'un run precedent (pas retraite)"))
            flush_report(entries)
            continue

        print(f"[{i}/{len(images)}] {image_path.name}")
        img_output_dir.mkdir(parents=True, exist_ok=True)

        start = time.time()
        try:
            process(image_path, img_output_dir)
        except Exception as e:
            print(f"  -> ECHEC : {e}")
            entries.append(HTML_ENTRY.format(
                name=image_path.name, image_uri=image_to_data_uri(image_path),
                meta="Erreur lors du traitement", content=f"<em>Erreur : {e}</em>",
            ))
            flush_report(entries)
            continue
        elapsed = time.time() - start

        entries.append(build_entry(image_path, img_output_dir, meta=f"Temps de traitement : {elapsed:.1f}s"))
        flush_report(entries)
        print(f"  -> termine en {elapsed:.1f}s (rapport mis a jour : {len(entries)}/{len(images)})")

    print(f"\nRapport genere : {report_path.resolve()}")

    import webbrowser
    webbrowser.open(report_path.resolve().as_uri())


if __name__ == "__main__":
    main()
