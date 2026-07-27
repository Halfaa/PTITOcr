"""
Verification de l'environnement virtuel actif.

Le projet utilise DEUX venv, parce que leurs dependances sont incompatibles :

    venv/          PaddleOCR-VL, PP-StructureV3, evaluation (transformers 4.x)
    venv_hunyuan/  HunyuanOCR-1.5 uniquement (transformers >= 5.13, Python 3.12)

Sans garde-fou, lancer un script depuis le mauvais venv produit soit un
ImportError obscur, soit -- pire -- un plantage apres plusieurs minutes de
chargement de modele. Ce module echoue immediatement, avec la commande exacte
a taper pour corriger.
"""

import importlib.metadata
import importlib.util
import sys
from pathlib import Path

ENVIRONMENTS = {
    "paddle": {
        "venv": "venv",
        "purpose": "PaddleOCR-VL / PP-StructureV3",
        "packages": ["paddleocr"],
    },
    "eval": {
        "venv": "venv",
        "purpose": "évaluation (TEDS, fusion multi-pages)",
        "packages": ["apted", "fitz"],
        "install_hint": "pip install apted PyMuPDF",
    },
    "hunyuan": {
        "venv": "venv_hunyuan",
        "purpose": "HunyuanOCR-1.5",
        # torchvision : requis par le processeur d'images de HunyuanOCR.
        # numpy : requis par torch, mais absent d'un venv fraichement cree.
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
    return prefix.name if prefix != Path(sys.base_prefix) else "aucun (Python système)"


def require(env_name: str) -> None:
    """Interrompt le script si l'environnement actif ne convient pas."""
    spec = ENVIRONMENTS[env_name]
    problems = []

    # Le nom du venv n'est qu'un indice (on peut le nommer autrement, ou
    # utiliser conda) : on AVERTIT sans bloquer. Cet avertissement reste
    # precieux -- un Python systeme qui possede par hasard les bons paquets
    # passe tous les autres controles, et on se retrouve a tourner sur un
    # PyTorch sans CUDA sans comprendre pourquoi (cas reellement rencontre).
    active = _active_venv()
    if active != spec["venv"]:
        print(f"[env] Attention : venv attendu '{spec['venv']}', "
              f"venv actif '{active}'\n"
              f"[env] Python utilisé : {sys.executable}", file=sys.stderr)

    for package in spec["packages"]:
        if importlib.util.find_spec(package) is None:
            problems.append(f"paquet absent : {package}")
            continue
        minimum = spec.get("min_versions", {}).get(package)
        if minimum:
            found = _parsed_version(package)
            if found and found < minimum:
                problems.append(
                    f"{package} {'.'.join(map(str, found))} trop ancien "
                    f"(il faut >= {'.'.join(map(str, minimum))})"
                )

    if not problems:
        return

    expected = spec["venv"]
    print("=" * 70, file=sys.stderr)
    print(f"MAUVAIS ENVIRONNEMENT pour {Path(sys.argv[0]).name}", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    print(f"  Ce script a besoin de : {spec['purpose']}", file=sys.stderr)
    print(f"  Venv attendu          : {expected}", file=sys.stderr)
    print(f"  Venv actif            : {_active_venv()}", file=sys.stderr)
    print(f"  Python utilisé        : {sys.executable}", file=sys.stderr)
    for problem in problems:
        print(f"  Problème              : {problem}", file=sys.stderr)
    print(f"\n  Corriger :\n      .\\{expected}\\Scripts\\Activate.ps1", file=sys.stderr)
    if spec.get("install_hint"):
        print(f"      {spec['install_hint']}", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    sys.exit(1)
