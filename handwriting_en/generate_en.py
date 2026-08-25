"""
Genere des specimens synthetiques (anglais) des DEUX PREMIERES PAGES du
"Periodic Health Examination Record" fourni par Halfaa (health record_en.docx),
avec contenu manuscrit simule -- meme architecture que le generateur
vietnamien (`handwriting/`), police et vocabulaire changes.

Perimetre : exactement le texte des pages 1-2 tel que colle par Halfaa --
en-tete national, bloc photo + identite (items 1-6), note sur la CCCD a puce,
emploi (7-9), emplois precedents (10, a/b), antecedents familiaux (11),
tableau d'antecedents personnels/maladies professionnelles (12, a-d), bloc de
signature de confirmation. La suite du document (I. MEDICAL HISTORY,
II. PHYSICAL EXAMINATION, ...) commence a la page 3 et n'est pas couverte ici.

Polices manuscrites : 7 styles differents (voir FONTS ci-dessous), pour
pouvoir tester plusieurs "ecritures" plutot qu'une seule -- chaque specimen
utilise UN seul style (coherent avec l'idee qu'un formulaire est rempli par
une seule personne), le style variant d'un specimen a l'autre. Toutes en
Google Fonts, verifiees sur le binaire (couverture ASCII complete), toutes
libres de droits (OFL, sauf Homemade Apple en Apache 2.0 -- egalement libre
en usage commercial). Halfaa a suggere Brittany Signature (dafont) au depart,
ecartee car "usage personnel uniquement, pas d'usage commercial" (achat
requis au-dela) -- incompatible avec la pratique du projet.

Police du texte imprime : Liberation Serif, embarquee localement (fonts/,
licence OFL) plutot que chargee comme police systeme -- \\setmainfont par nom
depend de la police installee sur la machine, ce qui s'est revele fragile
sous Windows/MiKTeX (echec intermittent "the font cannot be found" sur le
generateur vietnamien, alors que la meme police venait de fonctionner sur
d'autres specimens dans la meme execution). Embarquer le .ttf directement
supprime cette dependance a l'environnement.

    python generate_en.py --n 5                  # style au hasard par specimen
    python generate_en.py --n 5 --police caveat   # un seul style pour tout le lot
    python generate_en.py --lister-polices        # voir les styles disponibles
"""

import argparse
import json
import random
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from vocab_en import tirer_patient  # noqa: E402

RACINE = Path(__file__).resolve().parent
FONT_DIR = RACINE / "fonts"
SORTIE = RACINE / "generated"

# --- polices manuscrites disponibles : cle CLI -> (nom de fichier .ttf sans
# extension, description courte). Toutes verifiees sur le binaire (couverture
# ASCII complete -- lettres, chiffres, ponctuation) avant d'etre retenues.
FONTS = {
    "caveat": ("Caveat", "ecriture scolaire nette, cursive legere"),
    "alex_brush": ("AlexBrush", "script fluide, proche d'une signature"),
    "sacramento": ("Sacramento", "script fin et elegant"),
    "patrick_hand": ("PatrickHand", "impression a la main, propre et ronde"),
    "shadows_into_light": ("ShadowsIntoLight", "ecriture casual, trait epais"),
    "reenie_beanie": ("ReenieBeanie", "griffonnage rapide, plus difficile a lire"),
    "homemade_apple": ("HomemadeApple", "stylo-bille, irregulier, tres realiste"),
}

_SPECIAUX = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
    "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
    "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}
_RE_SPECIAUX = re.compile("|".join(re.escape(c) for c in _SPECIAUX))


def echapper(texte):
    return _RE_SPECIAUX.sub(lambda m: _SPECIAUX[m.group()], str(texte))


def hw(texte):
    return r"{\hw " + echapper(texte) + "}"


def boite(coche):
    """Case a cocher : le carre est imprime, la croix (si cochee) manuscrite."""
    return r"$\square$" + (hw(" X") if coche else "")


def _ligne_item12(lettre):
    return (f"{lettre}) & \\hw{{@@DISEASE_{lettre.upper()}_NAME@@}} & "
            f"\\hw{{@@DISEASE_{lettre.upper()}_YEAR@@}} & "
            f"\\hw{{@@DISEASE_{lettre.upper()}_OCC_NAME@@}} & "
            f"\\hw{{@@DISEASE_{lettre.upper()}_OCC_YEAR@@}} \\\\ \\hline")


ITEM12_LIGNES = "\n".join(_ligne_item12(l) for l in ("a", "b", "c", "d"))


