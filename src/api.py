"""
API d'extraction de factures -- le dos de la PWA.

Photo en entree, JSON en sortie, et chaque etape intermediaire exposee pour
que l'interface puisse montrer ce que la chaine a fait.

Pourquoi un serveur plutot que du calcul sur le telephone : les modeles font
0,9 a 1 milliard de parametres et pesent plusieurs gigaoctets. Le telephone
prend la photo, le serveur lit. C'est aussi ce qui permet de changer de
modele sans redeployer l'application.

    pip install "fastapi[standard]"
    python src/api.py                 # http://localhost:8000

Sur telephone, remplace localhost par l'IP du poste sur le reseau local :
l'API ecoute sur 0.0.0.0.

Deux modes :

    live     le modele tourne vraiment. 30 s a 3 min selon le modele et le
             nombre de pages.
    replay   rejoue un run deja calcule (results/<run>). Instantane, pour
             montrer la chaine sans faire attendre une salle de reunion.

Le traitement est lance en tache de fond et l'interface interroge l'etat :
une requete HTTP qui dure trois minutes se fait couper par a peu pres tous
les intermediaires reseau.
"""

import base64
import re
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from adaptive import HEADER_FIELDS, choose  # noqa: E402
from invoice_parse import parse_table  # noqa: E402
from invoice_validate import check_invoice  # noqa: E402
from table_merge import extract_tables, is_continuation, merge_table_sequence  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent
WEBAPP = RACINE / "webapp"
RESULTATS = RACINE / "results"


# --------------------------------------------------------------------------
# Etat des travaux
# --------------------------------------------------------------------------

@dataclass
class Etape:
    """Une etape de la chaine, telle que l'interface l'affiche."""

    nom: str
    titre: str
    etat: str = "en attente"          # en attente | en cours | fait | echec
    detail: str = ""
    donnees: dict = field(default_factory=dict)


@dataclass
class Travail:
    id: str
    mode: str
    modele: str
    deux_passes: str = "auto"         # auto | toujours | jamais
    cree: float = field(default_factory=time.time)
    etat: str = "en cours"            # en cours | fini | echec
    erreur: Optional[str] = None
    etapes: list = field(default_factory=list)
    resultat: Optional[dict] = None
    # Lecture des QR codes, faite a la reception sur l'image pleine
    # resolution. Conservee ici pour que l'assemblage final la retrouve : a
    # ce moment-la, les images ont deja ete reduites et recadrees.
    qr: Optional[dict] = None

    def etape(self, nom):
        """L'etape demandee, ou None si elle ne s'applique pas a ce travail.

        Toutes les etapes ne concernent pas tous les travaux : le recollage
        multi-pages n'a aucun sens sur une page unique. Renvoyer None plutot
        que de lever permet a la chaine de sauter proprement ce qui ne la
        concerne pas.
        """
        return next((e for e in self.etapes if e.nom == nom), None)

    def json(self):
        return {
            "id": self.id,
            "etat": self.etat,
            "erreur": self.erreur,
            "mode": self.mode,
            "modele": self.modele,
            "duree": round(time.time() - self.cree, 1),
            "etapes": [
                {"nom": e.nom, "titre": e.titre, "etat": e.etat,
                 "detail": e.detail, "donnees": e.donnees}
                for e in self.etapes
            ],
            "resultat": self.resultat,
        }


ETAPES = [
    ("reception", "Réception des pages"),
    ("pretraitement", "Localisation de la feuille et redressement"),
    ("ocr", "Lecture par le modèle"),
    ("fusion", "Recollage des tableaux multi-pages"),
    ("validation", "Vérification arithmétique"),
    ("choix", "Choix entre lecture brute et prétraitée"),
]

# Etapes qui n'ont de sens qu'a partir de deux pages.
ETAPES_MULTIPAGES = {"fusion"}


def construire_etapes(n_pages: int) -> list:
    """La liste d'etapes pertinente pour ce nombre de pages.

    Afficher « Recollage des tableaux multi-pages » sur une photo unique
    annonce un travail qui n'aura pas lieu : l'utilisateur attend une etape
    qui ne peut rien produire. On la retire plutot que de la montrer cochee
    avec la mention « rien a recoller ».
    """
    return [Etape(nom, titre) for nom, titre in ETAPES
            if n_pages > 1 or nom not in ETAPES_MULTIPAGES]

TRAVAUX: dict[str, Travail] = {}
_VERROU = threading.Lock()

