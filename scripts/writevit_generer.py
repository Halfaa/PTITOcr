"""
Genere des mots manuscrits vietnamiens MEDICAUX avec WriteViT.

A executer depuis le depot WriteViT (ses modules font `from params import *`,
qui ne resout que depuis sa racine). Le script s'en assure et refuse de
tourner autrement plutot que d'importer a moitie.

    cd ..\\WriteViT
    python ..\\MedicalRecord\\scripts\\writevit_generer.py --apercu
    python ..\\MedicalRecord\\scripts\\writevit_generer.py --n 25000

Ce que ca produit
-------------------
    <sortie>/images/<scripteur>_<index>.png
    <sortie>/labels.json      {"0003_00001.png": "khuỷu", ...}

Le `labels.json` a EXACTEMENT la forme de celui du jeu Cinnamon, donc
`src/eval_lignes.py` et `charger_labels()` le lisent sans modification. Ce
n'est pas un detail de confort : deux formats d'annotation pour la meme tache
finissent toujours par produire deux chiffres qu'on ne peut plus comparer.

Pourquoi des mots et pas des lignes
-------------------------------------
L'alphabet vietnamien de WriteViT compte 197 caracteres et ne contient NI
espace NI ponctuation. Le modele ne sait produire qu'un mot a la fois. Leur
propre `_generate_page` compose les lignes en concatenant les images de mots
avec un ecart de 16 px ; `--lignes` fait la meme chose ici.

Le controle qui decide de tout
--------------------------------
`--apercu` fabrique une planche de mots charges en diacritiques. C'est le
seul critere qui compte avant de lancer une generation de masse : si « ỗ »,
« ậ » ou « ư » sortent mal places, le jeu synthetique apprendra les mauvaises
formes au CRNN et on l'aura entraine a se tromper. C'est exactement le
reproche que le papier WriteViT fait a ScrabbleGAN.
"""

import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image

# Mots a diacritiques denses, tires de notre vocabulaire PHCN. Ils cumulent
# les cas durs : ton + chapeau (ế), ton + corne (ự), et « đ » qui n'est pas un
# « d » accentue mais une lettre a part entiere.
MOTS_CONTROLE = ["khuỷu", "Điều", "chườm", "ngải", "cứu", "thuật", "vận",
                 "động", "cột", "sống", "Kỹ", "tập", "được", "nghiệm",
                 "Nguyễn", "Isokinetic", "1972", "15"]


def charger_modele(depot: Path, checkpoint: Path):
    """Importe WriteViT depuis son depot et charge les poids."""
    sys.path.insert(0, str(depot))
    try:
        import params
    except ImportError:
        raise SystemExit(
            f"params.py introuvable dans {depot}.\n"
            "Lance le script depuis le depot WriteViT.")

    if params.DATASET != "VNDB":
        raise SystemExit(
            f"params.py est regle sur DATASET = '{params.DATASET}'.\n"
            "Mets 'VNDB' : sinon l'alphabet charge est celui d'IAM (80 "
            "caracteres) et le vietnamien sortirait sans accents, sans "
            "qu'aucune erreur ne soit levee.")

    import torch
    from models.model import WriteViT

    modele = WriteViT(batch_size=1, backbone=params.BACKBONE).to(params.DEVICE)
    etat = torch.load(str(checkpoint), map_location=params.DEVICE)
    if isinstance(etat, dict) and "state_dict" in etat:
        etat = etat["state_dict"]
    manquants, inattendus = modele.load_state_dict(etat, strict=False)
    if manquants or inattendus:
        # `strict=False` plutot qu'une erreur : le checkpoint sauvegarde le
        # modele entier (discriminateur et optimiseurs compris) et les noms
        # peuvent avoir bouge. Mais on AFFICHE l'ecart -- un generateur charge
        # a moitie produirait du bruit credible, pas une erreur.
        print(f"  poids manquants : {len(manquants)}, inattendus : "
              f"{len(inattendus)}")
        for n in list(manquants)[:5]:
            print(f"    manquant  {n}")
        if any(n.startswith("netG.") for n in manquants):
            raise SystemExit(
                "Des poids du GENERATEUR manquent : le checkpoint ne "
                "correspond pas a ce code. Generer donnerait du bruit.")
    modele.eval()
    return modele, params, torch


def styles(pickle_path: Path, n_scripteurs, graine):
    """Une image de reference par scripteur : c'est le mode one-shot.

    Dans leur `forward`, le style vient de `input["img"]` -- l'image reelle
    seule, pas des 15 echantillons de `simg`. On reproduit ce chemin.
    """
    import pickle
    d = pickle.load(open(pickle_path, "rb"))
    train = d["train"]
    ids = sorted(train)
    alea = random.Random(graine)
    if n_scripteurs and n_scripteurs < len(ids):
        ids = alea.sample(ids, n_scripteurs)
    for idx, wid in enumerate(sorted(ids)):
        ech = alea.choice(train[wid])
        yield wid, idx, ech["img"]


