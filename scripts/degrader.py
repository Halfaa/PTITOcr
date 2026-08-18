"""
Dégrader des pages de façon graduée et reproductible, pour tracer la courbe
de robustesse de la chaîne.

Pourquoi cette étude. Tous nos chiffres viennent de rendus Blender parfaits :
mise au point nette, éclairage maîtrisé, PNG sans perte. On sait donc que la
chaîne marche en laboratoire, et rien de plus. La question que l'encadrante
posera — **à partir de quelle qualité de photo cesse-t-elle de fonctionner ?**
— n'a aujourd'hui aucune réponse chiffrée, et c'est aussi le seul moyen, avant
d'avoir des photos réelles, de savoir si 0,97 est un chiffre robuste.

Les quatre dégradations sont celles d'une photo prise à la va-vite dans un
couloir d'hôpital, et pas un catalogue d'effets :

    flou        bougé de la main pendant la pose
    bruit       montée en ISO en lumière faible
    jpeg        compression de l'appareil ou de la messagerie
    exposition  sous-exposition, puis remontée par le traitement

Physique, pas cosmétique
------------------------
Trois choix qui changent le résultat et qu'il faut assumer.

**On travaille en lumière linéaire.** Un capteur intègre des photons, pas des
valeurs sRGB. Flouter ou bruiter directement les octets d'un PNG revient à
mélanger des grandeurs déjà passées par la gamma, ce qui donne un flou trop
sombre et un bruit mal réparti entre ombres et hautes lumières. On délinéarise
donc avant, on ré-encode après.

**Le bruit est dépendant du signal.** Le bruit d'un capteur est d'abord du
bruit de grenaille — Poisson, donc plus fort là où il y a de la lumière — plus
un bruit de lecture gaussien constant. Un bruit gaussien uniforme, le réflexe
habituel, épargne les blancs du papier alors que c'est justement là qu'il se
voit.

**La sous-exposition détruit par la QUANTIFICATION.** Assombrir une image puis
la ré-éclaircir est réversible à la virgule près ; ce qui ne l'est pas, c'est
que le capteur écrit 8 bits. À −3 diaphragmes, la page n'occupe plus qu'un
huitième de l'échelle, soit une trentaine de niveaux au lieu de 255. On
assombrit donc, on quantifie, on ajoute le bruit de lecture, et on ré-éclaircit
— c'est ce qu'un téléphone fait, et c'est là que l'information se perd.

Usage
-----
    python scripts/degrader.py --jeu variants_warped
    python scripts/degrader.py --jeu variants_warped --pages 1,2,3,4,11,12,13,14
    python scripts/degrader.py --jeu variants_warped --calibrer

`--calibrer` n'écrit rien : il mesure sur une page ce que chaque niveau fait
réellement (netteté, rapport signal/bruit, niveaux restants), pour que les
paliers soient décrits par des grandeurs mesurées et non par des noms.
"""

import argparse
import sys
import zipfile
import zlib
from pathlib import Path

try:
    import cv2
    import numpy as np
except ImportError:
    raise SystemExit("Il faut opencv et numpy :\n"
                     "    pip install 'opencv-python<4.12' 'numpy<2'")

RACINE = Path(__file__).resolve().parent.parent
DOC3D = RACINE.parent / "doc3D-renderer"

# Les 4 factures retenues par défaut, soit 8 pages.
#
# On garde des factures COMPLÈTES : le TEDS se calcule sur la facture
# reconstituée, une page orpheline fausserait la mesure. Et on garde les mêmes
# pages à tous les niveaux, ce qui rend la comparaison appariée -- bien plus
# solide, à effectif égal, que de tirer des pages différentes à chaque palier.
PAGES_DEFAUT = [1, 2, 3, 4, 11, 12, 13, 14]      # factures 1, 2, 6, 7


# --------------------------------------------------------------------------
# Lumière linéaire

