"""
Compare HTR models on the synthetic handwriting specimens (VN page 9 PHCN,
EN pages 1-2), field by field, against the exact ground truth the generators
wrote alongside each image (`..._verite.json`).

Unlike eval_fields.py (invoices), there is no per-model structured field
extractor here: each OCR model returns a free-form Markdown transcription of
the whole page, with its own layout conventions -- Chandra keeps the printed
labels, GLM's "Text Recognition:" prompt may not, PaddleOCR-VL returns its
own JSON-derived Markdown. Parsing named fields out of that would mean
writing (and trusting) one extractor per model, which is exactly the kind of
model-specific code this project has avoided elsewhere (bench_deformed.py
calls every model through the same three-line interface).

Instead, for each expected field we ask a more modest question: does this
text appear -- exactly, or approximately -- SOMEWHERE in the page
transcription? That is enough to say whether a model actually read a value
correctly, without needing it to also label the value the way we would.

Three signals per field, from strict to loose:
    exact     the normalised value is a literal substring of the transcription
    lenient   idem after stripping diacritics and non-alphanumeric characters
              (a reading defect on a single accent should not count the same
              as losing the field entirely -- same reasoning as eval_fields.py)
    score     best local similarity (0-100) found by sliding a same-size
              window over the transcription -- keeps saying something even
              when a field is missed outright, instead of collapsing every
              miss to the same flat zero. Approximate (stdlib difflib, no
              rapidfuzz dependency), not a true character error rate.

Purely numeric fields (a room number, a two-digit year count) AND very short
tokens ("X", "Đã") are matched on a word boundary (\\bVALUE\\b) instead of raw
substring: they are one or two characters wide, wide enough to turn up by
chance anywhere digits or short words are dense on the page (dates, phone
numbers, IDs), and a raw substring search would credit the model with a
field it never actually read.

Fields that are never actually handwritten on the generated page (the
department name in the VN header is printed, not filled by hand; "sex" is a
checkbox mark, not text) are excluded from the HANDWRITTEN column but kept
in the ALL FIELDS column, so the report can tell "reads handwriting well"
apart from "reads the page well" -- the two questions this benchmark exists
to answer are not the same question.

Usage:
    python src/eval_handwriting.py --run handwriting_vi_paddleocr_vl \\
        --verite-dir handwriting/generated --lang vi
    python src/eval_handwriting.py --run handwriting_en_chandra \\
        --verite-dir handwriting_en/generated --lang en --detail
    python src/eval_handwriting.py --runs-dir handwriting \\
        --verite-dir handwriting/generated --lang vi   # tous les runs du dossier
"""

import argparse
import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path


# --------------------------------------------------------------------------
# Normalisation -- same spirit as invoice_fields._deaccent_keep_length, kept
# local so this script has no import dependency on the invoice-specific code.

def _normalise(s) -> str:
    return re.sub(r"\s+", " ", str(s)).strip().lower()


# Chandra (et probablement d'autres) rendent les tableaux en HTML brut dans
# le Markdown, avec un <br/> entre deux lignes d'UNE MÊME cellule -- typique
# de "ngay_gio" ("15h00<br/>12/07"), où la vérité terrain attend un espace
# ("15h00 12/07"). Sans ce nettoyage, un champ correctement lu comptait comme
# manqué : trouvé en inspectant à la main le pire score VN de Chandra, où
# PRESQUE TOUS les "ngay_gio" de chaque specimen ressortaient comme ratés
# alors que la transcription était juste. Toute balise est retirée -- pas
# seulement <br/> -- parce que PaddleOCR-VL encadre chaque cellule de <td
# style='...'> et Chandra ajoute parfois <i>...</i>, qui ne cassent rien
# aujourd'hui mais pourraient sur un futur champ ; autant traiter la classe
# du problème plutôt que le seul symptôme trouvé.
def _sans_html(s) -> str:
    return re.sub(r"<[^>]+>", " ", str(s))


# "đ"/"Đ" do not decompose into "d" + diacritic under NFD/NFKD -- they are
# distinct Vietnamese letters, not accented ones -- so a plain
# decompose-and-drop-combining-marks pass leaves them untouched and every
# value containing one ("Đã ký", "Đông y", any name starting with "Đ")
# silently fails to match. Same fix already used in src/invoice_fields.py
# (`_EXTRA`), applied here so the two scripts agree on what "diacritic-free"
# means.
_EXTRA = {"đ": "d", "Đ": "d", "ð": "d", "Ð": "d"}