def preparer_style(img, params, torch):
    """Meme pretraitement que data/dataset.py : niveaux de gris, ToTensor,
    Normalize((0.5,), (0.5,)) -- donc des valeurs dans [-1, 1]."""
    a = np.array(img.convert("L"), dtype=np.float32) / 255.0
    t = torch.from_numpy(a)[None, None]           # (1, 1, H, W)
    return ((t - 0.5) / 0.5).to(params.DEVICE)


def generer(modele, params, torch, style, mots):
    """Rend une liste d'images numpy dans [0, 1], une par mot."""
    encode, longueurs = modele.netconverter.encode([m.encode() for m in mots])
    encode = encode.to(params.DEVICE)[None]       # (1, N, maxlen)
    with torch.no_grad():
        feat = modele.netW(style, None, training=False)
        fakes = modele.netG.Eval(feat, encode)
    images = []
    for i, f in enumerate(fakes):
        # Le generateur rend une largeur fixe ; la largeur UTILE d'un mot est
        # sa longueur en caracteres x `resolution` (16). Sans cette coupe, on
        # tracerait une longue zone vide apres chaque mot court.
        large = int(longueurs[i]) * params.resolution
        images.append((f[0, 0, :, :large].cpu().numpy() + 1) / 2)
    return images


def couverture(medical, appoint, part, n_images, params, part_maj=0.25,
               seuil=30):
    """Verifie que tous les caracteres de l'alphabet seront ecrits, et assez.

    Le lexique medical seul couvre 109 des 197 caracteres. Les 88 autres --
    dont presque toutes les majuscules accentuees -- ne seraient JAMAIS
    generes, et un CRNN entraine dessus ne saurait pas les lire. Le defaut ne
    se verrait qu'a l'evaluation finale, sous la forme d'erreurs inexplicables
    sur certaines lettres.

    D'ou le melange : le medical apporte le domaine, le generique la
    couverture. On compte ici les occurrences ATTENDUES de chaque caractere,
    pour le tirage qui va etre fait, et on nomme ce qui reste sous le seuil.
    """
    from collections import Counter

    def frequences(mots):
        c = Counter(ch for m in mots for ch in m)
        total = sum(c.values()) or 1
        moyenne = sum(len(m) for m in mots) / max(len(mots), 1)
        return {k: v / total for k, v in c.items()}, moyenne

    f_med, long_med = frequences(medical)
    f_app, long_app = frequences(appoint) if appoint else ({}, 0.0)

    # Les majuscules ACCENTUEES (Ế, Ộ, Ớ, Ự...) sont absentes des deux
    # lexiques : le medical est en minuscules et vn_words.txt n'a que des
    # capitales non accentuees. Aucun dosage entre les deux ne les fera
    # apparaitre. On en ecrit donc une part en capitales -- ce qui est aussi
    # ce que contiennent les en-tetes de formulaires hospitaliers.
    def melanger(freq, mots, part_maj):
        haut = Counter(ch for m in mots for ch in m.upper())
        total = sum(haut.values()) or 1
        haut = {k: v / total for k, v in haut.items()}
        return {ch: (1 - part_maj) * freq.get(ch, 0.0)
                    + part_maj * haut.get(ch, 0.0)
                for ch in set(freq) | set(haut)}

    f_med = melanger(f_med, medical, part_maj)
    if appoint:
        f_app = melanger(f_app, appoint, part_maj)

    caracteres = n_images * (part * long_med + (1 - part) * long_app)
    attendu = {}
    for ch in params.ALPHABET:
        attendu[ch] = caracteres * (part * f_med.get(ch, 0.0)
                                    + (1 - part) * f_app.get(ch, 0.0))

    absents = [c for c in params.ALPHABET if attendu[c] < 1]
    rares = [c for c in params.ALPHABET if 1 <= attendu[c] < seuil]
    print(f"couverture attendue : "
          f"{len(params.ALPHABET) - len(absents)}/{len(params.ALPHABET)} "
          f"caracteres, {len(rares)} sous {seuil} occurrences")
    if absents:
        print(f"  JAMAIS generes : {''.join(absents)}")
    if rares:
        print(f"  rares          : {''.join(rares)}")
    if absents:
        print("  -> ces caracteres seront illisibles pour le modele entraine. "
              "Baisse --part-medicale ou complete le lexique d'appoint.")


def _png(a):
    return Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8), mode="L")


