"""
Le plafond de recadrage remonte-t-il si on change de générateur de candidats ?

C'est LA question à trancher avant d'engager deux semaines sur une
segmentation apprise. Sur le jeu à fonds encombrés, le plafond mesuré est de
0,51 : aucune des segmentations candidates ne contient la bonne feuille, donc
aucun sélecteur ne peut sauver la situation. Mais ce 0,51 est une propriété du
**générateur de candidats**, pas du problème. Le remplacer change le plafond ;
mieux choisir parmi les mêmes candidats ne le change pas.

D'où deux colonnes qu'il ne faut jamais confondre :

    plafond   le meilleur IoU atteignable parmi les candidats proposés
              -> dépend du GÉNÉRATEUR
    obtenu    l'IoU du candidat que le scoring retient effectivement
              -> dépend du SCORING

Un plafond haut avec un obtenu bas veut dire que la sélection est le maillon
faible, et c'est une demi-journée de travail. Un plafond bas veut dire que
les indices eux-mêmes ne voient pas la feuille, et là il faut apprendre.

Trois générateurs sont comparés :

    actuel      seuillages (clarté, saturation, texture) + Canny + GrabCut,
                c'est-à-dire ce que fait `preprocess.py` aujourd'hui
    sam         les masques proposés par SAM, sans aucun entraînement
    actuel+sam  l'union des deux

et deux scorings : celui d'aujourd'hui, et le même avec la prime de
centralité (`_prime_centralite`).

    python scripts/sonde_plafond.py --jeu variants_encombre
    python scripts/sonde_plafond.py --jeu variants_encombre --sam
    python scripts/sonde_plafond.py --jeu variants_warped --sam

Le troisième appel est le contrôle de non-régression : ce qui aide sur le jeu
encombré ne doit pas casser le jeu propre, dont les chiffres sont publiés.

SAM est optionnel et vit dans son propre environnement -- surtout ne pas
l'installer dans `venv`, qui est épinglé numpy<2 pour PaddleOCR :

    python -m venv venv_sam
    venv_sam\\Scripts\\activate
    python -m pip install --upgrade pip
    pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu
    pip install --no-cache-dir ultralytics "opencv-python<4.12"

Deux epingles qui comptent. `opencv-python<4.12` : les versions 5.x rendent
None sur un .exr, sans lever d'erreur -- la sonde ne pourrait plus lire les
masques UV. Et le torch CPU explicite : la roue CUDA par defaut pese 2,4 Go
contre 200 Mo, pour un modele de 23 Mo qui tourne tres bien sur processeur.

Les poids (FastSAM-s, ~23 Mo) se téléchargent tout seuls au premier appel.
"""

import argparse
import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "src"))
# Sans cette variable, OpenCV rend None sur un .exr -- silencieusement.
os.environ.setdefault("OPENCV_IO_ENABLE_OPENEXR", "1")

try:
    import cv2
    import numpy as np
except ImportError:
    raise SystemExit("Il faut opencv et numpy :\n"
                     "    pip install 'opencv-python<4.12' 'numpy<2'")

from preprocess import (_candidate_masks, _document_score,  # noqa: E402
                        _grabcut_contour)

DOC3D = RACINE.parent / "doc3D-renderer"

# Même échelle de travail que `detect_document_quad`, pour que les candidats
# comparés ici soient exactement ceux que la chaîne verrait.
COTE_TRAVAIL = 480.0

# Un recadrage en dessous de ce seuil coupe du contenu : on compte les pages
# exploitables plutôt que de se fier à une moyenne, qu'une seule très bonne
# page suffit à embellir.
SEUIL_EXPLOITABLE = 0.7


def iou(quad, verite):
    """IoU entre le quadrilatère rempli et le masque exact de la feuille."""
    if quad is None:
        return 0.0
    predit = np.zeros(verite.shape, np.uint8)
    cv2.fillPoly(predit, [np.asarray(quad, dtype=np.int32)], 1)
    predit = predit.astype(bool)
    union = (predit | verite).sum()
    return float((predit & verite).sum() / union) if union else 0.0


# --------------------------------------------------------------------------
# Générateurs de candidats. Chacun rend une liste de contours, à l'échelle
# de travail.