def _vers_lineaire(image):
    x = image.astype(np.float32) / 255.0
    # sRGB -> linéaire, formule exacte plutôt qu'un gamma 2,2 approché.
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def _vers_srgb(lineaire):
    x = np.clip(lineaire, 0.0, 1.0)
    y = np.where(x <= 0.0031308, x * 12.92, 1.055 * x ** (1 / 2.4) - 0.055)
    return np.clip(y * 255.0 + 0.5, 0, 255).astype(np.uint8)


# --------------------------------------------------------------------------
# Les quatre dégradations

def flou_de_bouge(image, longueur, angle=20.0):
    """Bougé de la main : convolution par un segment.

    Un vrai bougé est un déplacement pendant la pose, donc l'intégrale de
    l'image le long d'une trajectoire -- approchée ici par un segment droit,
    ce qui est le cas dominant sur une pose courte. La longueur est en pixels
    à la résolution source.
    """
    if longueur < 2:
        return image.copy()
    noyau = np.zeros((longueur, longueur), np.float32)
    noyau[longueur // 2, :] = 1.0
    rotation = cv2.getRotationMatrix2D((longueur / 2 - 0.5, longueur / 2 - 0.5),
                                       angle, 1.0)
    noyau = cv2.warpAffine(noyau, rotation, (longueur, longueur))
    somme = noyau.sum()
    if somme <= 0:
        return image.copy()
    noyau /= somme
    return _vers_srgb(cv2.filter2D(_vers_lineaire(image), -1, noyau))


def bruit_capteur(image, photons_max, lecture=0.004, graine=0):
    """Bruit de grenaille (Poisson) + bruit de lecture (gaussien).

    `photons_max` est le nombre d'électrons collectés par un pixel saturé :
    c'est lui qui fixe le rapport signal/bruit, en racine. Plus il est bas,
    plus l'ISO est élevé. Le bruit de lecture est en fraction de la pleine
    échelle et domine dans les ombres.
    """
    rng = np.random.default_rng(graine)
    lineaire = _vers_lineaire(image)
    bruite = rng.poisson(lineaire * photons_max) / float(photons_max)
    bruite = bruite + rng.normal(0.0, lecture, lineaire.shape)
    return _vers_srgb(bruite)


def reduction(image, fraction):
    """Redimensionnement, tel qu'une messagerie l'inflige.

    C'est LA dégradation qui tue le petit texte, et elle manquait. Mesuré
    ici : la qualité JPEG seule sature à 24 dB de PSNR -- en dessous de q=3
    l'encodeur ne dégrade plus, parce qu'une page blanche à texte contrasté
    est précisément ce que le JPEG compresse bien. Le texte reste lisible à
    q=1. Ce qui le détruit, c'est de perdre des pixels.

    INTER_AREA et non INTER_LINEAR : c'est le filtre correct pour réduire,
    il moyenne les pixels source au lieu d'en échantillonner un sur n, donc
    il ne crée pas d'aliasing sur les traits fins du tableau.

    L'image reste à sa taille réduite : c'est le fichier tel qu'il arrive.
    """
    h, w = image.shape[:2]
    return cv2.resize(image, (max(1, int(w * fraction)), max(1, int(h * fraction))),
                      interpolation=cv2.INTER_AREA)


def compression_jpeg(image, qualite):
    ok, tampon = cv2.imencode(".jpg", image,
                              [int(cv2.IMWRITE_JPEG_QUALITY), int(qualite)])
    if not ok:
        raise RuntimeError("Encodage JPEG impossible")
    return cv2.imdecode(tampon, cv2.IMREAD_COLOR)


def sous_exposition(image, diaphragmes, lecture=0.003, graine=0,
                    rendre_sombre=False):
    """Sous-exposer, subir les 8 bits, puis ré-éclaircir.

    L'ordre est tout : c'est la quantification à 8 bits de l'image SOMBRE qui
    détruit l'information, pas la multiplication. À −3 diaphragmes la page
    n'occupe plus qu'un huitième de l'échelle.

    `rendre_sombre` rend l'état intermédiaire, celui où les 8 bits frappent.
    Il ne sert qu'à la calibration : c'est le seul endroit où la perte se
    mesure. Une fois l'image ré-éclaircie, le bruit de lecture a dispersé
    l'histogramme et le nombre de valeurs distinctes REMONTE -- il ne dit
    donc plus rien de l'information disponible.
    """
    rng = np.random.default_rng(graine)
    facteur = 2.0 ** (-abs(diaphragmes))
    lineaire = _vers_lineaire(image) * facteur
    lineaire = lineaire + rng.normal(0.0, lecture, lineaire.shape)

    sombre = _vers_srgb(lineaire)                 # <- les 8 bits frappent ici
    if rendre_sombre:
        return sombre
    remonte = _vers_lineaire(sombre) / facteur
    return _vers_srgb(remonte)


# --------------------------------------------------------------------------
# Les paliers.
#
# Cinq niveaux par dégradation, du à peine visible au franchement abîmé. Les
# valeurs sont choisies pour encadrer le point de rupture attendu, pas pour
# être régulières : une courbe plate sur cinq points ne dit rien.

# Paliers resserrés autour des ruptures repérées à l'œil sur la planche
# demo/figures/11_paliers_degradation.png. La première grille était mal
# calibrée : le flou passait de lisible à illisible entre deux paliers, et le
# JPEG restait lisible au palier le plus dur. Une courbe plate ne dit rien, et
# coûte quand même 40 pages de GPU.
NIVEAUX = {
    "flou":       [3, 6, 9, 13, 20],             # longueur du bougé, en px
    "bruit":      [500, 150, 50, 20, 8],         # photons à saturation
    "exposition": [2.0, 3.0, 4.0, 5.0, 6.0],     # diaphragmes sous-exposés
    "resolution": [0.75, 0.55, 0.40, 0.30, 0.22],  # fraction du côté long
    # Trois paliers seulement, et c'est un choix : l'échelle sature. Entre
    # q=3 et q=1 le PSNR ne bouge plus (23,8 dB), donc trois points suffisent
    # à montrer que la compression seule n'est pas la menace.
    "jpeg":       [25, 10, 3],                   # facteur qualité
}


def appliquer(image, degradation, valeur, graine=0):
    if degradation == "flou":
        return flou_de_bouge(image, int(valeur))
    if degradation == "bruit":
        return bruit_capteur(image, float(valeur), graine=graine)
    if degradation == "jpeg":
        return compression_jpeg(image, int(valeur))
    if degradation == "resolution":
        return reduction(image, float(valeur))
    if degradation == "exposition":
        return sous_exposition(image, float(valeur), graine=graine)
    raise ValueError(degradation)


# --------------------------------------------------------------------------
# Calibration : décrire les paliers par ce qu'ils font, pas par leur nom.

def nettete(image):
    """Variance du laplacien : l'indicateur de netteté usuel."""
    gris = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gris, cv2.CV_64F).var())


