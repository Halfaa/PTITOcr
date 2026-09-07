"""
Recenser TOUS les jeux d'images du projet dans un seul manifeste.

Pourquoi ce script existe. Neuf mois de travail ont produit une quinzaine de
jeux, éparpillés sur trois arborescences : les rendus Blender
(`../doc3D-renderer/img/`), le manuscrit synthétique (`handwriting/` et
`handwriting_en/`), et l'échantillon TabRecSet (`data/`). La vérité terrain,
elle, vit encore ailleurs (`../synthetic_invoice_generator/`). Savoir « quel
jeu contient quoi, et contre quoi le noter » supposait jusqu'ici de lire
quatre README et d'ouvrir trois dossiers.

Le manifeste répond à ça en une fois : une entrée par image, avec sa
famille, son jeu, sa résolution, sa langue, et le chemin de la vérité
terrain qui lui correspond. C'est un INDEX, pas une copie -- les images ne
sont pas dupliquées, ce qui éviterait 400 Mo de redondance dans un dépôt qui
sait déjà les régénérer.

    python dataset/build_manifest.py                 # écrit dataset/manifest.json
    python dataset/build_manifest.py --resume        # juste le résumé, sans écrire
    python dataset/build_manifest.py --export corpus # matérialise une copie unifiée
    python dataset/build_manifest.py --export corpus --zip

`--export` sert quand il faut vraiment un dossier unique à envoyer ou à
téléverser (Kaggle, Hugging Face) : il copie les images ET la vérité terrain
sous `<export>/<famille>/<jeu>/`, en gardant les noms d'origine pour que les
runs déjà produits restent appariables par `stem`.

Un jeu absent n'est pas une erreur : les rendus Blender ne sont pas dans le
dépôt (ils se régénèrent), donc le manifeste se construit avec ce qui est
présent et signale explicitement ce qui manque, plutôt que d'échouer.
"""

import argparse
import json
import shutil
from datetime import date
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
DOC3D = RACINE.parent / "doc3D-renderer"
GEN = RACINE.parent / "synthetic_invoice_generator" / "hospital_pharmacy"

try:
    from PIL import Image
except ImportError:
    raise SystemExit("Il faut Pillow :\n    pip install pillow")


# --------------------------------------------------------------------------
# Les jeux, décrits UNE fois. Tout le reste du script en découle.
#
# `gt` désigne le dossier de vérité terrain au niveau FACTURE (un JSON par
# facture, plusieurs pages par facture) ; `pdf` sert au découpage en factures.
# Les deux sont distincts et c'est délibéré -- voir l'en-tête de
# scripts/eval_all.py.

FACTURES_MULTIPAGE = {
    "gt": GEN / "ground_truth_labels_multipage",
    "pdf": GEN / "invoices_multipage_xelatex.pdf",
}
FACTURES_VARIANTS = {
    "gt": GEN / "ground_truth_labels_variants",
    "pdf": GEN / "invoices_variants.pdf",
}
FACTURES_SIMPLES = {
    "gt": GEN / "ground_truth_labels",
    "pdf": None,
}

