"""
Recadrer sur le CONTENU plutot que sur la feuille — et le flou de fond.

Point de depart : une idee de Halfaa. Puisque la profondeur de champ cree le
signal de bord (cf. `mesure_arete.py`), fabriquons-la — flouter le fond, puis
relancer le pretraitement sur l'image floutee.

Le piege, et sa sortie
----------------------
Pour flouter le fond il faut deja savoir ou est la feuille : circulaire.
L'essai de profondeur de champ qui donnait 0,40 -> 0,64 floutait d'apres le
masque UV, c'est-a-dire d'apres la reponse.

On sort du cercle en floutant d'apres le TABLEAU et non d'apres le BORD : les
boites de mise en page de PaddleOCR-VL localisent le contenu sans rien savoir
de la verite terrain. Le contenu, on sait le trouver ; c'est le contour qu'on
ne sait pas.

Ce que la mesure a donne (25 pages, variants_encombre)
------------------------------------------------------
    production (aucun traitement)          0,35 IoU     1/25 exploitables
    flou hors boite x1,6, puis detection   0,55         4/25
    flou hors boite x2,5, puis detection   0,39         1/25
    flou des seules boites rivales         0,36         0/25
    BOITE DILATEE x1,2, SANS RIEN D'AUTRE  0,578       12/25

Le controle de vacuite
----------------------
Resserrer la zone nette ameliorait l'IoU -- mais il y a une facon d'ameliorer
l'IoU qui n'apprend rien : si le detecteur suit la frontiere du flou, son
quadrilatere EST la boite dilatee, et on a seulement reparametre « boite de
texte x f ». On compare donc systematiquement le quadrilatere DETECTE a la
boite dilatee SEULE :

    facteur   detecte   boite seule   ecart
    x1,1        0,54       0,55       -0,01
    x1,2        0,56       0,58       -0,02
    x1,3        0,55       0,57       -0,02
    x1,4        0,59       0,54       +0,04

En dessous de 1,4 la detection est CREUSE : elle suit notre propre masque. Le
flou n'apporte reellement que +0,04, a un seul reglage. L'essentiel du gain
vient d'ailleurs -- de la boite elle-meme.

Surajustement
-------------
Le facteur 1,2 a ete choisi en regardant le jeu de test. Validation croisee a
deux plis, 200 partitions (choix du facteur sur une moitie, evaluation sur
l'autre) :

    boite dilatee seule    genie 0,578   croisee 0,576   surajustement +0,002
    detecte apres flou     genie 0,586   croisee 0,558   surajustement +0,028

La boite ne surajuste pas : entre 1,1 et 1,4 le facteur n'a presque pas
d'importance. La variante avec flou, si.

Conclusion
----------
L'idee du flou menait quelque part, mais pas par le mecanisme attendu. Ce
n'est pas la profondeur de champ qui aide ici, c'est le fait d'ARRETER DE
CHERCHER LA FEUILLE et de recadrer sur le contenu. Un rectangle grossier
autour du bon tableau bat les neuf generateurs qu'on avait construits (0,52
au mieux) et atteint le plafond de leur union (0,59) a lui seul.

A garder en tete : ce gain porte sur le RECADRAGE, dont on a montre qu'il
n'est pas le chemin critique -- ne pas recadrer du tout donne 0,604 de TEDS
avec Chandra et 0,677 avec PaddleOCR-VL. La regle vaut donc pour un lecteur
qui exige une page propre, pas comme fin en soi. Le pas suivant est de la
mesurer en TEDS de bout en bout, pas en IoU.

    python scripts/recadrage_par_contenu.py
    python scripts/recadrage_par_contenu.py --flou --facteurs 1.1 1.2 1.3 1.4
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "scripts"))

try:
    import cv2
    import numpy as np
except ImportError:
    raise SystemExit("Il faut opencv et numpy :\n"
                     "    pip install 'opencv-python<4.12' 'numpy<2'")

from mesure_arete import verite  # noqa: E402
from preprocess import detect_document_quad  # noqa: E402

DOC3D = RACINE.parent / "doc3D-renderer"
CACHE = RACINE / "results" / "_evaluations" / "recadrage_contenu.json"

COTE = 1400.0
SEUIL = 0.70
SIGMA_REL = 0.010           # 14 px a 1400, le reglage de l'essai profondeur de champ
FACTEUR_RETENU = 1.2


def boites_table(dossier, facteur):
    """Boites `table` de PaddleOCR-VL, remises a l'echelle de travail."""
    fichiers = list(Path(dossier).glob("*_res.json"))
    if not fichiers:
        return []
    d = json.loads(fichiers[0].read_text(encoding="utf-8"))
    return [[v * facteur for v in b["coordinate"]]
            for b in d.get("layout_det_res", {}).get("boxes", [])
            if b["label"] == "table"]


