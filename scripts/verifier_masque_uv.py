"""
Le masque UV contient-il autre chose que la feuille cible ?

C'est LA question à trancher avant de croire un chiffre mesuré sur un jeu à
fonds encombrés. Si les feuilles parasites ont fui dans la passe UV, la
vérité terrain du recadrage inclut des documents qui ne sont pas la cible —
et l'IoU devient faux sans qu'aucune erreur ne soit levée.

--------------------------------------------------------------------------
Pourquoi on ne compare PAS deux jeux entre eux

La première version de ce script comparait l'aire du masque entre le jeu
propre et le jeu encombré, en supposant que seuls les parasites changeaient.
C'était faux, et le résultat l'a montré : les aires variaient dans les **deux
sens**, jusqu'à -41 % et +49 %. Une fuite ne peut qu'agrandir un masque.

La cause est dans `render_mesh_multipage.py` : la caméra, la carte HDR et
l'éclairage sont tirés du module `random` **sans jamais l'initialiser**. Deux
lancements de Blender donnent donc des vues différentes pour la même page, et
les deux jeux ne sont pas appariables image par image.

D'où ce contrôle-ci, qui **ne dépend que du masque examiné** : la feuille
cible est un objet unique, donc son masque est d'un seul tenant. Plusieurs
taches séparées signifient qu'autre chose a été rendu dans la passe UV.

    python scripts/verifier_masque_uv.py --jeu variants_encombre
"""

import argparse
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
# Sans cette variable, OpenCV rend None sur un .exr -- silencieusement.
os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

DOC3D = RACINE.parent / "doc3D-renderer"

# Une tache secondaire au-dela de cette fraction de la principale n'est pas
# du bruit d'echantillonnage : c'est un autre objet. Cycles laisse quelques
# pixels isoles sur les bords, jamais 5 % de la surface.
SEUIL_TACHE = 0.05


def analyser(exr: Path) -> dict:
    """Composantes connexes du masque de feuille."""
    import cv2
    import numpy as np

    uv = cv2.imread(str(exr), cv2.IMREAD_UNCHANGED)
    if uv is None:
        raise SystemExit(
            f"Impossible de lire {exr.name}. OpenCV n'a pas le support "
            "OpenEXR actif dans cet environnement.")

    masque = (uv[:, :, 0] > 0.5).astype(np.uint8)
    # Une fermeture legere recolle les pixels que l'echantillonnage a troues,
    # sans jamais relier deux feuilles distinctes.
    masque = cv2.morphologyEx(masque, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))

    n, _, stats, _ = cv2.connectedComponentsWithStats(masque, 8)
    aires = sorted((stats[i, cv2.CC_STAT_AREA] for i in range(1, n)), reverse=True)
    total = masque.size

    principale = aires[0] if aires else 0
    secondaires = [a for a in aires[1:] if a > SEUIL_TACHE * principale]

    return {
        "aire": principale / total,
        "n_taches": 1 + len(secondaires),
        "secondaires": [round(a / principale, 3) for a in secondaires[:4]],
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--jeu", default="variants_encombre")
    args = p.parse_args()

    dossier = DOC3D / "uv" / args.jeu
    fichiers = sorted(dossier.glob("*.exr"),
                      key=lambda f: int("".join(c for c in f.stem.split("-")[0]
                                                if c.isdigit()) or 0))
    if not fichiers:
        raise SystemExit(f"Aucun .exr dans {dossier}")

    print(f"Composantes du masque UV — {args.jeu}\n")
    print(f"{'page':<10}{'aire':>9}{'taches':>9}   taches secondaires "
          f"(en fraction de la principale)")
    print("-" * 78)

    suspectes = []
    for f in fichiers:
        r = analyser(f)
        nom = f.stem.split("-")[0]
        if r["n_taches"] > 1:
            suspectes.append(nom)
        print(f"{nom:<10}{r['aire']:>9.4f}{r['n_taches']:>9}   "
              f"{r['secondaires'] if r['secondaires'] else ''}")

    print("-" * 78)
    print(f"{len(fichiers)} page(s)\n")

    if not suspectes:
        print("VERDICT : chaque masque est d'un seul tenant. Les parasites")
        print("sont bien exclus de la passe UV, la vérité terrain est saine.")
        print("Un IoU bas sur ce jeu est donc un VRAI résultat.")
    else:
        print(f"VERDICT : {len(suspectes)} masque(s) en plusieurs morceaux.")
        print(f"   {', '.join(suspectes[:12])}")
        print("\nLes parasites sont probablement rendus dans la passe UV.")
        print("Vérifier l'ordre dans render_pass : le masquage doit venir")
        print("APRÈS le rendu de l'image et AVANT celui de l'UV.")
        sys.exit(1)


if __name__ == "__main__":
    main()