def psnr(reference, image):
    """PSNR, ou None quand les tailles diffèrent.

    Comparer pixel à pixel deux images de tailles différentes n'a pas de
    sens ; ré-agrandir la petite pour y arriver mesurerait l'interpolation
    autant que la dégradation. Pour la réduction, la grandeur parlante est
    la hauteur de caractère restante, pas le PSNR.
    """
    if reference.shape != image.shape:
        return None
    erreur = np.mean((reference.astype(np.float64) - image.astype(np.float64)) ** 2)
    return float("inf") if erreur <= 0 else float(10 * np.log10(255.0 ** 2 / erreur))


def niveaux_distincts(image):
    """Combien de valeurs de gris distinctes ?

    Attention au sens de lecture, qui n'est pas le même selon la dégradation.
    Le flou fusionne des niveaux et le compte BAISSE ; le bruit en invente et
    il MONTE. Ce n'est donc pas une mesure de qualité, c'est une mesure de
    dispersion de l'histogramme.

    Pour la sous-exposition en particulier, il faut le mesurer sur l'image
    SOMBRE : après ré-éclaircissement, le bruit de lecture a dispersé
    l'histogramme et le compte remonte alors même que l'information est
    perdue. Première version de ce tableau : la colonne montait de 167 à 203
    en assombrissant de cinq diaphragmes, ce qui donnait exactement l'inverse
    de la réalité.
    """
    gris = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return int(np.count_nonzero(np.bincount(gris.ravel(), minlength=256)))


