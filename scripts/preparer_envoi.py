"""
Assembler un paquet a envoyer : les resultats + le corpus qui les fonde.

Envoyer un document de resultats sans les donnees oblige le destinataire a
croire les chiffres sur parole ; envoyer les donnees sans le document lui
laisse 71 images sans mode d'emploi. Ce script met les deux dans la meme
archive, avec le manifeste et la verite terrain, de sorte que tout y soit
verifiable.

Par defaut le paquet ne contient que le MANUSCRIT : c'est ce dont parlent
les documents. Y joindre les factures et les photos TabRecSet ferait porter
au destinataire des centaines de Mo qui n'illustrent rien de ce qu'il lit.

    python scripts/preparer_envoi.py
    python scripts/preparer_envoi.py --tout           # toutes les familles
    python scripts/preparer_envoi.py --n-specimens 6  # plus de pages propres
    python scripts/preparer_envoi.py --sortie D:/envoi

Contenu de l'archive :

    README.md                        le document de resultats principal
    deformation_3d.md                le second document, si present
    figures/                         les planches de paliers, si generees
    corpus/imgs/handwriting/<jeu>/   les images, avec leur *_verite.json
    corpus/manifest.json             une entree par image
    corpus/README.md                 la notice du corpus

Les jeux de degradation sont reduits aux paliers CITES dans les documents
(voir PALIERS_CITES), sur une seule page : envoyer les 24 ferait plusieurs
centaines de Mo -- les images bruitees sont incompressibles -- pour
illustrer une courbe que le tableau donne deja.

Le corpus est produit par `dataset/build_manifest.py`, dont les fonctions
sont importees plutot que relancees en sous-processus : une seule source de
verite pour ce qui va dans l'archive.

NON EXECUTE ici : l'environnement d'execution de l'assistant etait casse au
moment de l'ecriture (montage Windows, mise a jour du 8 septembre). Le
script affiche ce qu'il fait a chaque etape, et l'inventaire final permet
de verifier que rien ne manque avant d'envoyer.
"""

import argparse
import shutil
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "dataset"))

# Ce qui part avec les donnees. Le premier devient README.md dans l'archive :
# c'est le fichier qu'un destinataire ouvre en premier, autant que ce soit
# le document de resultats.
DOCUMENTS = [
    (RACINE / "docs" / "notion_handwriting_results.md", "README.md"),
    (RACINE / "docs" / "notion_deformation_3d.md", "deformation_3d.md"),
]

FIGURES = RACINE / "demo" / "figures"
MOTIFS_FIGURES = ("17_paliers_manuscrit*.png", "18_paliers_manuscrit*.png")


# Les paliers CITES dans les documents. Envoyer les 24 ferait une archive de
# plusieurs centaines de Mo -- les images bruitees sont incompressibles --
# pour illustrer une courbe que le tableau donne deja. Ceux-ci sont les
# points dont le lecteur voudra verifier l'image : le debut, la rupture, et
# le pire cas de chaque famille.
PALIERS_CITES = ("niveau0", "flou1", "flou2", "flou3", "flou5",
                 "resolution2", "resolution3", "resolution5")


