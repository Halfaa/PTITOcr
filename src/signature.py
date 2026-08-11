"""
Extraction de la zone de signature d'une facture.

Le mot **zone** est délibéré. On découpe une région, on ne prétend pas
détecter la signature — et c'est le résultat d'une mesure, pas d'un renoncement.

--------------------------------------------------------------------------
Pourquoi pas un détecteur

La signature n'a rien du QR code. Le QR s'auto-vérifie : il décode ou il ne
décode pas, et le code correcteur du standard rend un faux positif quasi
impossible. La signature, elle, n'offre aucune vérification interne.

Deux détecteurs ont été écrits et mesurés contre la vérité terrain exacte
(la boîte de l'image intégrée dans le PDF source) :

  1. composantes d'encre dans le quart bas-droit, filtrées sur le taux de
     remplissage -> 3 trouvées sur 5, et sur une page c'est le bloc de notes
     légales qui est désigné ;
  2. recherche dans la bande verticale exacte (x entre 0,78 et 1,00, connue
     du gabarit), filtrée sur la hauteur -> **IoU moyen 0,22, deux pages
     correctes sur huit**.

Et une troisième piste, plus simple, écartée par sa contre-épreuve : mesurer
le taux d'encre dans la zone du pied de page. Sur les pages porteuses d'une
signature il vaut 0,0003 à 0,135 ; sur les pages qui n'en portent pas,
0,0017 à 0,032. **Les deux plages se recouvrent entièrement.** La raison est
évidente après coup : sur une page de continuation, la colonne « Thành tiền »
occupe exactement cette région. Le taux d'encre ne sépare rien.

Le second échec est le plus instructif, pour deux raisons.

**La position verticale n'est pas prévisible.** x est fixe à 0,827 sur les
huit pages, mais y va de 0,060 à 0,615 : le bloc de pied de page flotte selon
la longueur du tableau. Un a priori de mise en page ne tient donc que sur une
dimension.

**Et la vérité terrain elle-même est ambiguë.** La boîte du PDF est le cadre
de l'image, marges transparentes comprises ; l'encre occupe une région plus
petite et plus basse. Une détection correcte de l'encre marque donc un IoU
médiocre contre ce cadre. Mesurer ce détecteur revenait à mesurer un
désaccord de définition, pas une performance.

--------------------------------------------------------------------------
Ce que le livrable demande vraiment

La signature n'a pas besoin d'être *décodée*, seulement d'être **préservée et
montrée**, pour qu'un humain la vérifie. C'est une exigence de conservation,
pas de reconnaissance.

D'où le choix : on découpe la région du pied de page où le gabarit la place,
on l'exporte à côté du JSON, et on dit que c'est une zone. Un relecteur voit
la signature ; personne ne croit qu'un algorithme l'a authentifiée.

**Ce qui reste hors périmètre.** Comparer une signature à une référence est
un domaine de recherche à part entière (signature verification), demande une
base de signatures connues, et n'est pas dans le sujet du stage. Sur un
document médical, c'est aussi une question à poser avant de coder : une
signature est une **donnée personnelle**, donc l'extraire et l'archiver
relève de la Phase 4 anonymisation.
"""

# Le gabarit place le bloc « Nhân viên bán hàng / signature / DS Vô Danh »
# dans la moitié droite. x est stable au millième près sur les huit pages
# mesurées (0,827 à 0,829) ; y ne l'est pas du tout (0,060 à 0,615), d'où une
# zone verticale large plutôt qu'une position.
ZONE_X = (0.74, 1.00)
ZONE_Y = (0.30, 1.00)

_ENCRE_MINI = 0.002   # en deçà, la zone est vide : pas de signature


def zone_signature(image, x=ZONE_X, y=ZONE_Y) -> dict:
    """Découpe la zone de pied de page et dit si elle contient de l'encre.

    Rend toujours un dictionnaire :

        {"zone": [x0, y0, w, h],        en fractions de l'image
         "encre": float,                part de pixels sombres, diagnostic
         "vide": bool,                  la zone est-elle blanche
         "apercu": ndarray|None}        le découpage, pour export

    **`vide` ne dit pas « pas de signature ».** Sur une page de continuation,
    la colonne des totaux occupe la même région : mesuré, les plages d'encre
    des pages avec et sans signature se recouvrent entièrement. Ce champ ne
    sert qu'à éviter d'écrire un PNG blanc.

    C'est l'appelant qui sait si la page peut porter une signature — le
    gabarit ne la met que sur la **dernière page d'une facture**, information
    que le recollage multi-pages fournit déjà. La localisation vient donc de
    la structure du document, pas d'un détecteur.
    """
    import cv2
    import numpy as np

    rien = {"zone": None, "encre": 0.0, "vide": True, "apercu": None}
    if image is None or image.size == 0:
        return rien

    h, w = image.shape[:2]
    x0, x1 = int(x[0] * w), int(x[1] * w)
    y0, y1 = int(y[0] * h), int(y[1] * h)
    if x1 <= x0 or y1 <= y0:
        return rien

    decoupe = image[y0:y1, x0:x1]
    gris = cv2.cvtColor(decoupe, cv2.COLOR_BGR2GRAY)
    # Seuil relatif au fond local : l'éclairage de nos rendus est inégal, et
    # un seuil absolu déclarerait « pleine d'encre » toute page sombre.
    fond = cv2.GaussianBlur(gris, (0, 0), 25)
    encre = float((gris.astype(int) < fond.astype(int) - 25).mean())

    return {
        "zone": [round(x[0], 3), round(y[0], 3),
                 round(x[1] - x[0], 3), round(y[1] - y[0], 3)],
        "encre": round(encre, 4),
        "vide": encre <= _ENCRE_MINI,
        "apercu": decoupe,
    }


def exporter(image, chemin, **kwargs) -> dict:
    """Écrit la zone en PNG et rend le descripteur, sans l'aperçu.

    L'aperçu (un tableau NumPy) est retiré du retour : ce descripteur part
    dans du JSON, et y glisser une image ferait échouer la sérialisation au
    pire moment — à l'écriture du livrable.
    """
    import cv2
    from pathlib import Path

    resultat = zone_signature(image, **kwargs)
    apercu = resultat.pop("apercu")
    if apercu is not None and not resultat["vide"]:
        Path(chemin).parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(chemin), apercu)
        resultat["fichier"] = Path(chemin).name
    else:
        resultat["fichier"] = None
    return resultat
