"""
TEDS, expliqué par l'exemple.

Fait tourner la métrique sur des cas construits à la main, où l'on sait
exactement quelle erreur a été introduite. C'est la façon la plus rapide de
comprendre ce que le score récompense et ce qu'il punit -- et de pouvoir
l'expliquer devant quelqu'un.

    python demo/explain_teds.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from teds import rows_to_html, teds  # noqa: E402

EN_TETE = ["STT", "Tên mặt hàng", "ĐVT", "Số lượng", "Đơn giá", "Thành tiền"]
VRAI = [
    EN_TETE,
    ["1", "Paracetamol 500mg", "viên", "10", "1500", "15000"],
    ["2", "Amoxicillin 500mg", "hộp", "2", "40000", "80000"],
    ["3", "Metformin 500mg", "hộp", "1", "36000", "36000"],
]


def exactitude_cellules(pred, vrai):
    """Métrique naïve : part des cellules identiques, à position égale.

    Sert de repoussoir. Elle suppose que les tableaux ont la même forme, ce
    qui est précisément ce que l'OCR ne garantit pas.
    """
    plates_v = [c for ligne in vrai for c in ligne]
    plates_p = [c for ligne in pred for c in ligne]
    if len(plates_p) != len(plates_v):
        return None      # indéfinie : c'est tout le problème
    justes = sum(1 for a, b in zip(plates_p, plates_v) if a == b)
    return justes / len(plates_v)


def copie(modif=None):
    lignes = [list(l) for l in VRAI]
    if modif:
        modif(lignes)
    return lignes


# --- les cas ---------------------------------------------------------------

def un_caractere(l):
    l[1][1] = "Paracetamol 500mq"          # g lu q

def diacritique(l):
    l[2][2] = "hôp"                        # ộ lu ô

def une_cellule_perdue(l):
    l[2][1] = ""

def un_chiffre_faux(l):
    l[3][5] = "38000"                      # 36000 lu 38000

def une_ligne_manquante(l):
    del l[2]

def colonne_perdue(l):
    for ligne in l:
        del ligne[2]                       # la colonne ĐVT disparaît

def entete_absente(l):
    del l[0]

CAS = [
    ("lecture parfaite", copie(), "le maximum atteignable"),
    ("1 caractère faux dans un nom", copie(un_caractere), "« 500mq » au lieu de « 500mg »"),
    ("1 diacritique abîmé", copie(diacritique), "« hôp » au lieu de « hộp »"),
    ("1 chiffre faux", copie(un_chiffre_faux), "36000 lu 38000"),
    ("1 cellule vide", copie(une_cellule_perdue), "le nom du médicament est perdu"),
    ("1 ligne entière manquante", copie(une_ligne_manquante), "l'OCR a sauté une ligne"),
    ("1 colonne perdue", copie(colonne_perdue), "la colonne ĐVT disparaît partout"),
    ("en-tête absente", copie(entete_absente), "les données sont là, l'en-tête non"),
]


def main():
    vrai_html = rows_to_html(VRAI)

    print("Tableau de référence : 1 en-tête + 3 lignes, 6 colonnes\n")
    print(f"{'cas':<32}{'TEDS':>8}{'Struct':>9}{'naïf':>8}   ce qui a changé")
    print("-" * 96)

    for nom, lignes, explication in CAS:
        pred = rows_to_html(lignes)
        t = teds(pred, vrai_html)
        s = teds(pred, vrai_html, structure_only=True)
        naif = exactitude_cellules(lignes, VRAI)
        naif_txt = f"{naif:.2f}" if naif is not None else "n/d"
        print(f"{nom:<32}{t:>8.3f}{s:>9.3f}{naif_txt:>8}   {explication}")

    # --- le cas qui motive la fusion multi-pages ---------------------------
    print("\n" + "-" * 96)
    print("Le cas qui justifie le recollage multi-pages\n")

    page_a = [EN_TETE, VRAI[1]]
    page_b = [EN_TETE, VRAI[2], VRAI[3]]

    sans_fusion = teds(rows_to_html(page_a), vrai_html)
    recolle = [EN_TETE] + [VRAI[1]] + [VRAI[2], VRAI[3]]
    avec_fusion = teds(rows_to_html(recolle), vrai_html)

    print(f"  page 1 seule, sans recoller     TEDS {sans_fusion:.3f}")
    print(f"  les deux pages recollées        TEDS {avec_fusion:.3f}")
    print(f"  gain                            {avec_fusion - sans_fusion:+.3f}")
    print("\n  Une lecture parfaite de la première page plafonne quand même très")
    print("  bas, parce qu'il manque les deux tiers du tableau. C'est exactement")
    print("  ce que mesure la colonne « TEDS w/o » des évaluations.")

    # --- pourquoi pas une métrique naïve -----------------------------------
    print("\n" + "-" * 96)
    print("Pourquoi pas une simple exactitude cellule à cellule\n")
    print("  Regarde la colonne « naïf » : elle vaut n/d dès qu'une ligne ou une")
    print("  colonne manque, parce qu'elle compare des cellules à position égale")
    print("  et qu'il n'y a plus de positions comparables. Or perdre une ligne")
    print("  est justement l'erreur la plus fréquente de l'OCR sur un tableau.")
    print("\n  TEDS reste défini dans tous les cas, et il gradue : un caractère")
    print("  faux coûte bien moins qu'une cellule vide, qui coûte moins qu'une")
    print("  ligne perdue. Une métrique binaire mettrait les trois au même prix.")


if __name__ == "__main__":
    main()