JEUX = {
    # -- Factures, rendus Blender ------------------------------------------
    "multipage_test": {
        "famille": "facture", "langue": "vi",
        "titre": "8 factures, 17 pages déformées, un seul gabarit",
        "role": "jeu de référence historique, celui de tous les premiers chiffres",
        "dossier": DOC3D / "img" / "multipage_test",
        "verite": FACTURES_MULTIPAGE,
        "generateur": "doc3D-renderer/render_mesh_multipage.py",
    },
    "multipage_flat_1800": {
        "famille": "facture", "langue": "vi",
        "titre": "les mêmes 17 pages, à plat, 1800 px",
        "role": "témoin haute résolution : le plafond de lecture sans déformation",
        "dossier": DOC3D / "img" / "multipage_flat_1800",
        "verite": FACTURES_MULTIPAGE,
        "generateur": "scripts/rendre_haute_resolution.py",
    },
    "multipage_test_noillum": {
        "famille": "facture", "langue": "vi",
        "titre": "17 pages rendues sans éclairage",
        "role": "isole l'effet de l'éclairage de celui de la déformation",
        "dossier": DOC3D / "img" / "multipage_test_noillum",
        "verite": FACTURES_MULTIPAGE,
        "generateur": "doc3D-renderer, passe sans HDR",
    },
    "multipage_test_unwarped": {
        "famille": "facture", "langue": "vi",
        "titre": "17 pages remises à plat par la vérité terrain UV",
        "role": "oracle de dewarping : le plafond atteignable si le dépliage était parfait",
        "dossier": DOC3D / "img" / "multipage_test_unwarped",
        "verite": FACTURES_MULTIPAGE,
        "generateur": "scripts/dewarp_oracle.py",
    },
    "multipage_test_preprocessed_v3": {
        "famille": "facture", "langue": "vi",
        "titre": "17 pages passées par le prétraitement (version courante)",
        "role": "branche « prétraitée » du comparatif avec/sans",
        "dossier": DOC3D / "img" / "multipage_test_preprocessed_v3",
        "verite": FACTURES_MULTIPAGE,
        "generateur": "src/preprocess.py",
    },
    "variants_flat": {
        "famille": "facture", "langue": "vi",
        "titre": "12 factures, 25 pages à plat, 6 gabarits",
        "role": "jeu diversifié : mesure la dépendance au gabarit",
        "dossier": DOC3D / "img" / "variants_flat",
        "verite": FACTURES_VARIANTS,
        "generateur": "synthetic_invoice_generator/create_latex_variants.py",
    },
    "variants_warped": {
        "famille": "facture", "langue": "vi",
        "titre": "les mêmes 12 factures, déformées",
        "role": "le couple à plat / déformé isole l'effet de la déformation seule",
        "dossier": DOC3D / "img" / "variants_warped",
        "verite": FACTURES_VARIANTS,
        "generateur": "doc3D-renderer/render_variants.ps1",
    },
    "variants_encombre": {
        "famille": "facture", "langue": "vi",
        "titre": "les mêmes pages, sur fond encombré (3 à 6 feuilles parasites)",
        "role": "casse la localisation de feuille -- voir docs/fonds_encombres.md",
        "dossier": DOC3D / "img" / "variants_encombre",
        "verite": FACTURES_VARIANTS,
        "generateur": "doc3D-renderer/render_variants.ps1 -Parasites -1",
    },
    "variants_encombre_recadre_contenu": {
        "famille": "facture", "langue": "vi",
        "titre": "jeu encombré recadré sur la plus grande boîte table (×1,2)",
        "role": "piste close : isole le tableau mais coupe l'en-tête (§18 fonds_encombres)",
        "dossier": DOC3D / "img" / "variants_encombre_recadre_contenu",
        "verite": FACTURES_VARIANTS,
        "generateur": "scripts/recadrage_par_contenu_extraire.py",
    },
    "batch1": {
        "famille": "facture", "langue": "vi",
        "titre": "100 factures d'une page, premier lot",
        "role": "jeu de volume des tout premiers essais, une page par facture",
        "dossier": DOC3D / "img" / "batch1",
        "verite": FACTURES_SIMPLES,
        "generateur": "doc3D-renderer, lot initial",
    },
    # -- Manuscrit synthétique ---------------------------------------------
    "handwriting_vi": {
        "famille": "manuscrit", "langue": "vi",
        "titre": "30 fiches PHCN page 9, manuscrites (Playwrite VN)",
        "role": "banc HTR vietnamien -- voir docs/resultats_handwriting.md",
        "dossier": RACINE / "handwriting" / "generated",
        "verite": "par_specimen",
        "generateur": "handwriting/generate.py",
    },
    "handwriting_en": {
        "famille": "manuscrit", "langue": "en",
        "titre": "30 dossiers de santé (pages 1-2), manuscrits, 7 polices",
        "role": "banc HTR anglais, avec variation de police mesurable",
        "dossier": RACINE / "handwriting_en" / "generated",
        "verite": "par_specimen",
        "generateur": "handwriting_en/generate_en.py",
    },
    # -- Données réelles ---------------------------------------------------
    "tabrecset_sample": {
        "famille": "reel", "langue": "zh/en",
        "titre": "échantillon TabRecSet (10 images annotées)",
        "role": "seul jeu de photos RÉELLES du projet, sert de garde-fou",
        "dossier": RACINE / "data" / "tabrecset_sample" / "images",
        "verite": "tabrecset",
        "generateur": "jeu public, non généré",
    },
}

