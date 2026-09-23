"""
Le bord de la feuille cible est-il seulement VISIBLE ? Mesure, pas conjecture.

Onze tentatives de recadrage ont echoue sur le jeu a fonds encombres, la
meilleure union plafonnant a 0,59 IoU contre 0,85 pour l'oracle. Avant d'en
ecrire une douzieme, ce script pose la question qu'aucune ne posait :
l'information cherchee existe-t-elle dans l'image ?

On peut y repondre exactement, parce qu'on possede le masque UV au pixel pres.
On sait donc OU est le bord, et on peut aller mesurer ce qu'on y trouve au
lieu d'essayer de le deviner.

Les trois mesures
-----------------
CONTRASTE
    Seuil de gradient retenant la moitie des pixels du vrai bord ; a ce
    seuil, quelle part des pixels retenus appartient au bord ? C'est le
    rapport signal/bruit qu'un detecteur d'aretes subit reellement. On le
    compare au tirage au hasard (= part du bord dans l'image) : si le gain
    est proche de 1, le gradient ne dit rien sur l'emplacement du bord.

    Une moyenne de gradient contre une autre ne suffirait pas : le « fond »
    melange du papier lisse (gradient nul) et des aretes parasites (gradient
    fort), et la moyenne cache cette bimodalite.

DROITURE
    Plus long arc du contour restant a moins de 2 px d'une droite, rapporte
    au grand cote de la feuille. C'est la definition operatoire de « droit »
    pour Hough. On mesure aussi l'ecart maximal du contour a son
    quadrilatere ajuste, qui capte la courbure la ou elle est.

SEGMENTS SUR LE BORD
    Parmi les segments que Hough rend effectivement, combien tombent sur le
    vrai contour ? C'est la mesure qui tranche, parce qu'elle porte sur ce
    que l'algorithme consomme et non sur une propriete abstraite de l'image.

Ce que la mesure a donne (25 pages, variants_encombre)
------------------------------------------------------
    precision a recall 50 %   2,2 %   contre 1,5 % au hasard   -> gain x1,5
    plus longue corde droite   100 % du grand cote de la feuille
    ecart max au 4-gone       2,9 % de la diagonale de l'image
    segments sur le bord      0 sur 7155, a trois seuils differents

Lecture. Les bords sont DROITS -- l'hypothese de la courbure comme cause de
l'echec de Hough est fausse. Ils sont INVISIBLES : blanc sur blanc, sans
profondeur de champ ni ombre portee pour les detacher. Aucune methode fondee
sur les aretes ne peut les trouver, quel que soit son reglage, parce que le
signal n'est pas dans l'image.

La forme du reste est instructive : la feuille doc3D est enroulee
cylindriquement, donc deux bords opposes (les generatrices) restent
rigoureusement droits tandis que les deux autres s'arquent. C'est exactement
le desequilibre observe dans le diagnostic de `essai_quadrilateres` -- une
famille d'orientation pleine, la perpendiculaire vide.

Consequence pour la suite. Les methodes publiees qui traitent ce probleme
(Pan & Zhu 2021 ; Tan et al., PRCV 2025) travaillent sur des PHOTOS, ou le
flou d'arriere-plan et l'ombre portee donnent au contour un contraste reel.
La profondeur de champ n'est donc pas « un facteur parmi d'autres » dans nos
resultats : c'est elle qui CREE le signal de bord. Un rendu doc3D sans
ouverture simulee retire l'indice principal, ce qui rend notre plafond de
0,59 pessimiste pour le monde reel -- reserve a formuler avant de conclure
quoi que ce soit sur la methode.

    python scripts/mesure_arete.py
    python scripts/mesure_arete.py --jeu variants_warped --figure
"""

import argparse
import re
import sys
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

DOC3D = RACINE.parent / "doc3D-renderer"
FIGURES = RACINE / "demo" / "figures"

TOLERANCE_DROITE = 2.0      # px : au-dela, Hough disperse son vote
TOLERANCE_BORD = 6.0        # px : « ce segment est sur le contour »
FRACTIONS = [0.35, 0.20, 0.10]      # minLineLength / diagonale du texte


def verite(exr):
    """Masque exact de la feuille cible : canal B du rendu UV."""
    import Imath
    import OpenEXR
    f = OpenEXR.InputFile(str(exr))
    dw = f.header()["dataWindow"]
    w, h = dw.max.x - dw.min.x + 1, dw.max.y - dw.min.y + 1
    pt = Imath.PixelType(Imath.PixelType.FLOAT)
    return np.frombuffer(f.channel("B", pt), dtype=np.float32).reshape(h, w) > 0.5


def gradient(image):
    gris = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY).astype(np.float32)
    gris = cv2.GaussianBlur(gris, (5, 5), 0)
    gx = cv2.Sobel(gris, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gris, cv2.CV_32F, 0, 1, ksize=3)
    return np.hypot(gx, gy)


