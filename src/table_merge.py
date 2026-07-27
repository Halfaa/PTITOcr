"""
Fusion de tableaux coupes sur plusieurs pages.

Detecte quand un tableau extrait d'une page N est la continuation d'un
tableau extrait de la page N-1 (meme facture, tableau de medicaments qui
deborde), et les fusionne en un tableau logique unique.

Fonctionne sur les sorties PaddleOCR-VL / PP-StructureV3 (tableaux en HTML
<table>...</table> a l'interieur du markdown de sortie).

Principe : on ne se fie jamais a un seul signal (trop fragile en presence de
bruit OCR). La decision combine plusieurs signaux independants :

  1. marqueur de continuation explicite ("Tiep trang truoc" / "continued")
     cherche dans TOUT le texte de la page B, pas seulement dans le tableau
     -- en pratique l'OCR sort ce marqueur comme bloc de texte separe.
  2. continuite de la colonne d'index (STT) : derniere ligne de A = N,
     premiere ligne de B = N+1
  3. meme nombre de colonnes + entetes similaires
  4. absence de ligne "Total" a la fin du tableau A (un tableau qui se
     termine normalement n'est pas coupe)

Un signal fort (1 ou 2) suffit a lui seul. A defaut, il faut la combinaison
du signal 3 sans le signal 4 contraire.

--------------------------------------------------------------------------
Robustesse au bruit OCR reel (constate sur les sorties PP-StructureV3) :

  * la 1re ligne du <table> n'est PAS forcement l'entete : l'OCR y insere
    souvent une ligne parasite ("vien 3 200"). L'entete est donc *cherchee*
    par mots-cles (STT / Ten mat hang / DVT / ...) au lieu d'etre supposee.
  * les cellules sont parfois permutees : l'index STT peut se retrouver en
    derniere colonne. On regarde donc la 1re ET la derniere cellule.
  * les montants (2900, 24000...) ne doivent jamais etre pris pour des
    index -> plafond _MAX_PLAUSIBLE_INDEX.
  * comparaisons de texte tolerantes (difflib) : "so luong" / "so lugng" /
    "soluong" doivent matcher.
"""

from dataclasses import dataclass
from difflib import SequenceMatcher
from html.parser import HTMLParser
import re
import unicodedata


@dataclass
class Table:
    rows: list  # liste de lignes, chaque ligne = liste de cellules (texte)
    raw_html: str = ""

    @property
    def n_cols(self):
        return max((len(r) for r in self.rows), default=0)

    @property
    def header(self):
        idx = _find_header_index(self)
        return self.rows[idx] if len(self.rows) > idx else []

    @property
    def data_rows(self):
        return self.rows[_find_header_index(self) + 1:]


class _TableHTMLParser(HTMLParser):
    """Parseur HTML minimaliste (stdlib, pas de dependance externe) : extrait
    toutes les <table> d'un bloc de texte sous forme de Table()."""

    def __init__(self):
        super().__init__()
        self.tables = []
        self._in_table = False
        self._in_row = False
        self._in_cell = False
        self._current_table_rows = None
        self._current_row = None
        self._current_cell_text = None
        self._current_table_html = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._in_table = True
            self._current_table_rows = []
            self._current_table_html = ["<table>"]
            return
        if not self._in_table:
            return
        self._current_table_html.append(self._start_tag_str(tag, attrs))
        if tag == "tr":
            self._in_row = True
            self._current_row = []
        elif tag in ("td", "th"):
            self._in_cell = True
            self._current_cell_text = []

    @staticmethod
    def _start_tag_str(tag, attrs):
        attr_str = "".join(f' {k}="{v}"' for k, v in attrs)
        return f"<{tag}{attr_str}>"

    def handle_endtag(self, tag):
        if not self._in_table:
            return
        self._current_table_html.append(f"</{tag}>")
        if tag in ("td", "th") and self._in_cell:
            text = "".join(self._current_cell_text).strip()
            self._current_row.append(text)
            self._in_cell = False
        elif tag == "tr" and self._in_row:
            self._current_table_rows.append(self._current_row)
            self._in_row = False
        elif tag == "table":
            self.tables.append(Table(rows=self._current_table_rows,
                                     raw_html="".join(self._current_table_html)))
            self._in_table = False

    def handle_data(self, data):
        if self._in_cell:
            self._current_cell_text.append(data)