# Le modele est charge une fois et garde en memoire. Le rechargement coute
# 30 a 90 s : le faire par requete rendrait l'application inutilisable.
_MODELE = {"nom": None, "objet": None}

# Cote long maximal envoye au modele.
#
# Une photo de telephone fait 3000 a 4000 px de large. Le cout d'un VLM
# croit plus vite que lineairement avec le nombre de patches d'image : lire
# la photo pleine resolution coute plusieurs fois ce que coute la meme page
# a 1600 px, pour un texte deja parfaitement lisible a cette taille. Nos
# mesures de reference sont faites sur des pages de 900x1200.
TAILLE_MAX_OCR = 1600

# En dessous de cette confiance, la premiere lecture est jugee douteuse et on
# paie une seconde lecture sur l'image pretraitee.
#
# Mesure sur les 12 factures deformees : la lecture brute marque 1,00 sur 5
# d'entre elles, et c'est exactement la ou le pretraitement n'apportait rien.
# Ne payer la seconde passe que lorsque la premiere doute divise le cout par
# deux environ, sans rien perdre la ou ca compte.
SEUIL_DEUXIEME_PASSE = 0.95
#
# Depuis le correctif de `adaptive.confidence` (un signal illisible ne
# rapporte plus le point qu'il rapportait), une lecture dont la colonne STT
# n'a pas ete reconnue perd 0,15 et passe donc sous ce seuil. C'est voulu :
# elle DOIT declencher la seconde lecture, puisqu'on ne peut plus verifier sa
# numerotation. Le prix est quelques secondes de calcul de plus sur ces
# pages-la ; le gain est qu'on ne livre plus comme sure une extraction dont
# un tiers des controles n'a pas pu tourner.


# --------------------------------------------------------------------------
# Utilitaires image
# --------------------------------------------------------------------------

def _en_data_uri(image_bgr, qualite=80, largeur_max=900):
    """Encode une image OpenCV pour l'affichage direct dans la page."""
    import cv2

    h, w = image_bgr.shape[:2]
    if w > largeur_max:
        facteur = largeur_max / w
        image_bgr = cv2.resize(image_bgr, None, fx=facteur, fy=facteur,
                               interpolation=cv2.INTER_AREA)
    ok, buffer = cv2.imencode(".jpg", image_bgr,
                              [int(cv2.IMWRITE_JPEG_QUALITY), qualite])
    if not ok:
        return None
    return "data:image/jpeg;base64," + base64.b64encode(buffer).decode("ascii")


def _quad_relatif(quad, largeur, hauteur):
    """Coordonnees du quadrilatere en fraction de l'image.

    L'interface redimensionne les images pour l'affichage ; des coordonnees
    en pixels seraient fausses des le premier redimensionnement.
    """
    if quad is None:
        return None
    return [[round(x / largeur, 4), round(y / hauteur, 4)] for x, y in quad]


# --------------------------------------------------------------------------
# La chaine
# --------------------------------------------------------------------------

def _charger_modele(nom):
    """Charge le modele demande, une fois pour toutes.

    Les modeles Paddle et HunyuanOCR ne cohabitent pas dans le meme
    environnement -- transformers 4.x contre 5.13. On lance donc l'API
    depuis le venv correspondant au modele voulu, et l'import n'a lieu qu'ici
    pour que l'autre famille n'ait pas besoin d'etre installee.
    """
    if _MODELE["nom"] == nom:
        return _MODELE["objet"]

    if nom == "paddleocr-vl":
        from paddleocr import PaddleOCRVL
        objet = PaddleOCRVL(pipeline_version="v1")
    elif nom == "ppstructure":
        from paddleocr import PPStructureV3
        objet = PPStructureV3(enable_mkldnn=False)
    elif nom == "hunyuan":
        objet = _charger_hunyuan()
    else:
        raise ValueError(f"Modele inconnu pour l'API : {nom}")

    _MODELE.update(nom=nom, objet=objet)
    return objet


def _charger_hunyuan():
    """HunyuanOCR-1.5 sur GPU.

    backend="pil" est OBLIGATOIRE : avec le backend torchvision, le
    reechantillonnage LANCZOS est silencieusement remplace par BICUBIC et le
    modele produit du charabia -- constate en pratique, sans la moindre
    erreur levee.
    """
    import torch
    from transformers import AutoProcessor

    identifiant = "tencent/HunyuanOCR"
    processeur = AutoProcessor.from_pretrained(identifiant, backend="pil",
                                               trust_remote_code=True)
    try:
        from transformers import HunYuanVLForConditionalGeneration as Classe
    except ImportError:
        from transformers import AutoModelForCausalLM as Classe

    peripherique = "cuda" if torch.cuda.is_available() else "cpu"
    modele = Classe.from_pretrained(
        identifiant, attn_implementation="eager",
        dtype=torch.bfloat16 if peripherique == "cuda" else torch.float32,
        device_map=peripherique, trust_remote_code=True)
    print(f"  HunyuanOCR chargé sur {peripherique}")
    return ("hunyuan", processeur, modele)