def iou_masque(quad, vrai):
    if quad is None:
        return 0.0
    p = np.zeros(vrai.shape, np.uint8)
    cv2.fillPoly(p, [np.asarray(quad, np.int32)], 1)
    p = p.astype(bool)
    u = (p | vrai).sum()
    return float((p & vrai).sum() / u) if u else 0.0


def dilatee(boite, facteur):
    x1, y1, x2, y2 = boite
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    dw, dh = (x2 - x1) / 2, (y2 - y1) / 2
    return [cx - dw * facteur, cy - dh * facteur,
            cx + dw * facteur, cy + dh * facteur]


def en_quad(boite):
    x1, y1, x2, y2 = boite
    return np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], np.float32)


def choisir_table(tables):
    """La plus grande boite. Mesure : c'est la bonne 23 fois sur 25.

    Une selection ORACLE ne fait pas mieux (0,52 contre 0,55) -- le choix du
    tableau n'est pas le goulot d'etranglement, inutile d'y investir.
    """
    return max(tables, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))


def recadrage_par_contenu(image, tables, facteur=FACTEUR_RETENU):
    """La regle retenue : la plus grande boite de tableau, dilatee.

    Rend un quadrilatere aligne sur les axes, dans le repere de `image`.
    """
    if not tables:
        return None
    return en_quad(dilatee(choisir_table(tables), facteur))


def garder_net(image, boite, facteur, sigma):
    """Tout est floute sauf une boite dilatee autour du tableau cible."""
    h, w = image.shape[:2]
    x1, y1, x2, y2 = dilatee(boite, facteur)
    masque = np.zeros((h, w), np.float32)
    masque[max(0, int(y1)):min(h, int(y2)), max(0, int(x1)):min(w, int(x2))] = 1.0
    # Transition douce : une marche nette creerait elle-meme une arete
    # franche, que le detecteur prendrait pour le bord de la feuille.
    masque = cv2.GaussianBlur(masque, (0, 0), sigma)[..., None]
    k = int(6 * sigma) | 1
    return (image * masque
            + cv2.GaussianBlur(image, (k, k), sigma) * (1 - masque)).astype(np.uint8)