def extract_tables(markdown_or_html: str) -> list:
    """Retourne la liste des Table() trouvees dans un texte (markdown ou HTML brut)."""
    parser = _TableHTMLParser()
    parser.feed(markdown_or_html)
    return parser.tables


# --------------------------------------------------------------------------
# Normalisation / comparaison tolerante au bruit OCR
# --------------------------------------------------------------------------

def _normalize(s) -> str:
    """Minuscules, sans accents, espaces normalises."""
    s = unicodedata.normalize("NFKD", str(s).lower().strip())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s)


def _fuzzy_eq(a, b, threshold: float = 0.75) -> bool:
    """Egalite tolerante : 'so luong' == 'so lugng' == 'soluong'.
    L'OCR confond regulierement u/g/y et avale les espaces ; une egalite
    stricte rejetterait des entetes pourtant identiques."""
    a, b = _normalize(a), _normalize(b)
    if not a or not b:
        return False
    if a == b or a.replace(" ", "") == b.replace(" ", ""):
        return True
    return SequenceMatcher(None, a, b).ratio() >= threshold


# Mots-cles de l'entete du tableau de medicaments (facture vietnamienne).
_HEADER_KEYWORDS = [
    "stt", "ten mat hang", "dich vu", "dvt",
    "so luong", "don gia", "thanh tien",
]
_CONTINUATION_KEYWORDS = ["tiep trang truoc", "suite", "continued", "tiep theo"]
_END_KEYWORDS = ["tong tien", "total", "grand total", "tong cong"]
_NEXT_PAGE_KEYWORDS = ["xem tiep trang sau", "continued on next page", "suite page suivante"]

# Un index STT plausible reste petit. Sans ce plafond, un montant (2900,
# 24000...) mal place serait pris pour un numero de ligne.
_MAX_PLAUSIBLE_INDEX = 200


def _row_contains_any(row, keywords) -> bool:
    joined = _normalize(" ".join(str(c) for c in row))
    return any(kw in joined for kw in keywords)


def _text_contains_any(text: str, keywords) -> bool:
    """Cherche des mots-cles dans du texte libre (markdown d'une page entiere).
    Les balises HTML sont retirees pour eviter les faux positifs."""
    if not text:
        return False
    plain = _normalize(re.sub(r"<[^>]+>", " ", text))
    return any(kw in plain for kw in keywords)


# --------------------------------------------------------------------------
# Detection de la ligne d'entete
# --------------------------------------------------------------------------

def _header_score(row) -> int:
    """Nombre de mots-cles d'entete retrouves dans la ligne."""
    if not row:
        return 0
    return sum(1 for kw in _HEADER_KEYWORDS
               if any(_fuzzy_eq(kw, cell) for cell in row))


def _find_header_index(table: "Table", search_depth: int = 4) -> int:
    """Indice de la VRAIE ligne d'entete.

    L'OCR insere frequemment une ligne parasite avant l'entete (fragment de
    texte de la page capture dans le tableau), et le marqueur de continuation
    peut aussi occuper la 1re ligne. On cherche donc, parmi les premieres
    lignes, celle qui ressemble le plus a un entete.
    """
    rows = table.rows
    if not rows:
        return 0

    best_idx, best_score = 0, 0
    for i, row in enumerate(rows[:search_depth]):
        score = _header_score(row)
        if score > best_score:
            best_idx, best_score = i, score

    if best_score >= 2:
        return best_idx

    # Repli : au minimum, sauter une ligne "marqueur de continuation".
    if _row_contains_any(rows[0], _CONTINUATION_KEYWORDS) and len(rows) > 1:
        return 1
    return 0


def _header_similarity(h1, h2) -> float:
    """0.0 a 1.0. Comparaison ENSEMBLISTE (et non colonne par colonne) car
    l'OCR permute parfois les colonnes : deux entetes identiques peuvent
    apparaitre dans un ordre different."""
    if not h1 or not h2:
        return 0.0
    matches = sum(1 for c in h1 if any(_fuzzy_eq(c, d) for d in h2))
    return matches / len(h1)


# --------------------------------------------------------------------------
# Detection de la colonne d'index (STT)
# --------------------------------------------------------------------------

