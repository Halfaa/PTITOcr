"""
Index EVERY image set in the project in a single manifest.

Why this script exists. Nine months of work produced some fifteen sets,
scattered across three trees: the Blender renders (`../doc3D-renderer/img/`),
the synthetic handwriting (`handwriting/` and `handwriting_en/`), and the
TabRecSet sample (`data/`). The ground truth lives somewhere else again
(`../synthetic_invoice_generator/`). Answering "which set holds what, and
what do I score it against" meant reading four READMEs and opening three
folders.

The manifest answers that once: one entry per image, with its family, its
set, its resolution, its language, and the path to the matching ground
truth. It is an INDEX, not a copy -- the images are not duplicated, which
would add 400 MB of redundancy to a repository that already knows how to
regenerate them.

    python dataset/build_manifest.py                 # writes dataset/manifest.json
    python dataset/build_manifest.py --resume        # summary only, writes nothing
    python dataset/build_manifest.py --export corpus # materialise a unified copy
    python dataset/build_manifest.py --export corpus --zip

`--export` is for when a single folder really is needed, to send or to
upload (Kaggle, Hugging Face): it copies the images AND the ground truth
under `<export>/<family>/<set>/`, keeping the original names so that runs
already produced stay matchable by `stem`.

A missing set is not an error: the Blender renders are not in the repository
(they are regenerated), so the manifest is built from whatever is present
and reports explicitly what is missing rather than failing.

Note on naming: identifiers, dictionary keys and CLI flags stay in French
throughout the project. They are the schema and the interface -- runs on
disk, notebooks and documented commands all depend on them, so only the
prose was translated.
"""

import argparse
import json
import os
import shutil
from datetime import date
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent

# The two NEIGHBOURING repositories that eleven sets out of fourteen depend on.
#
# This repository (PTITOcr) only covers MedicalRecord/. The Blender renders
# and the invoice ground truth live in two other repositories, and -- this is
# the point that matters -- NEITHER ONE versions its images or its JSON: both
# hold only the code that produces them. A fresh clone of PTITOcr can
# therefore rebuild just the three sets whose source is here
# (handwriting_vi, handwriting_en, tabrecset_sample).
#
# The paths are overridable through environment variables, for a tree that
# differs from ours (the two repositories elsewhere, a separate disk for the
# renders):
#     $env:DOC3D_ROOT = "D:/renders"
#     $env:INVOICE_GEN_ROOT = "D:/invoices"
DEPOTS_VOISINS = {
    "doc3D-renderer": "https://github.com/anhdungdo0906/doc3D-renderer.git",
    "synthetic_invoice_generator":
        "https://github.com/anhdungdo0906/synthetic_invoice_generator.git",
}

DOC3D = Path(os.environ.get("DOC3D_ROOT") or RACINE.parent / "doc3D-renderer")
GEN = Path(os.environ.get("INVOICE_GEN_ROOT")
           or RACINE.parent / "synthetic_invoice_generator") / "hospital_pharmacy"

try:
    from PIL import Image
except ImportError:
    raise SystemExit("Pillow is required:\n    pip install pillow")


