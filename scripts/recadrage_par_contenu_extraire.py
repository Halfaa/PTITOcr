"""
Produire, en pixels, le recadrage retenu au §17 de `docs/fonds_encombres.md` :
la plus grande boîte `table` de PaddleOCR-VL, dilatée ×1,2, découpée dans
l'image PLEINE RÉSOLUTION -- pas la copie 1400 px utilisée pour mesurer l'IoU.

`recadrage_par_contenu.py` a mesuré la RÈGLE (0,578 IoU, 12/25 exploitables,
ne surajuste pas) ; ce script l'APPLIQUE, pour que `bench_deformed.py` puisse
lire les images qui en résultent et qu'on mesure enfin le TEDS de bout en
bout -- la question que le §17 laissait ouverte.

Pourquoi la pleine résolution et pas la copie de travail : le §17 mesure sur
des images réduites à 1400 px de grand côté, un choix qui accélère la mesure
d'IoU mais coûterait 40 à 70 % des pixels d'un texte déjà petit si on lisait
dessus (c'est exactement la mise en garde de `--min-long-side` dans
`preprocess.py`). Les coordonnées `coordinate` des `_res.json` de
PaddleOCR-VL sont déjà dans le repère de l'image ORIGINALE (vérifié : sur une
page 900×1200, la plus grande boîte table vaut [10, 271, 236, 431], bien à
l'intérieur des deux dimensions) -- donc `facteur=1.0` suffit, aucune remise
à l'échelle n'est nécessaire ici contrairement à `recadrage_par_contenu.py`.

Le rectangle est déjà aligné sur les axes (la boîte de mise en page l'est par
construction) : un simple découpage numpy préserve les pixels d'origine sans
le ré-échantillonnage qu'imposerait un `warpPerspective` -- inutile ici
puisqu'il n'y a pas de perspective à corriger, seulement une fenêtre à
extraire.

Une page sans boîte `table` (le détecteur n'en a trouvé aucune) reçoit
l'image ORIGINALE, non recadrée -- le même réflexe de prudence que
`preprocess.py` en production : mieux vaut une lecture sur la scène entière
qu'un recadrage inventé.

Vérifié visuellement (page 8, 14 % des pixels conservés) : le tableau cible
est isolé proprement, les trois feuilles parasites entièrement exclues.

Combien de pages perdent leur en-tête, et ce que ça implique (signalé par
Halfaa, mesuré avant d'y répondre)
----------------------------------------------------------------------------
Sur les 25 pages : 15 gardent déjà un en-tête détecté DANS le recadrage,
5 en ont un mais hors de la dilatation ×1,2, et 5 n'en ont aucun -- même sur
la scène entière, ce n'est donc pas le recadrage qui le fait disparaître pour
celles-là. Mais élargir la boîte pour rattraper les 5 pages manquantes serait
dangereux : sur la page 8, le bloc de texte juste au-dessus de la table cible
ne recouvre que 68 px sur 456 en largeur avec elle -- ce n'est probablement
PAS l'en-tête de la bonne feuille, mais celui d'une feuille parasite voisine.
L'attacher silencieusement referait exactement l'erreur de provenance que
`adaptive.concordance()` existe pour empêcher (cf. `docs/fonds_encombres.md`
§9) -- une réponse fausse sans le signaler est pire qu'une réponse absente.

La bonne réponse n'est donc pas d'élargir CE recadrage, mais de ne jamais lui
demander les champs d'en-tête : ce script produit UNIQUEMENT la lecture
recadrée, à enregistrer comme candidat "prétraité" de la lecture BRUTE déjà
existante dans `scripts/eval_all.py` (`variants_encombre_recadre_contenu`).
`adaptive.choose()` s'occupe alors des deux lectures séparément -- le TABLEAU
vient du meilleur des deux (avec le garde de provenance, qui aurait rejeté le
recadrage de la page 8 si son contenu ne recoupait pas la scène brute), les
CHAMPS D'EN-TÊTE viennent TOUJOURS de la lecture brute en priorité
(`field_order=("raw", "preprocessed")`) -- déjà mesurés à 62-77 % selon le
modèle, jamais dégradés par ce recadrage. Rien à coder : c'est le même
mécanisme qui gère déjà brut/prétraité partout ailleurs dans le projet.

Usage :
    python scripts/recadrage_par_contenu_extraire.py
    python scripts/recadrage_par_contenu_extraire.py --facteur 1.4 --jeu variants_encombre

Puis, PaddleOCR-VL (local) :
    python scripts/bench_deformed.py --model paddleocr-vl \\
        --images-dir ../doc3D-renderer/img/variants_encombre_recadre_contenu \\
        --output variants_encombre_recadre_contenu_paddleocr
    python scripts/eval_all.py --modele paddleocr --jeu variants_encombre_recadre_contenu

Chandra (5 B) ne tient pas sur la RTX 3050 Ti : passer par
`kaggle/bench_kaggle_chandra.ipynb` (nouvelle branche à y ajouter), produire
`variants_encombre_recadre_contenu_chandra`, puis :
    python scripts/eval_all.py --modele chandra --jeu variants_encombre_recadre_contenu

Dans les deux cas, lire la ligne `adaptatif` du tableau -- c'est la réponse
à la question posée au §17, pas les lignes brut/prétraité isolées.
"""