# L'étude de dégradation : un jeu, 24 sous-lots de 8 pages, tirés de
# variants_warped. Traité à part parce que sa structure est différente --
# chaque lot est un palier d'une courbe, pas un jeu autonome.
DEGRADATION = {
    "famille": "facture", "langue": "vi",
    "titre": "24 paliers de dégradation × 8 pages (flou, bruit, jpeg, exposition, résolution)",
    "role": "courbe de robustesse à la qualité de photo -- docs/degradation.md",
    "dossier": DOC3D / "img" / "degradation",
    "verite": FACTURES_VARIANTS,
    "generateur": "scripts/degrader.py --jeu variants_warped",
}


# --------------------------------------------------------------------------

def _chemin_relatif(p: Path) -> str:
    """Chemin lisible depuis la racine du projet, séparateurs POSIX."""
    try:
        return p.resolve().relative_to(RACINE.parent).as_posix()
    except ValueError:
        return p.resolve().as_posix()


def _taille(p: Path):
    try:
        with Image.open(p) as im:
            return list(im.size)
    except Exception:
        return None


def _verite_pour(cle_jeu, spec, image: Path):
    """Où trouver la vérité terrain de CETTE image.

    Trois régimes distincts, et les confondre est exactement l'erreur que
    eval_all.py existe pour empêcher : les factures ont une vérité par
    FACTURE (plusieurs pages), le manuscrit une vérité par PAGE, TabRecSet
    ses propres annotations.
    """
    if spec == "par_specimen":
        candidat = image.parent / f"{image.stem}_verite.json"
        return {"type": "par_page", "chemin": _chemin_relatif(candidat)} if candidat.exists() else None
    if spec == "tabrecset":
        base = image.parent.parent
        return {"type": "tabrecset",
                "td": _chemin_relatif(base / "td_annotation"),
                "tsr_tcr": _chemin_relatif(base / "tsr_tcr_annotation")}
    if isinstance(spec, dict):
        d = {"type": "par_facture", "gt_dir": _chemin_relatif(spec["gt"])}
        if spec.get("pdf"):
            d["pdf_decoupage"] = _chemin_relatif(spec["pdf"])
        return d
    return None


def _images_de(dossier: Path):
    """Les PNG d'un jeu, à plat ou dans un sous-dossier par specimen."""
    if not dossier.is_dir():
        return []
    plat = sorted(dossier.glob("*.png")) + sorted(dossier.glob("*.jpg"))
    if plat:
        return plat
    return sorted(dossier.glob("*/*.png")) + sorted(dossier.glob("*/*.jpg"))


def _masque_uv(cle_jeu: str) -> bool:
    return (DOC3D / "uv" / cle_jeu).is_dir()


def construire():
    jeux_sortie, images_sortie, manquants = {}, [], []

    for cle, spec in JEUX.items():
        images = _images_de(spec["dossier"])
        if not images:
            manquants.append(cle)
            continue
        jeux_sortie[cle] = {
            "famille": spec["famille"], "langue": spec["langue"],
            "titre": spec["titre"], "role": spec["role"],
            "dossier": _chemin_relatif(spec["dossier"]),
            "generateur": spec["generateur"],
            "n_images": len(images),
            "masque_uv": _masque_uv(cle),
        }
        for img in images:
            images_sortie.append({
                "id": f"{cle}/{img.stem}",
                "jeu": cle, "famille": spec["famille"], "langue": spec["langue"],
                "chemin": _chemin_relatif(img),
                "taille": _taille(img),
                "verite": _verite_pour(cle, spec["verite"], img),
            })

    # Dégradation : un enregistrement par palier, mais un seul « jeu ».
    lots = sorted(p for p in DEGRADATION["dossier"].glob("*") if p.is_dir()) \
        if DEGRADATION["dossier"].is_dir() else []
    if lots:
        n_total = 0
        for lot in lots:
            for img in sorted(lot.glob("*.png")):
                n_total += 1
                images_sortie.append({
                    "id": f"degradation/{lot.name}/{img.stem}",
                    "jeu": "degradation", "palier": lot.name,
                    "famille": DEGRADATION["famille"], "langue": DEGRADATION["langue"],
                    "chemin": _chemin_relatif(img),
                    "taille": _taille(img),
                    "verite": _verite_pour("degradation", DEGRADATION["verite"], img),
                })
        jeux_sortie["degradation"] = {
            "famille": DEGRADATION["famille"], "langue": DEGRADATION["langue"],
            "titre": DEGRADATION["titre"], "role": DEGRADATION["role"],
            "dossier": _chemin_relatif(DEGRADATION["dossier"]),
            "generateur": DEGRADATION["generateur"],
            "n_images": n_total, "n_paliers": len(lots),
            "paliers": [p.name for p in lots],
            "masque_uv": False,
        }
    else:
        manquants.append("degradation")

    return {
        "genere_le": date.today().isoformat(),
        "racine": "les chemins sont relatifs au dossier PARENT de MedicalRecord "
                  "(il contient MedicalRecord/, doc3D-renderer/ et "
                  "synthetic_invoice_generator/)",
        "n_jeux": len(jeux_sortie),
        "n_images": len(images_sortie),
        "jeux_absents": manquants,
        "jeux": jeux_sortie,
        "images": images_sortie,
    }


