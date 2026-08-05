"""
Démonstration du recollage multi-pages.

On glisse les pages d'une facture, on voit les tableaux que le modèle a lus
page par page, la décision prise à chaque transition avec les signaux qui
l'ont motivée, puis le tableau reconstitué — chaque ligne teintée selon la
page dont elle vient.

C'est la contribution principale du stage, et c'est la seule partie de la
chaîne qu'une capture d'écran ne suffit pas à expliquer : il faut voir les
morceaux d'abord, puis le résultat.

    python demo/demo_fusion.py

Puis http://localhost:8010.

Deux modes.

**Rejeu** (défaut) : les images des jeux de test sont reconnues à leur nom
et l'OCR déjà calculé ressort instantanément. La fusion, elle, est calculée
en direct par `src/table_merge.py` — c'est le vrai algorithme qui tourne
devant le public, pas un résultat enregistré.

**Direct** : le modèle lit vraiment, y compris une photo prise sur le
moment. Compter ~80 s par page. À garder pour répondre à une question, pas
pour dérouler la démonstration.
"""

import io
import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "src"))

from table_merge import (extract_tables, is_continuation,  # noqa: E402
                         merge_tables)

try:
    from fastapi import FastAPI, File, Form, UploadFile
    from fastapi.responses import FileResponse, JSONResponse
except ImportError:
    raise SystemExit("Cette démo a besoin de FastAPI :\n"
                     '    pip install fastapi "uvicorn[standard]" python-multipart')

ICI = Path(__file__).resolve().parent
RESULTATS = RACINE / "results"


# --------------------------------------------------------------------------
# Rejeu : retrouver l'OCR déjà calculé
# --------------------------------------------------------------------------

def numero_de_page(nom: str):
    """`page_12-concave_mesh_1010001.png` -> 12."""
    m = re.search(r"\d+", nom)
    return int(m.group()) if m else None


def index_des_runs() -> dict:
    """{nom du run: {stem de l'image: markdown}}.

    L'index est construit à chaque appel plutôt que mis en cache : un run
    rapatrié de Kaggle pendant que la démo tourne apparaît alors sans
    relancer le serveur. Le coût est un parcours de répertoire, négligeable
    devant tout le reste.
    """
    index = {}
    if not RESULTATS.is_dir():
        return index
    for run in sorted(RESULTATS.iterdir()):
        pages = run / "pages"
        if not pages.is_dir():
            continue
        contenu = {}
        for dossier in pages.iterdir():
            if not dossier.is_dir():
                continue
            mds = sorted(dossier.glob("*.md"))
            if mds:
                contenu[dossier.name] = mds[0]
        if contenu:
            index[run.name] = contenu
    return index


def choisir_run(index: dict, stems: list, demande: str | None):
    """Le run qui couvre le plus d'images déposées.

    Sans ça, un utilisateur qui dépose des pages du jeu diversifié pendant
    qu'un run multi-pages est sélectionné obtiendrait « aucune lecture
    trouvée » sans comprendre pourquoi.
    """
    if demande and demande in index:
        return demande
    classement = sorted(index, key=lambda r: -sum(s in index[r] for s in stems))
    return classement[0] if classement else None


# --------------------------------------------------------------------------
# La chaîne de fusion, avec traçabilité
# --------------------------------------------------------------------------

def en_dictionnaire(table, provenance=None) -> dict:
    """Découpe le tableau en en-tête + corps, prêt à afficher.

    L'en-tête n'est pas toujours la première ligne : `_find_header_index` le
    cherche dans les premières, parce que l'OCR fait souvent précéder le
    tableau d'une ligne de bruit ou d'une bannière de continuation. Faire ce
    découpage ici plutôt que côté navigateur évite d'y refaire un calcul
    d'indices qui se désynchroniserait de la provenance.
    """
    lignes = [[str(c) for c in ligne] for ligne in table.rows]
    entete = [str(c) for c in table.header]
    depart = len(lignes) - len(table.data_rows)
    prov = provenance or []
    corps = [{"cellules": ligne, "page": prov[depart + i] if depart + i < len(prov) else None}
             for i, ligne in enumerate(lignes[depart:])]
    return {"entete": entete, "corps": corps,
            "n_colonnes": table.n_cols, "n_lignes_donnees": len(corps)}


# Les deux derniers sont les vetos : ils disent que le document affirme que
# le tableau précédent est terminé. Les afficher au même titre que les
# signaux positifs est délibéré — c'est ce qui rend visible qu'une non-fusion
# est une décision motivée, et non l'absence d'indice.
SIGNAUX_MONTRES = [
    ("table_b_has_continuation_marker", "marqueur « Tiếp trang trước » sur B"),
    ("table_a_has_next_page_marker", "marqueur « voir page suivante » sur A"),
    ("index_continuity", "numérotation qui s'enchaîne"),
    ("same_col_count", "même nombre de colonnes"),
    ("table_b_restarts_at_1", "veto — B redémarre à 1"),
    ("table_a_ends_with_total", "veto — A se termine par un total"),
]


