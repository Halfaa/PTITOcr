"""
Tracer la courbe de robustesse : TEDS en fonction de la qualité de l'image.

Lit les runs `degradation_<lot>_chandra` produits par le notebook Kaggle et
rend, pour chaque dégradation, le TEDS palier par palier plus le point de
rupture — le premier palier où le score passe sous un seuil utilisable.

Ce que ce script cherche, et pourquoi ce n'est pas « un tableau de plus » :
une note moyenne dit si la chaîne marche, une courbe dit **jusqu'où**. C'est
la différence entre « 0,97 sur nos rendus » et « il faut au moins tel niveau
de netteté », qui est une spécification exploitable par le contrôle qualité à
la capture.

Toutes les mesures sont APPARIÉES : mêmes 4 factures à tous les paliers, donc
l'écart entre deux paliers ne peut pas venir d'un échantillon différent.

    python scripts/eval_degradation.py
    python scripts/eval_degradation.py --figure
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "scripts"))

GEN = RACINE.parent / "synthetic_invoice_generator" / "hospital_pharmacy"
PDF = GEN / "invoices_variants.pdf"
GT = GEN / "ground_truth_labels_variants"

from degrader import NIVEAUX  # noqa: E402

# En dessous, la facture n'est plus exploitable sans relecture humaine
# intégrale — c'est le seuil déjà retenu pour le recadrage, gardé identique
# pour que les deux études se lisent ensemble.
SEUIL = 0.70

UNITES = {
    "flou": "px de bougé",
    "bruit": "photons à saturation",
    "exposition": "diaphragmes sous-exposés",
    "resolution": "fraction du côté long",
    "jpeg": "qualité JPEG",
}


def teds_du_run(run: str):
    """TEDS avec fusion, ou None si le run n'existe pas."""
    if not (RACINE / "results" / run / "pages").is_dir():
        return None
    r = subprocess.run(
        [sys.executable, "src/eval_teds.py", "--run", run,
         "--pdf", str(PDF), "--gt-dir", str(GT)],
        cwd=RACINE, capture_output=True, text=True, timeout=600)
    m = re.search(r"^TEDS\s+([\d.]+)", r.stdout, re.M)
    return float(m.group(1)) if m else None


def rupture(valeurs, scores, reference):
    """Premier palier sous le seuil, et la perte qu'il représente.

    On rend la VALEUR physique, pas le numéro de palier : « le bougé devient
    fatal au-delà de 9 px » se transporte dans un cahier des charges, « au
    palier 3 » non.
    """
    for valeur, score in zip(valeurs, scores):
        if score is not None and score < SEUIL:
            return valeur, score
    return None, None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--prefixe", default="degradation_")
    p.add_argument("--suffixe", default="_chandra")
    p.add_argument("--figure", action="store_true")
    args = p.parse_args()

    reference = teds_du_run(f"{args.prefixe}niveau0{args.suffixe}")
    if reference is None:
        raise SystemExit(
            f"Le run de référence '{args.prefixe}niveau0{args.suffixe}' est "
            "absent.\nSans lui, aucune comparaison n'a de sens : c'est la "
            "même page,\npassée par le même code, sans dégradation.")

    print(f"Référence (niveau 0) : TEDS {reference:.3f}")
    print(f"Seuil d'exploitabilité : {SEUIL:.2f}\n")

    tout = {}
    for degradation, valeurs in NIVEAUX.items():
        scores = [teds_du_run(f"{args.prefixe}{degradation}{i}{args.suffixe}")
                  for i in range(1, len(valeurs) + 1)]
        tout[degradation] = (valeurs, scores)

        entete = f"{degradation}  ({UNITES[degradation]})"
        print(entete)
        print("  " + "".join(f"{v:>9g}" for v in valeurs))
        print("  " + "".join(
            f"{('--' if s is None else f'{s:.3f}'):>9}" for s in scores))
        seuil_v, seuil_s = rupture(valeurs, scores, reference)
        if seuil_v is None:
            print(f"  -> tient sur toute l'échelle testée "
                  f"(au pire {min(s for s in scores if s is not None):.3f})")
        else:
            print(f"  -> rupture à {seuil_v:g} {UNITES[degradation]} "
                  f"(TEDS {seuil_s:.3f})")
        print()

    manquants = sum(1 for _, s in tout.values() for x in s if x is None)
    if manquants:
        print(f"{manquants} palier(s) sans run : la courbe est incomplète.\n")

    print("Lecture. Le point de rupture est une SPÉCIFICATION : il dit ce que")
    print("le contrôle qualité à la capture doit refuser. Une dégradation qui")
    print("tient sur toute l'échelle n'est pas une menace pour la chaîne, et")
    print("c'est un résultat aussi utile que l'inverse.")

    if args.figure:
        tracer(tout, reference)


def tracer(tout, reference):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("\n(figure sautée : pip install matplotlib)")
        return

    fig, axes = plt.subplots(1, len(tout), figsize=(4 * len(tout), 3.6),
                             sharey=True)
    for ax, (degradation, (valeurs, scores)) in zip(axes, tout.items()):
        x = list(range(1, len(valeurs) + 1))
        ax.axhline(reference, color="0.5", ls=":", lw=1)
        ax.axhline(SEUIL, color="crimson", ls="--", lw=1)
        connus = [(a, b) for a, b in zip(x, scores) if b is not None]
        if connus:
            ax.plot([a for a, _ in connus], [b for _, b in connus],
                    "o-", color="#1f4e79")
        ax.set_xticks(x)
        ax.set_xticklabels([f"{v:g}" for v in valeurs], fontsize=8)
        ax.set_title(f"{degradation}\n{UNITES[degradation]}", fontsize=9)
        ax.set_ylim(0, 1.02)
        ax.grid(alpha=0.25)
    axes[0].set_ylabel("TEDS")
    fig.suptitle("Robustesse de la chaîne — pointillé gris : référence "
                 f"({reference:.3f}) · tireté rouge : seuil {SEUIL:.2f}",
                 fontsize=10)
    fig.tight_layout()
    sortie = RACINE / "demo" / "figures" / "12_courbe_degradation.png"
    sortie.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(sortie, dpi=140)
    print(f"\nFigure -> {sortie}")


if __name__ == "__main__":
    main()
