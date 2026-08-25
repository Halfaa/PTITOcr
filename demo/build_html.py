"""
Construit REPORT.html a partir de REPORT.md, images comprises.

Pourquoi ce detour : **l'import Markdown de Notion ignore les images
locales**, meme a l'interieur d'un zip. Il ne garde que celles qui ont une
URL publique, si bien qu'un rapport importe en .md arrive amoute de ses
figures sans le moindre avertissement.

L'import HTML, lui, televerse les images encodees dans le fichier. On produit
donc un HTML autonome : chaque figure devient une data URI en base64, et le
fichier n'a plus aucune dependance externe. Il s'ouvre aussi tel quel dans un
navigateur, ce qui depanne si Notion n'est pas disponible.

    python demo/build_html.py
"""

import base64
import mimetypes
import re
import sys
from pathlib import Path

try:
    import markdown
except ImportError:
    raise SystemExit("Ce script a besoin de markdown :\n    pip install markdown")

ICI = Path(__file__).resolve().parent

STYLE = """
:root { --encre:#1f2933; --doux:#6b7785; --bord:#dde2e7; --accent:#2f6fb5;
        --fond-code:#f5f7f9; }
body { max-width: 820px; margin: 0 auto; padding: 48px 28px 96px;
       font: 16px/1.65 -apple-system, "Segoe UI", Roboto, Helvetica, sans-serif;
       color: var(--encre); background: #fff; }
h1 { font-size: 1.9rem; line-height: 1.25; margin: 0 0 8px; }
h2 { font-size: 1.35rem; margin: 44px 0 12px; padding-top: 8px; }
h3 { font-size: 1.08rem; margin: 28px 0 8px; }
p, li { color: #2b3742; }
hr { border: none; border-top: 1px solid var(--bord); margin: 36px 0; }
a { color: var(--accent); }
strong { color: var(--encre); }
table { border-collapse: collapse; width: 100%; margin: 18px 0; font-size: 0.93rem; }
th, td { border: 1px solid var(--bord); padding: 8px 11px; text-align: left;
         vertical-align: top; }
th { background: #f7f9fa; font-weight: 600; }
code { background: var(--fond-code); padding: 1px 5px; border-radius: 4px;
       font-size: 0.88em; font-family: ui-monospace, Menlo, Consolas, monospace; }
pre { background: var(--fond-code); padding: 14px 16px; border-radius: 8px;
      overflow-x: auto; border: 1px solid var(--bord); }
pre code { background: none; padding: 0; }
img { max-width: 100%; height: auto; display: block; margin: 22px auto;
      border: 1px solid var(--bord); border-radius: 6px; }
blockquote { border-left: 3px solid var(--bord); margin: 18px 0;
             padding: 2px 0 2px 16px; color: var(--doux); }
"""


def en_data_uri(chemin: Path) -> str:
    """Encode une image pour qu'elle voyage avec le HTML."""
    type_mime = mimetypes.guess_type(chemin.name)[0] or "image/png"
    donnees = base64.b64encode(chemin.read_bytes()).decode("ascii")
    return f"data:{type_mime};base64,{donnees}"


def main():
    # Le nom du rapport est un argument : le projet en a plusieurs, et
    # dupliquer ce script pour chacun garantirait qu'ils divergent.
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("source", nargs="?", default="REPORT.md",
                    help="Le .md a convertir, dans demo/. Defaut : REPORT.md")
    ap.add_argument("--titre", default="Advanced Information Extraction from "
                                       "Smartphone-Captured Medical Documents")
    args = ap.parse_args()

    source = ICI / args.source
    if not source.exists():
        raise SystemExit(f"{source} introuvable.")
    texte = source.read_text(encoding="utf-8")

    corps = markdown.markdown(
        texte, extensions=["tables", "fenced_code", "attr_list", "sane_lists"])

    # Les balises <img> pointent encore vers figures/... : on les remplace par
    # leur contenu. Une image absente est signalee plutot que silencieusement
    # laissee cassee -- c'est exactement le probleme qu'on corrige ici.
    manquantes = []

    def remplacer(m):
        src = m.group(1)
        if src.startswith(("http://", "https://", "data:")):
            return m.group(0)
        chemin = ICI / src
        if not chemin.exists():
            manquantes.append(src)
            return m.group(0)
        return m.group(0).replace(src, en_data_uri(chemin))

    corps, n = re.subn(r'<img[^>]*src="([^"]+)"[^>]*>', remplacer, corps)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{args.titre}</title>
<style>{STYLE}</style>
</head>
<body>
{corps}
</body>
</html>
"""

    sortie = ICI / (source.stem + ".html")
    sortie.write_text(html, encoding="utf-8")

    print(f"{sortie.name} : {sortie.stat().st_size / 1e6:.1f} Mo, "
          f"{n} image(s) intégrée(s)")
    if manquantes:
        print("Images introuvables, laissées telles quelles :")
        for m in manquantes:
            print("   ", m)
        sys.exit(1)
    print("\nDans Notion : Import → HTML → ce fichier.")


if __name__ == "__main__":
    main()