def exporter(manifeste, destination: Path):
    """Matérialise une copie unifiée : <dest>/<famille>/<jeu>/<image>."""
    destination.mkdir(parents=True, exist_ok=True)
    n = 0
    for entree in manifeste["images"]:
        source = RACINE.parent / entree["chemin"]
        if not source.exists():
            continue
        sous = destination / entree["famille"] / entree["jeu"]
        if entree.get("palier"):
            sous = sous / entree["palier"]
        sous.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, sous / source.name)
        # La vérité par page voyage AVEC son image : séparées, elles se
        # désapparient au premier déplacement de dossier.
        v = entree.get("verite") or {}
        if v.get("type") == "par_page":
            src_v = RACINE.parent / v["chemin"]
            if src_v.exists():
                shutil.copy2(src_v, sous / src_v.name)
        n += 1

    # Les vérités par facture sont partagées par tout un jeu : une copie par
    # dossier de vérité suffit, à la racine de l'export.
    for spec in (FACTURES_MULTIPAGE, FACTURES_VARIANTS, FACTURES_SIMPLES):
        if spec["gt"].is_dir():
            cible = destination / "verite_terrain" / spec["gt"].name
            if not cible.exists():
                shutil.copytree(spec["gt"], cible)
        if spec.get("pdf") and spec["pdf"].exists():
            (destination / "verite_terrain").mkdir(parents=True, exist_ok=True)
            shutil.copy2(spec["pdf"], destination / "verite_terrain" / spec["pdf"].name)

    (destination / "manifest.json").write_text(
        json.dumps(manifeste, ensure_ascii=False, indent=1), encoding="utf-8")
    return n


def resumer(m):
    print(f"{m['n_jeux']} jeux, {m['n_images']} images\n")
    print(f"{'jeu':<36}{'famille':<11}{'langue':<8}{'images':>7}  {'UV':<4}titre")
    print("-" * 110)
    for cle, j in sorted(m["jeux"].items(), key=lambda kv: (kv[1]["famille"], kv[0])):
        uv = "oui" if j["masque_uv"] else "--"
        print(f"{cle:<36}{j['famille']:<11}{j['langue']:<8}{j['n_images']:>7}  {uv:<4}{j['titre'][:52]}")
    if m["jeux_absents"]:
        print(f"\nAbsents du disque (régénérables) : {', '.join(m['jeux_absents'])}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sortie", default=str(Path(__file__).resolve().parent / "manifest.json"))
    p.add_argument("--resume", action="store_true",
                   help="Afficher le résumé sans écrire le manifeste.")
    p.add_argument("--export", default=None,
                   help="Matérialiser une copie unifiée dans ce dossier.")
    p.add_argument("--zip", action="store_true",
                   help="Zipper l'export (implique --export).")
    args = p.parse_args()

    manifeste = construire()
    resumer(manifeste)

    if not args.resume:
        Path(args.sortie).write_text(
            json.dumps(manifeste, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n-> {args.sortie}")

    if args.export or args.zip:
        dest = Path(args.export or (Path(__file__).resolve().parent / "corpus"))
        n = exporter(manifeste, dest)
        print(f"-> {n} images copiées dans {dest}")
        if args.zip:
            archive = shutil.make_archive(str(dest), "zip", dest.parent, dest.name)
            print(f"-> {archive} ({Path(archive).stat().st_size / 1e6:.0f} Mo)")


if __name__ == "__main__":
    main()
