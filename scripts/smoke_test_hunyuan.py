"""
Test a une seule image de HunyuanOCR-1.5, AVANT tout benchmark.

Objectif : repondre a la seule question qui bloque, savoir si le modele tient
dans les 4 Go de VRAM de la RTX 3050 Ti. Le README annonce 20 Go, mais c'est
la pre-allocation de vLLM : le modele ne fait qu'1 milliard de parametres,
soit ~2 Go de poids en bfloat16. Le reste depend de la resolution d'image.

Le script essaie le GPU, et bascule automatiquement sur le CPU s'il manque de
memoire -- en signalant clairement lequel des deux a servi, et en combien de
temps.

Usage :
    python scripts/smoke_test_hunyuan.py --image "..\\doc3D-renderer\\img\\multipage_test\\page_1-concave_mesh_10001.png"
    python scripts/smoke_test_hunyuan.py --image ... --device cpu
    python scripts/smoke_test_hunyuan.py --image ... --max-pixels 1000000
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from env_check import require as _require_env
_require_env("hunyuan")


import argparse
import time
import traceback
from pathlib import Path

import torch
from PIL import Image

MODEL_ID = "tencent/HunyuanOCR"

# Prompts officiels (le depot deconseille de les reecrire : les performances
# annoncees sont mesurees avec ceux-la).
PROMPTS = {
    # Ce qui nous interesse : le tableau directement en HTML, donc
    # directement exploitable par table_merge.py.
    "table": "把图中的表格解析为 HTML。",
    # Parsing complet de la page (texte + tableaux en HTML), equivalent de ce
    # que produisent PaddleOCR-VL / PP-StructureV3 dans nos benchmarks.
    "document": ("提取文档图片中正文的所有信息用markdown格式表示，其中页眉、页脚部分忽略，"
                 "表格用html格式表达，文档中公式用latex格式表示，按照阅读顺序组织进行解析。"),
    # Variante en anglais : a essayer si les prompts chinois ci-dessus (issus
    # du README de la version 1.0) ne declenchent pas la bonne tache sur les
    # poids 1.5.
    "document_en": ("Parse all the content of this document image into markdown. "
                    "Represent tables in HTML format. Ignore headers and footers. "
                    "Follow the natural reading order."),
    "table_en": "Parse the table in this image into HTML.",
}


DTYPES = {"bfloat16": torch.bfloat16, "float16": torch.float16, "float32": torch.float32}


def load_model(device: str, backend: str, dtype: str):
    from transformers import AutoProcessor

    # backend="pil" par defaut : le backend torchvision remplace le
    # reechantillonnage LANCZOS par BICUBIC (torchvision < 0.27), ce qui
    # ecarte le pretraitement de celui du modele original. Constate en
    # pratique : sortie correcte avec PIL, charabia avec torchvision.
    processor = AutoProcessor.from_pretrained(MODEL_ID, backend=backend,
                                              trust_remote_code=True)

    try:
        from transformers import HunYuanVLForConditionalGeneration as ModelClass
    except ImportError:
        # Selon la version de transformers, la classe peut ne pas etre
        # exportee au niveau du package.
        from transformers import AutoModelForCausalLM as ModelClass

    model = ModelClass.from_pretrained(
        MODEL_ID,
        attn_implementation="eager",
        dtype=DTYPES[dtype],
        device_map=device,
        trust_remote_code=True,
    )
    return processor, model


def run(image_path: Path, device: str, prompt: str, max_pixels, backend, dtype):
    processor, model = load_model(device, backend, dtype)
    print(f"  backend image : {backend}   precision : {dtype}")
    print(f"  prompt : {prompt[:70]}{'...' if len(prompt) > 70 else ''}")

    image = Image.open(image_path).convert("RGB")
    if max_pixels and image.width * image.height > max_pixels:
        ratio = (max_pixels / (image.width * image.height)) ** 0.5
        new_size = (int(image.width * ratio), int(image.height * ratio))
        print(f"  image redimensionnee {image.size} -> {new_size} (--max-pixels)")
        image = image.resize(new_size, Image.LANCZOS)

    messages = [
        {"role": "system", "content": ""},
        {"role": "user", "content": [
            {"type": "image", "image": str(image_path)},
            {"type": "text", "text": prompt},
        ]},
    ]
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = processor(text=[text], images=image, padding=True, return_tensors="pt")
    inputs = inputs.to(next(model.parameters()).device)

    start = time.time()
    with torch.no_grad():
        generated = model.generate(**inputs, max_new_tokens=4096, do_sample=False,
                                   repetition_penalty=1.08)
    elapsed = time.time() - start

    input_ids = inputs["input_ids"]
    trimmed = [out[len(inp):] for inp, out in zip(input_ids, generated)]
    output = processor.batch_decode(trimmed, skip_special_tokens=True,
                                    clean_up_tokenization_spaces=False)[0]
    return output, elapsed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto")
    parser.add_argument("--prompt", choices=list(PROMPTS), default="document")
    parser.add_argument("--prompt-text", default=None,
                        help="Prompt libre, remplace --prompt (pour tatonner)")
    parser.add_argument("--backend", choices=["pil", "torchvision"], default="pil",
                        help="Backend du processeur d'images. pil = conforme au "
                             "modele original (LANCZOS)")
    parser.add_argument("--dtype", choices=list(DTYPES), default="bfloat16",
                        help="Precision sur GPU (le CPU reste en float32)")
    parser.add_argument("--max-pixels", type=int, default=None,
                        help="Reduit l'image si elle depasse ce nombre de pixels "
                             "(premier levier a essayer en cas de manque de VRAM)")
    args = parser.parse_args()

    image_path = Path(args.image)
    if not image_path.exists():
        print(f"Image introuvable : {image_path}")
        return

    devices = ["cuda", "cpu"] if args.device == "auto" else [args.device]
    if "cuda" in devices and not torch.cuda.is_available():
        print("CUDA indisponible -> CPU directement.")
        devices = ["cpu"]

    for device in devices:
        print(f"\n=== Essai sur {device.upper()} ===")
        if device == "cuda":
            total = torch.cuda.get_device_properties(0).total_memory / 1e9
            print(f"  GPU : {torch.cuda.get_device_name(0)} ({total:.1f} Go)")
            torch.cuda.reset_peak_memory_stats()
        try:
            output, elapsed = run(image_path, device,
                                  args.prompt_text or PROMPTS[args.prompt],
                                  args.max_pixels, args.backend,
                                  args.dtype if device == "cuda" else "float32")
        except torch.cuda.OutOfMemoryError:
            print("  ECHEC : memoire GPU insuffisante.")
            print("  -> reessaie avec --max-pixels 1000000 avant de conclure.")
            torch.cuda.empty_cache()
            continue
        except Exception:
            traceback.print_exc()
            continue

        if device == "cuda":
            peak = torch.cuda.max_memory_allocated() / 1e9
            print(f"  pic memoire GPU : {peak:.2f} Go")
        print(f"  temps : {elapsed:.1f}s")
        print(f"  sortie : {len(output)} caracteres, "
              f"{output.count('<table')} balise(s) <table>")
        print("\n--- 1500 premiers caracteres ---")
        print(output[:1500])

        out_file = Path(__file__).resolve().parent.parent / "results" / "smoke_hunyuan.md"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(output, encoding="utf-8")
        print(f"\nSortie complete : {out_file}")
        return

    print("\nAucun peripherique n'a fonctionne.")


if __name__ == "__main__":
    main()