def candidats_actuels(petit, image=None, echelle=1.0):
    """Ce que `preprocess.py` propose aujourd'hui."""
    contours = []
    grabcut = _grabcut_contour(petit)
    if grabcut is not None:
        contours.append(grabcut)
    for masque in _candidate_masks(petit):
        trouves, _ = cv2.findContours(masque, cv2.RETR_EXTERNAL,
                                      cv2.CHAIN_APPROX_SIMPLE)
        contours.extend(sorted(trouves, key=cv2.contourArea, reverse=True)[:3])
    return contours


_modele_sam = None


TAILLE_SAM = 1024


def candidats_sam(petit, image=None, echelle=1.0):
    """Les masques de SAM, convertis en contours à l'échelle de travail.

    SAM ne sait pas ce qu'est un document : il découpe l'image en régions
    cohérentes, un point c'est tout. C'est précisément l'intérêt ici -- il
    propose une région PAR FEUILLE, y compris quand toutes les feuilles se
    ressemblent, là où un seuillage les fond en une seule tache. Le tri entre
    ces régions reste à notre scoring, qu'on ne change pas.

    On le nourrit avec l'image PLEINE, pas avec la copie en 480 px.

    Les 480 px sont un compromis de nos seuillages : ils y gagnent en vitesse
    ce qu'ils ne perdent pas en précision, parce qu'une tache de luminance ne
    demande pas de détail. SAM, lui, décide de ses frontières sur des indices
    fins, et le lui imposer le désavantage sans raison -- première mesure à
    480 px, il tombait à 0,80 de plafond sur le jeu propre là où un simple
    seuillage atteint 0,87, ce qui n'était pas croyable. Les contours sont
    ensuite ramenés à l'échelle de travail pour rester comparables.
    """
    global _modele_sam
    if _modele_sam is None:
        try:
            from ultralytics import FastSAM
        except ImportError:
            raise SystemExit(
                "SAM demande ultralytics, dans un environnement SÉPARÉ :\n"
                "    python -m venv venv_sam\n"
                "    venv_sam\\Scripts\\activate\n"
                "    python -m pip install --upgrade pip\n"
                "    pip install --no-cache-dir torch torchvision "
                "--index-url https://download.pytorch.org/whl/cpu\n"
                "    pip install --no-cache-dir ultralytics \"opencv-python<4.12\"\n"
                "Ne pas l'installer dans venv : il y remonterait numpy au-delà\n"
                "de 2, ce que PaddleOCR ne supporte pas.")
        _modele_sam = FastSAM("FastSAM-s.pt")

    source = petit if image is None else image
    rapport = 1.0 if image is None else echelle    # plein -> travail
    resultat = _modele_sam(source, verbose=False, retina_masks=True,
                           imgsz=TAILLE_SAM, conf=0.25, iou=0.9)
    contours = []
    for r in resultat:
        if r.masks is None:
            continue
        for m in r.masks.data.cpu().numpy():
            masque = (m > 0.5).astype(np.uint8)
            if masque.shape != source.shape[:2]:
                masque = cv2.resize(masque, (source.shape[1], source.shape[0]),
                                    interpolation=cv2.INTER_NEAREST)
            trouves, _ = cv2.findContours(masque, cv2.RETR_EXTERNAL,
                                          cv2.CHAIN_APPROX_SIMPLE)
            if not trouves:
                continue
            contour = max(trouves, key=cv2.contourArea)
            if rapport != 1.0:
                contour = (contour.astype(np.float32) * rapport).astype(np.int32)
            contours.append(contour)
    return contours


# --------------------------------------------------------------------------

