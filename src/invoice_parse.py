"""
From HTML table to typed fields.

The merged table produced by table_merge is still raw text: rows of cells.
Any downstream use -- and arithmetic validation in particular -- needs typed
objects:

    LineItem(index=1, name="Hydrocortisone 1%", unit="tuýp",
             quantity=1, unit_price=2900, total=2900)

Three real difficulties, systematically underestimated:

  1. column order is not guaranteed (OCR sometimes permutes it);
  2. numbers arrive in several formats: 2900, 2 900, 2.900, 2,900;
  3. some rows are not data: header, Total row, page-break markers.

Columns are therefore identified by their *content* rather than by their
position, reusing the header keywords already used by table_merge.
"""

from dataclasses import dataclass
import re

from table_merge import (_fuzzy_eq, _normalize, _find_header_index,  # noqa
                         _header_score,
                         _MAX_PLAUSIBLE_INDEX)


# Keywords per column. Order within each list is irrelevant: we look for the
# best fuzzy match, which absorbs OCR noise ("so lugng" / "soluong" /
# "Số lượng").
COLUMN_KEYWORDS = {
    # "s/t" et "st" : STT est le libellé le plus COURT du tableau, donc le
    # plus fragile -- perdre une lettre sur trois fait chuter la similarite
    # sous le seuil, alors que la meme perte sur "Thanh tien" ne se voit pas.
    # Mesure sur Chandra : il lit "S/T", le rapprochement echoue, et les 33
    # lignes de la facture 5 sortent avec index=None. Aucune erreur levee --
    # seule la colonne des numeros disparait, et avec elle la detection des
    # trous de numerotation.
    #
    # Ces deux variantes ne matchent QUE cette colonne : verifie contre les
    # cinq autres libelles de l'en-tete, aucune collision.
    "index": ["stt", "so tt", "s/t", "st"],
    "name": ["ten mat hang/dich vu", "ten mat hang", "dich vu", "ten"],
    "unit": ["dvt", "don vi tinh"],
    "quantity": ["so luong", "sl"],
    "unit_price": ["don gia", "gia"],
    "total": ["thanh tien", "tong"],
}

# A row whose cells contain any of these closes the table.
TOTAL_KEYWORDS = ["tong tien", "tong cong", "total"]


@dataclass
class LineItem:
    index: int = None
    name: str = ""
    unit: str = ""
    quantity: int = None
    unit_price: int = None
    total: int = None
    raw: list = None       # original row, so we can trace back to the source

    def __repr__(self):
        return (f"LineItem({self.index}, {self.name!r}, q={self.quantity}, "
                f"up={self.unit_price}, tot={self.total})")


@dataclass
class Invoice:
    items: list
    grand_total: int = None
    columns: dict = None   # {field: column index} as detected


def parse_number(cell):
    """'2 900' / '2.900' / '2,900' / '2900' -> 2900. None if unreadable.

    Thousand separators vary from one invoice to the next (and sometimes
    within a single invoice, depending on what OCR read): we strip them all
    rather than trying to guess the convention.
    """
    if cell is None:
        return None
    digits = re.sub(r"[^\d]", "", str(cell))
    return int(digits) if digits else None


def detect_columns(header_row) -> dict:
    """Map each field to a column index by fuzzy-matching the label -- not by
    position, which OCR does not guarantee."""
    mapping = {}
    used = set()
    for field, keywords in COLUMN_KEYWORDS.items():
        best_idx, best_score = None, 0.0
        for i, cell in enumerate(header_row):
            if i in used:
                continue
            for kw in keywords:
                if _fuzzy_eq(kw, cell, threshold=0.7):
                    # A longer matching label is a more specific match
                    score = len(kw)
                    if score > best_score:
                        best_idx, best_score = i, score
        if best_idx is not None:
            mapping[field] = best_idx
            used.add(best_idx)
    return mapping


