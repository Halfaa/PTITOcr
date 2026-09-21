"""
Reequilibre VNOnDB pour affiner WriteViT sur les CHIFFRES.

Le probleme mesure
--------------------
Le checkpoint vietnamien de WriteViT ne sait pas former les chiffres. Planche
de controle du 21 septembre : « 1972 » rendu « Mth », « 15 » rendu « lb », sur
trois scripteurs differents. Ce n'est pas une affaire de frequence brute --
« 1 » apparait 1 073 fois dans VNOnDB et « 5 » 441 fois -- mais de proportion :
les mots contenant un chiffre pesent **2,83 %** du corpus d'entrainement
(1 892 sur 66 955). Noye a ce point, le generateur apprend la cursive et
ignore les chiffres.

Pour des dossiers medicaux -- posologies, durees, dates, numeros de chambre --
c'est la donnee la plus critique du document.

Ce que fait ce script
-----------------------
Il ecrit un pickle au meme format, ou les mots numeriques passent d'environ
3 % a environ 30 % : on garde TOUS les mots a chiffres, et on sous-echantillonne
les autres. Pas de duplication -- repeter la meme image quatre fois apprend
l'image, pas le chiffre.

La contrainte a ne pas violer
-------------------------------
`TextDataset` attribue `author_idx` par l'ORDRE d'enumeration du dictionnaire,
et la tete de classification du checkpoint a ete entrainee sur ces indices-la.
Supprimer un scripteur, ou en changer l'ordre, decalerait tous les suivants :
l'affinage passerait son temps a corriger un desalignement qu'on aurait
introduit nous-memes.

Les 106 scripteurs sont donc TOUS conserves, dans leur ordre d'origine, y
compris les cinq qui n'ont aucun mot numerique -- ils ne contribuent que des
mots ordinaires.

Usage :
    python scripts/vnondb_rebalancer_chiffres.py \\
        --entree ../WriteViT/File/VN.pickle \\
        --sortie ../WriteViT/File/VN_chiffres.pickle
"""

import argparse
import pickle
import random
from collections import Counter
from pathlib import Path


def a_chiffre(label: str) -> bool:
    return any(c.isdigit() for c in str(label))


def rebalancer(split: dict, normaux_par_scripteur: int, alea) -> dict:
    """Garde tous les mots a chiffres, echantillonne les autres.

    L'ordre des cles est preserve : c'est lui qui fixe `author_idx`.
    """
    sortie = {}
    for scripteur, echantillons in split.items():
        avec = [e for e in echantillons if a_chiffre(e["label"])]
        sans = [e for e in echantillons if not a_chiffre(e["label"])]
        alea.shuffle(sans)
        # Meme les scripteurs sans aucun chiffre restent presents : leur
        # disparition decalerait les indices de tous les suivants.
        sortie[scripteur] = avec + sans[:normaux_par_scripteur]
    return sortie


def decrire(nom: str, split: dict) -> None:
    total = sum(len(v) for v in split.values())
    avec = sum(1 for v in split.values() for e in v if a_chiffre(e["label"]))
    vides = sum(1 for v in split.values() if not v)
    print(f"  {nom:<6} {len(split):>4} scripteurs, {total:>6} mots, "
          f"{avec:>5} a chiffre ({avec / max(total, 1):.1%})"
          + (f", {vides} scripteur(s) vide(s)" if vides else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--entree", default="File/VN.pickle")
    ap.add_argument("--sortie", default="File/VN_chiffres.pickle")
    ap.add_argument("--normaux-par-scripteur", type=int, default=40,
                    help="Mots sans chiffre conserves par scripteur. Ils "
                         "empechent l'oubli du style cursif pendant l'affinage.")
    ap.add_argument("--graine", type=int, default=12345)
    args = ap.parse_args()

    d = pickle.load(open(args.entree, "rb"))
    print(f"{args.entree}")
    for nom in d:
        decrire(nom, d[nom])

    alea = random.Random(args.graine)
    ordre_avant = {nom: list(d[nom]) for nom in d}
    neuf = {nom: rebalancer(d[nom], args.normaux_par_scripteur, alea)
            for nom in d}

    # Verification explicite plutot que confiance : un decalage d'indice ne
    # produit aucune erreur, seulement un affinage qui n'apprend rien.
    for nom in d:
        assert list(neuf[nom]) == ordre_avant[nom], \
            f"ordre des scripteurs modifie dans '{nom}'"
    print("\nordre des scripteurs preserve dans chaque split")

    print(f"\n{args.sortie}")
    for nom in neuf:
        decrire(nom, neuf[nom])

    chiffres = Counter(c for v in neuf["train"].values() for e in v
                       for c in str(e["label"]) if c.isdigit())
    print(f"\n  occurrences par chiffre (train) : "
          f"{dict(sorted(chiffres.items()))}")
    faibles = [c for c in "0123456789" if chiffres[c] < 50]
    if faibles:
        print(f"  encore rares (<50) : {''.join(faibles)} -- ceux-la "
              "resteront les moins fiables apres affinage")

    with open(args.sortie, "wb") as f:
        pickle.dump(neuf, f)
    print(f"\n-> {Path(args.sortie).stat().st_size / 1e6:.0f} Mo")


if __name__ == "__main__":
    main()