def _deaccent(s: str) -> str:
    out = []
    for ch in s:
        if ch in _EXTRA:
            out.append(_EXTRA[ch])
            continue
        decomposed = unicodedata.normalize("NFKD", ch)
        base = "".join(c for c in decomposed if not unicodedata.combining(c))
        out.append(base if base else ch)
    return "".join(out)


def _squash(s) -> str:
    """Lowercase, no diacritics, no spaces or punctuation -- the lenient key."""
    return re.sub(r"[^a-z0-9]", "", _deaccent(_normalise(s)))


def _needs_word_boundary(s: str) -> bool:
    """Purely numeric values ('5', '15') AND very short tokens ('X', 'Đã')
    are wide enough to turn up by chance anywhere in a page dense with
    digits or short words -- a raw substring search would credit the model
    with a field it never actually read. Matched on a word boundary instead."""
    s = str(s).strip()
    return bool(re.fullmatch(r"\d+", s)) or len(s) <= 2


def _best_local_score(needle: str, haystack: str, step: int = None) -> float:
    """0-100 : best similarity of `needle` against any same-size window of
    `haystack`, slid across the text. Approximate on purpose -- see module
    docstring -- but enough to separate "close" from "nowhere near"."""
    n = len(needle)
    if n == 0:
        return 100.0
    if len(haystack) <= n:
        return SequenceMatcher(None, needle, haystack).ratio() * 100
    step = step or max(1, n // 3)
    slack = max(2, n // 4)
    best = 0.0
    for i in range(0, len(haystack) - n + 1, step):
        window = haystack[max(0, i - slack): i + n + slack]
        r = SequenceMatcher(None, needle, window).ratio()
        if r > best:
            best = r
            if best > 0.995:
                break
    return best * 100


def match_field(valeur, texte_norm: str, texte_squash: str) -> dict:
    valeur_norm = _normalise(valeur)
    if _needs_word_boundary(valeur):
        exact = re.search(rf"\b{re.escape(valeur_norm)}\b", texte_norm) is not None
        lenient = exact
    else:
        exact = valeur_norm in texte_norm
        lenient = exact or (_squash(valeur) in texte_squash)
    score = 100.0 if exact else _best_local_score(valeur_norm, texte_norm)
    return {"exact": exact, "lenient": lenient, "score": round(score, 1)}


# --------------------------------------------------------------------------
# Quels champs du JSON de verite sont reellement rendus, et lesquels sont
# manuscrits -- construit a la main a partir des gabarits LaTeX des deux
# generateurs (handwriting/generate.py, handwriting_en/generate_en.py), pas
# devine depuis les cles du JSON : plusieurs cles existent dans le JSON sans
# jamais apparaitre sur la page (`nam_sinh`, utilise seulement pour calculer
# `tuoi`), et une est imprimee plutot que manuscrite (`khoa`).

def champs_vi(verite: dict):
    """(nom, valeur, manuscrit) pour un specimen handwriting/ (page 9 PHCN)."""
    p = verite["patient"]
    champs = [
        ("patient.ten", p["ten"], True),
        ("patient.tuoi", p["tuoi"], True),
        ("patient.gioi", p["gioi"], True),
        ("patient.buong", p["buong"], True),
        ("patient.giuong", p["giuong"], True),
        ("patient.chan_doan", p["chan_doan"], True),
        ("patient.so_y_te", p.get("so_y_te", ""), True),
        ("patient.khoa", p["khoa"], False),  # imprime, pas manuscrit
    ]
    for i, ligne in enumerate(verite["lignes"], start=1):
        for cle in ("ngay_gio", "mo_ta", "ky_thuat", "thoi_gian",
                    "nguoi_thuc_hien", "bs_chi_dinh", "xac_nhan"):
            champs.append((f"ligne{i}.{cle}", ligne[cle], True))
    return [(n, v, m) for n, v, m in champs if str(v).strip()]


def champs_en(verite: dict):
    """(nom, valeur, manuscrit) pour un specimen handwriting_en/ (pages 1-2)."""
    imprimes_ou_non_rendus = {"sex", "police"}
    champs = [(cle, val, True) for cle, val in verite.items()
              if cle not in imprimes_ou_non_rendus]
    return [(n, v, m) for n, v, m in champs if str(v).strip()]


CHAMPS = {"vi": champs_vi, "en": champs_en}


# --------------------------------------------------------------------------

class VeriteDir:
    """Retrouve <stem>_verite.json qu'il soit a plat ou dans generated/<stem>/
    -- les deux mises en page existent selon qu'on pointe sur le dossier de
    developpement (generated/<stem>/<stem>_verite.json) ou sur une copie a
    plat televersee comme dataset Kaggle."""

    def __init__(self, racine: Path):
        self.par_stem = {p.stem.replace("_verite", ""): p
                         for p in racine.glob("**/*_verite.json")}

    def get(self, stem: str):
        p = self.par_stem.get(stem)
        return json.loads(p.read_text(encoding="utf-8")) if p else None


def transcription_for(pages_dir: Path, stem: str):
    """Le .md le plus recent produit par bench_deformed.py pour ce specimen."""
    d = pages_dir / stem
    if not d.is_dir():
        return None
    md = list(d.glob("*.md"))
    if not md:
        return None
    return max(md, key=lambda p: p.stat().st_mtime).read_text(encoding="utf-8")


def evaluer_run(run_dir: Path, lang: str, verite_dir: VeriteDir, detail: bool):
    pages_dir = run_dir / "pages"
    if not pages_dir.is_dir():
        print(f"{run_dir.name:<40} (pas de dossier pages/)")
        return None

    extracteur = CHAMPS[lang]
    total = {"tous": {"n": 0, "exact": 0, "lenient": 0, "score": 0.0},
             "manuscrits": {"n": 0, "exact": 0, "lenient": 0, "score": 0.0}}
    manques = []
    n_specimens = 0

    for specimen_dir in sorted(pages_dir.iterdir()):
        if not specimen_dir.is_dir():
            continue
        stem = specimen_dir.name
        texte = transcription_for(pages_dir, stem)
        verite = verite_dir.get(stem)
        if texte is None or verite is None:
            continue

        n_specimens += 1
        texte = _sans_html(texte)
        texte_norm = _normalise(texte)
        texte_squash = _squash(texte)

        for nom, valeur, manuscrit in extracteur(verite):
            r = match_field(valeur, texte_norm, texte_squash)
            for groupe in (["tous"] + (["manuscrits"] if manuscrit else [])):
                total[groupe]["n"] += 1
                total[groupe]["exact"] += r["exact"]
                total[groupe]["lenient"] += r["lenient"]
                total[groupe]["score"] += r["score"]
            if detail and not r["lenient"]:
                manques.append((stem, nom, str(valeur)[:30], r["score"]))

    if n_specimens == 0:
        print(f"{run_dir.name:<40} (aucun specimen avec verite + transcription)")
        return None

    def resume(groupe):
        d = total[groupe]
        if d["n"] == 0:
            return "--"
        ok = 100 * d["lenient"] / d["n"]
        moy = d["score"] / d["n"]
        return f"{ok:5.1f}% ok  (score moy. {moy:5.1f})"

    print(f"{run_dir.name:<40} manuscrits: {resume('manuscrits'):<28} "
          f"tous champs: {resume('tous')}   [{n_specimens} specimens]")

    if detail and manques:
        print(f"  Champs manqués ({len(manques)}) :")
        for stem, nom, val, score in manques[:40]:
            print(f"    {stem:<16} {nom:<24} attendu={val!r:<32} score={score:.0f}")
        if len(manques) > 40:
            print(f"    ... et {len(manques) - 40} de plus")

    return total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", action="append", default=[],
                     help="Nom (ou chemin) d'un run sous results/ (répétable).")
    ap.add_argument("--runs-dir", default=None,
                     help="Évalue tous les sous-dossiers de results/<ce dossier>.")
    ap.add_argument("--results-root", default="results")
    ap.add_argument("--verite-dir", required=True,
                     help="Dossier contenant les *_verite.json sources "
                          "(ex. handwriting_en/generated).")
    ap.add_argument("--lang", required=True, choices=["vi", "en"])
    ap.add_argument("--detail", action="store_true")
    args = ap.parse_args()

    verite_dir = VeriteDir(Path(args.verite_dir).resolve())
    if not verite_dir.par_stem:
        print(f"Aucun *_verite.json trouvé sous {args.verite_dir} "
              "-- vérifier le chemin.")
        return

    results_root = Path(args.results_root).resolve()
    if args.runs_dir:
        runs = sorted(p for p in (results_root / args.runs_dir).iterdir() if p.is_dir())
    elif args.run:
        runs = [Path(r) if Path(r).is_absolute() else results_root / r for r in args.run]
    else:
        ap.error("Préciser --run (au moins une fois) ou --runs-dir.")
        return

    for run_dir in runs:
        evaluer_run(run_dir, args.lang, verite_dir, args.detail)


if __name__ == "__main__":
    main()
