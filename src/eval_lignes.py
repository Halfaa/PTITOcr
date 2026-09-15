"""
CER / WER sur des images de LIGNES manuscrites (jeu Cinnamon AI Marathon).

Pourquoi un second script d'evaluation. `eval_handwriting.py` cherche des
CHAMPS dans la transcription d'une page de formulaire ; il suppose donc un
formulaire, et une verite terrain par champ. Les jeux de vraie ecriture
vietnamienne disponibles -- Cinnamon AI Marathon, 1838 images -- sont des
LIGNES isolees avec leur transcription. Ce n'est pas la meme tache, et la
mesurer avec la meme metrique n'aurait pas de sens.

Ici on mesure ce que mesure la litterature :

    CER   taux d'erreur par caractere (distance d'edition / longueur de ref)
    WER   idem par mot
    SER   part des lignes qui ne sont pas exactement justes

Ce qui rend ces chiffres comparables a une reference publiee : le depot
Cinnamon (TomHuynhSG) annonce **CER 4,8 % / WER 15,7 %** avec un CRNN
entraine sur ce jeu. Un modele generaliste comme Chandra n'a jamais vu ces
donnees ; l'ecart, dans un sens ou dans l'autre, est le resultat.

Le piege vietnamien, et il fausserait tout
-------------------------------------------
« ệ » s'ecrit en Unicode de deux facons : un seul point de code (NFC), ou
« e » suivi de deux diacritiques combinantes (NFD). Les deux s'affichent
pareil. Si le modele rend l'une et la verite terrain l'autre, chaque
caractere accentue compte comme deux erreurs -- un CER de 4 % passerait
mecaniquement au-dessus de 30 % sans qu'une seule lettre soit fausse.
Les deux cotes sont donc normalises en NFC avant toute comparaison.

On rend aussi un **CER sans diacritiques**, qui separe deux fautes qu'on
confond sinon : lire la mauvaise LETTRE, et lire le mauvais ACCENT. C'est
la distinction centrale du projet -- PP-StructureV3 reconstruisait la
grille (0,857) mais pas les caracteres (0,557), et PaddleOCR-VL substitue
des caracteres CJK quand il doute d'un diacritique.

Agregation : au NIVEAU CORPUS, pas moyenne des lignes
------------------------------------------------------
CER corpus = somme des distances / somme des longueurs. La moyenne des CER
par ligne donne un autre chiffre, domine par les lignes courtes : une ligne
de trois caracteres dont un est faux pese alors autant qu'une ligne de
cent. Les deux sont affiches, parce que confondre les deux est le classique
de la comparaison entre papiers.

Usage :
    python src/eval_lignes.py --run cinnamon_chandra \\
        --labels ../datasets/cinnamon/labels.json --detail
"""

import argparse
import json
import re
import unicodedata
from pathlib import Path


# --------------------------------------------------------------------------
# Normalisation

_BALISES = re.compile(r"<[^>]+>")
_MARKDOWN = re.compile(r"[*_`#>|]+")


def _nettoyer(texte: str) -> str:
    """Retire ce que le modele ajoute autour du texte, pas le texte."""
    texte = _BALISES.sub(" ", str(texte))
    texte = _MARKDOWN.sub(" ", texte)
    return texte


def normaliser(texte: str, ignorer_casse=False, sans_diacritiques=False) -> str:
    # NFC d'abord : voir l'en-tete. C'est la seule normalisation qui n'est
    # pas optionnelle.
    texte = unicodedata.normalize("NFC", _nettoyer(texte))
    texte = re.sub(r"\s+", " ", texte).strip()
    if ignorer_casse:
        texte = texte.lower()
    if sans_diacritiques:
        # "đ"/"Đ" sont des LETTRES vietnamiennes, pas des lettres accentuees :
        # elles ne se decomposent pas en NFD et doivent etre traitees a part.
        # Meme correctif que dans src/invoice_fields.py et eval_handwriting.py.
        extra = {"đ": "d", "Đ": "D"}
        texte = "".join(extra.get(c, c) for c in texte)
        texte = "".join(c for c in unicodedata.normalize("NFD", texte)
                        if not unicodedata.combining(c))
    return texte


# --------------------------------------------------------------------------
# Distance d'edition

def levenshtein(a, b) -> int:
    """Distance d'edition entre deux sequences (caracteres ou mots).

    Implementee ici plutot qu'importee : `editdistance` est une dependance
    de plus pour trente lignes, et le projet tient a ce qu'un script
    d'evaluation s'execute sans installer quoi que ce soit.
    """
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)

    precedente = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        courante = [i]
        for j, cb in enumerate(b, start=1):
            courante.append(min(
                precedente[j] + 1,          # suppression
                courante[j - 1] + 1,        # insertion
                precedente[j - 1] + (ca != cb),  # substitution
            ))
        precedente = courante
    return precedente[-1]


# --------------------------------------------------------------------------
# Chargement

