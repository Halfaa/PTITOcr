"""
Fabriquer les planches visuelles des paliers de degradation (manuscrit).

Un chiffre dit qu'on perd 43,7 % des champs a 17 px de bouge ; il ne dit pas
a quoi ressemble la page a ce moment-la. Ces planches mettent la meme zone
de la meme page cote a cote d'un palier a l'autre, avec son score : c'est ce
qui rend la limite lisible en reunion, sans avoir a croire le tableau sur
parole.

    python scripts/figure_paliers_manuscrit.py
    python scripts/figure_paliers_manuscrit.py --jeu handwriting_vi_degradation

Produit dans demo/figures/ :
    17_paliers_manuscrit_flou.png         le bouge, 5 paliers + reference
    18_paliers_manuscrit_resolution.png   la reduction, 5 paliers + reference

La zone recadree est le bloc identite (items 1 a 6) : nom, date de
naissance, numero d'identification. C'est la que se joue la lisibilite, et
ce sont des champs qu'un lecteur reconnait au premier coup d'oeil.

Pour la RESOLUTION, les vignettes sont reagrandies a une largeur commune.
Ce n'est pas de la triche : c'est precisement ce que voit un modele a qui
on donne une image reduite, et les mettre cote a cote a leur taille reelle
rendrait la comparaison illisible.

NON EXECUTE ici : l'environnement d'execution de l'assistant etait casse au
moment de l'ecriture (montage Windows). A verifier en regardant les deux
PNG produits.
"""

import argparse
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
DOC3D = RACINE.parent / "doc3D-renderer"
SORTIE = RACINE / "demo" / "figures"

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    raise SystemExit("Il faut Pillow :\n    pip install pillow")

# Bloc identite (items 1-6), en fractions de la page : le recadrage suit
# donc la taille de l'image, y compris sur les paliers de resolution ou
# elle a change.
ZONE = (0.05, 0.13, 0.95, 0.24)   # gauche, haut, droite, bas

LARGEUR = 1100          # largeur commune des vignettes
MARGE = 12
HAUTEUR_TITRE = 34

# Scores mesures (Chandra, jeu anglais). Affiches sous chaque vignette :
# une planche sans ses chiffres se fait citer de travers.
SCORES = {
    "niveau0": ("reference", "100.0%"),
    "flou1": ("6 px", "97.2%"),
    "flou2": ("11 px", "73.2%"),
    "flou3": ("17 px", "43.7%"),
    "flou4": ("24 px", "15.5%"),
    "flou5": ("37 px", "8.5%"),
    "resolution1": ("1241 px wide", "100.0%"),
    "resolution2": ("910 px", "88.7%"),
    "resolution3": ("662 px", "63.4%"),
    "resolution4": ("496 px", "45.1%"),
    "resolution5": ("364 px", "18.3%"),
}

# Les dossiers de paliers gardent leurs noms francais -- c'est degrader.py
# qui les ecrit, et les renommer casserait les runs deja produits. Seul ce
# qui est IMPRIME sur la planche est traduit : les figures sont destinees a
# circuler.
ETIQUETTES = {
    "niveau0": "baseline",
    "flou": "blur",
    "bruit": "noise",
    "exposition": "underexposure",
    "resolution": "resolution",
    "jpeg": "JPEG",
}


def _etiquette(palier: str) -> str:
    """`flou2` -> `blur 2`, `niveau0` -> `baseline`."""
    if palier in ETIQUETTES:
        return ETIQUETTES[palier]
    famille = palier.rstrip("0123456789")
    niveau = palier[len(famille):]
    return f"{ETIQUETTES.get(famille, famille)} {niveau}".strip()


def _police(taille):
    """Une police lisible, sans supposer laquelle est installee."""
    for chemin in ("C:/Windows/Fonts/arial.ttf",
                   "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                   "/Library/Fonts/Arial.ttf"):
        try:
            return ImageFont.truetype(chemin, taille)
        except OSError:
            continue
    return ImageFont.load_default()


def vignette(chemin: Path, titre: str, score: str, police) -> Image.Image:
    with Image.open(chemin) as im:
        im = im.convert("RGB")
        l, h = im.size
        boite = (int(ZONE[0] * l), int(ZONE[1] * h),
                 int(ZONE[2] * l), int(ZONE[3] * h))
        crop = im.crop(boite)

    # Largeur commune : sur les paliers de resolution la vignette est
    # reagrandie, ce qui montre exactement l'information perdue.
    hauteur = max(1, round(crop.height * LARGEUR / crop.width))
    crop = crop.resize((LARGEUR, hauteur), Image.LANCZOS)

    planche = Image.new("RGB", (LARGEUR, hauteur + HAUTEUR_TITRE), "white")
    planche.paste(crop, (0, HAUTEUR_TITRE))
    d = ImageDraw.Draw(planche)
    d.text((4, 8), f"{titre}", fill="black", font=police)
    d.text((LARGEUR - 230, 8), f"fields read: {score}", fill="black", font=police)
    d.line([(0, HAUTEUR_TITRE - 1), (LARGEUR, HAUTEUR_TITRE - 1)], fill="#cccccc")
    return planche


def planche(jeu: Path, paliers, specimen: str, destination: Path):
    police = _police(20)
    vignettes = []
    for palier in paliers:
        chemin = jeu / palier / f"{specimen}.png"
        if not chemin.exists():
            print(f"  {palier} absent ({chemin}), saute")
            continue
        titre, score = SCORES.get(palier, ("", "?"))
        etiquette = _etiquette(palier)
        vignettes.append(vignette(
            chemin, f"{etiquette} — {titre}" if titre else etiquette,
            score, police))

    if not vignettes:
        print(f"  aucune vignette pour {destination.name}")
        return

    hauteur = sum(v.height for v in vignettes) + MARGE * (len(vignettes) + 1)
    finale = Image.new("RGB", (LARGEUR + 2 * MARGE, hauteur), "white")
    y = MARGE
    for v in vignettes:
        finale.paste(v, (MARGE, y))
        y += v.height + MARGE

    destination.parent.mkdir(parents=True, exist_ok=True)
    finale.save(destination)
    print(f"  {len(vignettes)} paliers -> {destination}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--jeu", default="handwriting_en_degradation")
    p.add_argument("--specimen", default="specimen_000")
    args = p.parse_args()

    jeu = DOC3D / "img" / args.jeu
    if not jeu.is_dir():
        raise SystemExit(f"{jeu} absent -- generer d'abord avec scripts/degrader.py")

    print("flou :")
    planche(jeu, ["niveau0", "flou1", "flou2", "flou3", "flou4", "flou5"],
            args.specimen, SORTIE / "17_paliers_manuscrit_flou.png")
    print("resolution :")
    planche(jeu, ["niveau0", "resolution1", "resolution2", "resolution3",
                  "resolution4", "resolution5"],
            args.specimen, SORTIE / "18_paliers_manuscrit_resolution.png")

    print("\nA regarder avant de s'en servir : la zone recadree doit montrer")
    print("le bloc identite (nom, date de naissance, numero d'ID). Si elle")
    print("tombe a cote, ajuster ZONE en haut du script.")


if __name__ == "__main__":
    main()