def _numeric_index(cell):
    cell = str(cell).strip()
    if not cell.isdigit():
        return None
    value = int(cell)
    return value if 0 < value <= _MAX_PLAUSIBLE_INDEX else None


def _row_index_candidates(row):
    """Valeurs pouvant etre l'index STT de la ligne.

    On regarde la 1re ET la derniere cellule : l'OCR fait parfois glisser la
    colonne STT en fin de ligne (constate sur les sorties PP-StructureV3)."""
    if not row:
        return []
    cells = [row[0]] if len(row) == 1 else [row[0], row[-1]]
    return [v for v in (_numeric_index(c) for c in cells) if v is not None]


def _index_sequence(table: "Table"):
    """Suite des index STT des lignes de donnees (valeurs manquantes ignorees).

    Quand une ligne offre deux candidats (index en 1re et en derniere
    position), on retient celui qui prolonge la suite deja construite."""
    seq = []
    for row in table.data_rows:
        candidates = _row_index_candidates(row)
        if not candidates:
            continue
        previous = seq[-1] if seq else None
        if previous is not None and previous + 1 in candidates:
            seq.append(previous + 1)
        else:
            seq.append(candidates[0])
    return seq


def _last_data_index(table: "Table"):
    """Plus grand index du tableau -- et non le dernier de la suite : une
    seule ligne bruitee en fin de tableau (cellules permutees, quantite lue
    a la place du STT) suffirait sinon a fausser completement le signal."""
    seq = _index_sequence(table)
    return max(seq) if seq else None


def _first_data_index(table: "Table"):
    """Premier index rencontre -- ici on garde bien la 1re valeur brute :
    c'est elle qui dit si le tableau *redemarre a 1* (nouvelle facture) ou
    reprend en cours de numerotation (continuation)."""
    seq = _index_sequence(table)
    return seq[0] if seq else None


# --------------------------------------------------------------------------
# Decision
# --------------------------------------------------------------------------

def is_continuation(table_a: Table, table_b: Table,
                    page_text_a: str = "", page_text_b: str = "",
                    min_header_similarity: float = 0.6) -> dict:
    """
    Determine si table_b est la suite de table_a. Retourne un dict avec la
    decision ET le detail des signaux (utile pour justifier/debugger,
    important dans un contexte de recherche ou il faut pouvoir expliquer
    pourquoi une fusion a (ou n'a pas) eu lieu).

    page_text_a / page_text_b : markdown complet des pages correspondantes.
    Les marqueurs "suite page suivante" / "suite de la page precedente" sont
    presque toujours extraits comme texte HORS du tableau -- les chercher
    uniquement dans les lignes du tableau les manque systematiquement.
    """
    signals = {}

    signals["same_col_count"] = table_a.n_cols == table_b.n_cols and table_a.n_cols > 0

    a_rows = table_a.data_rows
    signals["table_a_ends_with_total"] = (
        (bool(a_rows) and _row_contains_any(a_rows[-1], _END_KEYWORDS))
        or _text_contains_any(page_text_a, _END_KEYWORDS)
    )
    signals["table_a_has_next_page_marker"] = (
        (bool(a_rows) and _row_contains_any(a_rows[-1], _NEXT_PAGE_KEYWORDS))
        or _text_contains_any(page_text_a, _NEXT_PAGE_KEYWORDS)
    )
    signals["table_b_has_continuation_marker"] = (
        (bool(table_b.rows) and _row_contains_any(table_b.rows[0], _CONTINUATION_KEYWORDS))
        or _text_contains_any(page_text_b, _CONTINUATION_KEYWORDS)
    )

    signals["header_similarity"] = _header_similarity(table_a.header, table_b.header)

    last_idx_a = _last_data_index(table_a)
    first_idx_b = _first_data_index(table_b)
    signals["last_index_a"] = last_idx_a
    signals["first_index_b"] = first_idx_b
    signals["index_continuity"] = (
        last_idx_a is not None and first_idx_b is not None and first_idx_b == last_idx_a + 1
    )
    # Tolerance : l'OCR perd parfois une ligne entiere a la charniere entre
    # deux pages. Un saut de 1 a 3 reste compatible avec une continuation,
    # alors qu'un retour en arriere ne l'est pas.
    signals["index_near_continuity"] = (
        last_idx_a is not None and first_idx_b is not None
        and 0 < first_idx_b - last_idx_a <= 3
    )
    # Disqualifiant : si table_b redemarre a 1, c'est presque surement une
    # NOUVELLE table (nouvelle facture), meme si les entetes se ressemblent
    # (toutes les factures de ce generateur partagent le meme gabarit de
    # colonnes -> la similarite d'entete seule ne suffit jamais a distinguer
    # "continuation" de "nouvelle facture identique en forme").
    signals["table_b_restarts_at_1"] = first_idx_b == 1
    # Symetrique du precedent, et signal le plus robuste en pratique : si B
    # commence a un index > 1, la numerotation vient forcement d'ailleurs.
    # Hypothese metier assumee : le STT redemarre a 1 a chaque facture.
    # C'est ce signal qui rattrape les cas ou l'OCR a massacre la fin du
    # tableau A (index de fin illisible) -- la continuite +1 est alors
    # inverifiable, mais "B commence a 20" reste parlant.
    signals["table_b_starts_mid_numbering"] = first_idx_b is not None and first_idx_b > 1
    # Garde-fou "meme tableau" : exiger un nombre de colonnes strictement
    # identique est trop dur, l'OCR ajoute ou perd regulierement une colonne
    # d'une page a l'autre. Un entete suffisamment ressemblant fait aussi
    # bien l'affaire.
    signals["compatible_shape"] = signals["same_col_count"] or signals["header_similarity"] >= 0.5

    strong_signal = (
        signals["table_b_has_continuation_marker"]
        or signals["index_continuity"]
        or (signals["index_near_continuity"] and signals["compatible_shape"])
        or (signals["table_b_starts_mid_numbering"]
            and signals["compatible_shape"]
            and not signals["table_a_ends_with_total"])
    )
    weak_signal = (
        signals["same_col_count"]
        and signals["header_similarity"] >= min_header_similarity
        and not signals["table_a_ends_with_total"]
        and (signals["table_a_has_next_page_marker"] or last_idx_a is None or first_idx_b is None)
        and not signals["table_b_restarts_at_1"]
    )

    disqualified = signals["table_b_restarts_at_1"] and not signals["table_b_has_continuation_marker"]
    signals["decision"] = bool(strong_signal or weak_signal) and not disqualified
    signals["confidence"] = "forte" if strong_signal else ("faible" if weak_signal else "aucune")
    return signals


