"""
Genere des specimens synthetiques de la page 9 (PHIEU THUC HIEN KY THUAT PHCN,
formulaire 27/BV1) avec un contenu manuscrit simule, pour tester des modeles
de reconnaissance d'ecriture manuscrite vietnamienne.

Police retenue : Playwrite VN (Google Fonts, OFL, licence libre), le modele
officiel d'ecriture cursive scolaire vietnamienne (« mau chu thao tieng
Viet »). Verification faite sur le fichier binaire (pas la description
marketing) : couverture complete des 148 caracteres vietnamiens precomposes
reels (les 4 codes signales comme "manquants" par un premier test etaient des
faux positifs -- des combinaisons de deux tons superposes qui n'existent pas
en vietnamien). Deux polices Google Fonts generalistes testees avant --
Caveat (34/256 du bloc Latin Extended Additional) et Kalam (latin de base
seulement) -- echouent toutes les deux sur les diacritiques vietnamiens
empiles (ế, ộ, ữ...).

Police du texte imprime : Liberation Serif, embarquee localement (fonts/,
licence OFL) plutot que chargee comme police systeme -- \\setmainfont par nom
depend de la police installee sur la machine, ce qui s'est revele fragile
sous Windows/MiKTeX (echec intermittent "the font cannot be found" alors que
la meme police venait de fonctionner sur d'autres specimens dans la meme
execution). Embarquer le fichier .ttf directement, comme deja fait pour
PlaywriteVN, supprime cette dependance a l'environnement.

Ce que le script produit, par specimen :
    - un PDF (rendu XeLaTeX, cadre imprime + contenu manuscrit)
    - un PNG (pour les modeles qui attendent une image)
    - un JSON de verite terrain (chaque champ, valeur exacte)

    python generate.py --n 5
    python generate.py --n 1 --seed 0 --garder-tex   # pour inspecter le .tex
"""

import argparse
import json
import random
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from vocab_phcn import tirer_lignes, tirer_patient  # noqa: E402

RACINE = Path(__file__).resolve().parent
FONT_DIR = RACINE / "fonts"
SORTIE = RACINE / "generated"

# --- echappement LaTeX : le contenu vient de chaines vietnamiennes libres,
# jamais d'une source LaTeX -- tout caractere special doit etre neutralise.
_SPECIAUX = {
    "\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$",
    "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
    "~": r"\textasciitilde{}", "^": r"\textasciicircum{}",
}
_RE_SPECIAUX = re.compile("|".join(re.escape(c) for c in _SPECIAUX))


def echapper(texte):
    return _RE_SPECIAUX.sub(lambda m: _SPECIAUX[m.group()], str(texte))


def hw(texte):
    """Enrobe un texte dans la police manuscrite."""
    return r"{\hw " + echapper(texte) + "}"


def _ligne_tableau(l):
    return (f"{hw(l['ngay_gio'])} & {hw(l['mo_ta'])} & {hw(l['ky_thuat'])} & "
            f"{hw(l['thoi_gian'])} & {hw(l['nguoi_thuc_hien'])} & "
            f"{hw(l['bs_chi_dinh'])} & {hw(l['xac_nhan'])} \\\\ \\hline")


