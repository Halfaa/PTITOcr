"""
Construit le lexique de mots vietnamiens MEDICAUX a faire ecrire par WriteViT.

Pourquoi ce fichier existe
----------------------------
Le jeu de vraie ecriture qu'on a mesure (Cinnamon, 1838 lignes) ne contient
que des ADRESSES. Nos documents sont des dossiers de reeducation et des
factures d'hopital. Un HTR entraine sur des noms de rue n'a jamais vu
« Isokinetic », « khuỷu » ni « chườm », et c'est precisement ce qu'il devra
lire. C'est cet ecart de domaine que la generation doit combler -- sinon on
reproduit le papier WriteViT sans rien apporter au stage.

Contrainte imposee par WriteViT
---------------------------------
Son alphabet vietnamien compte 197 caracteres : lettres accentuees, chiffres
et « ! ». **Ni espace ni ponctuation.** Le modele genere donc des MOTS, pas
des lignes. On decoupe le vocabulaire en tokens, on ecarte ce qui sort de
l'alphabet, et les lignes seront recomposees par concatenation au moment de
fabriquer le jeu.

Ce que le script mesure au passage
------------------------------------
La part des tokens medicaux ABSENTS de leur lexique generique
(`vn_words.txt`, 14 185 mots). Ce pourcentage est l'argument chiffre du
choix de corpus : s'il est eleve, generer du vietnamien generique
n'apprendrait pas au CRNN les mots qu'il devra lire.

Usage :
    python scripts/lexique_medical.py
    python scripts/lexique_medical.py --sortie ..\\WriteViT\\File\\vn_medical_words.txt
"""

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent

# Recopie depuis WriteViT/params.py (DATASET == 'VNDB'). On ne l'importe pas :
# ce script doit tourner sans que le depot WriteViT soit present.
ALPHABET = (
    "aáàảãạăắằẳẵặâấầẩẫậbcdđeéèẻẽẹêếềểễệfghiíìỉĩịjklmnoóòỏõọôốồổỗộơớờởỡợpqrs"
    "tuúùủũụưứừửữựvwxyýỳỷỹỵzAÁÀẢÃẠĂẮẰẲẴẶÂẤẦẨẪẬBCDĐEÉÈẺẼẸÊẾỀỂỄỆFGHIÍÌỈĨỊJKLM"
    "NOÓÒỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢPQRSTUÚÙỦŨỤƯỨỪỬỮỰVWXYÝỲỶỸỴZ0123456789!"
)
JEU = set(ALPHABET)

# Tout ce qui n'est pas lettre ou chiffre separe deux tokens. « 27/BV1 » donne
# donc « 27 » et « BV1 » : deux mots que le modele sait ecrire, la barre
# oblique etant remise a la composition des lignes.
SEPARATEURS = re.compile(r"[^\w]+", re.UNICODE)


def tokeniser(texte: str):
    # NFC d'abord : « ệ » decompose ne se retrouverait dans aucun alphabet.
    texte = unicodedata.normalize("NFC", str(texte))
    for brut in SEPARATEURS.split(texte):
        if brut:
            yield brut


def textes_du_vocabulaire():
    """Les listes de vocab_phcn.py : nomenclature officielle du Bo Y te."""
    sys.path.insert(0, str(RACINE / "handwriting"))
    try:
        import vocab_phcn
    except Exception as e:
        print(f"  vocab_phcn.py illisible ({type(e).__name__}), ignore")
        return
    for nom in ("TECHNIQUES", "DESCRIPTIONS", "NOMS_KTV", "NOMS_BS",
                "NOMS_PATIENT", "CHAN_DOAN", "SO_Y_TE"):
        for t in getattr(vocab_phcn, nom, []):
            yield str(t)