TEMPLATE = r"""\documentclass[10pt]{article}
\usepackage[a4paper,margin=1.5cm]{geometry}
\usepackage{fontspec}
\usepackage{array}
\usepackage{amssymb}
\setmainfont{LiberationSerif}[
  Path = FONTPATH/, Extension = .ttf,
  UprightFont = *-Regular, BoldFont = *-Bold,
  ItalicFont = *-Italic, BoldItalicFont = *-BoldItalic,
]
\newfontfamily\hw{HW_FONT_STEM}[Path=FONTPATH/, Extension=.ttf, UprightFont=*]
\renewcommand{\arraystretch}{1.3}
\pagestyle{empty}
\begin{document}
\begin{center}
{\bfseries SOCIALIST REPUBLIC OF VIETNAM}\\
{\itshape Independence -- Freedom -- Happiness}\\
\rule{4.2cm}{0.4pt}
\end{center}

\vspace{0.3cm}
\begin{center}
{\bfseries\Large PERIODIC HEALTH EXAMINATION RECORD}
\end{center}
\vspace{0.25cm}

\noindent
\begin{tabular}{|p{3.0cm}|p{14.3cm}|}
\hline
\centering\footnotesize Photo\newline(4 x 6 cm)\newline(sealed across the\newline
corner, or a\newline scanned photo) &
1. Full name (write in BLOCK CAPITALS): \hw{@@FULL_NAME@@}

2. Sex: Male @@BOX_MALE@@ \quad Female @@BOX_FEMALE@@

3. Date of birth (Day/Month/Year): \hw{@@DOB@@} \quad (Age: \hw{@@AGE@@})

4. ID Card / Citizen ID / Passport / Personal identification No.: \hw{@@ID_NUMBER@@}

5. Issued on \hw{@@ID_ISSUE_DATE@@} \quad At \hw{@@ID_ISSUE_PLACE@@}

6. Current address: \hw{@@ADDRESS@@};

Contact phone number: \hw{@@PHONE@@} \\
\hline
\end{tabular}

\vspace{0.15cm}
\noindent\footnotesize\itshape
* Note: If the examinee holds a chip-embedded Citizen ID card, or a personal
identification number already connected to the National Population Database,
the ADMINISTRATIVE INFORMATION section above only needs to record items
(1) Full name, (3) Date of birth, and (4) Personal identification number.
\normalfont\normalsize

\vspace{0.3cm}
\noindent
7. Occupation: \hw{@@OCCUPATION@@} \\
8. Workplace / place of study: \hw{@@WORKPLACE@@} \\
9. Date of starting work at the current unit: \hw{@@WORK_START@@} \\[0.15cm]
10. Previous occupations / jobs (list jobs held over the last 10 years, starting
from the most recent):

a) \hw{@@PREV_JOB_A@@} \quad working period \hw{@@PREV_JOB_A_YEARS@@} years
\hw{@@PREV_JOB_A_MONTHS@@} months, from \hw{@@PREV_JOB_A_FROM@@}
to \hw{@@PREV_JOB_A_TO@@}

b) \hw{@@PREV_JOB_B@@} \quad working period \hw{@@PREV_JOB_B_YEARS@@} years
\hw{@@PREV_JOB_B_MONTHS@@} months, from \hw{@@PREV_JOB_B_FROM@@}
to \hw{@@PREV_JOB_B_TO@@}

\vspace{0.15cm}
11. Family medical / health history: \hw{@@FAMILY_HISTORY@@}

\vspace{0.2cm}
12. Personal medical / health history:

\vspace{0.1cm}
\begin{tabular}{|p{0.6cm}|p{5.0cm}|p{2.1cm}|p{5.0cm}|p{2.1cm}|}
\hline
& \textbf{Disease name} & \textbf{Year detected} &
\textbf{Occupational disease name} & \textbf{Year detected} \\
\hline
ITEM12_LIGNES
\end{tabular}

\vspace{0.6cm}
\noindent
\begin{tabular}{|p{8.4cm}|p{8.4cm}|}
\hline
The employee confirms \newline (Sign and write full name)
\vspace{1.1cm}
\newline\hspace*{1cm}\hw{@@FULL_NAME@@}
&
\hw{@@CONFIRM_PLACE@@}, date \hw{@@CONFIRM_DAY@@} month \hw{@@CONFIRM_MONTH@@}
year \hw{@@CONFIRM_YEAR@@}
\newline
Person who prepared the periodic health record
\newline (Sign and write full name)
\vspace{0.7cm}
\newline\hspace*{1cm}\hw{@@PREPARER@@}
\\
\hline
\end{tabular}

\end{document}
"""

TEMPLATE = TEMPLATE.replace("ITEM12_LIGNES", ITEM12_LIGNES)

# --- correction de portée : le gabarit ci-dessus écrit partout \hw{@@TOKEN@@}
# (accolade APRES la commande). Mais \hw n'est pas une macro à argument comme
# \textbf{...} -- \newfontfamily en fait une simple DECLARATION de police,
# comme \bfseries. `\hw{texte}` exécute donc \hw (bascule vers Caveat pour le
# reste du groupe englobant), puis ouvre un groupe à part qui affiche juste
# "texte" sans rien changer : la bascule de police fuit vers TOUT ce qui suit,
# jusqu'à la prochaine vraie frontière de groupe (ex. la cellule de tableau
# suivante) -- ce qui rendait aussi les libellés imprimés ("Disease name",
# "8. Workplace...") en écriture manuscrite. La syntaxe correcte est
# `{\hw texte}` (accolade AVANT la commande), qui confine la bascule au
# groupe. On corrige ici tout le corps du document (jamais le préambule, où
# `\newfontfamily\hw{Caveat}[...]` a la forme `\hw{...}` légitimement et ne
# doit pas être touché) -- le contenu entre \hw{ et } vient toujours de
# `echapper()`, qui a déjà neutralisé toute accolade littérale, donc la
# regex ne peut pas s'arrêter au mauvais endroit.
_preambule, _sep, _corps = TEMPLATE.partition(r"\begin{document}")
_corps = re.sub(r"\\hw\{([^{}]*)\}", r"{\\hw \1}", _corps)
TEMPLATE = _preambule + _sep + _corps


