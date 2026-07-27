"""
Script de test pour PaddleOCR-VL-0.9B.
Usage :
    python test_paddleocr_vl.py chemin\vers\image.png
1. Charge la pipeline PaddleOCR-VL (les poids se telechargent seuls au 1er lancement, ~1-2 min)
2. Traite l'image donnee en argument (texte, tableaux, mise en page)
3. Sauvegarde les resultats dans ./output (JSON + Markdown)
"""
import sys
from pathlib import Path
from paddleocr import PaddleOCRVL

def main():
    if len(sys.argv) < 2:
        print("Usage : python test_paddleocr_vl.py chemin_image.png")
        sys.exit(1)

    image_path = sys.argv[1]
    if not Path(image_path).exists():
        print(f"Image introuvable : {image_path}")
        sys.exit(1)

    print("Chargement de la pipeline PaddleOCR-VL (peut prendre du temps la 1ere fois)...")
    pipeline = PaddleOCRVL(pipeline_version="v1")

    print(f"Traitement de : {image_path}")
    output = pipeline.predict(image_path)

    Path("output").mkdir(exist_ok=True)
    for res in output:
        res.print()                              # apercu dans le terminal
        res.save_to_json(save_path="output")      # resultat structure (tableaux inclus)
        res.save_to_markdown(save_path="output")  # rendu lisible
        res.save_to_img(save_path="output")       # visualisation avec boites de layout (comme ta capture d'ecran)

    print("Termine. Resultats dans le dossier ./output")


if __name__ == "__main__":
    main()
