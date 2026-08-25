"""
D'où sort le seuil de 0,70 ? Le valider — ou le corriger.

`SEUIL_EXPLOITABLE = 0.70` traverse tous nos scripts, et la phrase « 0 page
sur 25 exploitables » en dépend entièrement. Or ce nombre n'a jamais été
mesuré : il vient d'un raisonnement plausible (« en dessous, le recadrage
mord sur l'en-tête »), pas d'une observation. Une convention déguisée en
critère.

Ce script la confronte à ce qui compte vraiment : **la lecture**.

La référence par page
---------------------
Le TEDS se calcule d'habitude par facture, pas par page — la vérité terrain
donne les lignes d'une facture, sans dire lesquelles sont sur quelle page. On
contourne en prenant comme référence la lecture des **pages à plat**
(`variants_chandra`, TEDS 0,981 contre la vérité terrain). À ce niveau de
fidélité, la lecture d'une page à plat EST la vérité de cette page.

On mesure donc, page par page :

    IoU     du recadrage, contre le masque UV exact
    TEDS    de la lecture PRÉTRAITÉE, contre la lecture de la page à plat

Les deux jeux sont regroupés pour couvrir toute la plage : `variants_warped`
fournit les IoU hauts, `variants_encombre` les bas.

    python scripts/eval_seuil_iou.py
"""

import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "src"))

try:
    import cv2
    import numpy as np
except ImportError:
    raise SystemExit("Il faut opencv et numpy.")

from preprocess import detect_document_quad  # noqa: E402
from table_merge import extract_tables  # noqa: E402
from teds import rows_to_html, teds  # noqa: E402

DOC3D = RACINE.parent / "doc3D-renderer"

# (jeu d'images, run prétraité à noter)
PAIRES = [("variants_warped", "variants_warped_preprocessed_chandra"),
          ("variants_encombre", "variants_encombre_preproc_chandra")]
REFERENCE = "variants_chandra"          # les mêmes pages, à plat


def verite(exr):
    import Imath
    import OpenEXR
    f = OpenEXR.InputFile(str(exr))
    dw = f.header()["dataWindow"]
    w, h = dw.max.x - dw.min.x + 1, dw.max.y - dw.min.y + 1
    pt = Imath.PixelType(Imath.PixelType.FLOAT)
    return np.frombuffer(f.channel("B", pt), dtype=np.float32).reshape(h, w) > 0.5


def iou(quad, vrai):
    if quad is None:
        return 0.0
    p = np.zeros(vrai.shape, np.uint8)
    cv2.fillPoly(p, [np.asarray(quad, np.int32)], 1)
    p = p.astype(bool)
    u = (p | vrai).sum()
    return float((p & vrai).sum() / u) if u else 0.0


def table_de_page(run, numero):
    """Le plus grand tableau lu sur cette page, ou None."""
    base = RACINE / "results" / run / "pages"
    if not base.is_dir():
        return None
    dossiers = [d for d in base.iterdir()
                if d.is_dir() and d.name.startswith(f"page_{numero}-")]
    if not dossiers:
        return None
    md = list(dossiers[0].glob("*.md"))
    if not md:
        return None
    trouves = extract_tables(md[0].read_text(encoding="utf-8"))
    return max(trouves, key=lambda t: len(t.rows)) if trouves else None


# Les points sont mis en cache : 50 pages de detection + TEDS depassent la
# minute, et on veut pouvoir relancer l'analyse sans tout recalculer.
CACHE = RACINE / "results" / "_evaluations" / "seuil_iou.json"