def manuscrit_seulement(manifeste, n_specimens):
    """Ne garder que le manuscrit, et seulement les paliers cites.

    Le paquet accompagne des documents sur l'ecriture manuscrite : y joindre
    les factures et les photos TabRecSet ferait porter au destinataire 400 Mo
    qui n'illustrent rien de ce qu'il lit.
    """
    gardees, resume = [], {}
    par_jeu = {}
    for e in manifeste["images"]:
        if e["famille"] != "manuscrit":
            continue
        par_jeu.setdefault(e["jeu"], []).append(e)

    for jeu, entrees in sorted(par_jeu.items()):
        if entrees[0].get("palier") is not None:
            choisies = [e for e in entrees if e["palier"] in PALIERS_CITES]
            # Une seule page, la meme a tous les paliers : c'est la
            # comparaison qui parle, pas le nombre de pages.
            noms = sorted({Path(e["chemin"]).name for e in choisies})
            if noms:
                choisies = [e for e in choisies
                            if Path(e["chemin"]).name == noms[0]]
            resume[jeu] = (f"{len(choisies)} images = 1 page x "
                           f"{len({e['palier'] for e in choisies})} paliers cites")
        else:
            choisies = entrees[:n_specimens] if n_specimens else entrees
            resume[jeu] = f"{len(choisies)} pages"
        gardees.extend(choisies)

    sortie = dict(manifeste)
    sortie["images"] = gardees
    sortie["n_images"] = len(gardees)
    jeux = {c: {**j, "n_images": len([e for e in gardees if e["jeu"] == c])}
            for c, j in manifeste["jeux"].items()
            if any(e["jeu"] == c for e in gardees)}
    sortie["jeux"] = jeux
    sortie["n_jeux"] = len(jeux)
    sortie["envoi"] = {
        "note": "Handwriting only. Degradation sets are reduced to the levels "
                "cited in the documents, on a single page, so that the archive "
                "stays mailable; the full sets are regenerated with "
                "scripts/degrader.py.",
        "paliers_retenus": list(PALIERS_CITES),
        "par_jeu": resume,
        "corpus_complet": {"n_images": manifeste["n_images"],
                           "n_jeux": manifeste["n_jeux"]},
    }
    return sortie


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sortie", default=str(RACINE / "envoi"),
                   help="Dossier de travail, zippe ensuite.")
    p.add_argument("--tout", action="store_true",
                   help="Toutes les familles (factures et photos reelles "
                        "comprises) au lieu du manuscrit seul.")
    p.add_argument("--n-specimens", type=int, default=3,
                   help="Pages propres par langue (defaut 3).")
    p.add_argument("--sans-corpus", action="store_true",
                   help="Documents et figures seulement.")
    args = p.parse_args()

    destination = Path(args.sortie)
    if destination.exists():
        # Un reste d'un envoi precedent partirait avec celui-ci sans qu'on
        # s'en apercoive.
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

    print("Documents :")
    for source, nom in DOCUMENTS:
        if source.exists():
            shutil.copy2(source, destination / nom)
            print(f"  {source.name} -> {nom}")
        else:
            print(f"  {source.name} ABSENT, saute")

    figures = [f for motif in MOTIFS_FIGURES for f in sorted(FIGURES.glob(motif))]
    if figures:
        (destination / "figures").mkdir()
        for f in figures:
            shutil.copy2(f, destination / "figures" / f.name)
        print(f"\nFigures : {len(figures)} planche(s)")
    else:
        print("\nFigures : aucune (python scripts/figure_paliers_manuscrit.py "
              "pour les produire)")

    if not args.sans_corpus:
        import build_manifest as bm

        print("\nCorpus :")
        bm.diagnostiquer_racines()
        manifeste = bm.construire()
        if not args.tout:
            manifeste = manuscrit_seulement(manifeste, args.n_specimens)
            for jeu, detail in sorted(manifeste["envoi"]["par_jeu"].items()):
                print(f"  {jeu:<36}{detail}")
        n = bm.exporter(manifeste, destination / "corpus")
        print(f"  {n} images copiees")

    archive = shutil.make_archive(str(destination), "zip",
                                  destination.parent, destination.name)
    taille = Path(archive).stat().st_size / 1e6

    print(f"\n-> {archive}  ({taille:.0f} Mo)")
    print("\nInventaire :")
    for chemin in sorted(destination.rglob("*")):
        if chemin.is_dir():
            n = len([f for f in chemin.rglob("*") if f.is_file()])
            if n:
                print(f"  {chemin.relative_to(destination).as_posix():<44}{n:>5} fichiers")
        elif chemin.parent == destination:
            print(f"  {chemin.name}")

    print("\nA verifier avant d'envoyer : que README.md soit bien le document")
    print("de resultats, et que corpus/manifest.json annonce le meme nombre")
    print("d'images que ce qui est dans corpus/imgs/.")


if __name__ == "__main__":
    main()