def _colonnes_equilibrees(data_rows, q, up, tot):
    """Nombre de lignes qui vérifient quantité x prix = total, pour ce trio."""
    ok = testees = 0
    for row in data_rows:
        vals = []
        for i in (q, up, tot):
            vals.append(parse_number(row[i]) if i < len(row) else None)
        vq, vup, vt = vals
        if None in vals:
            continue
        testees += 1
        if vq * vup == vt:
            ok += 1
    return ok, testees


def repair_columns(data_rows, columns) -> dict:
    """Recale les colonnes numériques quand l'en-tête ment.

    Un en-tête sur DEUX lignes, avec des `colspan`, décrit un nombre de
    colonnes différent de celui des lignes de données. Le rapprochement par
    position se décale alors d'un cran, en silence : les nombres lus sont les
    bons, ce sont les étiquettes qui glissent.

    Constaté sur Chandra, facture 1 du jeu multi-pages. « Đơn giá » désignait
    la colonne des quantités et « Thành tiền » celle des prix unitaires :

        prix unitaire = 1, quantité « corrigée » à 2900, total = 2900

    et la validation arithmétique confirmait, puisque 1 x 2900 = 2900. Vingt
    et une lignes sur trente-trois sont sorties ainsi, marquées `corrected`,
    avec des quantités de 75 000 boîtes de médicament. Aucune erreur levée.

    D'où cette réparation, qui n'utilise **aucune vérité terrain** : parmi les
    colonnes numériques, on cherche le trio (quantité, prix, total) qui fait
    boucler le plus de lignes. C'est la même redondance arithmétique que le
    reste de la chaîne exploite déjà — appliquée cette fois à l'identification
    des colonnes plutôt qu'à la détection des erreurs.

    Prudence délibérée : on ne remplace le rapprochement par en-tête que si
    l'alternative est **strictement meilleure** et qu'elle équilibre au moins
    la moitié des lignes. Sur un tableau normal, l'en-tête gagne et rien ne
    bouge.
    """
    if not data_rows:
        return columns

    largeur = max(len(r) for r in data_rows)
    # Une colonne est « numérique » si la plupart de ses cellules le sont.
    numeriques = []
    for i in range(largeur):
        lus = sum(1 for r in data_rows
                  if i < len(r) and parse_number(r[i]) is not None)
        if lus >= 0.6 * len(data_rows):
            numeriques.append(i)
    if len(numeriques) < 3:
        return columns

    actuel = (columns.get("quantity"), columns.get("unit_price"),
              columns.get("total"))
    reference = (_colonnes_equilibrees(data_rows, *actuel)[0]
                 if None not in actuel else -1)

    def _mediane(i):
        vals = sorted(parse_number(r[i]) for r in data_rows
                      if i < len(r) and parse_number(r[i]) is not None)
        return vals[len(vals) // 2] if vals else 0

    meilleur, meilleur_trio = reference, None
    for q in numeriques:
        for up in numeriques:
            if up == q:
                continue
            for tot in numeriques:
                if tot in (q, up):
                    continue
                ok, testees = _colonnes_equilibrees(data_rows, q, up, tot)
                if not testees or ok < 0.5 * len(data_rows):
                    continue
                # L'arithmetique NE PEUT PAS distinguer quantite et prix
                # unitaire : la multiplication est commutative, donc
                # (q, up, tot) et (up, q, tot) equilibrent identiquement.
                # Laisser l'ordre d'iteration trancher reviendrait a tirer au
                # sort entre « 6 boites a 63 000 » et « 63 000 boites a 6 ».
                #
                # On departage sur les ordres de grandeur : une facture de
                # pharmacie vend quelques unites a un prix qui se compte en
                # milliers de dongs. C'est une hypothese metier, au meme titre
                # que le redemarrage du STT a 1, et elle se revalidera sur
                # tout nouveau format.
                if _mediane(q) > _mediane(up):
                    continue
                if ok > meilleur:
                    meilleur, meilleur_trio = ok, (q, up, tot)

    if meilleur_trio is None:
        return columns

    q, up, tot = meilleur_trio
    repare = dict(columns)
    repare.update(quantity=q, unit_price=up, total=tot)
    # Les colonnes de texte ne doivent pas entrer en collision avec le trio.
    for champ in ("index", "name", "unit"):
        if repare.get(champ) in meilleur_trio:
            repare.pop(champ, None)

    # Un en-tete decale fait aussi perdre `name` et `index`, et leur absence
    # ne se voit pas dans les chiffres : la facture 2 de Chandra sortait avec
    # « 1 x 45 000 = 45 000 » -- exact -- mais sans nom de medicament. Une
    # ligne juste dont on ignore de quoi elle parle n'est pas exploitable.
    #
    # On les retrouve par le CONTENU, comme le trio numerique :
    #   name  = la colonne la plus alphabetique (les noms de medicaments sont
    #           longs, les unites courtes, les nombres n'en ont pas)
    #   index = une colonne d'entiers petits et croissants
    libres = [i for i in range(largeur) if i not in repare.values()]

    if "name" not in repare and libres:
        def lettres(i):
            return sum(sum(c.isalpha() for c in str(r[i]))
                       for r in data_rows if i < len(r))
        candidat = max(libres, key=lettres)
        if lettres(candidat) >= 3 * len(data_rows):   # au moins ~3 lettres/ligne
            repare["name"] = candidat
            libres.remove(candidat)

    if "index" not in repare and libres:
        def suite_plausible(i):
            vals = [parse_number(r[i]) for r in data_rows if i < len(r)]
            vals = [v for v in vals if v is not None and v <= _MAX_PLAUSIBLE_INDEX]
            if len(vals) < 0.6 * len(data_rows):
                return 0
            return sum(1 for a, b in zip(vals, vals[1:]) if b == a + 1)
        candidat = max(libres, key=suite_plausible)
        if suite_plausible(candidat) >= 0.5 * len(data_rows):
            repare["index"] = candidat

    repare["_repaired"] = True
    return repare


def _is_total_row(row) -> bool:
    joined = _normalize(" ".join(str(c) for c in row))
    return any(kw in joined for kw in TOTAL_KEYWORDS)


def parse_table(table) -> Invoice:
    """Table (merged or not) -> Invoice with typed line items."""
    header_idx = _find_header_index(table)
    header = table.rows[header_idx] if len(table.rows) > header_idx else []
    columns = detect_columns(header)

    # Lignes de donnees plausibles, hors ligne de total : c'est sur elles que
    # la reparation se juge.
    candidates = [r for r in table.rows[header_idx + 1:]
                  if r and not _is_total_row(r)]
    columns = repair_columns(candidates, columns)

    def cell(row, field):
        i = columns.get(field)
        return row[i] if i is not None and i < len(row) else None

    items, grand_total = [], None

    for row in table.rows[header_idx + 1:]:
        if not row:
            continue
        # Un en-tete sur DEUX lignes laisse la seconde derriere lui : elle
        # devient une pseudo-ligne de donnees, sans numero ni montant, et
        # ressort dans `lines_to_check` comme « trop de valeurs manquantes ».
        # Une ligne faite de libelles d'en-tete n'est pas une donnee.
        if _header_score(row) >= 2 and not any(
                parse_number(c) for c in row):
            continue
        if _is_total_row(row):
            # The grand total is the largest number on that row: the other
            # cells are empty or hold the label.
            numbers = [parse_number(c) for c in row]
            numbers = [n for n in numbers if n is not None]
            if numbers:
                grand_total = max(numbers)
            continue

        idx = parse_number(cell(row, "index"))
        qty = parse_number(cell(row, "quantity"))
        up = parse_number(cell(row, "unit_price"))
        tot = parse_number(cell(row, "total"))
        name = str(cell(row, "name") or "").strip()

        # A row with neither a name nor any amount is not a data row
        if not name and qty is None and up is None and tot is None:
            continue

        items.append(LineItem(
            index=idx, name=name,
            unit=str(cell(row, "unit") or "").strip(),
            quantity=qty, unit_price=up, total=tot, raw=list(row),
        ))

    return Invoice(items=items, grand_total=grand_total, columns=columns)
