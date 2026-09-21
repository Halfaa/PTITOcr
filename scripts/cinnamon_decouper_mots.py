"""
Decoupe les LIGNES manuscrites du jeu Cinnamon en MOTS isoles.

Pourquoi
---------
WriteViT travaille au niveau du mot : ses images font 32 px de haut et ~16 px
par caractere, et son alphabet vietnamien ne contient ni espace ni
ponctuation. Le jeu Cinnamon, lui, est fait de lignes entieres
(« Số 3 Nguyễn Ngọc Vũ, Hà Nội ») sans boites englobantes. Pour affiner le
modele sur cette ecriture, il faut donc fabriquer les mots nous-memes.

Le garde-fou, qui fait tout l'interet de la methode
-----------------------------------------------------
Un decoupage rate ne se voit pas a l'oeil sur 1838 lignes, et une paire
(image, label) mal alignee apprend au modele a ecrire n'importe quoi. Mais on
connait la reponse : le label dit combien de mots la ligne contient.

On n'accepte donc une ligne QUE si le nombre de fragments trouves egale le
nombre de mots du label. Sinon on l'ecarte. C'est conservateur -- on perd des
lignes -- mais chaque paire conservee est verifiee par construction.

Le seuil d'ecart est CHERCHE, pas fixe
----------------------------------------
Un seuil unique ne peut pas convenir : l'espacement varie d'un scripteur a
l'autre, et meme d'un mot a l'autre. Plutot que d'en choisir un mauvais pour
tout le monde, on balaie une plage et on retient le premier seuil qui donne
le bon nombre de fragments. Le label sert d'oracle -- ce n'est pas de la
triche, c'est exactement l'information dont on dispose.

Usage :
    python scripts/cinnamon_decouper_mots.py \\
        --images ../datasets/vn_lignes/vn_handwritten_images/data \\
        --labels ../datasets/vn_lignes/vn_handwritten_images/labels.json
"""

import argparse
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

EXT = (".png", ".jpg", ".jpeg")
HAUTEUR = 32          # hauteur cible, celle de WriteViT
SEPARATEURS = re.compile(r"[^\w]+", re.UNICODE)


def _lire(chemin: Path):
    data = np.fromfile(str(chemin), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)


def _ecrire(chemin: Path, img):
    ok, buf = cv2.imencode(".png", img)
    if ok:
        buf.tofile(str(chemin))
    return ok


def mots_du_label(texte: str):
    """Tokens du label, ponctuation retiree -- comme pour le lexique medical."""
    texte = unicodedata.normalize("NFC", str(texte))
    return [m for m in SEPARATEURS.split(texte) if m]