def fusionner(tables: list, textes: list, numeros: list) -> dict:
    """Déroule le recollage en gardant la trace de chaque décision.

    On reproduit ici la boucle de `merge_table_sequence` au lieu de
    l'appeler, pour une seule raison : il faut savoir de quelle page vient
    chaque ligne du tableau final. Les fonctions de décision et de fusion
    appelées sont exactement celles du module — rien n'est réimplémenté.
    """
    groupes = [{
        "table": tables[0],
        "pages": [numeros[0]],
        "provenance": [numeros[0]] * len(tables[0].rows),
    }]
    texte_courant = textes[0]
    decisions = []

    for i, (table, texte, numero) in enumerate(
            zip(tables[1:], textes[1:], numeros[1:])):
        groupe = groupes[-1]
        signaux = is_continuation(groupe["table"], table, texte_courant, texte)

        if signaux["decision"]:
            fusionnee = merge_tables(groupe["table"], table, signaux)
            # Les lignes de B ajoutées sont exactement ses lignes de données ;
            # ce qui reste devant vient donc du groupe, éventuellement amputé
            # de son marqueur « voir page suivante ».
            n_ajoutees = len(table.data_rows)
            n_gardees = len(fusionnee.rows) - n_ajoutees
            groupe["provenance"] = (groupe["provenance"][:n_gardees]
                                    + [numero] * n_ajoutees)
            groupe["table"] = fusionnee
            groupe["pages"].append(numero)
        else:
            groupes.append({
                "table": table,
                "pages": [numero],
                "provenance": [numero] * len(table.rows),
            })

        decisions.append({
            "de": numeros[i],          # la page qui précède, dans l'ordre déposé
            "vers": numero,
            "fusion": bool(signaux["decision"]),
            "certitude": signaux.get("confidence"),
            "similarite_entete": round(float(signaux["header_similarity"]), 2),
            "dernier_index_a": signaux["last_index_a"],
            "premier_index_b": signaux["first_index_b"],
            "signaux": [{"nom": libelle, "actif": bool(signaux.get(cle))}
                        for cle, libelle in SIGNAUX_MONTRES if cle in signaux],
        })
        texte_courant = texte

    return {
        "groupes": [{
            "pages": g["pages"],
            "table": en_dictionnaire(g["table"], g["provenance"]),
        } for g in groupes],
        "decisions": decisions,
    }


# --------------------------------------------------------------------------
# Lecture en direct
# --------------------------------------------------------------------------

_DIRECT = {}


def lire_en_direct(nom_modele: str, octets: bytes) -> str:
    """Fait tourner le modèle sur une image envoyée.

    L'import de `api` est retardé jusqu'ici : il tire torch et le modèle, et
    le mode rejeu doit rester utilisable sur un poste où rien de tout ça
    n'est installé.
    """
    import tempfile

    import cv2
    import numpy as np

    if "api" not in _DIRECT:
        import api
        _DIRECT["api"] = api

    api = _DIRECT["api"]
    image = cv2.imdecode(np.frombuffer(octets, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("image illisible")
    return api._lire(api._charger_modele(nom_modele), image)


# --------------------------------------------------------------------------

app = FastAPI(title="Démonstration — recollage multi-pages")


@app.get("/")
def page():
    return FileResponse(ICI / "fusion.html")


@app.get("/api/runs")
def runs():
    index = index_des_runs()
    return {"runs": [{"nom": r, "pages": len(p)} for r, p in index.items()]}


@app.post("/api/fusion")
async def fusion(fichiers: list[UploadFile] = File(...),
                 mode: str = Form("rejeu"),
                 run: str = Form(""),
                 modele: str = Form("hunyuan")):
    depots = [(f.filename, await f.read()) for f in fichiers]
    # Ordre « naturel » : page_2 avant page_10. L'ordre alphabétique
    # placerait la page 10 juste après la page 1, et le recollage verrait
    # une numérotation incohérente là où il n'y en a pas.
    depots.sort(key=lambda d: [int(t) if t.isdigit() else t.lower()
                               for t in re.split(r"(\d+)", d[0])])

    index = index_des_runs()
    stems = [Path(nom).stem for nom, _ in depots]
    run_retenu = choisir_run(index, stems, run or None) if mode == "rejeu" else None

    pages, absentes = [], []
    for (nom, octets), stem in zip(depots, stems):
        if mode == "rejeu":
            chemin = index.get(run_retenu, {}).get(stem)
            if chemin is None:
                absentes.append(nom)
                continue
            texte = chemin.read_text(encoding="utf-8")
        else:
            try:
                texte = lire_en_direct(modele, octets)
            except Exception as e:  # noqa: BLE001
                return JSONResponse(
                    {"erreur": f"Lecture impossible ({nom}) : {e}"}, 500)

        tables = extract_tables(texte)
        pages.append({
            "nom": nom,
            "numero": numero_de_page(nom),
            "texte": texte,
            "table": max(tables, key=lambda t: len(t.rows)) if tables else None,
        })

    utilisables = [p for p in pages if p["table"] is not None]
    if not utilisables:
        return JSONResponse({
            "erreur": "Aucun tableau à recoller.",
            "absentes": absentes,
            "run": run_retenu,
        }, 400)

    resultat = fusionner([p["table"] for p in utilisables],
                         [p["texte"] for p in utilisables],
                         [p["numero"] for p in utilisables])

    return {
        "mode": mode,
        "run": run_retenu,
        "absentes": absentes,
        "sans_table": [p["nom"] for p in pages if p["table"] is None],
        "pages": [{"nom": p["nom"], "numero": p["numero"],
                   "table": en_dictionnaire(p["table"])} for p in utilisables],
        **resultat,
    }


if __name__ == "__main__":
    import uvicorn

    print("Démonstration du recollage multi-pages -> http://localhost:8010")
    uvicorn.run(app, host="0.0.0.0", port=8010, log_level="warning")