def calibrer(image):
    print(f"{'dégradation':<12}{'niveau':<10}{'netteté':>10}{'PSNR dB':>10}"
          f"{'gris':>7}{'poids ko':>10}{'taille':>12}")
    print("-" * 71)
    base_poids = len(cv2.imencode(".png", image)[1]) / 1024
    print(f"{'(aucune)':<12}{'—':<10}{nettete(image):>10.0f}{'∞':>10}"
          f"{niveaux_distincts(image):>7}{base_poids:>10.0f}"
          f"{f'{image.shape[1]}x{image.shape[0]}':>12}")
    for degradation, valeurs in NIVEAUX.items():
        for i, v in enumerate(valeurs, 1):
            abime = appliquer(image, degradation, v)
            poids = len(cv2.imencode(".png", abime)[1]) / 1024
            # Cas particulier assumé : pour la sous-exposition, le nombre de
            # gris n'a de sens que sur l'état sombre. Voir niveaux_distincts.
            pour_gris = (sous_exposition(image, v, rendre_sombre=True)
                         if degradation == "exposition" else abime)
            valeur_psnr = psnr(image, abime)
            texte_psnr = ("—" if valeur_psnr is None
                          else f"{valeur_psnr:.1f}")
            taille = f"{abime.shape[1]}x{abime.shape[0]}"
            print(f"{degradation:<12}{f'{i} ({v:g})':<10}{nettete(abime):>10.0f}"
                  f"{texte_psnr:>10}{niveaux_distincts(pour_gris):>7}"
                  f"{poids:>10.0f}{taille:>12}")
    print("\n  netteté  variance du laplacien — chute avec le flou, MONTE avec")
    print("           le bruit, qui est de la haute fréquence lui aussi")
    print("  PSNR     écart à l'original ; sous ~28 dB la dégradation se voit")
    print("  gris     valeurs distinctes sur 256 — mesuré sur l'image SOMBRE")
    print("           pour la sous-exposition, seul état où les 8 bits mordent")
    print("  poids    taille en PNG : le bruit est incompressible, il enfle ;")
    print("           le flou et le JPEG l'allègent")


# --------------------------------------------------------------------------

