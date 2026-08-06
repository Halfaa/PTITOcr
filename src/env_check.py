"""
Active virtual-environment check.

The project uses TWO virtualenvs, because their dependencies are mutually
incompatible:

    venv/          PaddleOCR-VL, PP-StructureV3, evaluation (transformers 4.x)
    venv_hunyuan/  HunyuanOCR-1.5 only (transformers >= 5.13)

Without a guard, running a script from the wrong venv produces either an
obscure ImportError or -- worse -- a crash after several minutes of model
loading. This module fails immediately, printing the exact command to fix it.
"""

import importlib.metadata
import importlib.util
import sys
from pathlib import Path

ENVIRONMENTS = {
    "paddle": {
        "venv": "venv",
        "purpose": "PaddleOCR-VL / PP-StructureV3",
        "packages": ["paddleocr", "numpy"],
        # numpy < 2 is a hard constraint of paddlex, and violating it is
        # expensive to diagnose: PaddleOCR catches the ImportError and
        # re-raises "a dependency error occurred during pipeline creation",
        # naming neither numpy nor the real exception. Every image of the run
        # then fails identically. Any later `pip install` can silently pull
        # numpy 2.x in as a transitive dependency -- this has happened.
        "max_versions": {"numpy": (2, 0)},
        "install_hint": "pip install \"numpy<2\"",
    },
    "eval": {
        "venv": "venv",
        "purpose": "evaluation (TEDS, multi-page merging)",
        "packages": ["apted", "fitz"],
        "install_hint": "pip install apted PyMuPDF",
    },
    "chandra": {
        # venv None = no particular environment expected. Chandra is CPU-only
        # (5B parameters cannot fit in 4 GB of VRAM), so a CUDA build brings
        # nothing and there is no reason to duplicate 3 GB of torch into the
        # Paddle venv. Wherever it is installed, it runs at the same speed.
        "venv": None,
        "purpose": "Chandra OCR 2 (CPU only)",
        "packages": ["chandra", "torch", "transformers"],
        "install_hint": "pip install \"chandra-ocr[hf]\"",
    },
    "glm": {
        # Meme venv que HunyuanOCR : tous deux veulent un transformers recent
        # et sont donc incompatibles avec le venv Paddle. L'architecture
        # `glm_ocr` est plus recente encore que celle de Hunyuan -- si le
        # chargement echoue sur KeyError: 'glm_ocr', c'est la version de
        # developpement de transformers qu'il faut, pas une erreur de code.
        "venv": "venv_hunyuan",
        "purpose": "GLM-OCR (0,9 B, tient en 4 Go)",
        "packages": ["transformers", "torch", "torchvision", "numpy", "PIL"],
        "min_versions": {"transformers": (5, 14)},
        "install_hint": ("pip install git+https://github.com/huggingface/"
                         "transformers.git"),
    },
    "hunyuan": {
        "venv": "venv_hunyuan",
        "purpose": "HunyuanOCR-1.5",
        # torchvision: required by HunyuanOCR's image processor.
        # numpy: required by torch, but absent from a freshly created venv.
        "packages": ["transformers", "torch", "torchvision", "numpy", "PIL"],
        "min_versions": {"transformers": (5, 13)},
        "install_hint": ("pip install torch torchvision --index-url "
                         "https://download.pytorch.org/whl/cu128\n"
                         "      pip install \"transformers>=5.13.0\" accelerate pillow numpy"),
    },
}


def _parsed_version(package: str):
    try:
        raw = importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None
    parts = []
    for chunk in raw.split(".")[:2]:
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def _active_venv() -> str:
    prefix = Path(sys.prefix)
    return prefix.name if prefix != Path(sys.base_prefix) else "none (system Python)"


def require(env_name: str) -> None:
    """Abort the script if the active environment is not suitable."""
    spec = ENVIRONMENTS[env_name]
    problems = []

    # The venv name is only a hint (it may be named differently, or conda
    # may be used): we WARN without blocking. The warning is still valuable
    # -- a system Python that happens to hold the right packages passes every
    # other check, and you end up running on a CUDA-less PyTorch without
    # understanding why (this actually happened).
    active = _active_venv()
    if spec["venv"] is not None and active != spec["venv"]:
        print(f"[env] Warning: expected venv '{spec['venv']}', "
              f"active venv '{active}'\n"
              f"[env] Python in use: {sys.executable}", file=sys.stderr)

    for package in spec["packages"]:
        if importlib.util.find_spec(package) is None:
            problems.append(f"missing package: {package}")
            continue
        minimum = spec.get("min_versions", {}).get(package)
        if minimum:
            found = _parsed_version(package)
            if found and found < minimum:
                problems.append(
                    f"{package} {'.'.join(map(str, found))} too old "
                    f"(need >= {'.'.join(map(str, minimum))})"
                )
        maximum = spec.get("max_versions", {}).get(package)
        if maximum:
            found = _parsed_version(package)
            if found and found >= maximum:
                problems.append(
                    f"{package} {'.'.join(map(str, found))} too recent "
                    f"(need < {'.'.join(map(str, maximum))})"
                )

    if not problems:
        return

    expected = spec["venv"] or "any (no specific venv required)"
    print("=" * 70, file=sys.stderr)
    print(f"WRONG ENVIRONMENT for {Path(sys.argv[0]).name}", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    print(f"  This script needs     : {spec['purpose']}", file=sys.stderr)
    print(f"  Expected venv         : {expected}", file=sys.stderr)
    print(f"  Active venv           : {_active_venv()}", file=sys.stderr)
    print(f"  Python in use         : {sys.executable}", file=sys.stderr)
    for problem in problems:
        print(f"  Problem               : {problem}", file=sys.stderr)
    if spec["venv"]:
        print(f"\n  Fix:\n      .\\{spec['venv']}\\Scripts\\Activate.ps1", file=sys.stderr)
    else:
        print("\n  Fix:", file=sys.stderr)
    if spec.get("install_hint"):
        print(f"      {spec['install_hint']}", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    sys.exit(1)
