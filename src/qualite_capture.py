"""
Juger une photo AVANT de la lire : nettete et resolution.

Le §6 de `docs/application.md` liste ce controle comme manquant, et c'est le
moment ou la correction coute le moins cher -- l'utilisateur tient encore le
document. Aujourd'hui `qrcode_lecture.qualite_de_capture` fait un travail
voisin mais INDIRECT : elle deduit que la capture etait bonne du fait qu'un
QR a decode. Le QR n'existe que sur la derniere page d'une facture, jamais
sur un formulaire manuscrit, et son absence ne dit rien. Ce module-ci mesure
l'image elle-meme, sur n'importe quel document.

Les seuils ne sont pas choisis, ils sont MESURES
------------------------------------------------
`docs/degradation_handwriting.md` donne la part de champs retrouves par
Chandra selon la degradation, et `scripts/degrader.py --calibrer` donne la
variance du laplacien des memes images. Les deux tables se recoupent palier
par palier (specimens manuscrits, 1654 px de large) :

    flou     nettete   champs lus
    aucun      3551      100,0 %
     6 px       743       97,2 %
    11 px       218       73,2 %
    17 px       102       43,7 %
    24 px        49       15,5 %
    37 px        25        8,5 %

Le seuil retenu, 400, tombe entre le palier a 97 % et celui a 73 %. C'est
donc « en dessous, on sait qu'on perd au moins un quart des champs », et non
une valeur ronde posee au jugé.

Cote resolution, la meme etude donne 100 % a 1241 px de large et 88,7 % a
910 px : d'ou 950 px comme plancher, interpolé au point ou l'on passe sous
90 %.

Trois reserves, a garder en tete avant de croire un verdict
-----------------------------------------------------------
**La variance du laplacien depend du contenu.** Une page tres remplie sort
un chiffre plus haut qu'une page vide, a nettete egale. Nos deux jeux de
reference sont des formulaires denses ; sur un document tres aere, le seuil
sera pessimiste.

**Elle depend aussi de la taille.** On mesure donc toujours a une resolution
de travail fixe (`COTE_MESURE`), sinon deux photos de la meme scene prises a
des definitions differentes donneraient des chiffres incomparables.

**Elle a ete calibree sur du flou SYNTHETIQUE.** Un vrai bouge de telephone
et un flou de mise au point ne produisent pas la meme signature. Les seuils
sont des reperes utiles, pas une garantie : c'est le jeu de photos reelles
qui les validera.

Usage :
    from qualite_capture import mesurer
    verdict = mesurer(image_bgr)                 # image entiere
    verdict = mesurer(image_bgr, quad=quad)      # avec le document localise

    python src/qualite_capture.py photo1.jpg photo2.jpg
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Cote long auquel la nettete est mesuree. Toute image est ramenee la avant
# le laplacien, pour que deux photos de definitions differentes restent
# comparables.
COTE_MESURE = 1654

# Nettete (variance du laplacien) mesuree sur les paliers de flou, avec la
# part de champs retrouves en face. Sert au seuil ET au message : annoncer
# « on perdra environ un quart des champs » est plus actionnable que
# « nettete 218 ».
REPERES_NETTETE = [
    (3551, 100.0),
    (743, 97.2),
    (218, 73.2),
    (102, 43.7),
    (49, 15.5),
    (25, 8.5),
]

SEUIL_NETTETE = 400        # entre le palier a 97 % et celui a 73 %
SEUIL_NETTETE_BASSE = 150  # en dessous, on est deja sous la moitie des champs

# Largeur de PAGE, pas d'image : si le document n'occupe qu'un quart du
# cadre, la definition de la photo ne dit rien de ce que le modele verra.
SEUIL_LARGEUR = 950
SEUIL_LARGEUR_BASSE = 600


def _nettete(image) -> float:
    """Variance du laplacien, a resolution de mesure fixe."""
    import cv2

    cote = max(image.shape[:2])
    if cote != COTE_MESURE:
        f = COTE_MESURE / cote
        image = cv2.resize(image, None, fx=f, fy=f,
                           interpolation=cv2.INTER_AREA)
    gris = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gris, cv2.CV_64F).var())


def _champs_attendus(nettete: float) -> float:
    """Interpole la part de champs lisibles a cette nettete.

    Une interpolation sur six points mesures, pas un modele : elle sert a
    formuler le message, pas a produire un chiffre publiable.
    """
    reperes = sorted(REPERES_NETTETE)
    if nettete <= reperes[0][0]:
        return reperes[0][1]
    if nettete >= reperes[-1][0]:
        return reperes[-1][1]
    for (n0, c0), (n1, c1) in zip(reperes, reperes[1:]):
        if n0 <= nettete <= n1:
            part = (nettete - n0) / (n1 - n0) if n1 > n0 else 0
            return c0 + part * (c1 - c0)
    return reperes[-1][1]


def _largeur_page(image, quad=None) -> tuple:
    """(largeur en px, si elle vient du document ou de l'image entiere).

    Avec le quadrilatere du document on mesure la PAGE ; sans lui on ne peut
    que mesurer l'image, ce qui SURESTIME des que la feuille n'occupe pas
    tout le cadre. La distinction est rendue a l'appelant plutot que noyee :
    un plancher franchi sur une mesure surestimee ne vaut pas un plancher
    franchi sur la vraie page.
    """
    if quad is None:
        return float(max(image.shape[:2])), False

    import numpy as np

    pts = np.asarray(quad, dtype=float).reshape(-1, 2)
    cotes = [float(np.linalg.norm(pts[i] - pts[(i + 1) % len(pts)]))
             for i in range(len(pts))]
    # Le grand cote du quadrilatere : c'est lui qui porte la hauteur de page,
    # donc la taille des caracteres.
    return max(cotes), True


def mesurer(image, quad=None) -> dict:
    """Juge une image. Rend un verdict, ses mesures, et un message lisible."""
    nettete = _nettete(image)
    largeur, mesuree_sur_page = _largeur_page(image, quad)
    champs = _champs_attendus(nettete)

    motifs = []
    if nettete < SEUIL_NETTETE_BASSE:
        motifs.append(("refus", f"image tres floue (nettete {nettete:.0f}) : "
                                f"environ {champs:.0f} % des champs seraient lus"))
    elif nettete < SEUIL_NETTETE:
        motifs.append(("alerte", f"image floue (nettete {nettete:.0f}) : "
                                 f"environ {champs:.0f} % des champs seraient lus"))

    ou = "la page" if mesuree_sur_page else "l'image (page non localisee)"
    if largeur < SEUIL_LARGEUR_BASSE:
        motifs.append(("refus", f"definition trop faible : {largeur:.0f} px sur "
                                f"{ou}, il en faut {SEUIL_LARGEUR}"))
    elif largeur < SEUIL_LARGEUR:
        motifs.append(("alerte", f"definition juste : {largeur:.0f} px sur {ou}, "
                                 f"{SEUIL_LARGEUR} recommandes"))

    if any(niveau == "refus" for niveau, _ in motifs):
        etat = "refus"
    elif motifs:
        etat = "alerte"
    else:
        etat = "bonne"

    messages = [texte for _, texte in motifs]
    return {
        "etat": etat,
        "message": " ; ".join(messages) if messages
                   else f"nettete {nettete:.0f}, {largeur:.0f} px sur {ou}",
        "nettete": round(nettete, 1),
        "largeur_page_px": round(largeur),
        "largeur_mesuree_sur_page": mesuree_sur_page,
        "champs_attendus_pct": round(champs, 1),
        "motifs": messages,
    }


def _cli():
    import cv2

    chemins = [Path(a) for a in sys.argv[1:]]
    if not chemins:
        print(__doc__.strip().splitlines()[0])
        print("\nUsage : python src/qualite_capture.py <image> [image...]")
        return

    print(f"{'image':<38}{'etat':<10}{'nettete':>9}{'largeur':>9}  message")
    print("-" * 110)
    for chemin in chemins:
        image = cv2.imread(str(chemin))
        if image is None:
            print(f"{chemin.name:<38}illisible")
            continue
        v = mesurer(image)
        print(f"{chemin.name:<38}{v['etat']:<10}{v['nettete']:>9.0f}"
              f"{v['largeur_page_px']:>9}  {v['message']}")


if __name__ == "__main__":
    _cli()
