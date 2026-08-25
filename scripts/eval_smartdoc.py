"""
Notre détecteur de feuille, sur de VRAIES photos : SmartDoc 2015 — Challenge 1.

Pourquoi ce jeu précisément. Notre jeu à fonds encombrés superpose deux
difficultés — l'encombrement ET une déformation 3D très forte (écart mesuré
des bords à leur quadrilatère : 7,6 % de la diagonale). Le plafond de 0,59
mesure donc les deux à la fois, et on ne sait pas lequel domine.

SmartDoc les sépare, par construction : **les mêmes 30 documents sont
photographiés sur 5 fonds différents**, avec le même appareil et les mêmes
gestes. Seul le fond change. Et le cinquième est exactement notre cas —

    « the target document placed on top of a stack of papers, where four
      sides of another A4 page are partially visible »

Les feuilles y sont posées à plat sur une table, donc peu déformées, et ce
sont de vraies photos : profondeur de champ, flou de bougé, changements
d'éclairage, occlusions partielles.

Ce que la comparaison tranche
-----------------------------
Si notre IoU s'effondre de background01 à background05, **l'encombrement seul
suffit à casser la localisation**, et notre résultat négatif vaut pour le
monde réel.

S'il tient, alors ce qui casse notre jeu synthétique n'est pas l'encombrement
mais la déformation — ou l'absence de profondeur de champ, qui prive d'un
indice que la vraie photo fournit. Dans ce cas notre benchmark est
artificiellement pessimiste, et il faut le dire avant de conclure quoi que
ce soit sur la méthode.

Obtenir le jeu (1 fois, ~2 Go)
------------------------------
    curl.exe -L -o frames.tar.gz https://github.com/jchazalon/smartdoc15-ch1-dataset/releases/download/v2.0.0/frames.tar.gz
    mkdir ..\\smartdoc
    tar -xzf frames.tar.gz -C ..\\smartdoc

`curl.exe`, avec le .exe : sous PowerShell, `curl` tout court est un alias
d'`Invoke-WebRequest`, qui ne connait pas `-L` et repond « Impossible de
trouver un parametre correspondant au nom L ». L'equivalent natif serait
`Invoke-WebRequest -Uri <url> -OutFile frames.tar.gz`, qui suit les
redirections sans qu'on le lui demande.

Licence CC-BY 4.0. Citer : Burie et al., « ICDAR2015 Competition on Smartphone
Document Capture and OCR (SmartDoc) », ICDAR 2015.

    python scripts/eval_smartdoc.py --racine ..\\smartdoc
    python scripts/eval_smartdoc.py --racine ..\\smartdoc --pas 40
"""

import argparse
import csv
import gzip
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "src"))

try:
    import cv2
    import numpy as np
except ImportError:
    raise SystemExit("Il faut opencv et numpy :\n"
                     "    pip install 'opencv-python<4.12' 'numpy<2'")

from preprocess import detect_document_quad  # noqa: E402

SEUIL = 0.70


def iou(quad, verite, forme):
    """IoU entre deux quadrilatères, rastérisés à la taille de l'image."""
    if quad is None:
        return 0.0
    a = np.zeros(forme, np.uint8)
    b = np.zeros(forme, np.uint8)
    cv2.fillPoly(a, [np.asarray(quad, np.int32)], 1)
    cv2.fillPoly(b, [np.asarray(verite, np.int32)], 1)
    a, b = a.astype(bool), b.astype(bool)
    u = (a | b).sum()
    return float((a & b).sum() / u) if u else 0.0


def lire_metadonnees(racine):
    chemin = racine / "metadata.csv.gz"
    if not chemin.exists():
        raise SystemExit(
            f"{chemin} absent.\nTéléverse et décompresse frames.tar.gz — voir "
            "l'en-tête de ce script.")
    with gzip.open(chemin, "rt", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--racine", required=True,
                   help="Dossier où frames.tar.gz a été décompressé.")
    p.add_argument("--pas", type=int, default=25,
                   help="N'évaluer qu'une image sur N. 24 889 images au "
                        "total ; un pas de 25 en laisse ~1 000, assez pour "
                        "comparer les fonds et rapide.")
    p.add_argument("--min-score", type=float, default=0.55)
    args = p.parse_args()

    racine = Path(args.racine)
    lignes = lire_metadonnees(racine)
    print(f"{len(lignes)} images décrites, une sur {args.pas} évaluée\n")

    par_fond = {}
    for i, ligne in enumerate(lignes):
        if i % args.pas:
            continue
        chemin = racine / ligne["image_path"]
        if not chemin.exists():
            continue
        image = cv2.imread(str(chemin))
        if image is None:
            continue

        # La vérité terrain est donnée dans l'ordre haut-gauche, bas-gauche,
        # bas-droite, haut-droite -- déjà cyclique, on la garde telle quelle.
        verite = np.array([[float(ligne["tl_x"]), float(ligne["tl_y"])],
                           [float(ligne["bl_x"]), float(ligne["bl_y"])],
                           [float(ligne["br_x"]), float(ligne["br_y"])],
                           [float(ligne["tr_x"]), float(ligne["tr_y"])]],
                          dtype=np.float32)

        trouve = detect_document_quad(image, min_score=args.min_score,
                                      return_score=True)
        quad = trouve[0] if isinstance(trouve, tuple) else None
        score = iou(quad, verite, image.shape[:2])

        fond = par_fond.setdefault(ligne["bg_name"], {"scores": [], "recadre": 0})
        fond["scores"].append(score)
        fond["recadre"] += quad is not None

    if not par_fond:
        raise SystemExit("Aucune image lue : vérifie --racine.")

    print(f"{'fond':<16}{'images':>8}{'IoU moyen':>12}{'recadrées':>12}"
          f"{'exploitables':>15}")
    print("-" * 63)
    for nom in sorted(par_fond):
        d = par_fond[nom]
        n = len(d["scores"])
        util = sum(s >= SEUIL for s in d["scores"])
        moyen = float(np.mean(d["scores"]))
        recadre = f"{d['recadre']}/{n}"
        print(f"{nom:<16}{n:>8}{moyen:>12.2f}{recadre:>12}"
              f"{f'{util}/{n}':>15}")
    print("-" * 63)

    print("\nLecture. `background05` est le fond encombré : le document posé")
    print("sur une pile de papiers. Les autres vont du bureau nu au fond")
    print("moyennement chargé. Comme ce sont LES MÊMES documents photographiés")
    print("de la même façon, l'écart entre les fonds ne mesure que le fond.")
    print("\nSi l'IoU s'effondre sur background05, l'encombrement seul suffit")
    print("à casser la localisation, et notre résultat négatif vaut pour le")
    print("réel. S'il tient, c'est la déformation de nos rendus — ou l'absence")
    print("de profondeur de champ — qui explique notre plafond de 0,59.")


if __name__ == "__main__":
    main()