# --------------------------------------------------------------------------
# The sets, described ONCE. Everything else in this script follows from it.
#
# `gt` points at the ground truth at INVOICE level (one JSON per invoice,
# several pages per invoice); `pdf` drives the page-to-invoice split. The two
# are distinct, deliberately -- see the header of scripts/eval_all.py.

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
    # -- Invoices, Blender renders -----------------------------------------
    "multipage_test": {
        "famille": "facture", "langue": "vi",
        "titre": "8 invoices, 17 warped pages, a single template",
        "role": "historical reference set, the source of all the early figures",
        "dossier": DOC3D / "img" / "multipage_test",
        "verite": FACTURES_MULTIPAGE,
        "generateur": "doc3D-renderer/render_mesh_multipage.py",
    },
    "multipage_flat_1800": {
        "famille": "facture", "langue": "vi",
        "titre": "the same 17 pages, flat, 1800 px",
        "role": "high-resolution control: the reading ceiling without warping",
        "dossier": DOC3D / "img" / "multipage_flat_1800",
        "verite": FACTURES_MULTIPAGE,
        "generateur": "scripts/rendre_haute_resolution.py",
    },
    "multipage_test_noillum": {
        "famille": "facture", "langue": "vi",
        "titre": "17 pages rendered without lighting",
        "role": "separates the effect of lighting from the effect of warping",
        "dossier": DOC3D / "img" / "multipage_test_noillum",
        "verite": FACTURES_MULTIPAGE,
        "generateur": "doc3D-renderer, pass without HDR",
    },
    "multipage_test_unwarped": {
        "famille": "facture", "langue": "vi",
        "titre": "17 pages flattened using the UV ground truth",
        "role": "dewarping oracle: the ceiling if unwarping were perfect",
        "dossier": DOC3D / "img" / "multipage_test_unwarped",
        "verite": FACTURES_MULTIPAGE,
        "generateur": "scripts/dewarp_oracle.py",
    },
    "multipage_test_preprocessed_v3": {
        "famille": "facture", "langue": "vi",
        "titre": "17 pages through the pre-processing module (current version)",
        "role": "the 'pre-processed' branch of the with/without comparison",
        "dossier": DOC3D / "img" / "multipage_test_preprocessed_v3",
        "verite": FACTURES_MULTIPAGE,
        "generateur": "src/preprocess.py",
    },
    "variants_flat": {
        "famille": "facture", "langue": "vi",
        "titre": "12 invoices, 25 flat pages, 6 templates",
        "role": "diversified set: measures how much the chain depends on the template",
        "dossier": DOC3D / "img" / "variants_flat",
        "verite": FACTURES_VARIANTS,
        "generateur": "synthetic_invoice_generator/create_latex_variants.py",
    },
    "variants_warped": {
        "famille": "facture", "langue": "vi",
        "titre": "the same 12 invoices, warped",
        "role": "the flat/warped pair isolates the effect of warping alone",
        "dossier": DOC3D / "img" / "variants_warped",
        "verite": FACTURES_VARIANTS,
        "generateur": "doc3D-renderer/render_variants.ps1",
    },
    "variants_encombre": {
        "famille": "facture", "langue": "vi",
        "titre": "the same pages, on a cluttered background (3 to 6 distractor sheets)",
        "role": "breaks sheet localisation -- see docs/fonds_encombres.md",
        "dossier": DOC3D / "img" / "variants_encombre",
        "verite": FACTURES_VARIANTS,
        "generateur": "doc3D-renderer/render_variants.ps1 -Parasites -1",
    },
    "variants_encombre_recadre_contenu": {
        "famille": "facture", "langue": "vi",
        "titre": "cluttered set cropped to the largest table box (x1.2)",
        "role": "closed avenue: isolates the table but cuts the header (fonds_encombres section 18)",
        "dossier": DOC3D / "img" / "variants_encombre_recadre_contenu",
        "verite": FACTURES_VARIANTS,
        "generateur": "scripts/recadrage_par_contenu_extraire.py",
    },
    "batch1": {
        "famille": "facture", "langue": "vi",
        "titre": "100 single-page invoices, first batch",
        "role": "volume set from the earliest trials, one page per invoice",
        "dossier": DOC3D / "img" / "batch1",
        "verite": FACTURES_SIMPLES,
        "generateur": "doc3D-renderer, initial batch",
    },
    # -- Synthetic handwriting ---------------------------------------------
    "handwriting_vi": {
        "famille": "manuscrit", "langue": "vi",
        "titre": "30 PHCN page-9 forms, handwritten (Playwrite VN)",
        "role": "Vietnamese HTR benchmark -- see docs/resultats_handwriting.md",
        "dossier": RACINE / "handwriting" / "generated",
        "verite": "par_specimen",
        "generateur": "handwriting/generate.py",
    },
    "handwriting_en": {
        "famille": "manuscrit", "langue": "en",
        "titre": "30 health records (pages 1-2), handwritten, 7 fonts",
        "role": "English HTR benchmark, with measurable font variation",
        "dossier": RACINE / "handwriting_en" / "generated",
        "verite": "par_specimen",
        "generateur": "handwriting_en/generate_en.py",
    },
    # -- Real data ---------------------------------------------------------
    "tabrecset_sample": {
        "famille": "reel", "langue": "zh/en",
        "titre": "TabRecSet sample (10 annotated images)",
        "role": "the project's only REAL photographs, used as a sanity check",
        "dossier": RACINE / "data" / "tabrecset_sample" / "images",
        "verite": "tabrecset",
        "generateur": "public dataset, not generated",
    },
}

# The degradation study: one set, 24 sub-batches of 8 pages, drawn from
# variants_warped. Handled separately because its structure differs -- each
# batch is one step of a curve, not a set in its own right.
DEGRADATION = {
    "famille": "facture", "langue": "vi",
    "titre": "24 degradation steps x 8 pages (blur, noise, jpeg, exposure, resolution)",
    "role": "robustness curve against photo quality -- docs/degradation.md",
    "dossier": DOC3D / "img" / "degradation",
    "verite": FACTURES_VARIANTS,
    "generateur": "scripts/degrader.py --jeu variants_warped",
}


# --------------------------------------------------------------------------