def colonnes_encrees(img):
    """Profil vertical : True la ou la colonne contient de l'encre.

    Otsu + inversion plutot qu'un seuil fixe : les photos Cinnamon n'ont ni
    le meme fond ni le meme contraste d'une prise a l'autre.
    """
    _, binaire = cv2.threshold(img, 0, 255,
                               cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return binaire.sum(axis=0) > 0, binaire


def fragments(encre, ecart_min: int):
    """Intervalles [debut, fin) separes par au moins `ecart_min` colonnes vides."""
    bords, dans, debut = [], False, 0
    vides = 0
    for x, plein in enumerate(encre):
        if plein:
            if not dans:
                dans, debut = True, x
            vides = 0
        elif dans:
            vides += 1
            if vides >= ecart_min:
                bords.append((debut, x - vides + 1))
                dans = False
    if dans:
        bords.append((debut, len(encre)))
    return bords


def desaccord(bords, mots) -> float:
    """Ecart entre la repartition des LARGEURS et celle des CARACTERES.

    Le bon nombre de fragments ne prouve pas les bonnes coupes : un
    diacritique detache compte pour un fragment pendant que deux mots
    fusionnent, et le total tombe juste. Mesure faite sur 300 lignes, ce cas
    representait les deux tiers des rejets tardifs.

    On dispose pourtant d'une contrainte forte et gratuite : dans une
    ecriture donnee, la largeur d'un mot suit a peu pres son nombre de
    caracteres. On compare donc les deux repartitions, normalisees, par leur
    distance en variation totale -- 0 si elles coincident, 1 si elles sont
    disjointes. Une coupe qui separe un accent donne un fragment minuscule
    la ou le label attend un mot long : le desaccord explose.
    """
    largeurs = np.array([b - a for a, b in bords], dtype=float)
    carac = np.array([len(m) for m in mots], dtype=float)
    if largeurs.sum() <= 0 or carac.sum() <= 0:
        return 1.0
    return float(np.abs(largeurs / largeurs.sum()
                        - carac / carac.sum()).sum() / 2)


def decouper(img, mots, plage, tolerance: float):
    """Meilleur decoupage en len(mots) fragments, ou rien.

    Tous les seuils qui donnent le bon compte sont evalues, et c'est le plus
    COHERENT qui gagne -- pas le premier trouve. Deux seuils differents
    peuvent produire le bon nombre de fragments a des endroits differents ;
    s'arreter au premier revenait a tirer au sort.
    """
    encre, _ = colonnes_encrees(img)
    if not encre.any():
        return None, "image vide"

    candidats = []
    for ecart in plage:
        bords = fragments(encre, ecart)
        if len(bords) == len(mots):
            candidats.append((desaccord(bords, mots), bords))
    if not candidats:
        return None, "aucun seuil ne donne le bon compte"

    score, bords = min(candidats, key=lambda c: c[0])
    if score > tolerance:
        # Une ligne dont on n'a pas su retrouver les mots est une ligne dont
        # on ignore a quoi correspond chaque fragment : elle est ecartee, pas
        # rattrapee.
        return None, f"desaccord {score:.2f} > {tolerance}"
    return bords, None


def normaliser_hauteur(vignette):
    h, l = vignette.shape[:2]
    if h == 0 or l == 0:
        return None
    return cv2.resize(vignette, (max(1, int(round(l * HAUTEUR / h))), HAUTEUR),
                      interpolation=cv2.INTER_AREA)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", required=True)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--sortie", default="../datasets/cinnamon_mots")
    ap.add_argument("--ecart-min", type=int, default=4)
    ap.add_argument("--ecart-max", type=int, default=40)
    ap.add_argument("--limite", type=int, default=0)
    ap.add_argument("--tolerance", type=float, default=0.20,
                    help="Desaccord largeurs/caracteres maximal accepte "
                         "(distance en variation totale, 0 = parfait).")
    args = ap.parse_args()

    labels = json.loads(Path(args.labels).read_text(encoding="utf-8"))
    images = sorted(p for p in Path(args.images).iterdir()
                    if p.suffix.lower() in EXT)
    if args.limite:
        images = images[: args.limite]
    print(f"{len(images)} lignes, {len(labels)} labels")

    sortie = Path(args.sortie)
    (sortie / "images").mkdir(parents=True, exist_ok=True)
    plage = range(args.ecart_min, args.ecart_max + 1)

    mots_sortis, causes = {}, Counter()
    gardees = 0
    for p in images:
        label = labels.get(p.name)
        if label is None:
            causes["sans label"] += 1
            continue
        attendus = mots_du_label(label)
        if not attendus:
            causes["label vide"] += 1
            continue

        img = _lire(p)
        if img is None:
            causes["illisible"] += 1
            continue

        bords, raison = decouper(img, attendus, plage, args.tolerance)
        if bords is None:
            causes[raison.split()[0] if raison else "decoupage"] += 1
            continue

        vignettes = []
        for (x0, x1), mot in zip(bords, attendus):
            v = normaliser_hauteur(img[:, x0:x1])
            if v is None or v.shape[1] < 8:
                vignettes = None
                break
            vignettes.append((v, mot))
        if vignettes is None:
            causes["fragment trop etroit"] += 1
            continue

        for i, (v, mot) in enumerate(vignettes):
            nom = f"{p.stem}_{i:02d}.png"
            if _ecrire(sortie / "images" / nom, v):
                mots_sortis[nom] = mot
        gardees += 1

    (sortie / "labels.json").write_text(
        json.dumps(mots_sortis, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\nlignes conservees : {gardees}/{len(images)} "
          f"({gardees / len(images):.0%})")
    for cause, n in causes.most_common():
        print(f"  ecartees, {cause:<22} {n}")
    print(f"\n{len(mots_sortis)} mots ecrits -> {sortie}")
    if mots_sortis:
        distincts = len(set(mots_sortis.values()))
        print(f"  {distincts} mots distincts")


if __name__ == "__main__":
    main()
