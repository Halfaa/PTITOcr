"""
Rend le jeu de test à plus haute résolution, et mesure ce que ça change.

Nos rendus font 900 px de large. Une photo de téléphone en fait 3000 à 4000.
Ce facteur quatre n'est pas un détail cosmétique : il décide de ce qui reste
lisible dans les petits éléments de la page.

Mesuré : le QR fait 67 px à 900 px de large, soit 2,7 pixels par module quand
un décodeur en demande environ 3. Rendu directement depuis le PDF il décode ;
passé par la déformation 3D, il ne décode plus. Il n'y avait aucune marge.

    python scripts/rendre_haute_resolution.py --largeur 1800
    python scripts/rendre_haute_resolution.py --mesure-seulement

Ce script rend depuis le **PDF source**, donc à plat. C'est délibéré : il
produit la référence « papier parfait » à cette résolution, et il mesure le
plafond du QR. Pour obtenir les versions déformées il faut repasser par
Blender (`doc3D-renderer/render_variants.ps1`) avec la même largeur — ce
script écrit les PNG dont le pipeline 3D a besoin.
"""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "src"))
from env_check import require as _require_env

_require_env("eval")

import argparse  # noqa: E402

from qrcode_lecture import lire_qr  # noqa: E402

PDF_DEFAUT = (RACINE.parent / "synthetic_invoice_generator" / "hospital_pharmacy"
              / "invoices_multipage_xelatex.pdf")


def rendre(pdf: Path, largeur: int, sortie: Path = None):
    """Rend chaque page du PDF à la largeur voulue, et lit le QR au passage."""
    import cv2
    import fitz
    import numpy as np

    document = fitz.open(pdf)
    if sortie:
        sortie.mkdir(parents=True, exist_ok=True)

    resultats = []
    for n, page in enumerate(document, start=1):
        zoom = largeur / page.rect.width
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR if pix.n == 3
                           else cv2.COLOR_RGBA2BGR)
        if sortie:
            # Nom aligné sur celui qu'attend le reste de la chaîne : le
            # numéro de page en tête, puisque tout le pipeline l'extrait par
            # « premier entier du nom de fichier ».
            cv2.imwrite(str(sortie / f"page_{n}-flat_{largeur}.png"), img)
        resultats.append((n, img.shape[1], lire_qr(img)))
    return resultats


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--pdf", default=str(PDF_DEFAUT))
    p.add_argument("--largeur", type=int, default=1800)
    p.add_argument("--sortie", default=None,
                   help="Dossier des PNG. Par défaut : "
                        "../doc3D-renderer/img/multipage_flat_<largeur>")
    p.add_argument("--mesure-seulement", action="store_true",
                   help="Compare plusieurs largeurs sans rien écrire.")
    args = p.parse_args()

    pdf = Path(args.pdf)
    if not pdf.exists():
        raise SystemExit(f"PDF introuvable : {pdf}")

    if args.mesure_seulement:
        print("Lecture du QR selon la largeur de rendu (pages à plat, "
              "sans déformation) :\n")
        print(f"{'largeur':>9}{'pages avec QR':>16}{'décodés':>10}"
              f"{'px/module médian':>20}")
        print("-" * 55)
        for largeur in (900, 1200, 1800, 2400, 3600):
            res = rendre(pdf, largeur)
            avec = [q for _, _, q in res if q["trouve"]]
            dec = [q for q in avec if q["decode"]]
            med = (sorted(q["px_par_module"] for q in avec)[len(avec) // 2]
                   if avec else None)
            print(f"{largeur:>9}{len(avec):>10}/{len(res):<5}{len(dec):>10}"
                  f"{med if med else '—':>20}")
        print("\nUn décodeur demande environ 3 px par module ; en dessous de 2,"
              "\naucune sur-résolution ne récupère l'information — elle n'est"
              "\nplus dans le signal.")
        return

    sortie = Path(args.sortie) if args.sortie else (
        RACINE.parent / "doc3D-renderer" / "img" / f"multipage_flat_{args.largeur}")
    res = rendre(pdf, args.largeur, sortie)
    avec = [q for _, _, q in res if q["trouve"]]
    dec = [q for q in avec if q["decode"]]

    print(f"{len(res)} page(s) rendues à {args.largeur} px -> {sortie}")
    print(f"QR : {len(avec)} repéré(s), {len(dec)} décodé(s)")
    for n, _, q in res:
        if q["trouve"]:
            print(f"   page {n:>2} : {q['px_par_module']} px/module — "
                  f"{q['decode'] or q['diagnostic']}")

    print("\nPour les versions déformées, repasser ces PNG dans Blender :")
    print("   cd ..\\doc3D-renderer  &&  .\\render_variants.ps1")


if __name__ == "__main__":
    main()