def croisee(table, tirages=200, graine=12345):
    """Choisir le facteur sur une moitie des pages, l'evaluer sur l'autre.

    L'ecart au « genie » (meilleur facteur choisi sur le jeu entier) mesure
    exactement le surajustement du balayage.
    """
    rng = np.random.default_rng(graine)
    facteurs = sorted(table)
    M = np.vstack([table[f] for f in facteurs])
    n = M.shape[1]
    scores = []
    for _ in range(tirages):
        perm = rng.permutation(n)
        a, b = perm[:n // 2], perm[n // 2:]
        for tr, te in ((a, b), (b, a)):
            meilleur = facteurs[int(np.argmax(M[:, tr].mean(axis=1)))]
            scores.append(table[meilleur][te].mean())
    return float(np.mean(scores)), float(np.std(scores))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--jeu", default="variants_encombre")
    p.add_argument("--run", default="variants_encombre_paddleocr",
                   help="Run PaddleOCR-VL fournissant les boites de mise en page.")
    p.add_argument("--facteurs", type=float, nargs="+",
                   default=[1.1, 1.2, 1.3, 1.4, 1.6])
    p.add_argument("--flou", action="store_true",
                   help="Mesurer aussi les variantes avec flou de fond "
                        "(lent : GrabCut par facteur et par page).")
    p.add_argument("--budget", type=float, default=1e9,
                   help="Secondes avant de s'arreter ; relancer reprend.")
    p.add_argument("--recalculer", action="store_true")
    args = p.parse_args()

    img = DOC3D / "img" / args.jeu
    uv = DOC3D / "uv" / args.jeu
    run = RACINE / "results" / args.run / "pages"
    if not img.is_dir():
        raise SystemExit(f"{img} absent.")
    if not run.is_dir():
        raise SystemExit(f"{run} absent — il faut les boites de PaddleOCR-VL.")

    def num(chemin):
        return int(re.match(r"page_(\d+)", chemin.name).group(1))

    cache = {}
    if CACHE.exists() and not args.recalculer:
        cache = json.loads(CACHE.read_text(encoding="utf-8")).get(args.jeu, {})

    depart = time.time()
    for chemin in sorted(img.glob("*.png"), key=num):
        exr = uv / f"{chemin.stem}.exr"
        if not exr.exists():
            continue
        cle = str(num(chemin))
        besoin = ["base"] + [f"boite{f}" for f in args.facteurs]
        if args.flou:
            besoin += [f"det{f}" for f in args.facteurs]
        if all(b in cache.get(cle, {}) for b in besoin):
            continue
        if time.time() - depart > args.budget:
            print("(budget atteint — relancer pour continuer)")
            break

        image = cv2.imread(str(chemin))
        if image is None:
            continue
        fac = COTE / max(image.shape[:2])
        petit = cv2.resize(image, None, fx=fac, fy=fac, interpolation=cv2.INTER_AREA)
        vrai = cv2.resize(verite(exr).astype(np.uint8),
                          (petit.shape[1], petit.shape[0]),
                          interpolation=cv2.INTER_NEAREST).astype(bool)
        dossiers = list(run.glob(f"{chemin.stem}*"))
        tables = boites_table(dossiers[0], fac) if dossiers else []
        if not tables:
            continue

        page = dict(cache.get(cle, {}))
        t = detect_document_quad(petit, min_score=0.55, return_score=True)
        page["base"] = iou_masque(t[0] if isinstance(t, tuple) else None, vrai)
        cible = choisir_table(tables)
        sigma = SIGMA_REL * max(petit.shape[:2])
        for f in args.facteurs:
            page[f"boite{f}"] = iou_masque(en_quad(dilatee(cible, f)), vrai)
            if args.flou:
                t = detect_document_quad(garder_net(petit, cible, f, sigma),
                                         min_score=0.55, return_score=True)
                page[f"det{f}"] = iou_masque(
                    t[0] if isinstance(t, tuple) else None, vrai)
        cache[cle] = page

        CACHE.parent.mkdir(parents=True, exist_ok=True)
        tout = {}
        if CACHE.exists():
            tout = json.loads(CACHE.read_text(encoding="utf-8"))
        tout[args.jeu] = cache
        CACHE.write_text(json.dumps(tout, indent=1), encoding="utf-8")
        print(f"  page {cle:<3} base {page['base']:.2f}", flush=True)

    pages = sorted(int(k) for k in cache
                   if all(f"boite{f}" in cache[k] for f in args.facteurs))
    if not pages:
        raise SystemExit("Aucune page complete.")

    def col(prefixe, f):
        return np.array([cache[str(n)][f"{prefixe}{f}"] for n in pages])

    base = np.array([cache[str(n)]["base"] for n in pages])
    print(f"\n{len(pages)} pages\n")
    print(f"{'variante':<26}{'IoU moyen':>11}{'exploitables':>14}")
    print("-" * 51)
    print(f"{'production (rien)':<26}{base.mean():>11.2f}"
          f"{f'{int((base >= SEUIL).sum())}/{len(base)}':>14}")
    print("-" * 51)
    for f in args.facteurs:
        a = col("boite", f)
        print(f"{f'boite tableau x{f}':<26}{a.mean():>11.2f}"
              f"{f'{int((a >= SEUIL).sum())}/{len(a)}':>14}")

    if args.flou:
        print("-" * 51)
        print(f"\n{'facteur':<12}{'detecte':>10}{'boite seule':>14}{'ecart':>9}")
        print("-" * 45)
        for f in args.facteurs:
            d, b = col("det", f), col("boite", f)
            print(f"x{f:<11}{d.mean():>10.2f}{b.mean():>14.2f}"
                  f"{d.mean() - b.mean():>+9.2f}")
        print("-" * 45)
        print("Un ecart ~0 signale une detection CREUSE : le detecteur suit")
        print("notre masque de flou, il ne trouve pas le bord de la feuille.")

    print("\n--- Surajustement du facteur ---")
    tables_cv = {"boite dilatee seule": {f: col("boite", f) for f in args.facteurs}}
    if args.flou:
        tables_cv["detecte apres flou"] = {f: col("det", f) for f in args.facteurs}
    for nom, t in tables_cv.items():
        genie = max(t, key=lambda f: t[f].mean())
        m, s = croisee(t)
        print(f"{nom}")
        print(f"  genie (choisi sur tout) x{genie} -> {t[genie].mean():.3f}")
        print(f"  validation croisee                 {m:.3f} (+-{s:.3f})")
        print(f"  surajustement                      {t[genie].mean() - m:+.3f}")

    print("\nReperes : meilleur generateur 0,52   plafond de l'union 0,59")
    print("          ORACLE 0,85   seuil d'exploitabilite 0,70")
    print("\nRappel : ce gain porte sur le RECADRAGE, qui n'est pas le chemin")
    print("critique — ne pas recadrer donne 0,604 de TEDS (Chandra) et 0,677")
    print("(PaddleOCR-VL). Le pas suivant est de mesurer cette regle en TEDS.")


if __name__ == "__main__":
    main()