def _lire_hunyuan(paquet, chemin):
    import torch
    from PIL import Image

    from hunyuan_prompts import ALL as PROMPTS

    _, processeur, modele = paquet
    image = Image.open(chemin).convert("RGB")
    messages = [
        {"role": "system", "content": ""},
        {"role": "user", "content": [
            {"type": "image", "image": str(chemin)},
            {"type": "text", "text": PROMPTS["document"]},
        ]},
    ]
    texte = processeur.apply_chat_template(messages, tokenize=False,
                                           add_generation_prompt=True)
    entrees = processeur(text=[texte], images=image, padding=True,
                         return_tensors="pt")
    entrees = entrees.to(next(modele.parameters()).device)
    with torch.no_grad():
        sortie = modele.generate(**entrees, max_new_tokens=4096, do_sample=False,
                                 repetition_penalty=1.08)
    coupe = [s[len(e):] for e, s in zip(entrees["input_ids"], sortie)]
    return processeur.batch_decode(coupe, skip_special_tokens=True,
                                   clean_up_tokenization_spaces=False)[0]


def _reduire(image):
    """Ramene l'image sous TAILLE_MAX_OCR sans deformer."""
    import cv2

    cote = max(image.shape[:2])
    if cote <= TAILLE_MAX_OCR:
        return image
    facteur = TAILLE_MAX_OCR / cote
    return cv2.resize(image, None, fx=facteur, fy=facteur,
                      interpolation=cv2.INTER_AREA)


def _lire(modele, image):
    """Une image -> le markdown produit par le modele."""
    import tempfile

    import cv2

    with tempfile.TemporaryDirectory() as tmp:
        chemin = Path(tmp) / "page.png"
        cv2.imwrite(str(chemin), _reduire(image))

        # HunyuanOCR rend directement du texte ; les pipelines Paddle
        # ecrivent des fichiers qu'il faut relire.
        if isinstance(modele, tuple) and modele[0] == "hunyuan":
            return _lire_hunyuan(modele, chemin)

        for res in modele.predict(str(chemin)):
            res.save_to_markdown(save_path=tmp)
        mds = [m for m in Path(tmp).glob("*.md")]
        return mds[0].read_text(encoding="utf-8") if mds else ""