def diagnostiquer_sam(contours, petit, echelle, verite):
    """SAM ne voit pas la feuille, ou la voit en morceaux ?

    Les deux se soldent par un IoU bas, et ils appellent des réponses
    opposées. S'il ne la voit pas, la voie du recadrage est morte sur ce type
    de scène. S'il la voit en morceaux, la perception est là et c'est la
    DÉFINITION de l'objet qui manque -- un modèle entraîné à sortir « le
    document » d'un seul tenant n'aurait pas ce problème, et l'investissement
    se justifie.

    On tranche avec la surface : on compare l'aire du meilleur masque à celle
    de la vraie feuille. Nettement plus petite, ce sont des morceaux.
    """
    aire_vraie = float(verite.sum())
    meilleur, aire_meilleur = 0.0, 0.0
    for contour in contours:
        quad = cv2.boxPoints(cv2.minAreaRect(contour)) / echelle
        score = iou(quad, verite)
        if score > meilleur:
            meilleur = score
            meilleur_masque = np.zeros(verite.shape, np.uint8)
            cv2.fillPoly(meilleur_masque, [np.asarray(quad, np.int32)], 1)
            aire_meilleur = float(meilleur_masque.sum())
    return {
        "n_masques": len(contours),
        "couverture": (aire_meilleur / aire_vraie) if aire_vraie else 0.0,
        "iou": meilleur,
    }