def _chemin_relatif(p: Path) -> str:
    """Readable path from the project root, POSIX separators."""
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
    """Where to find the ground truth for THIS image.

    Three distinct regimes, and confusing them is exactly the mistake
    eval_all.py exists to prevent: invoices have one truth per INVOICE
    (several pages), handwriting one truth per PAGE, TabRecSet its own
    annotations.
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
    """A set's PNGs, either flat or inside one sub-folder per specimen."""
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

    # Degradation: one record per step, but a single "set".
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
        "racine": "paths are relative to the PARENT folder of MedicalRecord "
                  "(it contains MedicalRecord/, doc3D-renderer/ and "
                  "synthetic_invoice_generator/)",
        # The manifest indexes a LOCAL corpus: since the images are versioned
        # in none of the three repositories, these paths only resolve on a
        # machine where the corpus was generated. To hand the corpus to
        # someone, use `--export corpus --zip`, not this file.
        "prerequis": {
            "note": "11 of the 14 sets come from two neighbouring repositories, "
                    "which version NEITHER their images NOR the ground truth: "
                    "only the code is there. Rebuilding those sets means "
                    "replaying the generation (LaTeX, then Blender).",
            "depots_voisins": DEPOTS_VOISINS,
            "arborescence_attendue": [
                "<parent>/MedicalRecord/   (this repository)",
                "<parent>/doc3D-renderer/",
                "<parent>/synthetic_invoice_generator/",
            ],
            "surcharge": ["DOC3D_ROOT", "INVOICE_GEN_ROOT"],
            "autonomes": ["handwriting_vi", "handwriting_en", "tabrecset_sample"],
        },
        "n_jeux": len(jeux_sortie),
        "n_images": len(images_sortie),
        "jeux_absents": manquants,
        "jeux": jeux_sortie,
        "images": images_sortie,
    }


def exporter(manifeste, destination: Path):
    """Materialise a unified copy: <dest>/<family>/<set>/<image>."""
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
        # Per-page truth travels WITH its image: kept apart, the two come
        # unpaired the first time a folder is moved.
        v = entree.get("verite") or {}
        if v.get("type") == "par_page":
            src_v = RACINE.parent / v["chemin"]
            if src_v.exists():
                shutil.copy2(src_v, sous / src_v.name)
        n += 1

    # Per-invoice truth is shared by a whole set: one copy per truth folder
    # is enough, at the root of the export.
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


def diagnostiquer_racines():
    """Say straight away what is missing, and how to fix it.

    Without this, a fresh clone of PTITOcr prints "3 sets, 70 images" and a
    list of eleven missing ones, with nothing explaining why -- when the
    cause is structural: the images are versioned in NONE of the three
    repositories, neither here nor in the two neighbours.
    """
    absents = [(nom, chemin) for nom, chemin in
               (("doc3D-renderer", DOC3D),
                ("synthetic_invoice_generator", GEN.parent))
               if not chemin.is_dir()]
    if not absents:
        return
    print("Neighbouring repository/repositories not found:")
    for nom, chemin in absents:
        print(f"  {nom:<30} expected at {chemin}")
    print("\nThe sets that depend on them will simply be absent from the manifest.")
    print("To fetch them, next to MedicalRecord:")
    for nom, url in DEPOTS_VOISINS.items():
        if any(nom == a for a, _ in absents):
            print(f"    git clone {url}")
    print("\nCareful: those repositories hold only the generation CODE, not")
    print("the images nor the ground truth. Cloning them is not enough --")
    print("the generation has to be replayed (LaTeX, then Blender). See")
    print("dataset/README.md, section 'This repository is not enough'.")
    print("If your folders live elsewhere: $env:DOC3D_ROOT / $env:INVOICE_GEN_ROOT\n")


def resumer(m):
    print(f"{m['n_jeux']} sets, {m['n_images']} images\n")
    print(f"{'set':<36}{'family':<11}{'lang':<8}{'images':>7}  {'UV':<4}title")
    print("-" * 110)
    for cle, j in sorted(m["jeux"].items(), key=lambda kv: (kv[1]["famille"], kv[0])):
        uv = "yes" if j["masque_uv"] else "--"
        print(f"{cle:<36}{j['famille']:<11}{j['langue']:<8}{j['n_images']:>7}  {uv:<4}{j['titre'][:52]}")
    if m["jeux_absents"]:
        print(f"\nMissing from disk (regenerable): {', '.join(m['jeux_absents'])}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sortie", default=str(Path(__file__).resolve().parent / "manifest.json"))
    p.add_argument("--resume", action="store_true",
                   help="Print the summary without writing the manifest.")
    p.add_argument("--export", default=None,
                   help="Materialise a unified copy in this folder.")
    p.add_argument("--zip", action="store_true",
                   help="Zip the export (implies --export).")
    args = p.parse_args()

    diagnostiquer_racines()
    manifeste = construire()
    resumer(manifeste)

    if not args.resume:
        Path(args.sortie).write_text(
            json.dumps(manifeste, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n-> {args.sortie}")

    if args.export or args.zip:
        dest = Path(args.export or (Path(__file__).resolve().parent / "corpus"))
        n = exporter(manifeste, dest)
        print(f"-> {n} images copied into {dest}")
        if args.zip:
            archive = shutil.make_archive(str(dest), "zip", dest.parent, dest.name)
            print(f"-> {archive} ({Path(archive).stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