def textes_des_verites(dossiers):
    """Les valeurs des verites terrain deja generees.

    On prend les FEUILLES du JSON, quelle que soit la profondeur : la forme
    des fichiers a bouge au fil du projet et un parcours en dur raterait
    silencieusement une partie du vocabulaire.
    """
    def feuilles(o):
        if isinstance(o, dict):
            for v in o.values():
                yield from feuilles(v)
        elif isinstance(o, list):
            for v in o:
                yield from feuilles(v)
        elif isinstance(o, str):
            yield o

    for dossier in dossiers:
        for f in sorted(Path(dossier).rglob("*_verite.json")):
            try:
                yield from feuilles(json.loads(f.read_text(encoding="utf-8")))
            except Exception as e:
                print(f"  {f.name} illisible ({type(e).__name__}), ignore")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sortie", default="../WriteViT/File/vn_medical_words.txt")
    ap.add_argument("--lexique-generique", default="../WriteViT/File/vn_words.txt",
                    help="Pour mesurer le recouvrement. Facultatif.")
    ap.add_argument("--labels-reels",
                    default="../datasets/vn_lignes/vn_handwritten_images/labels.json",
                    help="Labels du jeu de vraie ecriture (Cinnamon). C'est LE "
                         "point de comparaison qui compte : ce que le CRNN "
                         "aurait vu s'il n'apprenait que sur du reel.")
    ap.add_argument("--min-occurrences", type=int, default=1)
    args = ap.parse_args()

    # `handwriting_en/` est volontairement exclu : ce sont les specimens
    # ANGLAIS. Les y inclure remplissait le lexique de « Hypertension »,
    # « Treadmill » et de prenoms americains, et faisait croire a un enorme
    # vocabulaire medical inconnu qui n'etait que de l'anglais mal range.
    sources = list(textes_du_vocabulaire()) + list(textes_des_verites([
        RACINE / "handwriting" / "generated",
    ]))
    print(f"{len(sources)} chaines source")

    retenus, rejetes = Counter(), Counter()
    for texte in sources:
        for token in tokeniser(texte):
            (retenus if set(token) <= JEU else rejetes)[token] += 1

    vocabulaire = {m: n for m, n in retenus.items()
                   if n >= args.min_occurrences}
    print(f"{len(vocabulaire)} mots retenus, {sum(vocabulaire.values())} occurrences")

    if rejetes:
        # Ces tokens contiennent un caractere hors alphabet -- typiquement une
        # lettre latine non vietnamienne. Les lister plutot que les compter :
        # si l'un d'eux est un terme medical frequent, il faudra le traiter,
        # pas l'ignorer.
        print(f"\n{len(rejetes)} token(s) hors alphabet, ecartes :")
        for mot, n in rejetes.most_common(15):
            hors = "".join(sorted(set(mot) - JEU))
            print(f"    {mot:<22} x{n:<4} caractere(s) fautif(s) : {hors!r}")

    generique = Path(args.lexique_generique)
    if generique.exists():
        connus = {l.strip().lower()
                  for l in generique.read_text(encoding="utf-8").splitlines()
                  if l.strip()}
        # Les suites de chiffres (numeros de dossier, dates, durees) sont
        # absentes de TOUT lexique par construction. Les compter comme du
        # vocabulaire inedit gonflerait le chiffre sans rien dire du domaine
        # medical -- elles restent dans le lexique a generer, mais sortent de
        # la statistique de recouvrement.
        mots = [m for m in vocabulaire if not m.isdigit()]
        inedits = [m for m in mots if m.lower() not in connus]
        chiffres = len(vocabulaire) - len(mots)
        print(f"\nRecouvrement avec {generique.name} ({len(connus)} mots) :")
        print(f"  {len(inedits)}/{len(mots)} mots medicaux ABSENTS de leur "
              f"lexique ({len(inedits) / len(mots):.0%})"
              f"   [{chiffres} tokens purement numeriques exclus du calcul]")
        print("  exemples :", ", ".join(sorted(inedits)[:14]))
    else:
        print(f"\n{generique} absent : recouvrement non mesure.")

    # --- La comparaison qui decide du corpus -------------------------------
    # Un dictionnaire dit ce qui EXISTE en vietnamien. Ce qui compte pour un
    # HTR, c'est ce qu'il a VU. Si le CRNN n'apprend que sur Cinnamon, son
    # monde se limite aux adresses : il n'aura jamais rencontre « khuỷu » ni
    # « Isokinetic », meme si ces mots figurent dans tous les dictionnaires.
    reels = Path(args.labels_reels)
    if reels.exists():
        vus = set()
        for texte in json.loads(reels.read_text(encoding="utf-8")).values():
            for t in tokeniser(texte if isinstance(texte, str)
                               else texte.get("label", "")):
                vus.add(t.lower())
        mots = [m for m in vocabulaire if not m.isdigit()]
        jamais_vus = [m for m in mots if m.lower() not in vus]
        print(f"\nFace au jeu REEL ({reels.name}, {len(vus)} mots distincts) :")
        print(f"  {len(jamais_vus)}/{len(mots)} mots medicaux jamais vus "
              f"({len(jamais_vus) / len(mots):.0%})")
        print("  exemples :", ", ".join(sorted(jamais_vus, key=str.lower)[:16]))
    else:
        print(f"\n{reels} absent : comparaison au jeu reel non mesuree.")

    sortie = Path(args.sortie)
    sortie.parent.mkdir(parents=True, exist_ok=True)
    # Tri par frequence puis alphabetique : les termes les plus presents dans
    # les documents se retrouvent en tete, ce qui rend le fichier lisible a
    # l'oeil et permet de tronquer par le bas sans perdre l'essentiel.
    ordonnes = sorted(vocabulaire.items(), key=lambda kv: (-kv[1], kv[0]))
    sortie.write_text("\n".join(m for m, _ in ordonnes) + "\n",
                      encoding="utf-8")
    print(f"\n-> {sortie}  ({len(ordonnes)} mots)")
    print("   les 15 plus frequents :",
          ", ".join(f"{m}({n})" for m, n in ordonnes[:15]))


if __name__ == "__main__":
    main()