def main():
    import argparse
    import json
    ap = argparse.ArgumentParser()
    ap.add_argument("--jeu", action="append",
                    help="Ne calculer que ce(s) jeu(x). Repetable. Les points "
                         "s'accumulent dans le cache.")
    ap.add_argument("--recalculer", action="store_true",
                    help="Ignorer le cache.")
    args = ap.parse_args()

    def num(p):
        return int(re.match(r"page_(\d+)", p.name).group(1))

    cache = {}
    if CACHE.exists() and not args.recalculer:
        cache = {tuple(k.split("|")): v for k, v in
                 json.loads(CACHE.read_text(encoding="utf-8")).items()}

    points = []
    for jeu, run in PAIRES:
        if args.jeu and jeu not in args.jeu:
            # Le jeu n'est pas demande : on reprend ses points du cache.
            points += [(j, int(n), v[0], v[1]) for (j, n), v in cache.items()
                       if j == jeu]
            continue
        img, uv = DOC3D / "img" / jeu, DOC3D / "uv" / jeu
        if not img.is_dir():
            print(f"(jeu {jeu} absent, ignoré)")
            continue
        for chemin in sorted(img.glob("*.png"), key=num):
            exr = uv / f"{chemin.stem}.exr"
            if not exr.exists():
                continue
            n = num(chemin)
            ref = table_de_page(REFERENCE, n)
            lu = table_de_page(run, n)
            if ref is None:
                continue

            vrai = verite(exr)
            image = cv2.imread(str(chemin))
            trouve = detect_document_quad(image, min_score=0.55, return_score=True)
            quad = trouve[0] if isinstance(trouve, tuple) else None
            score_iou = iou(quad, vrai)

            qualite = (0.0 if lu is None
                       else teds(rows_to_html(lu.rows), rows_to_html(ref.rows)))
            points.append((jeu, n, score_iou, qualite))
            print(f"  {jeu} page {n:<3} IoU {score_iou:.2f}  TEDS {qualite:.2f}",
                  flush=True)

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    fusion = dict(cache)
    for jeu, n, a, b in points:
        fusion[(jeu, str(n))] = [a, b]
    CACHE.write_text(json.dumps({f"{k[0]}|{k[1]}": v for k, v in fusion.items()},
                                indent=1), encoding="utf-8")
    points = [(j, int(n), v[0], v[1]) for (j, n), v in fusion.items()]

    if not points:
        raise SystemExit("Aucun point : les runs sont-ils dans results/ ?")

    ious = np.array([p[2] for p in points])
    teds_ = np.array([p[3] for p in points])
    print(f"{len(points)} pages\n")

    # Des tranches d'IoU, et la lecture obtenue dans chacune. Si un seuil
    # existe, c'est là qu'il se voit : une tranche où le TEDS s'effondre.
    bornes = [0.0, 0.2, 0.4, 0.5, 0.6, 0.7, 0.8, 1.01]
    print(f"{'tranche IoU':<16}{'pages':>7}{'TEDS moyen':>13}{'TEDS median':>14}")
    print("-" * 50)
    for a, b in zip(bornes, bornes[1:]):
        m = (ious >= a) & (ious < b)
        if not m.any():
            continue
        print(f"{f'{a:.1f} – {b:.1f}':<16}{m.sum():>7}"
              f"{teds_[m].mean():>13.2f}{np.median(teds_[m]):>14.2f}")
    print("-" * 50)
    print(f"corrélation IoU / TEDS : r = {np.corrcoef(ious, teds_)[0, 1]:+.2f}")

    # Le seuil qui sépare le mieux les bonnes lectures des mauvaises.
    # « Bonne » = TEDS >= 0,70, la même barre que pour le recadrage, appliquée
    # cette fois à ce qui nous intéresse vraiment.
    bonne = teds_ >= 0.70
    print(f"\nLectures correctes (TEDS >= 0,70) : {bonne.sum()}/{len(points)}")
    print(f"\n{'seuil IoU':>10}{'exactitude':>12}{'vrais pos.':>12}"
          f"{'faux pos.':>11}{'faux neg.':>11}")
    print("-" * 56)
    meilleur = (0.0, -1.0)
    for s in np.arange(0.30, 0.91, 0.05):
        predit = ious >= s
        vp = int((predit & bonne).sum())
        fp = int((predit & ~bonne).sum())
        fn = int((~predit & bonne).sum())
        exact = float((predit == bonne).mean())
        if exact > meilleur[1]:
            meilleur = (s, exact)
        print(f"{s:>10.2f}{exact:>12.0%}{vp:>12}{fp:>11}{fn:>11}")
    print("-" * 56)
    print(f"\nSeuil le plus discriminant : {meilleur[0]:.2f} "
          f"({meilleur[1]:.0%} d'accord avec la qualité de lecture).")
    print("À comparer au 0,70 utilisé partout. S'ils diffèrent nettement, la")
    print("convention est à corriger — et toutes les phrases « N pages sur 25")
    print("exploitables » avec elle.")


if __name__ == "__main__":
    main()
