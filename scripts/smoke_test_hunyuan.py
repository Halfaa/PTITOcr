"""
Single-image smoke test for HunyuanOCR-1.5, BEFORE running any benchmark.

Goal: answer the one blocking question -- does the model fit in the 4 GB of
VRAM of the RTX 3050 Ti? The README announces 20 GB, but that is vLLM's
pre-allocation: the model has only 1 billion parameters, i.e. ~2 GB of
weights in bfloat16. The rest depends on image resolution.

The script tries the GPU and falls back to CPU automatically if it runs out
of memory -- clearly reporting which of the two was used, and how long it
took.

Usage:
    python scripts/smoke_test_hunyuan.py --image "..\\doc3D-renderer\\img\\multipage_test\\page_1-concave_mesh_10001.png"
    python scripts/smoke_test_hunyuan.py --image ... --device cpu
    python scripts/smoke_test_hunyuan.py --image ... --max-pixels 1000000
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from env_check import require as _require_env
from hunyuan_prompts import ALL as HUNYUAN_PROMPTS
_require_env("hunyuan")


import argparse
import time
import traceback
from pathlib import Path

import torch
from PIL import Image

MODEL_ID = "tencent/HunyuanOCR"

PROMPTS = HUNYUAN_PROMPTS

DTYPES = {"bfloat16": torch.bfloat16, "float16": torch.float16, "float32": torch.float32}


def load_model(device: str, backend: str, dtype: str):
    from transformers import AutoProcessor

    # backend="pil" by default: the torchvision backend replaces LANCZOS
    # resampling with BICUBIC (torchvision < 0.27), which departs from the
    # original model's preprocessing. Observed in practice: correct output
    # with PIL, gibberish with torchvision.
    processor = AutoProcessor.from_pretrained(MODEL_ID, backend=backend,
                                              trust_remote_code=True)

    try:
        from transformers import HunYuanVLForConditionalGeneration as ModelClass
    except ImportError:
        # Depending on the transformers version, the class may not be
        # exported at package level.
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
    print(f"  image backend: {backend}   precision: {dtype}")
    print(f"  prompt : {prompt[:70]}{'...' if len(prompt) > 70 else ''}")

    image = Image.open(image_path).convert("RGB")
    if max_pixels and image.width * image.height > max_pixels:
        ratio = (max_pixels / (image.width * image.height)) ** 0.5
        new_size = (int(image.width * ratio), int(image.height * ratio))
        print(f"  image resized {image.size} -> {new_size} (--max-pixels)")
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
                        help="Free-form prompt, overrides --prompt (for experimenting)")
    parser.add_argument("--backend", choices=["pil", "torchvision"], default="pil",
                        help="Image processor backend. pil = matches the "
                             "original model (LANCZOS)")
    parser.add_argument("--dtype", choices=list(DTYPES), default="bfloat16",
                        help="GPU precision (CPU stays in float32)")
    parser.add_argument("--max-pixels", type=int, default=None,
                        help="Downscale the image beyond this pixel count "
                             "(first lever to try when VRAM is short)")
    args = parser.parse_args()

    image_path = Path(args.image)
    if not image_path.exists():
        print(f"Image not found: {image_path}")
        return

    devices = ["cuda", "cpu"] if args.device == "auto" else [args.device]
    if "cuda" in devices and not torch.cuda.is_available():
        print("CUDA unavailable -> going straight to CPU.")
        devices = ["cpu"]

    for device in devices:
        print(f"\n=== Trying {device.upper()} ===")
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
            print("  FAILED: not enough GPU memory.")
            print("  -> retry with --max-pixels 1000000 before concluding.")
            torch.cuda.empty_cache()
            continue
        except Exception:
            traceback.print_exc()
            continue

        if device == "cuda":
            peak = torch.cuda.max_memory_allocated() / 1e9
            print(f"  peak GPU memory: {peak:.2f} GB")
        print(f"  time: {elapsed:.1f}s")
        print(f"  output: {len(output)} characters, "
              f"{output.count('<table')} <table> tag(s)")
        print("\n--- first 1500 characters ---")
        print(output[:1500])

        out_file = Path(__file__).resolve().parent.parent / "results" / "smoke_hunyuan.md"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(output, encoding="utf-8")
        print(f"\nFull output: {out_file}")
        return

    print("\nNo device worked.")


if __name__ == "__main__":
    main()
