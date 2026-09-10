"""
Préparer les pages manuscrites comme TEXTURES pour le rendu Blender.

But : soumettre le manuscrit au même traitement que les factures —
déformation 3D, éclairage HDR, et (une fois le plan récepteur ajouté, voir
plus bas) ombres portées. Aujourd'hui les specimens sont des rendus
parfaitement plats, alors que tous les chiffres factures ont été mesurés
sous déformation : la comparaison manuscrit/imprimé porte donc sur deux
régimes différents, et ce script existe pour supprimer cet écart.

`doc3D-renderer` attend simplement un dossier de PNG plats, listés dans un
CSV par `generate_multipage_tex_csv.py`. Il n'y a donc rien à convertir :
copier les specimens au bon endroit suffit.

    python scripts/preparer_textures_manuscrit.py
    python scripts/preparer_textures_manuscrit.py --langue vi --n 10

Puis, depuis doc3D-renderer :

    .\\render_variants.ps1 -FolderId handwriting_vi_warped `
        -Source tex/handwriting_vi -TexCsv tex_handwriting_vi.csv -Verifier

`-Verifier` ne rend qu'UNE image : à regarder avant d'engager le lot, c'est
la seule façon de voir si le texte manuscrit survit à la projection.

Le nom des sorties, et pourquoi il compte
-----------------------------------------
`render_mesh_multipage.py` nomme ses rendus `<texture>-<maillage>`, donc
`specimen_000.png` ressort en `specimen_000-concave_mesh_10001.png`. La
vérité terrain, elle, reste indexée sur `specimen_000`. `VeriteDir.get()`
dans `src/eval_handwriting.py` retombe sur la partie avant le premier tiret
pour cette raison — sans quoi un run sur le manuscrit déformé ne trouverait
aucune vérité et sortirait un zéro qu'on lirait comme un échec du modèle.

Deux réserves à lever AVANT de lancer le lot complet
-----------------------------------------------------
**La résolution de rendu est codée en dur à 900x1200** dans
`render_mesh_multipage.py` (lignes 119-120). Nos specimens font 1654x2339 :
les projeter tels quels ramènerait le texte manuscrit à 54 % de sa taille,
et la courbe mélangerait alors deux causes — la déformation et la perte de
résolution. Or on sait déjà, par l'étude de dégradation, que la résolution
est la dégradation la plus brutale. Il faut donc porter la résolution de
rendu à la hauteur des specimens avant de conclure quoi que ce soit.

**Il n'y a pas d'ombre portée**, contrairement à ce qu'on pourrait attendre.
La scène n'a qu'un éclairage HDR de monde, sans plan récepteur : la feuille
s'auto-ombre en se courbant, mais rien ne reçoit son ombre. Les feuilles
parasites (`-Parasites`) sont placées derrière le long de l'axe de vue,
elles n'en projettent pas davantage. Une vraie ombre portée demande
d'ajouter un plan sous le document dans la scène Blender.

C'est aussi ce qui explique le §16 de `docs/fonds_encombres.md` : le bord de
la feuille est invisible faute d'ombre et de profondeur de champ. Ajouter le
plan récepteur servirait donc deux expériences d'un coup.
"""

import argparse
import shutil
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
DOC3D = RACINE.parent / "doc3D-renderer"

SOURCES = {
    "vi": RACINE / "handwriting" / "generated",
    "en": RACINE / "handwriting_en" / "generated",
}


def preparer(langue: str, n: int | None) -> int:
    source = SOURCES[langue]
    if not source.is_dir():
        print(f"  {source} absent -- générer d'abord les specimens.")
        return 0

    # Les specimens vivent dans un sous-dossier chacun ; les textures, elles,
    # sont attendues à plat.
    images = sorted(source.glob("*/*.png"))
    if n:
        images = images[:n]
    if not images:
        print(f"  aucune image dans {source}")
        return 0

    destination = DOC3D / "tex" / f"handwriting_{langue}"
    destination.mkdir(parents=True, exist_ok=True)

    # Un dossier de textures qui contient un reste d'un lot précédent
    # produirait des rendus qu'on croirait à jour. On le vide.
    anciens = list(destination.glob("*.png"))
    for f in anciens:
        f.unlink()
    if anciens:
        print(f"  {len(anciens)} texture(s) précédente(s) retirée(s)")

    for img in images:
        shutil.copy2(img, destination / img.name)

    from PIL import Image
    with Image.open(images[0]) as im:
        taille = im.size
    print(f"  {len(images)} textures -> {destination}")
    print(f"  résolution des specimens : {taille[0]}x{taille[1]}")
    if taille[0] > 900:
        print(f"  ATTENTION : le rendu est codé en dur à 900x1200, soit "
              f"{900 / taille[0]:.0%} de cette largeur.")
        print("  Relever resolution_x/resolution_y dans "
              "render_mesh_multipage.py (lignes 119-120)")
        print("  avant le lot complet, sinon la déformation et la perte de")
        print("  résolution seront mesurées ensemble.")
    return len(images)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--langue", choices=["vi", "en", "toutes"], default="toutes")
    p.add_argument("--n", type=int, default=None,
                   help="Nombre de specimens à préparer (défaut : tous).")
    args = p.parse_args()

    if not DOC3D.is_dir():
        raise SystemExit(
            f"{DOC3D} absent.\n"
            "Le rendu vit dans un dépôt voisin :\n"
            "    git clone https://github.com/anhdungdo0906/doc3D-renderer.git")

    langues = ["vi", "en"] if args.langue == "toutes" else [args.langue]
    total = 0
    for langue in langues:
        print(f"\n{langue} :")
        total += preparer(langue, args.n)

    if not total:
        return
    print("\nEnsuite, depuis doc3D-renderer, une image d'essai par langue :")
    for langue in langues:
        print(f"    .\\render_variants.ps1 -FolderId handwriting_{langue}_warped "
              f"-Source tex/handwriting_{langue} "
              f"-TexCsv tex_handwriting_{langue}.csv -Verifier")
    print("\nRegarder le rendu d'essai AVANT le lot : c'est la seule façon de")
    print("voir si l'écriture manuscrite survit à la projection.")


if __name__ == "__main__":
    main()
