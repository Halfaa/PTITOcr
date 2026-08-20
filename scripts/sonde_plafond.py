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


# Deux mots de texte appartiennent au meme document s'ils sont proches, de
# meme taille et de meme inclinaison. Ces trois seuils definissent « meme ».
_DIST_MAX = 6.0      # en hauteurs de caractere
_RAPPORT_TAILLE = 1.7
_ANGLE_MAX = 18.0    # degres


def _mots(petit):
    """Les blocs-mots de l'image : centre, taille, inclinaison."""
    gris = cv2.cvtColor(petit, cv2.COLOR_BGR2GRAY)
    grad = cv2.morphologyEx(gris, cv2.MORPH_GRADIENT, np.ones((3, 3), np.uint8))
    _, bw = cv2.threshold(grad, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # Noyau de 5, pas de 9, et surtout pas proportionnel a la resolution.
    # Mesure sur une page encombree : k=5 rend 138 mots, k=9 en rend 109,
    # k=27 seulement 63. Elargir le noyau ne recolle pas mieux les mots, il
    # fusionne des colonnes entieres du tableau, et les pates obtenues sont
    # rejetees par le filtre de forme.
    fusion = cv2.morphologyEx(bw, cv2.MORPH_CLOSE, np.ones((1, 5), np.uint8))

    n, etiquettes, stats, centres = cv2.connectedComponentsWithStats(fusion, 8)
    mots = []
    for i in range(1, n):
        x, y, w, h, aire = stats[i]
        # Un mot imprime est plus LARGE que haut. Les veines d'un marbre ou
        # les fibres d'une moquette donnent des taches rondes ou verticales.
        if aire < 20 or not (3 <= h <= petit.shape[0] // 15) or w < 1.5 * h:
            continue
        points = cv2.findNonZero((etiquettes == i).astype(np.uint8))
        (_, _), (rw, rh), angle = cv2.minAreaRect(points)
        if rw < rh:                      # normaliser : l'angle du GRAND cote
            angle += 90.0
        mots.append({"centre": centres[i], "hauteur": float(h),
                     "angle": angle % 180.0, "points": points})
    return mots


# Cote long auquel on cherche le texte.
#
# Surtout PAS les 480 px de travail : a cette echelle, sur une scene encombree
# ou la feuille cible n'occupe qu'un quart du cadre, un caractere fait deux
# pixels et le filtre de forme ne retient plus rien -- mesure, 5 mots sur une
# page entiere. Meme lecon qu'avec SAM : 480 px est un compromis regle pour
# des taches de luminance, pas pour du texte.
COTE_TEXTE = 1400

# Front-end de detection des mots : morphologique par defaut, DBNet avec
# --dbnet. Le premier ne demande rien, le second demande `venv`.
MOTS_APPRIS = False


_detecteur = None


def _mots_dbnet(image):
    """Les mots vus par le detecteur de texte de PaddleOCR (DBNet).

    Le front-end morphologique de `_mots` est le maillon faible de la piste
    texte : mesure, 26 a 138 mots par page la ou une facture en contient plus
    de trois cents, et deux pages sur dix n'en donnent pas assez pour former
    le moindre bloc. Le regroupement, lui, fait son travail des qu'on
    l'alimente.

    DBNet est un detecteur appris, deja installe dans `venv` avec PaddleOCR.
    Il rend des quadrilateres de mots fiables, y compris sur du texte
    faiblement contraste et incline -- exactement ce qui manque ici.

    NON TESTE au moment ou ces lignes sont ecrites : PaddleOCR n'existe pas
    dans l'environnement ou ce code a ete redige. L'API `PaddleOCR(det=True,
    rec=False)` est celle du projet, mais son retour peut avoir change de
    forme selon la version -- d'ou le decorticage defensif ci-dessous, et le
    message explicite s'il ne rend rien.
    """
    global _detecteur
    if _detecteur is None:
        try:
            from paddleocr import PaddleOCR
        except ImportError:
            raise SystemExit(
                "Le detecteur DBNet demande PaddleOCR, donc l'environnement "
                "`venv` :\n    .\\venv\\Scripts\\activate\n"
                "C'est le meme venv que pour eval_preprocess et les "
                "evaluations.")
        # Les trois desactivations sont INDISPENSABLES, pas de l'optimisation.
        #
        # Par defaut, PaddleOCR fait tourner en amont un classifieur
        # d'orientation (PP-LCNet_doc_ori) et un dewarping (UVDoc). Il
        # detecte donc le texte sur une image REDRESSEE, et rend des
        # polygones dans le repere de cette image-la -- pas dans le notre.
        # Les coordonnees sont alors inutilisables pour situer une feuille
        # dans la photo d'origine, et rien ne le signale : on recupere des
        # boites parfaitement valides, simplement au mauvais endroit.
        #
        # C'est exactement ce qui s'est produit au premier essai, et ca
        # expliquait un plafond de 0,37 qu'on aurait pu prendre pour un
        # echec de la methode.
        _detecteur = PaddleOCR(use_doc_orientation_classify=False,
                               use_doc_unwarping=False,
                               use_textline_orientation=False,
                               lang="en")

    brut = _detecteur.predict(image)
    boites = []
    for page in (brut or []):
        # Selon la version, le resultat est un dict-like ou un objet ; on
        # cherche les polygones sous les deux noms connus.
        for cle in ("dt_polys", "rec_polys", "boxes"):
            valeur = None
            if isinstance(page, dict) and cle in page:
                valeur = page[cle]
            elif hasattr(page, cle):
                valeur = getattr(page, cle)
            if valeur is not None and len(valeur):
                boites = list(valeur)
                break
        if boites:
            break

    if not boites:
        raise SystemExit(
            "DBNet n'a rendu aucune boite. La forme du resultat de PaddleOCR "
            "a probablement\nchange : afficher `type(brut)` et son contenu, "
            "puis ajuster _mots_dbnet.")

    mots = []
    for boite in boites:
        points = np.asarray(boite, dtype=np.float32).reshape(-1, 1, 2)
        (cx, cy), (rw, rh), angle = cv2.minAreaRect(points)
        if rw < rh:
            angle += 90.0
            rw, rh = rh, rw
        mots.append({"centre": np.array([cx, cy]), "hauteur": float(max(rh, 1.0)),
                     "angle": angle % 180.0, "points": points.astype(np.int32)})
    return mots


def candidats_texte(petit, image=None, echelle=1.0):
    """Un document = un BLOC de texte coherent, pas une zone claire.

    C'est le seul indice qui survit au blanc-sur-blanc. Quand la feuille et le
    fond ont la meme couleur, la meme saturation et la meme texture, il reste
    que le texte imprime est a haut contraste et qu'il est, par construction,
    SUR la feuille.

    `_text_hull_contour` de preprocess.py exploite deja cette idee, mais prend
    l'enveloppe de TOUT le texte de l'image : sur un bureau encombre, elle
    englobe les cinq feuilles a la fois. Ce qui manque, c'est de les separer.

    Le critere de regroupement. Deux mots appartiennent au meme document s'ils
    sont proches, de meme corps et de meme inclinaison. L'inclinaison est le
    discriminant fort : chaque feuille posee sur le bureau a sa propre
    rotation, alors que sa luminance est identique a celle des voisines. On
    construit donc un graphe de voisinage sur ces trois criteres et on prend
    ses composantes connexes -- une par bloc de texte, donc une par feuille.

    LIMITE CONNUE, et elle est dans la detection des mots, pas dans le
    regroupement. Le front-end morphologique (gradient + Otsu + fermeture)
    ne trouve que 26 a 138 mots par page la ou une facture en contient plus
    de trois cents, et sur une page il n'en trouve pas assez pour former le
    moindre bloc. Le regroupement, lui, fait ce qu'on lui demande des qu'il a
    de la matiere : 1 a 3 blocs par image, la ou les feuilles sont.
    Autrement dit, l'idee n'est pas invalidee -- elle est mal alimentee.

    La suite naturelle est de remplacer ce front-end par un vrai detecteur de
    texte appris. On en a DEJA un installe : le module de detection de
    PaddleOCR, dans `venv`. C'est un DBNet entraine, il rend des boites de
    mots fiables, et le regroupement ci-dessous s'y branche sans changer une
    ligne. C'est la mesure a faire avant de conclure quoi que ce soit sur
    cette piste.
    """
    # On cherche le texte en haute resolution, on rend les contours a
    # l'echelle de travail pour rester comparable aux autres generateurs.
    source = petit if image is None else image
    facteur = COTE_TEXTE / max(source.shape[:2])
    if facteur < 1.0:
        travail = cv2.resize(source, None, fx=facteur, fy=facteur,
                             interpolation=cv2.INTER_AREA)
    else:
        travail, facteur = source, 1.0
    vers_travail = (1.0 if image is None else echelle) / facteur

    mots = _mots_dbnet(travail) if MOTS_APPRIS else _mots(travail)
    if len(mots) < 6:
        return []

    # Union-find : O(n^2) sur quelques centaines de mots, c'est instantane et
    # ca evite une dependance a scipy.
    parent = list(range(len(mots)))

    def racine(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(mots)):
        for j in range(i + 1, len(mots)):
            a, b = mots[i], mots[j]
            echelle_locale = max(a["hauteur"], b["hauteur"])
            if np.hypot(*(a["centre"] - b["centre"])) > _DIST_MAX * echelle_locale:
                continue
            if max(a["hauteur"], b["hauteur"]) > _RAPPORT_TAILLE * min(
                    a["hauteur"], b["hauteur"]):
                continue
            ecart = abs(a["angle"] - b["angle"])
            if min(ecart, 180.0 - ecart) > _ANGLE_MAX:
                continue
            ra, rb = racine(i), racine(j)
            if ra != rb:
                parent[ra] = rb

    blocs = {}
    for i, mot in enumerate(mots):
        blocs.setdefault(racine(i), []).append(mot)

    contours = []
    for bloc in blocs.values():
        # Un bloc de moins de huit mots n'est pas un document : c'est du bruit
        # de fond qui a passe les filtres de forme.
        if len(bloc) < 8:
            continue
        points = np.vstack([m["points"] for m in bloc])
        enveloppe = cv2.convexHull(points).reshape(-1, 2).astype(np.float32)
        # La feuille deborde de son texte d'au moins une marge d'impression.
        centre = enveloppe.mean(axis=0)
        grossie = (centre + (enveloppe - centre) * 1.18) * vers_travail
        grossie[:, 0] = np.clip(grossie[:, 0], 0, petit.shape[1] - 1)
        grossie[:, 1] = np.clip(grossie[:, 1], 0, petit.shape[0] - 1)
        contours.append(grossie.astype(np.int32).reshape(-1, 1, 2))
    return contours


# Etiquettes de mise en page qui appartiennent au CORPS d'un document.
# `image` est exclu : un logo ou un QR peut etre pose a cote de la feuille.
_BLOCS_DOCUMENT = {"table", "text", "paragraph_title", "title", "header",
                   "footer", "abstract", "content", "seal", "formula"}

# Marge ajoutee autour du groupe de blocs. Une feuille deborde de son contenu
# imprime d'au moins une marge, et le modele ne detecte que le contenu.
_MARGE_LAYOUT = 1.15


def candidats_layout(petit, image=None, echelle=1.0, dossier_json=None):
    """Les blocs de mise en page de PaddleOCR-VL, groupes par feuille.

    Decouvert sur un smoke test : le detecteur de mise en page de
    PaddleOCR-VL **separe les feuilles**. Sur une page encombree il rend deux
    tableaux distincts -- un a 3,3 % du cadre (une feuille parasite) et un a
    19,4 % (la facture cible) -- la ou nos seuillages fondent tout en une
    tache. C'est ce que SAM ne savait pas faire : SAM decoupe des objets,
    lui connait la notion de document.

    On ne relance pas le modele : les boites sont deja dans le `_res.json`
    ecrit par `bench_deformed.py`. Cette sonde ne coute donc aucun GPU, elle
    exploite un run existant.

    Le regroupement est spatial : un tableau et les textes qui le touchent
    appartiennent a la meme feuille. On part de chaque bloc `table` -- le
    coeur d'une facture -- et on agrege les blocs qui le chevauchent ou le
    jouxtent, puis on prend l'enveloppe, elargie d'une marge d'impression.
    """
    if dossier_json is None:
        return []
    fichiers = list(Path(dossier_json).glob("*_res.json"))
    if not fichiers:
        return []
    import json
    donnees = json.loads(fichiers[0].read_text(encoding="utf-8"))
    boites = [(b["label"], b["coordinate"])
              for b in donnees.get("layout_det_res", {}).get("boxes", [])
              if b["label"] in _BLOCS_DOCUMENT]
    if not boites:
        return []

    # Facteur image pleine -> echelle de travail. Le JSON est en coordonnees
    # de l'image d'origine, comme celle passee au modele.
    vers_travail = echelle if image is not None else 1.0

    def touche(a, b, marge=20.0):
        return not (a[2] + marge < b[0] or b[2] + marge < a[0]
                    or a[3] + marge < b[1] or b[3] + marge < a[1])

    contours = []
    for etiquette, ancre in boites:
        if etiquette != "table":
            continue
        groupe = [ancre]
        change = True
        while change:                     # fermeture transitive du voisinage
            change = False
            for _, autre in boites:
                if any(autre is g for g in groupe):
                    continue
                if any(touche(autre, g) for g in groupe):
                    groupe.append(autre)
                    change = True

        xs = [c for b in groupe for c in (b[0], b[2])]
        ys = [c for b in groupe for c in (b[1], b[3])]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        demi_l = (max(xs) - min(xs)) / 2 * _MARGE_LAYOUT
        demi_h = (max(ys) - min(ys)) / 2 * _MARGE_LAYOUT
        boite = np.array([[cx - demi_l, cy - demi_h], [cx + demi_l, cy - demi_h],
                          [cx + demi_l, cy + demi_h], [cx - demi_l, cy + demi_h]],
                         dtype=np.float32) * vers_travail
        boite[:, 0] = np.clip(boite[:, 0], 0, petit.shape[1] - 1)
        boite[:, 1] = np.clip(boite[:, 1], 0, petit.shape[0] - 1)
        contours.append(boite.astype(np.int32).reshape(-1, 1, 2))
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


def candidats_oracle(petit, image=None, echelle=1.0, verite=None):
    """Le contour EXACT de la feuille, pris dans la verite terrain.

    Ce n'est pas un generateur utilisable : il triche, par construction. Il
    sert de TEMOIN, et il repond a une question qu'on n'aurait jamais du
    laisser sans reponse -- le seuil de 0,70 est-il seulement ATTEIGNABLE ?

    Tous les generateurs rendent un rectangle tourne (`minAreaRect`). Une
    feuille photographiee de biais et gondolee n'est pas un rectangle : le
    meilleur rectangle qui l'englobe garde forcement du fond a l'interieur.
    Ce temoin mesure ce plafond-la, celui de la REPRESENTATION, sans aucune
    detection.

    Sans lui on compare des scores a un seuil dont on ignore s'il est dans le
    domaine du possible, et on conclut « la detection echoue » alors que
    c'est peut-etre la FORME du candidat qui est en cause.
    """
    if verite is None:
        return []
    trouves, _ = cv2.findContours(verite.astype(np.uint8), cv2.RETR_EXTERNAL,
                                  cv2.CHAIN_APPROX_SIMPLE)
    if not trouves:
        return []
    contour = max(trouves, key=cv2.contourArea)
    return [(contour.astype(np.float32) * echelle).astype(np.int32)]


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
    p.add_argument("--dbnet", action="store_true",
                   help="Detecter les mots avec DBNet (PaddleOCR) au lieu "
                        "de la morphologie. Demande le venv `venv`.")
    p.add_argument("--layout", metavar="RUN",
                   help="Ajouter les blocs de mise en page de PaddleOCR-VL, "
                        "lus dans les _res.json d'un run existant. Aucun GPU.")
    p.add_argument("--oracle", action="store_true",
                   help="Temoin : le seuil de 0,70 est-il atteignable "
                        "avec un rectangle tourne sur cette verite ?")
    p.add_argument("--texte", action="store_true",
                   help="Ajouter le generateur par blocs de texte. Aucune "
                        "dependance, tourne en une seconde par page.")
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

    if args.dbnet:
        globals()["MOTS_APPRIS"] = True
        args.texte = True
        print("Detection des mots par DBNet (PaddleOCR)")

    generateurs = {"actuel": candidats_actuels}
    if args.layout:
        generateurs["layout"] = candidats_layout
        generateurs["actuel+layout"] = None       # assemble dans la boucle
    if args.oracle:
        generateurs["ORACLE (temoin)"] = candidats_oracle
    if args.texte:
        generateurs["texte"] = candidats_texte
        generateurs["actuel+texte"] = (
            lambda pt, im=None, ec=1.0: candidats_actuels(pt, im, ec)
                                        + candidats_texte(pt, im, ec))
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
            dossier_json = None
            if args.layout:
                dossiers = list((RACINE / "results" / args.layout /
                                 "pages").glob(f"{chemin.stem}*"))
                dossier_json = dossiers[0] if dossiers else None
            if nom.startswith("ORACLE"):
                contours = candidats_oracle(petit, image, echelle, verite)
            elif nom == "layout":
                contours = candidats_layout(petit, image, echelle, dossier_json)
            elif nom == "actuel+layout":
                contours = (candidats_actuels(petit, image, echelle)
                            + candidats_layout(petit, image, echelle,
                                               dossier_json))
            else:
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
    if_temoin = "ORACLE (temoin)"
    if if_temoin in resultats:
        plafond_forme = np.mean(resultats[if_temoin]["plafond"])
        print(f"\nTEMOIN : avec le contour EXACT de la feuille, un "
              f"rectangle tourne\nplafonne a {plafond_forme:.2f} d'IoU.")
        if plafond_forme < SEUIL_EXPLOITABLE + 0.05:
            print(f"  Le seuil de {SEUIL_EXPLOITABLE:.2f} est donc hors "
                  "d'atteinte QUELLE QUE SOIT la detection :")
            print("  ce n'est pas la localisation qui echoue, c'est la "
                  "FORME du candidat.")
            print("  Une feuille gondolee vue de biais n'est pas un "
                  "rectangle, et le meilleur")
            print("  rectangle qui l'englobe garde du fond. Il faudrait un "
                  "quadrilatere libre,")
            print("  voire la mise a plat par courbes que `curved_flatten` "
                  "sait deja faire.")
        else:
            print(f"  Le seuil de {SEUIL_EXPLOITABLE:.2f} est atteignable. "
                  "L'ecart au temoin mesure\n  donc ce que la detection "
                  "perd reellement.")

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