def charger_labels(chemin: Path) -> dict:
    """stem -> transcription attendue.

    Les jeux publics ne s'accordent pas sur la forme du JSON : un
    dictionnaire {fichier: texte}, ou une liste d'objets. On accepte les
    deux plutot que d'imposer une conversion prealable.
    """
    donnees = json.loads(Path(chemin).read_text(encoding="utf-8"))
    labels = {}

    if isinstance(donnees, dict):
        for cle, valeur in donnees.items():
            texte = valeur if isinstance(valeur, str) else (
                valeur.get("label") or valeur.get("text") or "")
            labels[Path(str(cle)).stem] = texte
    elif isinstance(donnees, list):
        for entree in donnees:
            if not isinstance(entree, dict):
                continue
            nom = (entree.get("file") or entree.get("image")
                   or entree.get("filename") or entree.get("name") or "")
            texte = (entree.get("label") or entree.get("text")
                     or entree.get("transcription") or "")
            if nom:
                labels[Path(str(nom)).stem] = texte
    return labels


def transcription(pages_dir: Path, stem: str):
    dossier = pages_dir / stem
    if not dossier.is_dir():
        return None
    md = list(dossier.glob("*.md"))
    if not md:
        return None
    return max(md, key=lambda p: p.stat().st_mtime).read_text(encoding="utf-8")


# --------------------------------------------------------------------------

def evaluer(run_dir: Path, labels: dict, ignorer_casse=False, detail=False):
    pages_dir = run_dir / "pages"
    if not pages_dir.is_dir():
        print(f"{run_dir.name} : pas de dossier pages/")
        return None

    d_car = n_car = d_mot = n_mot = 0
    d_car_sd = n_car_sd = 0
    exactes = lues = 0
    par_ligne = []

    for dossier in sorted(pages_dir.iterdir()):
        if not dossier.is_dir():
            continue
        stem = dossier.name
        attendu = labels.get(stem) or labels.get(stem.split("-")[0])
        texte = transcription(pages_dir, stem)
        if attendu is None or texte is None:
            continue

        lues += 1
        ref = normaliser(attendu, ignorer_casse)
        hyp = normaliser(texte, ignorer_casse)

        d = levenshtein(ref, hyp)
        d_car += d
        n_car += len(ref)
        if ref == hyp:
            exactes += 1

        mots_ref, mots_hyp = ref.split(), hyp.split()
        d_mot += levenshtein(mots_ref, mots_hyp)
        n_mot += len(mots_ref)

        ref_sd = normaliser(attendu, ignorer_casse, sans_diacritiques=True)
        hyp_sd = normaliser(texte, ignorer_casse, sans_diacritiques=True)
        d_car_sd += levenshtein(ref_sd, hyp_sd)
        n_car_sd += len(ref_sd)

        par_ligne.append((d / len(ref) if ref else 0.0, stem, ref, hyp))

    if not lues:
        print(f"{run_dir.name} : aucune ligne appariee "
              "(les noms du JSON correspondent-ils aux dossiers de pages/ ?)")
        return None

    cer = d_car / n_car if n_car else 0.0
    wer = d_mot / n_mot if n_mot else 0.0
    cer_sd = d_car_sd / n_car_sd if n_car_sd else 0.0
    ser = 1 - exactes / lues
    cer_moyen = sum(c for c, *_ in par_ligne) / len(par_ligne)

    print(f"\n{run_dir.name}  ({lues} lignes)")
    print(f"  CER  {cer:6.2%}   (moyenne par ligne {cer_moyen:.2%})")
    print(f"  WER  {wer:6.2%}")
    print(f"  SER  {ser:6.2%}   lignes exactes : {exactes}/{lues}")
    print(f"  CER sans diacritiques {cer_sd:6.2%}"
          f"   -- l'ecart ({cer - cer_sd:+.2%}) est la part des accents")
    print("  reference publiee (CRNN, Cinnamon) : CER 4,80 %  WER 15,66 %")

    if detail:
        print("\n  Pires lignes :")
        for c, stem, ref, hyp in sorted(par_ligne, reverse=True)[:12]:
            print(f"    {stem:<26} CER {c:5.1%}")
            print(f"      attendu : {ref[:90]}")
            print(f"      lu      : {hyp[:90]}")

    return {"cer": cer, "wer": wer, "ser": ser, "cer_sans_diacritiques": cer_sd,
            "n_lignes": lues}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="append", required=True,
                    help="Nom (ou chemin) d'un run sous results/. Repetable.")
    ap.add_argument("--labels", required=True,
                    help="JSON des transcriptions attendues.")
    ap.add_argument("--results-root", default="results")
    ap.add_argument("--ignorer-casse", action="store_true",
                    help="Comparer sans tenir compte de la casse.")
    ap.add_argument("--detail", action="store_true",
                    help="Afficher les lignes les plus fausses.")
    args = ap.parse_args()

    labels = charger_labels(Path(args.labels))
    if not labels:
        raise SystemExit(
            f"Aucun label lu depuis {args.labels}.\n"
            "Formes acceptees : {\"fichier.png\": \"texte\"} ou "
            "[{\"file\": ..., \"label\": ...}]")
    print(f"{len(labels)} labels charges depuis {args.labels}")

    racine = Path(args.results_root).resolve()
    for nom in args.run:
        chemin = Path(nom) if Path(nom).is_absolute() else racine / nom
        evaluer(chemin, labels, args.ignorer_casse, args.detail)


if __name__ == "__main__":
    main()