def contour_principal(masque):
    m = masque.astype(np.uint8) * 255
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    return max(cnts, key=cv2.contourArea).reshape(-1, 2) if cnts else None


def segments(image, longueur_mini):
    gris = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gris = cv2.bilateralFilter(gris, 7, 50, 50)
    bords = cv2.Canny(gris, 30, 90, apertureSize=3)
    lignes = cv2.HoughLinesP(bords, 1, np.pi / 360, threshold=60,
                             minLineLength=longueur_mini, maxLineGap=12)
    if lignes is None:
        return []
    return [tuple(int(v) for v in np.asarray(l).ravel()[:4]) for l in lignes]


def plus_longue_corde(contour, tolerance=TOLERANCE_DROITE):
    """Plus long arc du contour restant a `tolerance` px d'une droite.

    L'ecart croit avec la longueur de l'arc, ce qui autorise une dichotomie
    sur la longueur pour chaque point de depart.
    """
    n = len(contour)
    if n < 3:
        return 0.0
    pts = contour.astype(np.float64)
    meilleur = 0.0
    pas = max(1, n // 400)          # le contour est lisse : 400 departs suffisent
    for i in range(0, n, pas):
        lo, hi = 1, n - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            arc = pts[np.arange(i, i + mid + 1) % n]
            a, d = arc[0], arc[-1] - arc[0]
            norme = float(np.hypot(*d))
            if norme < 1e-6:
                hi = mid - 1
                continue
            ecart = np.abs(d[0] * (arc[:, 1] - a[1]) - d[1] * (arc[:, 0] - a[0])) / norme
            if ecart.max() <= tolerance:
                lo = mid
            else:
                hi = mid - 1
        arc = pts[np.arange(i, i + lo + 1) % n]
        meilleur = max(meilleur, float(np.hypot(*(arc[-1] - arc[0]))))
    return meilleur


def ecart_au_quadrilatere(contour, diagonale):
    """Ecart maximal du contour a son 4-gone ajuste, en % de la diagonale."""
    c = contour.astype(np.float32)
    peri = cv2.arcLength(c, True)
    for f in np.arange(0.005, 0.15, 0.002):
        approx = cv2.approxPolyDP(c, f * peri, True)
        if len(approx) == 4:
            quad = approx.reshape(4, 2).astype(np.float32)
            d = max(abs(cv2.pointPolygonTest(quad, (float(p[0]), float(p[1])), True))
                    for p in c)
            return 100.0 * d / diagonale
    return float("nan")


def figure(pages, sortie):
    """Le constat, en image : le vrai bord, et ce que Hough a trouve.

    Une planche vaut ici tous les tableaux -- on voit le rouge partout sauf
    sur le vert.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, len(pages), figsize=(5.2 * len(pages), 6.0))
    if len(pages) == 1:
        axes = [axes]
    for ax, (n, petit, contour, segs, ok) in zip(axes, pages):
        ax.imshow(cv2.cvtColor(petit, cv2.COLOR_BGR2RGB))
        for x1, y1, x2, y2 in segs:
            ax.plot([x1, x2], [y1, y2], color="#d62728", lw=1.1, alpha=0.85)
        ax.plot(np.append(contour[:, 0], contour[0, 0]),
                np.append(contour[:, 1], contour[0, 1]),
                color="#2ca02c", lw=2.6)
        ax.set_title(f"page {n} - {len(segs)} segments, {ok} on the edge",
                     fontsize=11)
        ax.set_xticks([])
        ax.set_yticks([])
    fig.suptitle("Green: the true edge of the target sheet.   "
                 "Red: the straight lines Hough finds.", fontsize=13)
    fig.tight_layout()
    sortie.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(sortie, dpi=130, bbox_inches="tight")
    print(f"\nfigure : {sortie}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--jeu", default="variants_encombre")
    p.add_argument("--cote", type=float, default=1400.0,
                   help="Cote long de travail, comme dans la sonde.")
    p.add_argument("--figure", action="store_true",
                   help="Ecrire demo/figures/16_bord_invisible.png")
    args = p.parse_args()

    img, uv = DOC3D / "img" / args.jeu, DOC3D / "uv" / args.jeu
    if not img.is_dir():
        raise SystemExit(f"{img} absent.")

    def num(chemin):
        return int(re.match(r"page_(\d+)", chemin.name).group(1))

    lignes, total = [], {f: [0, 0] for f in FRACTIONS}
    pour_figure = []
    print(f"{'page':<6}{'precision':>11}{'hasard':>9}{'gain':>7}"
          f"{'% cote droit':>14}{'ecart 4-gone':>14}{'seg/bord':>11}")
    print("-" * 72)
    for chemin in sorted(img.glob("*.png"), key=num):
        exr = uv / f"{chemin.stem}.exr"
        if not exr.exists():
            continue
        vrai = verite(exr)
        image = cv2.imread(str(chemin))
        if image is None:
            continue
        facteur = args.cote / max(image.shape[:2])
        petit = cv2.resize(image, None, fx=facteur, fy=facteur,
                           interpolation=cv2.INTER_AREA)
        masque = cv2.resize(vrai.astype(np.uint8),
                            (petit.shape[1], petit.shape[0]),
                            interpolation=cv2.INTER_NEAREST).astype(bool)
        if masque.sum() < 100:
            continue
        contour = contour_principal(masque)
        if contour is None:
            continue

        # --- contraste ---
        g = gradient(petit)
        noyau = np.ones((7, 7), np.uint8)
        bande = (cv2.dilate(masque.astype(np.uint8), noyau).astype(bool)
                 & ~cv2.erode(masque.astype(np.uint8), noyau).astype(bool))
        seuil = float(np.median(g[bande]))
        retenus = g >= seuil
        n_ret = int(retenus.sum())
        precision = float((retenus & bande).sum() / n_ret) if n_ret else 0.0
        hasard = float(bande.sum() / bande.size)
        gain = precision / hasard if hasard else float("nan")

        # --- droiture ---
        diag_img = float(np.hypot(*petit.shape[:2]))
        (_, (w, h), _) = cv2.minAreaRect(contour.astype(np.float32))
        corde = plus_longue_corde(contour)
        pct_cote = 100.0 * corde / max(w, h) if max(w, h) else 0.0
        ecart = ecart_au_quadrilatere(contour, diag_img)

        # --- segments sur le bord ---
        cf = contour.astype(np.float32).reshape(-1, 1, 2)

        def sur_bord(s):
            return all(abs(cv2.pointPolygonTest(cf, (float(s[i]), float(s[i + 1])),
                                                True)) <= TOLERANCE_BORD
                       for i in (0, 2))

        diag_txt = float(np.hypot(w, h))
        par_seuil = []
        for f in FRACTIONS:
            segs = segments(petit, longueur_mini=max(40, int(f * diag_txt * 0.5)))
            ok = sum(sur_bord(s) for s in segs)
            total[f][0] += len(segs)
            total[f][1] += ok
            par_seuil.append((segs, ok))
        segs_ref, ok_ref = par_seuil[0]

        if args.figure and len(pour_figure) < 3:
            pour_figure.append((num(chemin), petit, contour, segs_ref, ok_ref))

        lignes.append((precision, hasard, gain, pct_cote, ecart))
        print(f"{num(chemin):<6}{precision:>10.1%}{hasard:>9.1%}{gain:>7.2f}"
              f"{pct_cote:>14.0f}{ecart:>14.2f}{f'{len(segs_ref)}/{ok_ref}':>11}")

    a = np.array(lignes)
    print("-" * 72)
    print(f"{'moyenne':<6}{a[:, 0].mean():>10.1%}{a[:, 1].mean():>9.1%}"
          f"{a[:, 2].mean():>7.2f}{a[:, 3].mean():>14.0f}{a[:, 4].mean():>14.2f}")

    print("\n--- Contraste ---")
    print(f"A recall 50 %, precision {a[:, 0].mean():.1%} contre "
          f"{a[:, 1].mean():.1%} au hasard : gain x{a[:, 2].mean():.2f}.")
    if a[:, 2].mean() < 2.0:
        print(f"Pour un point d'arete utile, un detecteur en recoit "
              f"{1 / a[:, 0].mean():.0f} d'inutiles. Le gradient ne localise")
        print("pas le bord : ce n'est pas un probleme de reglage.")

    print("\n--- Droiture ---")
    print(f"Plus longue portion droite : {a[:, 3].mean():.0f} % du grand cote.")
    print(f"Ecart max au 4-gone ajuste : {a[:, 4].mean():.2f} % de la diagonale.")
    if a[:, 3].mean() > 80:
        print("Les bords sont droits. La courbure n'explique donc PAS l'echec")
        print("de Hough -- l'enroulement cylindrique laisse deux generatrices")
        print("rectilignes et n'arque que les deux autres bords.")

    print("\n--- Segments sur le bord ---")
    for f in FRACTIONS:
        n, ok = total[f]
        print(f"  minLineLength = {f:.2f} x diag : {n:>5} segments, {ok:>4} "
              f"sur le bord ({(ok / n if n else 0):.1%})")
    grand_total = sum(n for n, _ in total.values())
    grand_ok = sum(ok for _, ok in total.values())
    print(f"  TOTAL : {grand_ok} sur {grand_total}.")
    if grand_ok == 0:
        print("\nAucun segment, a aucun seuil, ne tombe sur le vrai bord. Les")
        print("methodes publiees (Pan & Zhu 2021 ; Tan et al. 2025) operent sur")
        print("des PHOTOS, ou le flou d'arriere-plan et l'ombre portee donnent")
        print("au contour un contraste reel. La profondeur de champ ne module")
        print("pas le signal de bord : elle le CREE.")

    if args.figure and pour_figure:
        figure(pour_figure, FIGURES / "16_bord_invisible.png")


if __name__ == "__main__":
    main()
