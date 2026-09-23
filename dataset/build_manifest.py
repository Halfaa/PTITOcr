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
import re
import shutil
import sys
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

# Names used in the EXPORT only. Upstream these folders are called
# `ground_truth_labels_variants` and so on -- long, and redundant once they
# live under `annotations/`. The source tree keeps its own names: renaming
# there would break the `--gt-dir` paths that the eval scripts, the docs and
# the Kaggle notebooks all pass around.
NOMS_ANNOTATIONS = {
    "ground_truth_labels": "invoices_single_page",
    "ground_truth_labels_multipage": "invoices_multipage",
    "ground_truth_labels_variants": "invoices_variants",
}

# Family names in the EXPORT. The archive is a standalone deliverable, read
# by people outside this project, so it carries no French: images all sit
# under `imgs/`, annotations under `annotations/`. Inside the repository the
# `famille` values stay as they are -- they are dictionary keys, and the
# whole codebase reads them.
NOMS_FAMILLES = {
    "facture": "invoice",
    "manuscrit": "handwriting",
    "reel": "real",
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
    "handwriting_gan": {
        "famille": "manuscrit", "langue": "vi",
        "titre": "20 PHCN forms filled with GAN-generated handwriting "
                 "(WriteViT, one real VNOnDB writer per document)",
        "role": "the final deliverable of the internship. Paired one-for-one "
                "with handwriting_vi: same text, same layout, only the "
                "handwriting differs, which is what makes the -37.7 point "
                "drop attributable to the handwriting itself -- see "
                "docs/notion_final_report.md section 7.6",
        "dossier": RACINE / "handwriting_gan" / "generated",
        "verite": "par_specimen",
        "generateur": "scripts/remplir_gan.py",
    },
    "handwriting_vi_warped": {
        "famille": "manuscrit", "langue": "vi",
        "titre": "handwritten VN forms projected on curved meshes (Blender)",
        "role": "3D deformation on handwriting -- docs/notion_deformation_3d.md; "
                "the first handwriting set to carry UV masks",
        "dossier": DOC3D / "img" / "handwriting_vi_warped",
        "verite": "par_specimen",
        "generateur": "scripts/preparer_textures_manuscrit.py + render_variants.ps1",
    },
    "handwriting_en_warped": {
        "famille": "manuscrit", "langue": "en",
        "titre": "same, English (not rendered yet)",
        "role": "English counterpart of the deformation set",
        "dossier": DOC3D / "img" / "handwriting_en_warped",
        "verite": "par_specimen",
        "generateur": "scripts/preparer_textures_manuscrit.py + render_variants.ps1",
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

# The degradation studies: one entry each, 24 sub-batches per set. Handled
# separately from JEUX because their structure differs -- each batch is one
# step of a curve, not a set in its own right.
#
# The handwriting ones apply the same five degradations to the handwritten
# specimens. Their blur steps are NOT the same numbers: blur is expressed in
# absolute pixels, and the specimens are 1654 px wide against 900 for the
# invoices, so degrader.py rescales them (see niveaux_pour()).
DEGRADATIONS = {
    "degradation": {
        "famille": "facture", "langue": "vi",
        "titre": "24 degradation steps x 8 pages (blur, noise, jpeg, exposure, resolution)",
        "role": "robustness curve against photo quality -- docs/degradation.md",
        "dossier": DOC3D / "img" / "degradation",
        "verite": FACTURES_VARIANTS,
        "generateur": "scripts/degrader.py --jeu variants_warped",
    },
    "handwriting_vi_degradation": {
        "famille": "manuscrit", "langue": "vi",
        "titre": "24 degradation steps x 3 handwritten VN specimens",
        "role": "does handwriting break earlier than printed invoices?",
        "dossier": DOC3D / "img" / "handwriting_vi_degradation",
        "verite": "par_specimen",
        "generateur": "scripts/degrader.py --images-dir handwriting/generated --n 3",
    },
    "handwriting_en_degradation": {
        "famille": "manuscrit", "langue": "en",
        "titre": "24 degradation steps x 3 handwritten EN specimens",
        "role": "same question in English, where the baseline is 99.1%",
        "dossier": DOC3D / "img" / "handwriting_en_degradation",
        "verite": "par_specimen",
        "generateur": "scripts/degrader.py --images-dir handwriting_en/generated --n 3",
    },
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
        if not candidat.exists():
            # Degraded specimens live in a step folder, away from their
            # truth: the degradation only touches pixels, so the truth of
            # the SOURCE specimen still describes them exactly. Looked up by
            # stem in the generator's output.
            for source in (RACINE / "handwriting" / "generated",
                           RACINE / "handwriting_en" / "generated"):
                repli = source / image.stem / f"{image.stem}_verite.json"
                if repli.exists():
                    candidat = repli
                    break
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

    # Degradation: one record per step, but a single "set" each.
    for cle, spec in DEGRADATIONS.items():
        lots = sorted(p for p in spec["dossier"].glob("*") if p.is_dir()) \
            if spec["dossier"].is_dir() else []
        if not lots:
            manquants.append(cle)
            continue
        n_total = 0
        for lot in lots:
            for img in sorted(lot.glob("*.png")):
                n_total += 1
                images_sortie.append({
                    "id": f"{cle}/{lot.name}/{img.stem}",
                    "jeu": cle, "palier": lot.name,
                    "famille": spec["famille"], "langue": spec["langue"],
                    "chemin": _chemin_relatif(img),
                    "taille": _taille(img),
                    "verite": _verite_pour(cle, spec["verite"], img),
                })
        jeux_sortie[cle] = {
            "famille": spec["famille"], "langue": spec["langue"],
            "titre": spec["titre"], "role": spec["role"],
            "dossier": _chemin_relatif(spec["dossier"]),
            "generateur": spec["generateur"],
            "n_images": n_total, "n_paliers": len(lots),
            "paliers": [p.name for p in lots],
            "masque_uv": False,
        }

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


def _numero_page(chemin: str):
    """Page number from a `page_12-concave_mesh_...png` style name."""
    m = re.match(r"page_(\d+)", Path(chemin).name)
    return int(m.group(1)) if m else None


def _groupes_factures(pdf: Path):
    """Page-to-invoice split, read from the source PDF.

    Imported lazily: it pulls in eval_teds, hence PyMuPDF, which the plain
    manifest has no need of. A sampling run without the PDF is not an error
    -- it falls back to taking whole sets, and says so.
    """
    try:
        sys.path.insert(0, str(RACINE / "src"))
        import eval_teds as E
        return E.page_groups_from_pdf(pdf)
    except Exception as e:
        print(f"  (page-to-invoice split unavailable: {type(e).__name__}) ")
        return None


def echantillonner(manifeste, n_factures=1, n_specimens=3, n_reel=3,
                   n_pages_degradation=1):
    """Cut the corpus down to a small but COMPLETE sample.

    The subtlety that dictates the whole function: invoice ground truth is
    per INVOICE, not per page. Sampling isolated pages would produce a
    dataset whose truth cannot be used -- an invoice JSON describes a table
    spread over two or three pages, and scoring it against one of them is
    meaningless. So we sample whole invoices, pages included.

    Degradation is sampled the other way round: the SAME page is kept at all
    24 steps, because what the set is for is the curve. Two pages at three
    steps would be more images and less information.

    Handwriting and TabRecSet carry per-page truth, so they can be sampled
    image by image without precaution.
    """
    par_jeu = {}
    for e in manifeste["images"]:
        par_jeu.setdefault(e["jeu"], []).append(e)

    retenus, resume = [], {}

    for jeu, entrees in par_jeu.items():
        famille = entrees[0]["famille"]

        if jeu in DEGRADATIONS:
            # One image kept across ALL steps, whatever the naming: invoice
            # steps are numbered pages, handwriting steps are specimens.
            noms = sorted({Path(e["chemin"]).name for e in entrees})
            gardes = set(noms[:n_pages_degradation])
            choisis = [e for e in entrees if Path(e["chemin"]).name in gardes]
            resume[jeu] = (f"{len(choisis)} images = {len(gardes)} page(s) "
                           f"x {len({e['palier'] for e in choisis})} steps")

        elif famille == "facture":
            verite = entrees[0].get("verite") or {}
            pdf = RACINE.parent / verite["pdf_decoupage"] if verite.get("pdf_decoupage") else None
            groupes = _groupes_factures(pdf) if pdf and pdf.exists() else None
            if groupes:
                voulues = set()
                for groupe in groupes[:n_factures]:
                    voulues.update(groupe)
                choisis = [e for e in entrees if _numero_page(e["chemin"]) in voulues]
                resume[jeu] = (f"{len(choisis)} images = {min(n_factures, len(groupes))} "
                               f"complete invoice(s)")
            elif all(_numero_page(e["chemin"]) is None for e in entrees):
                # No `page_N` numbering: this set is one invoice per image
                # (batch1, `invoice_1-...png`). Each image is therefore
                # self-contained, and taking the first N loses nothing.
                choisis = entrees[:n_factures]
                resume[jeu] = f"{len(choisis)} images = {len(choisis)} single-page invoice(s)"
            else:
                # Multi-page set whose split we cannot read: say so loudly
                # rather than ship a truncated invoice, which is exactly the
                # trap this function exists to avoid.
                choisis = entrees[:2]
                resume[jeu] = f"{len(choisis)} images (SPLIT UNAVAILABLE: partial truth)"

        elif famille == "manuscrit":
            choisis = entrees[:n_specimens]
            resume[jeu] = f"{len(choisis)} specimens"

        else:
            choisis = entrees[:n_reel]
            resume[jeu] = f"{len(choisis)} images"

        retenus.extend(choisis)

    echantillon = dict(manifeste)
    echantillon["images"] = retenus
    echantillon["n_images"] = len(retenus)
    echantillon["echantillon"] = {
        "note": "Sampled subset of the full corpus. Invoice sets are sampled "
                "by WHOLE INVOICE (ground truth is per invoice, not per "
                "page); the degradation set keeps the same page across every "
                "step, so the robustness curve stays readable.",
        "par_jeu": resume,
        "corpus_complet": {"n_images": manifeste["n_images"],
                           "n_jeux": manifeste["n_jeux"]},
    }
    # Set-level counts have to follow, otherwise the manifest announces 547
    # images next to a folder holding 60.
    jeux = {}
    for cle, j in manifeste["jeux"].items():
        n = len([e for e in retenus if e["jeu"] == cle])
        if n:
            jeux[cle] = {**j, "n_images": n}
    echantillon["jeux"] = jeux
    echantillon["n_jeux"] = len(jeux)
    return echantillon


def exporter(manifeste, destination: Path):
    """Materialise a unified copy: <dest>/<family>/<set>/<image>.

    The manifest is REWRITTEN on the way out, so that every path in it
    resolves inside the archive. Shipping the source paths would hand
    someone a manifest pointing at `doc3D-renderer/img/...` and
    `ground_truth_labels_variants/`, neither of which exists in what they
    just unzipped.
    """
    destination.mkdir(parents=True, exist_ok=True)
    groupes_par_gt, n = {}, 0
    images_exportees = []

    for entree in manifeste["images"]:
        source = RACINE.parent / entree["chemin"]
        if not source.exists():
            continue
        famille = NOMS_FAMILLES.get(entree["famille"], entree["famille"])
        sous = destination / "imgs" / famille / entree["jeu"]
        if entree.get("palier"):
            sous = sous / entree["palier"]
        sous.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, sous / source.name)

        sortie = dict(entree)
        sortie["famille"] = famille
        sortie["chemin"] = (sous.relative_to(destination) / source.name).as_posix()

        v = dict(entree.get("verite") or {})
        if v.get("type") == "par_page":
            # Per-page truth travels WITH its image: kept apart, the two come
            # unpaired the first time a folder is moved.
            src_v = RACINE.parent / v["chemin"]
            if src_v.exists():
                shutil.copy2(src_v, sous / src_v.name)
                v["chemin"] = (sous.relative_to(destination) / src_v.name).as_posix()
        elif v.get("type") == "par_facture":
            nom_amont = v["gt_dir"].split("/")[-1]
            v["gt_dir"] = f"annotations/{NOMS_ANNOTATIONS.get(nom_amont, nom_amont)}"
            if v.get("pdf_decoupage"):
                v["pdf_decoupage"] = f"annotations/{Path(v['pdf_decoupage']).name}"
            # Which invoice this page belongs to. Without it, going from
            # `invoice_1.json` to its images means re-opening the source PDF
            # -- which the archive's recipient does not necessarily have.
            pdf_amont = (entree.get("verite") or {}).get("pdf_decoupage")
            if pdf_amont:
                if pdf_amont not in groupes_par_gt:
                    groupes_par_gt[pdf_amont] = _groupes_factures(RACINE.parent / pdf_amont)
                groupes = groupes_par_gt[pdf_amont]
                page = _numero_page(entree["chemin"])
                if groupes and page is not None:
                    for k, groupe in enumerate(groupes, start=1):
                        if page in groupe:
                            v["facture"] = f"invoice_{k}.json"
                            sortie["page"] = page
                            break
        elif v.get("type") == "tabrecset":
            v["td"] = f"imgs/real/{entree['jeu']}/td_annotation"
            v["tsr_tcr"] = f"imgs/real/{entree['jeu']}/tsr_tcr_annotation"
        sortie["verite"] = v
        images_exportees.append(sortie)
        n += 1

    # TabRecSet keeps its own annotation folders, next to its images.
    for jeu in {e["jeu"] for e in manifeste["images"] if e["famille"] == "reel"}:
        base = RACINE / "data" / jeu
        for nom in ("td_annotation", "tsr_tcr_annotation"):
            cible = destination / "imgs" / "real" / jeu / nom
            if (base / nom).is_dir() and not cible.exists():
                shutil.copytree(base / nom, cible)

    manifeste = {**manifeste, "images": images_exportees}
    manifeste["racine"] = "paths are relative to the root of this archive"

    # Per-invoice truth is shared by a whole set: one copy per truth folder
    # is enough, at the root of the export.
    #
    # Folder names are rewritten on the way out. Upstream they are called
    # `ground_truth_labels_variants` and friends, which is both a mouthful
    # and redundant once they sit under `annotations/`. `annotations/` is
    # also the name public datasets use (COCO and the rest), so anyone
    # opening the archive already knows what is inside.
    # Seulement si l'export contient vraiment des pages de facture. Un
    # paquet manuscrit n'a que faire de la verite terrain des factures, et
    # la joindre ferait douter de ce qu'on envoie.
    annotations = destination / "annotations"
    specs = ((FACTURES_MULTIPAGE, FACTURES_VARIANTS, FACTURES_SIMPLES)
             if any((e.get("verite") or {}).get("type") == "par_facture"
                    for e in images_exportees) else ())
    for spec in specs:
        if spec["gt"].is_dir():
            cible = annotations / NOMS_ANNOTATIONS.get(spec["gt"].name, spec["gt"].name)
            if not cible.exists():
                shutil.copytree(spec["gt"], cible)
        if spec.get("pdf") and spec["pdf"].exists():
            annotations.mkdir(parents=True, exist_ok=True)
            shutil.copy2(spec["pdf"], annotations / spec["pdf"].name)

    (destination / "manifest.json").write_text(
        json.dumps(manifeste, ensure_ascii=False, indent=1), encoding="utf-8")
    (destination / "README.md").write_text(_lisezmoi(manifeste), encoding="utf-8")
    return n


def _correspondance(manifeste):
    """annotation folder -> the image sets it scores.

    Built from the manifest rather than hard-coded, so it cannot drift away
    from what the archive actually contains.
    """
    par_gt = {}
    for e in manifeste["images"]:
        v = e.get("verite") or {}
        if v.get("type") != "par_facture":
            continue
        par_gt.setdefault(v["gt_dir"].split("/")[-1], set()).add(e["jeu"])
    return par_gt


def _lisezmoi(manifeste) -> str:
    """A README written INTO the export, so the archive explains itself.

    An archive that travels without its instructions gets opened six months
    later by someone who has no idea which truth goes with which image --
    and the three ground-truth regimes below are exactly the kind of thing
    nobody guesses right.
    """
    # `echantillon` vient du mode --echantillon, `envoi` du paquet monte par
    # scripts/preparer_envoi.py : les deux decrivent un sous-ensemble, et le
    # README doit le dire dans les deux cas plutot que d'annoncer un corpus
    # complet qui n'est pas dans l'archive.
    ech = manifeste.get("echantillon") or manifeste.get("envoi")
    lignes = [
        "# Medical document corpus" + (" — subset" if ech else ""),
        "",
        f"{manifeste['n_images']} images across {manifeste['n_jeux']} sets, "
        "with their ground truth.",
        "",
    ]
    if ech:
        lignes += [
            f"Drawn from a full corpus of {ech['corpus_complet']['n_images']} "
            f"images. {ech['note']}",
            "",
            "| set | what is included |",
            "|---|---|",
        ]
        lignes += [f"| `{jeu}` | {detail} |"
                   for jeu, detail in sorted(ech["par_jeu"].items())]
        lignes.append("")

    # Un paquet manuscrit n'a ni dossier `annotations/` ni page de facture :
    # decrire une arborescence qui n'est pas dans l'archive ferait chercher
    # des fichiers absents.
    familles = {e["famille"] for e in manifeste["images"]}
    familles |= {NOMS_FAMILLES.get(f, f) for f in familles}
    avec_factures = bool(_correspondance(manifeste))

    plan = ["```"]
    if "invoice" in familles or "facture" in familles:
        plan.append("imgs/  invoice/<set>/       invoice pages, synthetic (LaTeX + Blender)")
    if "handwriting" in familles or "manuscrit" in familles:
        plan.append("       handwriting/<set>/   handwritten forms, VN and EN")
    if "real" in familles or "reel" in familles:
        plan.append("       real/<set>/          real photographs (TabRecSet sample)")
    if avec_factures:
        plan.append("annotations/                per-invoice labels + source PDFs")
    plan += ["manifest.json               one entry per image", "```", ""]

    lignes += ["## Layout", ""] + plan

    if avec_factures:
        lignes += [
        "## Where are the images for a given annotation?",
        "",
        "`annotations/` holds only JSON, and that surprises people. The "
        "reason: **the same invoices were rendered several times, under "
        "different conditions**. One annotation folder therefore serves "
        "several image folders — `invoices_variants/` describes the same 12 "
        "invoices whether you look at them flat, warped, on a cluttered "
        "background, cropped, or degraded.",
        "",
        "| annotation folder | image folders it scores |",
        "|---|---|",
    ] + [
        f"| `annotations/{gt}/` | {', '.join('`imgs/invoice/' + j + '/`' for j in sorted(jeux))} |"
        for gt, jeux in sorted(_correspondance(manifeste).items())
    ] + [
        "",
        "To go from `invoice_1.json` to its pages, use `manifest.json`: every "
        "invoice-page entry carries `verite.facture` (the JSON that scores "
        "it) and `page` (its number in the source PDF). No need to reopen "
        "the PDF, though it is included under `annotations/` as well.",
        "",
        "```python",
        "import json",
        "m = json.load(open('manifest.json', encoding='utf-8'))",
        "pages = [e for e in m['images']",
        "         if (e.get('verite') or {}).get('facture') == 'invoice_1.json'",
        "         and e['jeu'] == 'variants_warped']",
        "for e in sorted(pages, key=lambda e: e['page']):",
        "    print(e['page'], e['chemin'])",
        "```",
        "",
    ]

    lignes += ["## Ground truth", ""]
    if avec_factures:
        lignes += [
            "**Invoices** — one JSON per INVOICE, in `annotations/`, covering "
            "several pages. Invoices are sampled whole, so every page of a "
            "sampled invoice is here. The invoice labels are shipped in full, "
            "not only for the sampled ones: the files are small, and a missing "
            "one would be fatal.",
            "",
        ]
    if "handwriting" in familles or "manuscrit" in familles:
        lignes += [
            "**Handwriting** — one `*_verite.json` per image, right next to "
            "it, holding the exact value of every handwritten field (and, for "
            "English, the handwriting font used). Degraded and warped pages "
            "keep the truth of their source specimen: the degradation only "
            "touches pixels.",
            "",
        ]
    if "real" in familles or "reel" in familles:
        lignes += [
            "**Real photographs** — the TabRecSet annotations, detection and "
            "structure, under their original folders.",
            "",
        ]

    lignes += [
        "## Caveats",
        "",
        "Every synthetic set is generated: LaTeX for the content, Blender for "
        "warping and lighting, handwriting fonts for the script. That is what "
        "makes the ground truth exact — and it is also the main limitation. "
        "Vietnamese handwriting uses a single font, English uses seven.",
    ]
    return "\n".join(lignes) + "\n"


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
    # Left at None so that sample mode can tell "the user asked for this
    # path" from "nobody said anything". Without that distinction, a sample
    # run overwrites manifest.json -- the index of the FULL corpus -- with a
    # 71-image manifest, and the repository then advertises a corpus it no
    # longer describes.
    p.add_argument("--sortie", default=None)
    p.add_argument("--resume", action="store_true",
                   help="Print the summary without writing the manifest.")
    p.add_argument("--export", default=None,
                   help="Materialise a unified copy in this folder.")
    p.add_argument("--zip", action="store_true",
                   help="Zip the export (implies --export).")
    p.add_argument("--echantillon", action="store_true",
                   help="Keep only a small representative sample of each set "
                        "(whole invoices, see echantillonner()).")
    p.add_argument("--n-factures", type=int, default=2,
                   help="Complete invoices per invoice set (default 2).")
    p.add_argument("--n-specimens", type=int, default=3,
                   help="Specimens per handwriting set (default 3).")
    p.add_argument("--n-reel", type=int, default=3,
                   help="Images from the real-photograph set (default 3).")
    p.add_argument("--n-pages-degradation", type=int, default=1,
                   help="Pages kept across ALL degradation steps (default 1).")
    args = p.parse_args()

    diagnostiquer_racines()
    manifeste = construire()

    if args.echantillon:
        manifeste = echantillonner(
            manifeste, n_factures=args.n_factures,
            n_specimens=args.n_specimens, n_reel=args.n_reel,
            n_pages_degradation=args.n_pages_degradation)
        print("SAMPLE mode\n")

    resumer(manifeste)

    if args.echantillon:
        print("\nSample composition:")
        for jeu, detail in sorted(manifeste["echantillon"]["par_jeu"].items()):
            print(f"  {jeu:<36}{detail}")
        complet = manifeste["echantillon"]["corpus_complet"]
        print(f"\n  {manifeste['n_images']} images kept out of "
              f"{complet['n_images']} in the full corpus")

    if not args.resume:
        if args.sortie:
            sortie = Path(args.sortie)
        elif args.echantillon:
            # The sample's own manifest already travels inside the export;
            # writing a second copy next to the full one only invites
            # confusion about which is which.
            sortie = None
        else:
            sortie = Path(__file__).resolve().parent / "manifest.json"
        if sortie:
            sortie.write_text(
                json.dumps(manifeste, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"\n-> {sortie}")
        else:
            print("\n(sample mode: manifest.json left untouched, the sample's "
                  "manifest goes inside the export)")

    if args.export or args.zip:
        dest = Path(args.export or (Path(__file__).resolve().parent / "corpus"))
        n = exporter(manifeste, dest)
        print(f"-> {n} images copied into {dest}")
        if args.zip:
            archive = shutil.make_archive(str(dest), "zip", dest.parent, dest.name)
            print(f"-> {archive} ({Path(archive).stat().st_size / 1e6:.0f} MB)")


if __name__ == "__main__":
    main()
