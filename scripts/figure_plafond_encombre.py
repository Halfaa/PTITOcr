"""
Cluttered backgrounds: seven method families against a demonstrated ceiling.

Regenerates `demo/figures/13_plafond_fonds_encombres.png`. The original plate
was drawn by hand in a throwaway session and existed only as a PNG, in French,
with no way to reproduce it. This script is that missing source.

Where the numbers come from
---------------------------
`docs/fonds_encombres.md`, section 12 ("Deux tentatives de plus pour approcher
l'oracle"), which is the last consolidated table of the whole cropping effort.
Every family is a best-case per-family ceiling, taken over all its variants on
the 25-page cluttered set. Nothing here is recomputed: the script draws the
recorded measurement, so it must stay in step with that table.

The ORACLE bar is not a method. It scores the EXACT sheet outline taken from
the UV ground truth, so it cheats by construction. It is there to answer the
only question that makes the other bars meaningful: is 0.70 reachable at all
on this set? It is, at 0.85, which turns seven separate failures into one
property of the problem.

    python scripts/figure_plafond_encombre.py
"""

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

RACINE = Path(__file__).resolve().parent.parent
SORTIE = RACINE / "demo" / "figures" / "13_plafond_fonds_encombres.png"

# docs/fonds_encombres.md, section 12. Order is the order they were tried.
FAMILLES = [
    ("Thresholding + GrabCut\n(in production)", 0.52),
    ("SAM / FastSAM", 0.56),
    ("Text blocks\n(morphology)", 0.33),
    ("Text blocks\n(learned DBNet)", 0.43),
    ("PaddleOCR-VL\nlayout boxes", 0.49),
    ("GrabCut seeded by\nthe distractor sheets", 0.47),
    ("Rotated rectangle\naround the text", 0.47),
    ("All unions combined", 0.59),
]
ORACLE = 0.85
EXPLOITABLE = 0.70

ROUGE = "#c0392b"
BLEU = "#2c5d8f"


def main():
    fig, ax = plt.subplots(figsize=(12.6, 5.6))

    noms = [n for n, _ in FAMILLES]
    vals = [v for _, v in FAMILLES]
    y = range(len(FAMILLES))

    ax.barh(y, vals, color=ROUGE, height=0.62)
    for i, v in enumerate(vals):
        ax.text(v + 0.012, i, f"{v:.2f}", va="center", fontsize=11)

    ax.set_yticks(list(y))
    ax.set_yticklabels(noms, fontsize=11)
    ax.invert_yaxis()

    ax.set_xlim(0, 1.0)
    ax.set_xlabel("Cropping IoU (cluttered-background set, 25 pages)",
                  fontsize=12)
    ax.grid(axis="x", alpha=0.25)
    ax.set_axisbelow(True)

    ax.axvline(EXPLOITABLE, color="#555555", ls="--", lw=1.6)
    ax.axvline(ORACLE, color=BLEU, lw=2.4)

    # Les deux reperes sont a 0,15 l'un de l'autre : empiles, leurs etiquettes
    # se chevauchaient dans la planche d'origine. Celle du seuil passe donc a
    # gauche de son trait, celle de l'oracle a droite du sien.
    ax.text(EXPLOITABLE - 0.012, -0.72, "usability threshold 0.70",
            ha="right", va="center", fontsize=10.5, color="#555555")
    ax.text(ORACLE + 0.012, -0.95, "ORACLE 0.85",
            ha="left", va="center", fontsize=11.5, color=BLEU, weight="bold")
    ax.text(ORACLE + 0.012, -0.52, "exact outline of the sheet",
            ha="left", va="center", fontsize=10, color=BLEU)

    ax.set_title("Cluttered backgrounds: seven method families, one shared "
                 "ceiling,\nand a target demonstrated to be reachable",
                 fontsize=14, pad=16)

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(SORTIE, dpi=130, bbox_inches="tight")
    print(f"figure : {SORTIE}")


if __name__ == "__main__":
    main()