def _traiter(travail: Travail, pages_brutes: list):
    """Deroule la chaine complete. Tourne dans un thread separe."""
    import cv2
    import numpy as np

    from preprocess import preprocess

    # --- 1. Reception ------------------------------------------------------
    etape = travail.etape("reception")
    etape.etat = "en cours"
    images = []
    for octets in pages_brutes:
        tableau = np.frombuffer(octets, np.uint8)
        image = cv2.imdecode(tableau, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("Image illisible (format non reconnu)")
        images.append(image)
    # Le QR se lit ICI, sur l'image telle qu'elle est arrivee -- avant le
    # pretraitement qui recadre, et surtout avant `_reduire` qui ramene tout
    # a TAILLE_MAX_OCR pour le modele.
    #
    # Ramener une photo de 4000 px a 1600 divise la taille du QR par 2,5. Or
    # un decodeur a besoin d'environ 3 pixels par module : sur nos rendus a
    # 900 px le QR fait 67 px, soit 2,7 px/module -- il decode depuis le PDF
    # et ne decode plus une fois gondole par Blender. Il n'y avait aucune
    # marge. Reduire avant de lire reviendrait a jeter celle qui reste.
    from qrcode_lecture import lire_qr, qualite_de_capture

    lectures_qr = [lire_qr(i) for i in images]
    qualite = qualite_de_capture(lectures_qr)

    etape.etat = "fait"
    etape.detail = f"{len(images)} page(s)"
    if qualite["etat"] != "sans_objet":
        etape.detail += f" — {qualite['message']}"
    etape.donnees = {
        "pages": [{"apercu": _en_data_uri(i),
                   "qr": q if q["trouve"] else None}
                  for i, q in zip(images, lectures_qr)],
        "qualite_capture": qualite,
    }
    travail.qr = {"lectures": lectures_qr, "qualite": qualite}

    # --- 2. Pretraitement --------------------------------------------------
    etape = travail.etape("pretraitement")
    etape.etat = "en cours"
    pretraitees, infos = [], []
    for image in images:
        resultat, info = preprocess(image)
        pretraitees.append(resultat)
        infos.append(info)

    h_w = [(i.shape[0], i.shape[1]) for i in images]
    etape.donnees = {"pages": [
        {"quad": _quad_relatif(info.get("quad"), w, h),
         "score": info.get("score"),
         "methode": info.get("method", "aucune"),
         "repli": info.get("fallback"),
         "apercu": _en_data_uri(p)}
        for info, (h, w), p in zip(infos, h_w, pretraitees)
    ]}
    trouves = sum(1 for i in infos if i.get("quad_found"))
    etape.etat = "fait"
    etape.detail = f"feuille localisée sur {trouves}/{len(images)} page(s)"

    # --- 3. OCR, une lecture puis peut-etre une seconde --------------------
    # La politique adaptative a besoin de DEUX lectures pour choisir. Mais
    # les payer systematiquement double le temps d'attente, alors que la
    # premiere suffit souvent : sur les 12 factures deformees, la lecture
    # brute marquait deja 1,00 de confiance sur 5 d'entre elles -- et c'est
    # precisement la que le pretraitement n'apportait rien.
    #
    # On lit donc l'image brute, on la NOTE sans verite terrain, et on ne
    # paie la seconde lecture que si ce score doute. C'est la meme idee que
    # la politique adaptative, appliquee cette fois au temps de calcul.
    etape = travail.etape("ocr")
    etape.etat = "en cours"
    modele = _charger_modele(travail.modele)

    textes = {"raw": []}
    for i, image in enumerate(images):
        etape.detail = f"page {i + 1}/{len(images)}, lecture brute"
        textes["raw"].append(_lire(modele, image))

    confiance = _confiance_source(textes["raw"])
    if travail.deux_passes == "toujours" or (
            travail.deux_passes == "auto" and confiance < SEUIL_DEUXIEME_PASSE):
        textes["preprocessed"] = []
        for i, image in enumerate(pretraitees):
            etape.detail = (f"page {i + 1}/{len(images)}, "
                            f"seconde lecture (confiance {confiance:.2f})")
            textes["preprocessed"].append(_lire(modele, image))

    etape.etat = "fait"
    n = sum(len(v) for v in textes.values())
    etape.detail = (f"{n} lecture(s) — confiance de la première {confiance:.2f}"
                    + ("" if "preprocessed" in textes
                       else ", seconde lecture inutile"))

    _assembler(travail, textes)


def _tables_d_une_source(pages):
    """Les tableaux d'une lecture, avec le texte de leur page."""
    tables, contextes = [], []
    for texte in pages:
        for table in extract_tables(texte):
            tables.append(table)
            contextes.append(texte)
    return tables, contextes


def _confiance_source(pages):
    """Note la lecture d'une source, sans verite terrain."""
    from adaptive import confidence

    tables, contextes = _tables_d_une_source(pages)
    if not tables:
        return 0.0
    fusion, _ = merge_table_sequence(tables, contextes)
    return confidence(fusion[0] if fusion else None).score


def _assembler(travail: Travail, textes: dict):
    """Fusion, validation, choix adaptatif -- commun au live et au rejeu."""
    # --- 4. Fusion ---------------------------------------------------------
    # L'etape peut ne pas exister : sur une page unique il n'y a rien a
    # recoller, et merge_table_sequence rend alors le tableau inchange.
    etape = travail.etape("fusion")
    if etape:
        etape.etat = "en cours"

    candidats, decisions = {}, []
    for source, pages in textes.items():
        tables, contextes = _tables_d_une_source(pages)

        if not tables:
            candidats[source] = (None, pages)
            continue

        if source == "raw":
            # On expose le detail des signaux pour la lecture brute
            # seulement : montrer deux fois la meme mecanique n'apprend rien.
            for a in range(len(tables) - 1):
                signaux = is_continuation(tables[a], tables[a + 1],
                                          contextes[a], contextes[a + 1])
                decisions.append({
                    "de": a + 1, "vers": a + 2,
                    "fusionne": bool(signaux["decision"]),
                    "confiance": signaux["confidence"],
                    "signaux": {c: signaux.get(c) for c in (
                        "table_b_has_continuation_marker", "index_continuity",
                        "table_b_starts_mid_numbering", "table_a_ends_with_total",
                        "table_b_restarts_at_1", "same_col_count",
                        "header_similarity", "last_index_a", "first_index_b",
                        "index_offset")},
                })

        fusion, _ = merge_table_sequence(tables, contextes)
        candidats[source] = (fusion[0] if fusion else None, pages)

    if etape:
        etape.etat = "fait"
        etape.donnees = {"decisions": decisions}
        fusionnees = sum(1 for d in decisions if d["fusionne"])
        etape.detail = (f"{fusionnees} fusion(s) sur {len(decisions)} transition(s)"
                        if decisions else "aucune transition exploitable")

    # --- 5. Choix adaptatif ------------------------------------------------
    etape = travail.etape("choix")
    etape.etat = "en cours"
    retenu = choose(candidats)
    etape.etat = "fait"
    etape.detail = f"tableau retenu : lecture {retenu.table_source}"
    etape.donnees = {
        "table_source": retenu.table_source,
        "confiances": {nom: {"score": round(c.score, 3), "detail": str(c)}
                       for nom, c in retenu.confidences.items()},
        "champs_source": retenu.field_sources,
    }

    # --- 6. Validation -----------------------------------------------------
    etape = travail.etape("validation")
    etape.etat = "en cours"

    lignes, controle = [], None
    if retenu.table is not None:
        facture = parse_table(retenu.table)
        controle = check_invoice(facture)
        for article, verif in zip(facture.items, controle["checks"]):
            lignes.append({
                "index": article.index,
                "nom": article.name,
                "unite": article.unit,
                "quantite": article.quantity,
                "prix_unitaire": article.unit_price,
                "total": article.total,
                "statut": verif.status,
                "explication": getattr(verif, "detail", ""),
            })

    if controle:
        etape.etat = "fait"
        douteuses = controle["n_suspect"]
        etape.detail = (f"{controle['n_lines']} ligne(s), "
                        f"{douteuses} à relire, "
                        f"total {'cohérent' if controle['total_ok'] else 'incohérent'}")
        etape.donnees = {
            "n_lignes": controle["n_lines"],
            "n_ok": controle["n_ok"],
            "n_corrigees": controle["n_corrected"],
            "n_douteuses": douteuses,
            "total_ok": controle["total_ok"],
            "total_detail": controle["total_detail"],
            "trous": controle["index_gaps"],
        }
    else:
        etape.etat = "echec"
        etape.detail = "aucun tableau exploitable"

    travail.resultat = {
        "champs": {nom: retenu.fields.get(nom) for nom in HEADER_FIELDS},
        "champs_source": retenu.field_sources,
        "lignes": lignes,
        "total_declare": (parse_table(retenu.table).grand_total
                          if retenu.table is not None else None),
        "extraction": "ok" if lignes else "aucune ligne extraite",
        # Le QR voyage jusqu'ici depuis la reception : c'est la seule donnee
        # du document dont la lecture soit verifiable de facon absolue, et
        # « la capture etait-elle assez bonne » est une information que le
        # consommateur du JSON veut, meme quand l'extraction a reussi.
        "qr": (travail.qr["qualite"] if travail.qr else None),
        "qr_urls": (travail.qr["qualite"]["urls"] if travail.qr else []),
    }
    travail.etat = "fini"


def pages_d_un_run(run: str) -> dict:
    """{numero de page: markdown} pour un run de results/.

    Les dossiers ne suivent pas tous la meme convention : "page_3-mesh_04"
    pour les jeux multi-pages, "invoice_12" pour les lots d'une page. On
    prend donc le PREMIER nombre du nom, quel que soit ce qui l'entoure, et
    on ignore les dossiers ou il n'y en a aucun -- plutot que de supposer un
    format et d'echouer sur un ValueError qui ne dit rien a l'utilisateur.
    """
    dossier = RESULTATS / run / "pages"
    if not dossier.exists():
        return {}

    sortie = {}
    for md in dossier.glob("*/*.md"):
        trouve = re.search(r"\d+", md.parent.name)
        if trouve:
            sortie[int(trouve.group())] = md
    return sortie


def _rejouer(travail: Travail, run_brut: str, run_pretraite: str, pages: list):
    """Rejoue deux runs deja calcules, sans toucher au modele."""
    for nom in ("reception", "pretraitement", "ocr"):
        etape = travail.etape(nom)
        if etape:
            etape.etat = "fait"
            etape.detail = "rejeu d'un run existant"

    textes = {}
    for source, run in (("raw", run_brut), ("preprocessed", run_pretraite)):
        disponibles = pages_d_un_run(run)
        manquantes = [p for p in pages if p not in disponibles]
        if manquantes:
            raise ValueError(
                f"Le run '{run}' n'a pas les pages {manquantes}. "
                f"Il contient {sorted(disponibles)[:12]}"
                f"{' ...' if len(disponibles) > 12 else ''}.")
        textes[source] = [disponibles[p].read_text(encoding="utf-8") for p in pages]

    _assembler(travail, textes)


def _lancer(travail: Travail, cible, *args):
    def executer():
        try:
            cible(travail, *args)
        except Exception as e:  # noqa: BLE001
            import traceback
            travail.etat = "echec"
            travail.erreur = f"{type(e).__name__}: {e}"
            traceback.print_exc()
            for etape in travail.etapes:
                if etape.etat == "en cours":
                    etape.etat = "echec"

    threading.Thread(target=executer, daemon=True).start()


# --------------------------------------------------------------------------
# L'API
# --------------------------------------------------------------------------

def creer_app():
    from fastapi import FastAPI, File, Form, HTTPException, UploadFile
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    app = FastAPI(title="Extraction de factures médicales", version="1.0")

    # Le telephone et le serveur sont sur deux origines differentes des que
    # l'on sort de localhost.
    app.add_middleware(CORSMiddleware, allow_origins=["*"],
                       allow_methods=["*"], allow_headers=["*"])

    @app.post("/api/extract")
    async def extraire(images: list[UploadFile] = File(...),
                       modele: str = Form("paddleocr-vl"),
                       deux_passes: str = Form("auto")):
        contenus = [await f.read() for f in images]
        if not contenus:
            raise HTTPException(400, "Aucune image reçue")

        travail = Travail(id=uuid.uuid4().hex[:12], mode="live", modele=modele,
                          deux_passes=deux_passes)
        travail.etapes = construire_etapes(len(contenus))
        with _VERROU:
            TRAVAUX[travail.id] = travail
        _lancer(travail, _traiter, contenus)
        return {"id": travail.id}

    @app.post("/api/replay")
    async def rejouer(run_brut: str = Form(...), run_pretraite: str = Form(...),
                      pages: str = Form(...)):
        numeros = [int(p) for p in pages.replace(" ", "").split(",") if p]
        travail = Travail(id=uuid.uuid4().hex[:12], mode="replay", modele="—")
        travail.etapes = construire_etapes(len(numeros))
        with _VERROU:
            TRAVAUX[travail.id] = travail
        _lancer(travail, _rejouer, run_brut, run_pretraite, numeros)
        return {"id": travail.id}

    @app.get("/api/jobs/{job_id}")
    async def etat(job_id: str):
        travail = TRAVAUX.get(job_id)
        if travail is None:
            raise HTTPException(404, "Travail inconnu")
        return travail.json()

    @app.get("/api/runs")
    async def runs():
        """Les runs disponibles pour le rejeu, avec leurs pages.

        On renvoie les numeros de page pour que l'interface propose des
        valeurs valides : les deviner menait a des erreurs incomprehensibles.
        """
        if not RESULTATS.exists():
            return {"runs": []}
        sortie = []
        for d in sorted(RESULTATS.iterdir()):
            if not (d.is_dir() and (d / "pages").exists()):
                continue
            numeros = sorted(pages_d_un_run(d.name))
            if numeros:
                sortie.append({"nom": d.name, "pages": numeros})
        return {"runs": sortie}

    @app.get("/api/health")
    async def sante():
        return {"ok": True, "modele_charge": _MODELE["nom"]}

    if WEBAPP.exists():
        app.mount("/static", StaticFiles(directory=WEBAPP), name="static")

        @app.get("/")
        async def accueil():
            return FileResponse(WEBAPP / "index.html")

        @app.get("/sw.js")
        async def service_worker():
            # Un service worker ne controle que les pages de son propre
            # dossier ou en dessous : servi depuis /static/, il ne verrait
            # pas la racine. Il doit donc etre expose a la racine.
            return FileResponse(WEBAPP / "sw.js", media_type="application/javascript")

        @app.get("/manifest.json")
        async def manifeste():
            return FileResponse(WEBAPP / "manifest.json")

    return app


app = creer_app()


if __name__ == "__main__":
    import uvicorn

    print("Interface : http://localhost:8000")
    print("Depuis un telephone du meme reseau : http://<ip-du-poste>:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)