TEMPLATE_UTF8 = r"""\documentclass[11pt]{article}
\usepackage[a4paper,margin=1.6cm]{geometry}
\usepackage{fontspec}
\usepackage{array}
\setmainfont{LiberationSerif}[
  Path = FONTPATH/, Extension = .ttf,
  UprightFont = *-Regular, BoldFont = *-Bold,
  ItalicFont = *-Italic, BoldItalicFont = *-BoldItalic,
]
\newfontfamily\hw{PlaywriteVN}[Path=FONTPATH/, Extension=.ttf, UprightFont=*]
\renewcommand{\arraystretch}{1.6}
\pagestyle{empty}
\begin{document}
\footnotesize
\noindent
\begin{minipage}[t]{0.55\linewidth}
Bộ Y tế/Sở Y tế: SO_Y_TE_VAL \\
Bệnh viện: BENH_VIEN \\
Khoa/Trung tâm: KHOA \\
Buồng BUONG \quad Giường GIUONG
\end{minipage}
\hfill
\begin{minipage}[t]{0.4\linewidth}
\raggedleft
(Mẫu phiếu số 3) \\
MS: MS_VAL \\
Số vào viện SO_VAO_VIEN
\end{minipage}

\begin{center}
\textbf{\large PHIẾU THỰC HIỆN KỸ THUẬT} \\
\textbf{\large PHỤC HỒI CHỨC NĂNG}
\end{center}

\noindent
- Họ tên người bệnh: TEN_BN
  \quad Năm sinh/Tuổi: TUOI_BN
  \quad Nam/Nữ: GIOI_BN \\
- Khoa: KHOA \quad Số buồng: BUONG
  \quad Số giường: GIUONG \\
- Chẩn đoán: CHAN_DOAN

\vspace{0.3cm}
\begin{tabular}{|p{1.7cm}|p{3.9cm}|p{3.7cm}|p{1.0cm}|p{1.9cm}|p{2.1cm}|p{1.5cm}|}
\hline
\textbf{Ngày giờ} &
\textbf{Mô tả diễn biến} &
\textbf{Tên dịch vụ kỹ thuật} &
\textbf{TG (phút)} &
\textbf{Người thực hiện} &
\textbf{BS chỉ định} &
\textbf{Xác nhận} \\
\hline
LIGNES
\end{tabular}

\end{document}
"""


def construire_tex(patient, lignes, ms="27/BV1-P3", so_vao_vien="000123"):
    tex = TEMPLATE_UTF8
    tex = tex.replace("FONTPATH", str(FONT_DIR).replace("\\", "/"))
    tex = tex.replace("SO_Y_TE_VAL", hw(patient["so_y_te"]))
    tex = tex.replace("BENH_VIEN", "Bệnh viện Phục hồi chức năng")
    tex = tex.replace("KHOA", echapper(patient["khoa"]))
    tex = tex.replace("MS_VAL", ms)
    tex = tex.replace("SO_VAO_VIEN", so_vao_vien)
    tex = tex.replace("TEN_BN", hw(patient["ten"]))
    tex = tex.replace("TUOI_BN", hw(patient["tuoi"]))
    tex = tex.replace("GIOI_BN", hw(patient["gioi"]))
    tex = tex.replace("BUONG", hw(patient["buong"]))
    tex = tex.replace("GIUONG", hw(patient["giuong"]))
    tex = tex.replace("CHAN_DOAN", hw(patient["chan_doan"]))
    tex = tex.replace("LIGNES", "\n".join(_ligne_tableau(l) for l in lignes))
    return tex


def compiler(tex_src, dossier, nom):
    """Compile en PDF (xelatex), puis rend un PNG.

    Le PDF -> PNG passe par PyMuPDF (`pip install pymupdf`) plutot que par
    `pdftoppm` (poppler) : un seul binaire externe a installer (xelatex) au
    lieu de deux, et PyMuPDF s'installe par pip sur Windows sans rien de
    plus a telecharger a part.
    """
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
    page = doc.load_page(0)
    page.get_pixmap(dpi=200).save(png_path)
    doc.close()
    return pdf_path, png_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=3, help="Nombre de specimens.")
    ap.add_argument("--lignes", type=int, default=6, help="Lignes par tableau.")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--garder-tex", action="store_true")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    SORTIE.mkdir(parents=True, exist_ok=True)

    for i in range(args.n):
        nom = f"specimen_{i:03d}"
        patient = tirer_patient(rng)
        lignes = tirer_lignes(rng, args.lignes)
        tex_src = construire_tex(patient, lignes)

        try:
            pdf_path, png_path = compiler(tex_src, SORTIE / nom, nom)
        except RuntimeError as e:
            print(f"[{nom}] ÉCHEC : {e}")
            continue

        verite = {"patient": patient, "lignes": lignes}
        (SORTIE / nom / f"{nom}_verite.json").write_text(
            json.dumps(verite, ensure_ascii=False, indent=2), encoding="utf-8")

        if not args.garder_tex:
            for ext in (".aux", ".log"):
                p = (SORTIE / nom / f"{nom}{ext}")
                try:
                    if p.exists():
                        p.unlink()
                except PermissionError:
                    pass  # dossier en lecture seule (ex. copie finale livree) : sans consequence

        print(f"[{nom}] OK -> {png_path.relative_to(RACINE)}")


if __name__ == "__main__":
    main()
