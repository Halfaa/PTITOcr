# Project corpus — 14 sets, 547 images

Everything produced or collected since the start of the internship, listed
in one place. `manifest.json` is the machine-readable version: one entry per
image, with its family, its set, its resolution and the path to the matching
ground truth.

```powershell
python dataset\build_manifest.py            # (re)builds manifest.json
python dataset\build_manifest.py --resume   # just the table below
python dataset\build_manifest.py --export corpus --zip   # unified copy, ready to send
```

**It is an index, not a copy.** The images stay where they are: duplicating
them would cost 400 MB in a repository that already knows how to regenerate
them. `--export` materialises a unified copy when one is genuinely needed
(Kaggle upload, sending to the supervisor), carrying the ground truth along
with it.

---

## Read this before cloning: this repository is not enough

`manifest.json` indexes a **local** corpus. Its paths only resolve on a
machine where the corpus was generated — and a fresh clone of PTITOcr is not
one. Three cumulative reasons:

1. **PTITOcr only covers `MedicalRecord/`.** The Blender renders and the
   invoice ground truth live in two neighbouring repositories:
   [`doc3D-renderer`](https://github.com/anhdungdo0906/doc3D-renderer) and
   [`synthetic_invoice_generator`](https://github.com/anhdungdo0906/synthetic_invoice_generator).
2. **Neither repository versions its images or its ground-truth JSON** —
   checked: `git ls-files img/` returns zero files there. They hold only the
   code that produces them.
3. So **cloning them is not enough either**: the generation has to be
   replayed, LaTeX then Blender.

What remains reconstructible from **this repository alone**: three sets out
of fourteen, i.e. 70 images out of 547.

| set | how |
|---|---|
| `handwriting_vi` | `python handwriting/generate.py --n 30 --lignes 6 --seed 100` (MiKTeX required) |
| `handwriting_en` | `python handwriting_en/generate_en.py --n 30 --seed 100` |
| `tabrecset_sample` | already versioned under `data/` |

`build_manifest.py` says so itself on startup: it lists the missing
repositories, gives the clone commands, and reminds you that cloning is not
enough. If the tree differs from ours, two environment variables straighten
it out: `DOC3D_ROOT` and `INVOICE_GEN_ROOT`.

### To hand the corpus to someone

Do not rely on the manifest: produce an archive.

```powershell
python dataset\build_manifest.py --export corpus --zip
```

It contains the images AND the ground truth, arranged by family and by set,
with the manifest inside — that is what gets sent, uploaded to Kaggle, and
opened without rebuilding anything.

---

## The three families

| family | sets | what it measures |
|---|---|---|
| `facture` | 11 sets, 477 images | the full chain: localisation, dewarping, table reading, multi-page merging, arithmetic validation |
| `manuscrit` | 2 sets, 60 images | handwriting recognition, VN and EN |
| `reel` | 1 set, 10 images | sanity check: the project's only non-synthetic photographs |

---

## The detail

| set | images | UV | what it is for |
|---|---|---|---|
| `multipage_test` | 17 | yes | historical reference set, the source of all the early figures |
| `multipage_flat_1800` | 17 | — | high-resolution control: the reading ceiling without warping |
| `multipage_test_noillum` | 17 | — | separates the effect of lighting from the effect of warping |
| `multipage_test_unwarped` | 17 | — | dewarping oracle: the ceiling if unwarping were perfect |
| `multipage_test_preprocessed_v3` | 17 | — | the "pre-processed" branch of the with/without comparison |
| `variants_flat` | 25 | — | 12 invoices, 6 templates: dependence on the template |
| `variants_warped` | 25 | yes | the same, warped — the pair isolates warping alone |
| `variants_encombre` | 25 | yes | 3 to 6 distractor sheets: breaks localisation |
| `variants_encombre_recadre_contenu` | 25 | — | closed avenue (`fonds_encombres.md` §18): isolates the table, cuts the header |
| `batch1` | 100 | yes | initial batch, one page per invoice |
| `degradation` | 192 | — | 24 steps x 8 pages: robustness curve against photo quality |
| `handwriting_vi` | 30 | — | Vietnamese HTR benchmark (PHCN form, page 9) |
| `handwriting_en` | 30 | — | English HTR benchmark, 7 handwriting fonts |
| `tabrecset_sample` | 10 | — | annotated real photographs, a guard against overfitting to the synthetic |

**UV column**: the marked sets have pixel-exact ground-truth masks
(`doc3D-renderer/uv/<set>`), which makes sheet localisation scorable
exactly — that is what makes all the cropping work measurable.

---

## Three ground-truth regimes, not to be confused

This is the distinction `scripts/eval_all.py` exists to protect: handing a
set the wrong truth raises no error, it just produces numbers that mean
nothing.

**`par_facture`** (all `facture` sets) — one JSON per invoice, several pages
per invoice. The page-to-invoice split comes from the source PDF, not from
the OCR output: deriving it from the OCR would mean scoring the merging
algorithm on the very data that inspired it. Two sets of labels depending on
the image set: `ground_truth_labels_multipage` (8 invoices) or
`ground_truth_labels_variants` (12 invoices).

**`par_page`** (`manuscrit` sets) — one `*_verite.json` per specimen,
written by the generator at render time, next to its image. It holds the
exact value of every handwritten field, and for English the font used
(`police`), which is what makes it possible to analyse results by
handwriting style.

**`tabrecset`** (`reel` set) — the public dataset's own annotations,
detection (`td_annotation`) and structure/content (`tsr_tcr_annotation`).

---

## Regenerating what is missing

The repository does not version the images: they weigh hundreds of MB and
can be rebuilt. `build_manifest.py` lists the sets missing from disk at the
end of its run rather than failing.

| set | command |
|---|---|
| Blender renders | `doc3D-renderer/render_variants.ps1 -FolderId <set>` (`-Parasites -1` for the cluttered one) |
| pre-processed | `python src/preprocess.py --images-dir <set> --out <set>_preprocessed --debug` |
| high resolution | `python scripts/rendre_haute_resolution.py` |
| dewarping oracle | `python scripts/dewarp_oracle.py` |
| degradation | `python scripts/degrader.py --jeu variants_warped --zip` |
| handwriting VN | `python handwriting/generate.py --n 30 --lignes 6 --seed 100` |
| handwriting EN | `python handwriting_en/generate_en.py --n 30 --seed 100` |
| content-based crop | `python scripts/recadrage_par_contenu_extraire.py` |

The Blender renders are **reproducible since the seed fix**
(`random.seed(zlib.crc32(page_name))`): two renders of the same set give the
same views. Sets produced BEFORE that fix are not matched image-for-image
across sets — detailed in `docs/fonds_encombres.md`.

---

## What this corpus does not contain, and why it matters

**No real photograph of a Vietnamese medical document.** Every `facture` and
every `manuscrit` set is synthetic: LaTeX for the content, Blender for the
warping and the lighting, handwriting fonts for the script. That is what
makes the ground truth pixel-exact — and it is also the main limitation of
the project's figures.

**No depth of field.** The renders have no simulated aperture, so background
sheets are as sharp as the target. Measured (`docs/fonds_encombres.md` §16):
this is what makes the sheet's edge literally invisible, and therefore the
cluttered set harder than reality.

**A single handwriting font for Vietnamese** (Playwrite VN), against seven
for English. The font effect is measurable on EN (up to 13 points between
fonts); on VN it cannot be measured at all.

**TabRecSet is the only real counterweight**, and it is only 10 annotated
images, in other languages. Any conclusion drawn from the synthetic sets
remains to be confirmed on real photographs.

---

## Licences

The synthetic sets (`facture`, `manuscrit`) are produced by this project
from LaTeX templates and free fonts — handwriting fonts under the OFL,
except Homemade Apple under Apache 2.0 (detail in
`handwriting_en/README.md`), and Liberation Serif under the OFL for the
printed text.

`tabrecset_sample` comes from the public TabRecSet dataset and remains under
its original licence; only a 10-image sample is versioned here, the full set
is git-ignored (`data/TabRecSet/`).
