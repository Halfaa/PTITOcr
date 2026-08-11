"""
Lecture du QR code d'une facture.

Le QR est le seul élément du document dont la lecture se vérifie de façon
**absolue** : il décode ou il ne décode pas. Partout ailleurs on mesure des
degrés — un TEDS de 0,97, un champ « à peu près juste ». Ici, le code de
correction d'erreur du standard QR rend un faux positif quasi impossible.

Ça lui donne deux usages, et le second est le plus intéressant.

**Une donnée** : l'URL de vérification de la facture, à mettre dans le JSON.

**Un capteur de qualité de capture.** Un QR qui décode prouve que la
résolution et la netteté sont suffisantes *à cet endroit de la page*. S'il ne
décode pas alors qu'on sait qu'il y en a un, c'est le signal qu'il faut
redemander la photo — pendant que l'utilisateur tient encore le document,
c'est-à-dire au seul moment où la correction est gratuite.

--------------------------------------------------------------------------
Le point qui décide de tout : la RÉSOLUTION, et quand on lit.

Un décodeur a besoin d'environ **3 pixels par module** ; en dessous de 2,
aucune sur-résolution ne peut inventer l'information, elle n'est plus dans le
signal. Pour « https://example.com/ » — un QR version 2, 25x25 modules :

    QR de  40 px  ->  1,6 px/module   impossible
    QR de  67 px  ->  2,7 px/module   à la limite
    QR de 133 px  ->  5,3 px/module   confortable
    QR de 285 px  -> 11,4 px/module   photo de téléphone typique

Mesuré sur nos rendus : à 900 px de large, le QR fait 67 px. Rendu
directement depuis le PDF il décode ; passé par la déformation 3D de
Blender, il ne décode plus. Il n'y avait aucune marge, et le gondolement l'a
mangée.

D'où la règle appliquée par `api.py` : **on décode AVANT de réduire l'image
à TAILLE_MAX_OCR**. Réduire une photo de 4000 px à 1600 divise la taille du
QR par 2,5 — c'est jeter gratuitement la marge qui fait la différence.
"""

_TAILLE_MIN_UTILE = 60   # en deçà, ce n'est plus la peine d'essayer


def lire_qr(image) -> dict:
    """Cherche et décode un QR dans une image OpenCV (BGR).

    Rend toujours un dictionnaire, jamais None : l'absence de QR est une
    information, pas une erreur.

        {"trouve": bool, "decode": str|None, "boite": [x,y,w,h]|None,
         "px_par_module": float|None, "diagnostic": str}

    `diagnostic` est destiné à l'utilisateur : c'est lui qui dira « rapproche
    l'appareil » plutôt que « échec ».
    """
    import cv2
    import numpy as np

    vide = {"trouve": False, "decode": None, "boite": None,
            "px_par_module": None, "diagnostic": "aucun QR code détecté"}
    if image is None or min(image.shape[:2]) < _TAILLE_MIN_UTILE:
        return vide

    try:
        texte, points, _ = cv2.QRCodeDetector().detectAndDecode(image)
    except cv2.error:
        return vide

    if points is None or len(points) == 0:
        return vide

    pts = np.asarray(points, dtype=float).reshape(-1, 2)
    x, y = float(pts[:, 0].min()), float(pts[:, 1].min())
    w = float(pts[:, 0].max()) - x
    h = float(pts[:, 1].max()) - y
    cote = max(w, h)

    # 25 modules = QR version 2, ce que produit notre gabarit. Sur un autre
    # format le chiffre bougerait, mais l'ordre de grandeur suffit a dire
    # « trop petit » ou « confortable », qui est tout ce qu'on veut ici.
    par_module = cote / 25.0

    if texte:
        diagnostic = "QR décodé"
    elif par_module < 2:
        diagnostic = ("QR repéré mais trop petit pour être lu "
                      f"({cote:.0f} px, ~{par_module:.1f} px/module) — "
                      "rapprocher l'appareil ou photographier en plus haute "
                      "résolution")
    else:
        diagnostic = (f"QR repéré ({cote:.0f} px) mais illisible — "
                      "probablement flou, reflet ou page trop gondolée à cet "
                      "endroit")

    return {
        "trouve": True,
        "decode": texte or None,
        "boite": [int(x), int(y), int(w), int(h)],
        "px_par_module": round(par_module, 1),
        "diagnostic": diagnostic,
    }


def qualite_de_capture(lectures: list) -> dict:
    """Synthèse sur l'ensemble des pages d'un document.

    Un seul QR lisible suffit à établir que la capture était bonne : le QR
    ne figure que sur la dernière page de chaque facture, et son absence
    ailleurs n'est pas un défaut. On distingue donc « aucun QR sur le
    document » de « un QR présent mais illisible » — la première situation
    est normale, la seconde est un signal.
    """
    presents = [l for l in lectures if l.get("trouve")]
    decodes = [l for l in presents if l.get("decode")]

    if not presents:
        etat, message = "sans_objet", "aucun QR code sur ce document"
    elif decodes:
        etat, message = "bonne", f"{len(decodes)}/{len(presents)} QR décodé(s)"
    else:
        etat = "insuffisante"
        message = presents[0]["diagnostic"]

    return {
        "etat": etat,
        "message": message,
        "qr_presents": len(presents),
        "qr_decodes": len(decodes),
        "urls": [l["decode"] for l in decodes],
    }
