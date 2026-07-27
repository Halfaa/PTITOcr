"""
Genere un rapport HTML propre (image annotee a gauche, resultat rendu a droite)
a partir des sorties de test_paddleocr_vl.py (dossier "output/").

Usage :
    python render_output.py chemin\vers\image_annotee.jpg chemin\vers\resultat.md

Le script cherche automatiquement les fichiers dans "output/" si aucun argument
n'est donne (prend le 1er .jpg et le 1er .md trouves).

Resultat : cree report.html dans le meme dossier et l'ouvre dans le navigateur.
"""

import base64
import sys
import webbrowser
from pathlib import Path

OUTPUT_DIR = Path("output")


def image_to_data_uri(path: Path) -> str:
    """Encode l'image en base64 et l'embarque dans le HTML (data URI) pour que
    le rapport soit autonome et s'affiche partout (Notion, navigateur, email...)."""
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{data}"

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<title>Resultat PaddleOCR-VL</title>
<style>
  body {{ font-family: Arial, sans-serif; margin: 0; background: #1e1e1e; color: #eee; }}
  .container {{ display: flex; min-height: 100vh; align-items: flex-start; }}
  .panel {{ flex: 1; overflow: auto; padding: 20px; box-sizing: border-box; }}
  .panel.left {{ border-right: 2px solid #444; text-align: center; position: sticky; top: 0; }}
  .panel.left img {{ max-width: 100%; height: auto; }}
  table {{ border-collapse: collapse; margin: 12px 0; width: 100%; background: #fff; color: #000; }}
  table, th, td {{ border: 1px solid #999; }}
  td {{ padding: 6px 10px; text-align: center; }}
  h1, h2, h3 {{ color: #4da3ff; }}
</style>
</head>
<body>
<div class="container">
  <div class="panel left">
    <img src="{image_path}" alt="Image annotee">
  </div>
  <div class="panel right">
    {content}
  </div>
</div>
</body>
</html>
"""


def find_default(*patterns):
    # Prend le fichier le plus RECEMMENT MODIFIE parmi tous les patterns donnes,
    # pas le premier par ordre alphabetique, pour ne pas melanger des fichiers
    # issus de deux runs differents (et PaddleOCR-VL genere parfois du .jpg,
    # parfois du .png selon le type de document en entree).
    matches = []
    for pattern in patterns:
        matches.extend(OUTPUT_DIR.rglob(pattern))
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)


def main():
    if len(sys.argv) >= 3:
        image_path = Path(sys.argv[1])
        md_path = Path(sys.argv[2])
    else:
        image_path = find_default("*.jpg", "*.png")
        md_path = find_default("*.md")
        if not image_path or not md_path:
            print("Usage : python render_output.py image_annotee.jpg resultat.md")
            print(f"(aucun .jpg/.png + .md trouve automatiquement dans {OUTPUT_DIR}/)")
            sys.exit(1)
        print(f"Fichiers detectes automatiquement : {image_path.name}, {md_path.name}")

    md_content = md_path.read_text(encoding="utf-8")
    # Le markdown genere par PaddleOCR-VL contient deja du HTML pour les tableaux,
    # donc on l'injecte tel quel : les tableaux se rendent, le reste (titres, texte)
    # reste lisible meme sans conversion markdown->html complete.
    md_content = md_content.replace("\n\n", "<br><br>")

    html = HTML_TEMPLATE.format(
        image_path=image_to_data_uri(image_path),
        content=md_content,
    )

    report_path = Path("report.html")
    report_path.write_text(html, encoding="utf-8")
    print(f"Rapport genere : {report_path.resolve()}")
    webbrowser.open(report_path.resolve().as_uri())


if __name__ == "__main__":
    main()