def merge_tables(table_a: Table, table_b: Table, decision: dict = None) -> Table:
    """Fusionne table_b a la suite de table_a : retire la ligne "marqueur de
    continuation" et l'entete repetee de table_b, garde un seul entete."""
    merged_rows = list(table_a.rows)

    # Si la derniere ligne de A est un marqueur "voir page suivante" (et pas
    # une vraie ligne de donnees), on la retire de la fusion.
    if merged_rows and _row_contains_any(merged_rows[-1], _NEXT_PAGE_KEYWORDS):
        merged_rows = merged_rows[:-1]

    # De table_b on ne garde que les lignes de donnees : tout ce qui precede
    # son entete (parasite OCR, marqueur de continuation) et l'entete elle-meme
    # sont des artefacts de la coupure de page.
    merged_rows.extend(table_b.data_rows)
    return Table(rows=merged_rows)


def merge_table_sequence(tables: list, page_texts: list = None,
                         min_header_similarity: float = 0.6):
    """
    Prend une liste de Table() (une par page, dans l'ordre) et retourne une
    liste de Table() fusionnees : chaque element est soit une table qui ne
    continue pas ailleurs, soit le resultat de la fusion de plusieurs pages
    consecutives. Retourne aussi le detail des decisions prises.

    page_texts : markdown complet de chaque page, meme ordre que `tables`
    (optionnel mais fortement recommande, cf. is_continuation).
    """
    if not tables:
        return [], []

    texts = list(page_texts) if page_texts else [""] * len(tables)
    merged = [tables[0]]
    # Texte de la derniere page du groupe courant : c'est elle qui porte
    # l'eventuel marqueur "suite page suivante".
    current_text = texts[0]
    decisions = []

    for t, text in zip(tables[1:], texts[1:]):
        decision = is_continuation(merged[-1], t, current_text, text, min_header_similarity)
        decisions.append(decision)
        if decision["decision"]:
            merged[-1] = merge_tables(merged[-1], t, decision)
        else:
            merged.append(t)
        current_text = text

    return merged, decisions
