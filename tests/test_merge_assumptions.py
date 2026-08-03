"""
Attaque les hypotheses metier de la fusion multi-pages.

Le benchmark mesure la fusion sur 8 factures issues d'UN SEUL gabarit, ou la
colonne STT redemarre a 1 a chaque facture. C'est l'hypothese sur laquelle
repose le signal le plus discriminant de l'algorithme, et un jeu de test qui
la respecte partout ne peut pas la mettre en defaut.

Ces cas sont construits a la main, sans OCR : on isole ainsi la LOGIQUE de
decision du bruit de lecture. Un echec ici est un defaut d'algorithme, pas de
modele.

    python tests/test_merge_assumptions.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from table_merge import Table, is_continuation  # noqa: E402

EN_TETE = ["STT", "Tên mặt hàng/Dịch vụ", "ĐVT", "Số lượng", "Đơn giá", "Thành tiền"]
MARQUEUR = "-- Tiếp trang trước --"


def table(premier_index, n_lignes, en_tete=EN_TETE, avec_total=False,
          ligne_marqueur=False):
    """Fabrique un tableau plausible, numerote a partir de `premier_index`."""
    lignes = []
    if ligne_marqueur:
        lignes.append([MARQUEUR] + [""] * (len(en_tete) - 1))
    lignes.append(list(en_tete))
    for k in range(n_lignes):
        i = premier_index + k
        lignes.append([str(i), f"Paracetamol {500 + i}mg", "viên",
                       str(1 + i % 9), "1500", str(1500 * (1 + i % 9))])
    if avec_total:
        lignes.append(["Tổng tiền:", "", "", "", "", "4 112 900"])
    html = "<table>" + "".join(
        "<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in lignes) + "</table>"
    return Table(rows=lignes, raw_html=html)


# Chaque cas : (nom, table_a, table_b, texte_a, texte_b, fusion_attendue, pourquoi)
CAS = [
    # ---------- Ce que le jeu de test actuel couvre deja ----------
    ("continuation classique",
     table(1, 19), table(20, 8, ligne_marqueur=True),
     "", MARQUEUR, True,
     "marqueur present et numerotation continue"),

    ("deux factures distinctes, STT redemarrant a 1",
     table(1, 19, avec_total=True), table(1, 15),
     "", "", False,
     "B redemarre a 1 sans marqueur : disqualifie"),

    # ---------- Ce qu'il ne couvre PAS ----------
    ("continuation sans marqueur",
     table(1, 19), table(20, 8),
     "", "", True,
     "seule la continuite du STT peut trancher"),

    ("continuation avec une colonne perdue par l'OCR",
     table(1, 19), table(20, 8, en_tete=EN_TETE[:1] + EN_TETE[2:]),
     "", "", True,
     "nombre de colonnes different, mais numerotation continue"),

    ("facture sur 3 pages, page 3",
     table(20, 19), table(39, 6, ligne_marqueur=True),
     "", MARQUEUR, True,
     "ni A ni B ne commence a 1"),

    # ---------- Le cas qui attaque l'hypothese ----------
    ("DEUX FACTURES, compteur STT global",
     table(1, 32, avec_total=True), table(33, 14),
     "", "", False,
     "A se termine par Tong tien : la facture est CLOSE. La continuite du "
     "STT n'est plus une preuve de continuation si le format numerote en "
     "continu d'une facture a l'autre"),

    ("DEUX FACTURES, compteur global, sans ligne de total",
     table(1, 32), table(33, 14),
     "", "", None,
     "indecidable sans le contexte de la page : documente, non teste"),
]


def executer():
    echecs = []
    print(f"{'cas':<48}{'attendu':>9}{'obtenu':>9}{'signal':>10}")
    print("-" * 80)

    for nom, ta, tb, txt_a, txt_b, attendu, pourquoi in CAS:
        d = is_continuation(ta, tb, txt_a, txt_b)
        obtenu = d["decision"]
        if attendu is None:
            verdict, marque = "n/a", " "
        else:
            ok = obtenu == attendu
            verdict = "oui" if ok else "NON"
            marque = " " if ok else "!"
            if not ok:
                echecs.append((nom, attendu, obtenu, d, pourquoi))
        print(f"{marque}{nom:<47}{str(attendu):>9}{str(obtenu):>9}"
              f"{d['confidence']:>10}")

    print("-" * 80)
    if not echecs:
        print("Tous les cas passent.")
        return 0

    print(f"\n{len(echecs)} echec(s) :\n")
    for nom, attendu, obtenu, d, pourquoi in echecs:
        print(f"  {nom}")
        print(f"    attendu {attendu}, obtenu {obtenu}")
        print(f"    {pourquoi}")
        actifs = [k for k, v in d.items()
                  if v is True and k not in ("decision",)]
        print(f"    signaux actifs : {', '.join(actifs)}\n")
    return 1


if __name__ == "__main__":
    sys.exit(executer())