def planche(images, mots, chemin, hauteur):
    """Planche de controle : un mot par ligne, avec de l'air entre eux."""
    large = max(i.shape[1] for i in images)
    lignes = []
    for img in images:
        pad = np.ones((hauteur, large - img.shape[1]), dtype=np.float32)
        lignes.append(np.concatenate([img, pad], 1))
        lignes.append(np.ones((8, large), dtype=np.float32))
    _png(np.concatenate(lignes, 0)).save(chemin)
    print(f"  planche -> {chemin}  ({', '.join(mots)})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--depot", default=".")
    ap.add_argument("--checkpoint", default="File/vn_ckpt.pth")
    ap.add_argument("--pickle", default="File/VN.pickle")
    ap.add_argument("--mots", default="File/vn_medical_words.txt")
    ap.add_argument("--appoint", default="File/vn_words.txt",
                    help="Lexique generique, pour la couverture des lettres "
                         "que le medical n'emploie jamais.")
    ap.add_argument("--part-majuscules", type=float, default=0.25,
                    help="Part des mots ecrits en CAPITALES. Sans elle, les "
                         "majuscules accentuees (Ế, Ộ, Ớ...) ne sont jamais "
                         "generees : aucun lexique n'en contient.")
    ap.add_argument("--part-medicale", type=float, default=0.6,
                    help="Part des mots tires du lexique medical. 1.0 = que "
                         "du medical, au prix de 88 caracteres jamais ecrits.")
    ap.add_argument("--sortie", default="../datasets/manuscrit_synth_vn")
    ap.add_argument("--n", type=int, default=25000, help="Nombre d'images.")
    ap.add_argument("--scripteurs", type=int, default=0,
                    help="0 = tous les scripteurs d'entrainement.")
    ap.add_argument("--lot", type=int, default=32, help="Mots par appel.")
    ap.add_argument("--graine", type=int, default=12345)
    ap.add_argument("--apercu", action="store_true",
                    help="Ne genere que la planche de controle diacritiques.")
    args = ap.parse_args()

    depot = Path(args.depot).resolve()
    modele, params, torch = charger_modele(depot, depot / args.checkpoint)
    print(f"modele charge sur {params.DEVICE}, alphabet {params.VOCAB_SIZE} car.")

    sortie = Path(args.sortie)
    sortie.mkdir(parents=True, exist_ok=True)

    if args.apercu:
        wid, idx, img = next(iter(styles(depot / args.pickle, 1, args.graine)))
        style = preparer_style(img, params, torch)
        images = generer(modele, params, torch, style, MOTS_CONTROLE)
        planche(images, MOTS_CONTROLE, sortie / "apercu_diacritiques.png",
                params.IMG_HEIGHT)
        print("\nREGARDE cette planche avant d'aller plus loin : position des "
              "tons sur ỗ / ậ / ư, et « đ » qui doit avoir sa barre.")
        return

    def lire(nom):
        chemin = depot / nom
        if not chemin.exists():
            raise SystemExit(f"{chemin} introuvable.")
        return [l.strip() for l in
                chemin.read_text(encoding="utf-8").splitlines() if l.strip()]

    medical = lire(args.mots)
    appoint = lire(args.appoint) if args.part_medicale < 1.0 else []
    lexique = medical + appoint
    hors = [m for m in lexique if not set(m) <= set(params.ALPHABET)]
    if hors:
        raise SystemExit(f"{len(hors)} mot(s) hors alphabet : {hors[:5]}")
    print(f"{len(medical)} mots medicaux + {len(appoint)} d'appoint")

    couverture(medical, appoint, args.part_medicale, args.n, params,
               args.part_majuscules)

    alea = random.Random(args.graine)
    refs = list(styles(depot / args.pickle, args.scripteurs, args.graine))
    print(f"{len(refs)} scripteurs de reference")

    (sortie / "images").mkdir(exist_ok=True)
    labels, faits = {}, 0
    for wid, idx, img in refs:
        if faits >= args.n:
            break
        style = preparer_style(img, params, torch)
        # On repartit la cible equitablement entre scripteurs : un jeu ou un
        # seul style domine entrainerait le CRNN sur une ecriture, pas sur
        # l'ecriture manuscrite.
        part = min(args.n - faits, -(-args.n // len(refs)))
        for debut in range(0, part, args.lot):
            # Le tirage respecte --part-medicale a chaque mot : le jeu reste
            # melange d'un bout a l'autre, plutot que medical au debut et
            # generique a la fin -- ce qui biaiserait toute coupe du jeu.
            mots = []
            for _ in range(min(args.lot, part - debut)):
                source = (medical if alea.random() < args.part_medicale
                          or not appoint else appoint)
                mot = alea.choice(source)
                mots.append(mot.upper()
                            if alea.random() < args.part_majuscules else mot)
            for m, im in zip(mots, generer(modele, params, torch, style, mots)):
                faits += 1
                nom = f"{wid}_{faits:06d}.png"
                _png(im).save(sortie / "images" / nom)
                labels[nom] = m
        print(f"  {wid}  {faits}/{args.n}")

    (sortie / "labels.json").write_text(
        json.dumps(labels, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{len(labels)} images -> {sortie}")


if __name__ == "__main__":
    main()