import argparse
import re
import shutil
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "scripts"))

try:
    import cv2
    import numpy as np
except ImportError:
    raise SystemExit("Il faut opencv et numpy :\n"
                     "    pip install 'opencv-python<4.12' 'numpy<2'")

from recadrage_par_contenu import boites_table, choisir_table, dilatee  # noqa: E402

DOC3D = RACINE.parent / "doc3D-renderer"
FACTEUR_RETENU = 1.2  # voir docs/fonds_encombres.md §17 : plage 1,1-1,3 quasi indifférente


def num(chemin: Path) -> int:
    return int(re.match(r"page_(\d+)", chemin.name).group(1))


def decouper(image: np.ndarray, boite) -> np.ndarray:
    """Découpe la boîte (déjà dilatée), bornée aux dimensions de l'image."""
    h, w = image.shape[:2]
    x1, y1, x2, y2 = boite
    x1, y1 = max(0, int(round(x1))), max(0, int(round(y1)))
    x2, y2 = min(w, int(round(x2))), min(h, int(round(y2)))
    if x2 <= x1 or y2 <= y1:
        return image  # boîte dégénérée après bornage -- garde-fou, ne devrait pas arriver
    return image[y1:y2, x1:x2]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--jeu", default="variants_encombre")
    p.add_argument("--run", default="variants_encombre_paddleocr",
                   help="Run PaddleOCR-VL fournissant les boîtes de mise en page.")
    p.add_argument("--facteur", type=float, default=FACTEUR_RETENU)
    p.add_argument("--out", default=None,
                   help="Dossier de sortie (défaut : <jeu>_recadre_contenu, à côté du jeu source)")
    args = p.parse_args()

    img_dir = DOC3D / "img" / args.jeu
    run_dir = RACINE / "results" / args.run / "pages"
    out_dir = Path(args.out) if args.out else DOC3D / "img" / f"{args.jeu}_recadre_contenu"

    if not img_dir.is_dir():
        raise SystemExit(f"{img_dir} absent.")
    if not run_dir.is_dir():
        raise SystemExit(f"{run_dir} absent -- il faut d'abord un run PaddleOCR-VL "
                         f"sur {args.jeu} pour ses boîtes de mise en page.")

    out_dir.mkdir(parents=True, exist_ok=True)

    n_recadrees, n_brutes, n_manquantes = 0, 0, 0
    for chemin in sorted(img_dir.glob("*.png"), key=num):
        dossiers = list(run_dir.glob(f"{chemin.stem}*"))
        tables = boites_table(dossiers[0], facteur=1.0) if dossiers else []

        destination = out_dir / chemin.name
        if not tables:
            shutil.copy2(chemin, destination)
            n_brutes += 1
            print(f"  page {num(chemin):<3} aucune boîte table -> image brute copiée")
            continue

        image = cv2.imread(str(chemin))
        if image is None:
            n_manquantes += 1
            print(f"  page {num(chemin):<3} illisible, ignorée")
            continue

        cible = choisir_table(tables)
        boite = dilatee(cible, args.facteur)
        recadree = decouper(image, boite)
        cv2.imwrite(str(destination), recadree)
        n_recadrees += 1
        h0, w0 = image.shape[:2]
        h1, w1 = recadree.shape[:2]
        print(f"  page {num(chemin):<3} {w0}x{h0} -> {w1}x{h1} "
              f"({100 * w1 * h1 / (w0 * h0):.0f}% des pixels)")

    print(f"\n{n_recadrees} recadrées, {n_brutes} laissées brutes "
          f"(aucune boîte table), {n_manquantes} illisibles")
    print(f"-> {out_dir}")
    try:
        images_dir_arg = out_dir.relative_to(RACINE.parent)
    except ValueError:
        images_dir_arg = out_dir
    print("\nSuite :")
    print(f"    python scripts/bench_deformed.py --model paddleocr-vl "
          f"--images-dir {images_dir_arg} "
          f"--output {args.jeu}_recadre_contenu_paddleocr")
    print(f"    python scripts/eval_all.py --modele paddleocr "
          f"--jeu {args.jeu}_recadre_contenu")


if __name__ == "__main__":
    main()