def construire_tex(p, police):
    """Remplace chaque jeton @@CLE@@ par la valeur echappee correspondante.

    Jetons entoures de @@ pour eviter toute collision avec un mot ordinaire
    du gabarit (bug rencontre au premier essai avec des cles nues -- voir
    README).

    `police` : cle de FONTS -- un seul style manuscrit par specimen (un
    formulaire est rempli par une seule personne).
    """
    if police not in FONTS:
        raise ValueError(f"Police inconnue : {police!r} (voir --lister-polices)")
    tex = TEMPLATE
    tex = tex.replace("FONTPATH", str(FONT_DIR).replace("\\", "/"))
    tex = tex.replace("HW_FONT_STEM", FONTS[police][0])
    tex = tex.replace("@@BOX_MALE@@", boite(p["sex"] == "Male"))
    tex = tex.replace("@@BOX_FEMALE@@", boite(p["sex"] == "Female"))
    for cle, valeur in p.items():
        tex = tex.replace(f"@@{cle.upper()}@@", echapper(valeur))
    restants = re.findall(r"@@[A-Z_]+@@", tex)
    if restants:
        raise RuntimeError(f"Jetons non remplacés (vérité terrain incomplète) : {restants}")
    if "HW_FONT_STEM" in tex:
        raise RuntimeError("Jeton de police non remplacé -- vérifier FONTS.")
    return tex


def compiler(tex_src, dossier, nom):
    """Compile en PDF (xelatex), puis rend un PNG via PyMuPDF (evite de
    dependre en plus de poppler/pdftoppm -- un seul binaire externe a
    installer, xelatex)."""
    dossier.mkdir(parents=True, exist_ok=True)
    tex_path = dossier / f"{nom}.tex"
    tex_path.write_text(tex_src, encoding="utf-8")
    try:
        r = subprocess.run(
            ["xelatex", "-interaction=nonstopmode", "-halt-on-error",
             f"-output-directory={dossier}", tex_path.name],
            cwd=dossier, capture_output=True, text=True, timeout=60)
    except FileNotFoundError:
        raise RuntimeError(
            "xelatex introuvable. Il faut une distribution LaTeX (MiKTeX ou "
            "TeX Live) installee et sur le PATH -- voir le README.")
    pdf_path = dossier / f"{nom}.pdf"
    if not pdf_path.exists():
        raise RuntimeError(f"xelatex a échoué :\n{r.stdout[-3000:]}")

    import fitz  # PyMuPDF
    png_path = dossier / f"{nom}.png"
    doc = fitz.open(pdf_path)
    doc.load_page(0).get_pixmap(dpi=200).save(png_path)
    doc.close()
    return pdf_path, png_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--garder-tex", action="store_true")
    ap.add_argument(
        "--police", choices=list(FONTS), default=None,
        help="Force un seul style manuscrit pour tout le lot (defaut : "
             "un style au hasard par specimen, pour varier l'ecriture).")
    ap.add_argument(
        "--lister-polices", action="store_true",
        help="Affiche les styles manuscrits disponibles et quitte.")
    args = ap.parse_args()

    if args.lister_polices:
        for cle, (fichier, desc) in FONTS.items():
            print(f"  {cle:20s} {fichier:18s} {desc}")
        return

    rng = random.Random(args.seed)
    SORTIE.mkdir(parents=True, exist_ok=True)

    for i in range(args.n):
        nom = f"specimen_{i:03d}"
        patient = tirer_patient(rng)
        police = args.police or rng.choice(list(FONTS))
        patient = {**patient, "police": police}
        tex_src = construire_tex(patient, police)
        try:
            pdf_path, png_path = compiler(tex_src, SORTIE / nom, nom)
        except RuntimeError as e:
            print(f"[{nom}] ÉCHEC : {e}")
            continue

        (SORTIE / nom / f"{nom}_verite.json").write_text(
            json.dumps(patient, ensure_ascii=False, indent=2), encoding="utf-8")

        if not args.garder_tex:
            for ext in (".aux", ".log"):
                p = SORTIE / nom / f"{nom}{ext}"
                try:
                    if p.exists():
                        p.unlink()
                except PermissionError:
                    pass

        print(f"[{nom}] OK ({police}) -> {png_path.relative_to(RACINE)}")


if __name__ == "__main__":
    main()