def mesurer(contours, petit, echelle, verite):
    """Rend (plafond, obtenu_actuel, obtenu_centralite)."""
    aire = petit.shape[0] * petit.shape[1]
    centre = (petit.shape[1] / 2.0, petit.shape[0] / 2.0)

    plafond, meilleur_actuel, meilleur_central = 0.0, (-1.0, None), (-1.0, None)
    for contour in contours:
        quad = cv2.boxPoints(cv2.minAreaRect(contour)) / echelle
        score_iou = iou(quad, verite)
        plafond = max(plafond, score_iou)

        note = _document_score(contour, aire)
        if note > meilleur_actuel[0]:
            meilleur_actuel = (note, score_iou)
        note_c = _document_score(contour, aire, centre=centre)
        if note_c > meilleur_central[0]:
            meilleur_central = (note_c, score_iou)

    return (plafond,
            meilleur_actuel[1] or 0.0,
            meilleur_central[1] or 0.0)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--jeu", default="variants_encombre")
    p.add_argument("--sam", action="store_true",
                   help="Ajouter les générateurs SAM (environnement séparé).")
    p.add_argument("--diagnostic-sam", action="store_true",
                   help="SAM ne voit pas la feuille, ou la voit en morceaux ?")
    p.add_argument("--taille-sam", type=int, default=TAILLE_SAM,
                   help="Résolution donnée à SAM. 480 reproduit la première "
                        "mesure, qui le désavantageait.")
    args = p.parse_args()

    dossier_img = DOC3D / "img" / args.jeu
    dossier_uv = DOC3D / "uv" / args.jeu
    images = sorted(dossier_img.glob("*.png"))
    if not images:
        raise SystemExit(f"Aucune image dans {dossier_img}")

    generateurs = {"actuel": candidats_actuels}
    if args.sam:
        globals()["TAILLE_SAM"] = args.taille_sam
        print(f"SAM à {args.taille_sam} px (les seuillages restent à "
              f"{COTE_TRAVAIL:.0f})")
        generateurs["sam"] = candidats_sam
        generateurs["actuel+sam"] = (
            lambda pt, im=None, ec=1.0: candidats_actuels(pt, im, ec)
                                        + candidats_sam(pt, im, ec))

    resultats = {nom: {"plafond": [], "actuel": [], "central": []}
                 for nom in generateurs}
    n_pages, diagnostics, noms_pages = 0, [], []

    for chemin in images:
        uv = dossier_uv / f"{chemin.stem}.exr"
        if not uv.exists():
            continue
        carte = cv2.imread(str(uv), cv2.IMREAD_UNCHANGED)
        if carte is None:
            raise SystemExit(
                f"OpenCV ne lit pas {uv.name}. Le support OpenEXR n'est pas "
                "actif :\n    pip install 'opencv-python<4.12'")
        verite = carte[:, :, 0] > 0.5

        image = cv2.imread(str(chemin))
        echelle = COTE_TRAVAIL / max(image.shape[:2])
        petit = cv2.resize(image, None, fx=echelle, fy=echelle)
        n_pages += 1

        for nom, generer in generateurs.items():
            contours = generer(petit, image, echelle)
            if nom == "sam" and args.diagnostic_sam:
                diagnostics.append(diagnostiquer_sam(contours, petit,
                                                     echelle, verite))
                noms_pages.append(chemin.stem.split("-")[0].replace("page_", ""))
            plafond, obtenu, central = mesurer(contours, petit, echelle, verite)
            resultats[nom]["plafond"].append(plafond)
            resultats[nom]["actuel"].append(obtenu)
            resultats[nom]["central"].append(central)

    if not n_pages:
        raise SystemExit(f"Aucune carte UV dans {dossier_uv}")

    if diagnostics:
        couvertures = [d["couverture"] for d in diagnostics]
        print(f"\nDiagnostic SAM — {np.mean([d['n_masques'] for d in diagnostics]):.0f} "
              f"masques par image en moyenne")
        print(f"{'page':<8}{'masques':>9}{'couverture':>13}{'IoU':>8}")
        print("-" * 38)
        for nom, d in zip(noms_pages, diagnostics):
            print(f"{nom:<8}{d['n_masques']:>9}{d['couverture']:>12.0%}{d['iou']:>8.2f}")
        print("-" * 38)
        print(f"{'moyenne':<8}{'':>9}{np.mean(couvertures):>12.0%}")
        # Surtout PAS de moyenne ici.
        #
        # La première version de ce diagnostic comparait la couverture moyenne
        # à un seuil unique, et concluait « les masques ont la bonne taille »
        # sur une moyenne de 69 %. C'était faux : cette moyenne mélangeait
        # 7 pages à 15 % et 6 pages à 130 %, deux échecs OPPOSÉS qui
        # s'annulent. Une statistique de position n'a aucun sens sur une
        # distribution bimodale -- il faut compter les groupes.
        groupes = {
            "morceaux (<50 %)":       [d for d in diagnostics if d["couverture"] < 0.50],
            "bonne taille (50-100 %)": [d for d in diagnostics
                                        if 0.50 <= d["couverture"] <= 1.00],
            "trop gros (>100 %)":     [d for d in diagnostics if d["couverture"] > 1.00],
        }
        print("\n  Couverture = aire du meilleur masque / aire réelle de la feuille.\n")
        for nom, g in groupes.items():
            if not g:
                continue
            moy = np.mean([d["iou"] for d in g])
            print(f"  {nom:<26}{len(g):>3} pages   IoU moyen {moy:.2f}")
        n_bon = len(groupes["bonne taille (50-100 %)"])
        if n_bon and np.mean([d["iou"] for d in groupes["bonne taille (50-100 %)"]]) < 0.7:
            print("\n  Même sur les pages où le masque a la BONNE TAILLE, l'IoU")
            print("  plafonne. SAM ne se contente donc pas de mal découper : sur")
            print("  ce type de scène il ne désigne pas la bonne feuille.")

    print(f"\nJeu : {args.jeu}   ({n_pages} pages)\n")
    entete = (f"{'générateur':<14}{'plafond':>9}{'obtenu':>9}"
              f"{'+centralité':>13}{'exploitables':>15}")
    print(entete)
    print("-" * len(entete))
    for nom, r in resultats.items():
        util = sum(v >= SEUIL_EXPLOITABLE for v in r["central"])
        print(f"{nom:<14}{np.mean(r['plafond']):>9.2f}"
              f"{np.mean(r['actuel']):>9.2f}{np.mean(r['central']):>13.2f}"
              f"{f'{util}/{n_pages}':>15}")
    print("-" * len(entete))

    base = resultats["actuel"]
    print("\nComment lire.")
    print("  plafond      dépend du GÉNÉRATEUR. S'il ne bouge pas d'une ligne")
    print("               à l'autre, les nouveaux candidats ne contiennent pas")
    print("               davantage la feuille -- il faudra apprendre.")
    print("  +centralité  dépend du SCORING seul, à générateur constant.")
    gain = np.mean(base["central"]) - np.mean(base["actuel"])
    print(f"\n  Prime de centralité, à générateur inchangé : {gain:+.3f} IoU.")
    if "sam" in resultats:
        saut = np.mean(resultats["actuel+sam"]["plafond"]) - np.mean(base["plafond"])
        print(f"  Apport de SAM au plafond : {saut:+.3f}.")
        print("  Un saut franc dit qu'une segmentation apprise a de quoi")
        print("  travailler ; un saut nul dit que le problème est ailleurs.")
    print("\n  Vérifier ensuite sur variants_warped : ce qui aide ici ne doit")
    print("  pas dégrader le jeu propre, dont les chiffres sont publiés.")


if __name__ == "__main__":
    main()