def ecrire_zip(dossiers, racine_sortie, archive):
    """Archive avec des séparateurs UNIX, seuls valides dans un zip.

    Surtout pas `Compress-Archive` de PowerShell 5.1 : il écrit les
    sous-dossiers avec des antislashs, alors que la spécification ZIP impose
    la barre oblique. Kaggle refuse l'import avec « contains a forbidden
    character in name ('\\') », et le message ne dit pas d'où ça vient. Le
    défaut est corrigé dans PowerShell 7, mais Windows livre encore la 5.1.

    C'est le premier zip du projet à contenir des sous-dossiers -- les
    précédents étaient plats, d'où le fait que le piège n'ait jamais mordu.
    """
    archive.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for nom, lot in dossiers.items():
            for fichier, _ in lot:
                chemin = racine_sortie / nom / fichier.name
                z.write(chemin, arcname=f"{nom}/{fichier.name}")
                n += 1
    mauvais = [i for i in zipfile.ZipFile(archive).namelist() if "\\" in i]
    assert not mauvais, f"antislash dans {len(mauvais)} entrées"
    return n


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--jeu", default="variants_warped")
    p.add_argument("--pages", default=None,
                   help="Numéros séparés par des virgules. Défaut : "
                        + ",".join(map(str, PAGES_DEFAUT)))
    p.add_argument("--out", default=None)
    p.add_argument("--zip", action="store_true",
                   help="Écrire kaggle/images_degradation.zip, prêt pour Kaggle.")
    p.add_argument("--calibrer", action="store_true",
                   help="Mesurer les paliers sur une page, sans rien écrire.")
    args = p.parse_args()

    source = DOC3D / "img" / args.jeu
    fichiers = sorted(source.glob("page_*.png"))
    if not fichiers:
        raise SystemExit(f"Aucune image dans {source}")

    voulues = ([int(x) for x in args.pages.split(",")] if args.pages
               else PAGES_DEFAUT)
    def numero(f):
        return int(f.name.split("-")[0].replace("page_", ""))
    retenues = [f for f in fichiers if numero(f) in voulues]
    manquantes = set(voulues) - {numero(f) for f in retenues}
    if manquantes:
        raise SystemExit(f"Pages absentes de {args.jeu} : {sorted(manquantes)}")

    if args.calibrer:
        image = cv2.imread(str(retenues[0]))
        print(f"Calibration sur {retenues[0].name}  "
              f"({image.shape[1]}x{image.shape[0]})\n")
        calibrer(image)
        return

    racine_sortie = Path(args.out) if args.out else (DOC3D / "img" / "degradation")
    total = 0

    # Le niveau 0 est indispensable : c'est la même page, passée par le même
    # code d'écriture, sans dégradation. Sans lui on comparerait la courbe à
    # un chiffre mesuré ailleurs, et le moindre écart de pipeline se lirait
    # comme un effet de la dégradation.
    dossiers = {"niveau0": [(f, cv2.imread(str(f))) for f in retenues]}
    for degradation, valeurs in NIVEAUX.items():
        for i, valeur in enumerate(valeurs, 1):
            lot = []
            for f in retenues:
                image = cv2.imread(str(f))
                # Graine liée à la page ET au palier : reproductible d'un
                # lancement à l'autre, mais pas identique d'une page à
                # l'autre, ce qui ferait un bruit corrélé irréaliste.
                #
                # crc32 et non hash() : le hash des chaînes est SALÉ par
                # processus depuis Python 3.3, donc deux lancements ne
                # donneraient pas le même bruit. Même piège déjà rencontré
                # dans doc3D-renderer/distracteurs.py.
                graine = zlib.crc32(
                    f"{f.name}|{degradation}|{i}".encode("utf-8"))
                lot.append((f, appliquer(image, degradation, valeur, graine)))
            dossiers[f"{degradation}{i}"] = lot

    for nom, lot in dossiers.items():
        dossier = racine_sortie / nom
        dossier.mkdir(parents=True, exist_ok=True)
        for f, image in lot:
            cv2.imwrite(str(dossier / f.name), image)
            total += 1
        print(f"  {nom:<14}{len(lot):>3} pages -> {dossier}")

    # Les lots d'un ancien découpage traînent et partiraient dans le zip.
    # On ne les supprime pas d'autorité -- effacer des images sans le dire est
    # le genre de service qu'on ne rend pas -- mais on refuse de les ignorer.
    perimes = sorted(d.name for d in racine_sortie.iterdir()
                     if d.is_dir() and d.name not in dossiers)
    if perimes:
        print(f"\nLots PÉRIMÉS, d'une grille précédente : {', '.join(perimes)}")
        print("  Ils seraient zippés avec les autres et fausseraient le run.")
        print("  À supprimer :")
        for nom in perimes:
            print(f"    Remove-Item -Recurse -Force {racine_sortie / nom}")

    print(f"\n{total} images dans {racine_sortie}")
    print(f"{len(dossiers)} lots × {len(retenues)} pages")

    if args.zip:
        archive = RACINE / "kaggle" / "images_degradation.zip"
        n = ecrire_zip(dossiers, racine_sortie, archive)
        print(f"\n{archive}  ({n} entrées, "
              f"{archive.stat().st_size / 1e6:.0f} Mo)")
        print("  Kaggle : Add Input -> Datasets, nommer le dataset "
              "« degradation ».")
    else:
        print("\nPour l'archive Kaggle, relancer avec --zip.")
        print("  Ne PAS utiliser Compress-Archive : voir ecrire_zip().")


if __name__ == "__main__":
    main()
