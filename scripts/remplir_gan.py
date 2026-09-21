"""
Remplit le formulaire PHCN avec de l'ecriture manuscrite GENEREE par le GAN.

Ce que ca change par rapport a `handwriting/generate.py`
---------------------------------------------------------
Le generateur existant ecrit les champs manuscrits avec une POLICE
manuscrite (PlaywriteVN). C'est propre, mais une police produit toujours le
meme trace pour la meme lettre : ce n'est pas de l'ecriture, c'est de la
typographie qui y ressemble. Les rapports du projet le signalent comme la
limite principale de tout le volet manuscrit.

Ici, chaque MOT est une image produite par WriteViT dans le style d'un
scripteur reel de VNOnDB. Un document, un scripteur -- comme une vraie feuille
remplie par une seule personne.

Comment, sans refaire la mise en page
---------------------------------------
Tous les champs manuscrits du generateur passent par une seule fonction,
`hw()`. On la remplace : au lieu d'enrober le texte dans la police, elle rend
une suite de `\\includegraphics`, un par mot, separes par de vraies espaces
LaTeX.

C'est ce dernier point qui compte. Une image unique par champ ne pourrait pas
se couper, et la colonne « description » du tableau est etroite : le texte y
tient sur deux ou trois lignes. En gardant un mot par image et des espaces
entre elles, **LaTeX continue de gerer les retours a la ligne**, les largeurs
de cellule et l'alignement. Rien d'autre du template ne bouge.

Verite terrain
----------------
Par defaut, les specimens REPRENNENT les verites terrain deja generees
(`handwriting/generated/specimen_*_verite.json`). Le document produit a donc
exactement le meme contenu que son homologue en police, ce qui donne une
comparaison APPARIEE : meme texte, meme mise en page, seule l'ecriture change.
C'est la seule facon de mesurer ce que le GAN apporte.

Prerequis
-----------
- torch + timm (le venv du projet), pour WriteViT
- xelatex sur le PATH, comme pour `handwriting/generate.py`

Usage :
    python scripts/remplir_gan.py --depot-writevit ..\\WriteViT --n 5
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "handwriting"))
sys.path.insert(0, str(RACINE / "scripts"))

SEPARATEURS = re.compile(r"\s+")


def mots_de(texte: str):
    """Decoupe un champ en mots dessinables.

    WriteViT n'a ni espace ni ponctuation dans son alphabet. La ponctuation
    SEPARE donc les mots au lieu d'etre supprimee : « 12/07 » devient
    « 12 » puis « 07 », et non « 1207 ». Effacer la barre fabriquerait un
    nombre qui n'a jamais ete ecrit, et la verite terrain mentirait sur
    l'image.
    """
    return [m for m in re.split(r"[^\w]+", str(texte), flags=re.UNICODE) if m]


def collecter(verite: dict):
    """Tous les mots manuscrits d'un specimen, dans l'ordre du document."""
    champs = []
    p = verite["patient"]
    for cle in ("so_y_te", "ten", "tuoi", "gioi", "buong", "giuong",
                "chan_doan"):
        champs.append(str(p[cle]))
    for l in verite["lignes"]:
        for cle in ("ngay_gio", "mo_ta", "ky_thuat", "thoi_gian",
                    "nguoi_thuc_hien", "bs_chi_dinh", "xac_nhan"):
            champs.append(str(l[cle]))
    return champs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--depot-writevit", default="../WriteViT")
    ap.add_argument("--checkpoint", default="File/vn_ckpt.pth")
    ap.add_argument("--pickle", default="File/VN.pickle")
    ap.add_argument("--verites", default="handwriting/generated",
                    help="Dossier des verites terrain a reprendre.")
    ap.add_argument("--sortie", default="handwriting_gan/generated")
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--hauteur-pt", type=float, default=8.0,
                    help="Hauteur des images de mots dans le document, en "
                         "points LaTeX. A ajuster si l'ecriture parait trop "
                         "grande ou trop petite face au texte imprime.")
    ap.add_argument("--echelle-repli", type=float, default=0.55,
                    help="Facteur applique aux mots ecrits en police de "
                         "repli, pour les mettre a la taille des images du "
                         "GAN. Baisse si les chiffres paraissent encore trop "
                         "gros.")
    ap.add_argument("--avec-chiffres", action="store_true",
                    help="Laisser le GAN dessiner les mots contenant des "
                         "chiffres. Deconseille : il ne sait pas les former, "
                         "meme apres affinage. Par defaut ils passent en "
                         "police manuscrite de repli.")
    ap.add_argument("--graine", type=int, default=12345)
    args = ap.parse_args()

    depot = Path(args.depot_writevit).resolve()
    # Resolus AVANT tout changement de repertoire courant.
    chemin_verites = Path(args.verites).resolve()
    sortie = Path(args.sortie).resolve()
    import writevit_generer as wg
    modele, params, torch = wg.charger_modele(depot, depot / args.checkpoint)
    print(f"WriteViT charge sur {params.DEVICE}")

    # Un scripteur par document. Une vraie feuille est remplie par une seule
    # personne ; melanger les styles dans une meme page produirait un document
    # qui n'existe pas.
    scripteurs = list(wg.styles(depot / args.pickle, 0, args.graine))
    print(f"{len(scripteurs)} scripteurs disponibles")

    verites = sorted(chemin_verites.glob("specimen_*/*_verite.json"))
    if not verites:
        raise SystemExit(f"Aucune verite terrain sous {args.verites}. "
                         "Lance d'abord handwriting/generate.py.")
    verites = verites[: args.n]
    print(f"{len(verites)} specimen(s) a remplir")

    import generate as gen

    for i, chemin_verite in enumerate(verites):
        nom = chemin_verite.parent.name
        verite = json.loads(chemin_verite.read_text(encoding="utf-8"))
        wid, _, img_style = scripteurs[i % len(scripteurs)]
        style = wg.preparer_style(img_style, params, torch)

        dossier = sortie / nom
        (dossier / "mots").mkdir(parents=True, exist_ok=True)

        # Un seul appel au generateur pour tout le document : le modele traite
        # un lot de mots d'un coup, et l'appeler champ par champ serait
        # nettement plus lent pour un resultat identique.
        besoin = []
        for champ in collecter(verite):
            besoin.extend(mots_de(champ))
        uniques = sorted(set(besoin))
        # Deux raisons d'ecarter un mot du GAN. Un caractere hors alphabet,
        # qu'il ne sait pas encoder. Et surtout les CHIFFRES : ils sont bien
        # dans l'alphabet, donc le modele les dessine -- mal. Planche de
        # controle du 21 septembre, avant ET apres affinage : « 1972 » et
        # « 15 » sortent en traits informes. Sur un dossier medical, ce sont
        # les posologies, les durees et les dates.
        def dessinable(m):
            if not set(m) <= set(params.ALPHABET):
                return False
            return args.avec_chiffres or not any(c.isdigit() for c in m)

        uniques = [m for m in uniques if dessinable(m)]

        chemins = {}
        for debut in range(0, len(uniques), 32):
            lot = uniques[debut:debut + 32]
            for mot, im in zip(lot, wg.generer(modele, params, torch, style, lot)):
                f = dossier / "mots" / f"{abs(hash(mot)) % 10**10}.png"
                wg._png(im).save(f)
                chemins[mot] = f.resolve().as_posix()

        # --- le remplacement, et tout l'interet du script ---------------
        replis = set()

        def hw_images(texte):
            morceaux = []
            for mot in mots_de(texte):
                if mot in chemins:
                    morceaux.append(
                        r"\raisebox{-0.15ex}{\includegraphics[height="
                        f"{args.hauteur_pt}pt]{{{chemins[mot]}}}}}")
                else:
                    # Repli sur la POLICE manuscrite, pas sur le texte
                    # imprime. Le generateur ne sait pas former les chiffres
                    # (§7.3 du rapport), et ils pesent 36 % des mots d'un
                    # formulaire : posologies, durees, dates, numeros de
                    # chambre. Les laisser en imprime rendrait le document
                    # incoherent et fausserait toute lecture.
                    replis.add(mot)
                    # Reduit a l'echelle des images du GAN. La police
                    # PlaywriteVN dessine des glyphes nettement plus grands
                    # que les mots generes a la meme taille nominale : sans
                    # cette mise a l'echelle, les chiffres ecrasent le reste
                    # du document et trahissent le repli au premier coup
                    # d'oeil.
                    morceaux.append(
                        r"\scalebox{" + f"{args.echelle_repli}" +
                        r"}{{\hw " + gen.echapper(mot) + "}}")
            # De vraies espaces entre les images : LaTeX peut donc couper la
            # ligne entre deux mots, exactement comme avec du texte.
            return " ".join(morceaux)

        gen.hw = hw_images
        tex = gen.construire_tex(verite["patient"], verite["lignes"])
        tex = tex.replace(r"\usepackage{array}",
                          "\\usepackage{array}\n\\usepackage{graphicx}")

        try:
            _, png = gen.compiler(tex, dossier, nom)
        except RuntimeError as e:
            print(f"  [{nom}] ECHEC : {e}")
            continue

        # La verite terrain enregistree est celle REELLEMENT ecrite : sans la
        # ponctuation, que le GAN ne sait pas dessiner. Enregistrer le texte
        # d'origine ferait compter comme erreurs des caracteres absents de
        # l'image.
        verite_ecrite = json.loads(json.dumps(verite, ensure_ascii=False))
        p = verite_ecrite["patient"]
        for cle in ("so_y_te", "ten", "tuoi", "gioi", "buong", "giuong",
                    "chan_doan"):
            p[cle] = " ".join(mots_de(p[cle]))
        for l in verite_ecrite["lignes"]:
            for cle in ("ngay_gio", "mo_ta", "ky_thuat", "thoi_gian",
                        "nguoi_thuc_hien", "bs_chi_dinh", "xac_nhan"):
                l[cle] = " ".join(mots_de(l[cle]))
        verite_ecrite["scripteur"] = wid
        (dossier / f"{nom}_verite.json").write_text(
            json.dumps(verite_ecrite, ensure_ascii=False, indent=2),
            encoding="utf-8")

        try:
            affiche = png.relative_to(RACINE)
        except ValueError:
            affiche = png          # sortie hors du depot : chemin absolu
        part = len(replis) / max(len(uniques), 1)
        print(f"  [{nom}] scripteur {wid}, {len(uniques)} mots, "
              f"{len(replis)} en police de repli ({part:.0%}) -> "
              f"{affiche}")

    print(f"\n-> {sortie}")


if __name__ == "__main__":
    main()
