"""
TEDS -- Tree-Edit-Distance-based Similarity.

The standard metric for table recognition, introduced with PubTabNet (Zhong
et al., 2020, "Image-based table recognition: data, model, and evaluation")
and reused in the ICDAR competitions. Using THIS metric rather than a
home-grown score means the numbers are directly comparable to the
literature.

Principle
---------
An HTML table is a tree (table -> tr -> td, with colspan/rowspan and text in
the leaves). We measure the minimum number of edit operations (insert /
delete / rename a node) needed to turn the predicted tree into the expected
one, then normalise:

    TEDS = 1 - edit_distance / max(n_nodes_pred, n_nodes_true)

Result between 0 (nothing matches) and 1 (identical).

Renaming a cell is not a binary cost: it is the normalised edit distance
between the two strings. Reading "Aspirin 300mq" instead of "Aspirin 300mg"
is therefore far cheaper than missing the cell entirely.

Two variants
------------
  TEDS         : structure + text content
  TEDS-Struct  : structure only (cell text ignored)

Reporting both separates two very different kinds of error: a badly
reconstructed grid (merged columns, shifted rows) versus badly read text
(Vietnamese diacritics damaged by the 3D warping). A large gap between the
two scores tells you which one dominates.
"""

from html.parser import HTMLParser

from apted import APTED, Config
from apted.helpers import Tree  # noqa: F401  (apted dependency required)


# --------------------------------------------------------------------------
# Tree representation
# --------------------------------------------------------------------------

class TableTree:
    """Table tree node, in the shape APTED expects."""

    def __init__(self, tag, colspan=1, rowspan=1, content=None, children=None):
        self.tag = tag
        self.colspan = colspan
        self.rowspan = rowspan
        self.content = content if content is not None else []
        self.children = children if children is not None else []

    def bracket(self):
        """Representation APTED uses to identify the node."""
        if self.tag == "td":
            result = f'"tag": {self.tag}, "colspan": {self.colspan}, ' \
                     f'"rowspan": {self.rowspan}, "text": {"".join(self.content)}'
        else:
            result = f'"tag": {self.tag}'
        for child in self.children:
            result += child.bracket()
        return "{" + result + "}"

    def n_nodes(self):
        return 1 + sum(c.n_nodes() for c in self.children)


class _Config(Config):
    """Edit costs. `structure_only` ignores cell text."""

    def __init__(self, structure_only=False):
        self.structure_only = structure_only

    @staticmethod
    def _normalized_levenshtein(a, b) -> float:
        """Edit distance between two strings, scaled to 0..1."""
        a, b = list(a), list(b)
        if not a and not b:
            return 0.0
        if not a or not b:
            return 1.0
        previous = list(range(len(b) + 1))
        for i, ca in enumerate(a, start=1):
            current = [i]
            for j, cb in enumerate(b, start=1):
                current.append(min(
                    previous[j] + 1,              # deletion
                    current[j - 1] + 1,           # insertion
                    previous[j - 1] + (ca != cb)  # substitution
                ))
            previous = current
        return previous[-1] / max(len(a), len(b))

    def rename(self, node1, node2) -> float:
        if (node1.tag != node2.tag
                or node1.colspan != node2.colspan
                or node1.rowspan != node2.rowspan):
            return 1.0
        if node1.tag == "td" and not self.structure_only:
            if node1.content or node2.content:
                return self._normalized_levenshtein(node1.content, node2.content)
        return 0.0

    def children(self, node):
        return node.children


# --------------------------------------------------------------------------
# HTML -> tree
# --------------------------------------------------------------------------

class _TreeBuilder(HTMLParser):
    """Builds the TableTree from the first <table> encountered."""

    _STRUCTURAL = {"table", "thead", "tbody", "tr"}

    def __init__(self):
        super().__init__()
        self.root = None
        self._stack = []
        self._cell = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in self._STRUCTURAL:
            node = TableTree(tag)
            if self.root is None:
                self.root = node
            elif self._stack:
                self._stack[-1].children.append(node)
            self._stack.append(node)
        elif tag in ("td", "th"):
            # th and td are treated alike: OCR models do not reliably
            # distinguish the header from the body of a table.
            self._cell = TableTree(
                "td",
                colspan=int(attrs.get("colspan", 1) or 1),
                rowspan=int(attrs.get("rowspan", 1) or 1),
            )
            if self._stack:
                self._stack[-1].children.append(self._cell)

    def handle_endtag(self, tag):
        if tag in self._STRUCTURAL and self._stack:
            self._stack.pop()
        elif tag in ("td", "th"):
            self._cell = None

    def handle_data(self, data):
        if self._cell is not None:
            text = data.strip()
            if text:
                self._cell.content.extend(list(text))


def html_to_tree(html: str):
    """Return the tree of the first table found, or None."""
    builder = _TreeBuilder()
    builder.feed(html)
    return builder.root


# --------------------------------------------------------------------------
# Metric
# --------------------------------------------------------------------------

# Au-dela de ce rapport de taille entre les deux arbres, la prediction est
# declaree DEGENEREE et notee 0 sans appeler APTED.
#
# Ce n'est pas un raccourci de confort, c'est une borne demontrable. La
# distance d'edition vaut au moins la difference des nombres de noeuds : il
# faut bien inserer ou supprimer l'ecart. Donc
#
#     TEDS <= 1 - |n_pred - n_vrai| / max(...) = min(...) / max(...) = 1 / r
#
# ou r est le rapport de taille. A r = 4, le score ne pouvait pas depasser
# 0,25 ; l'arrondir a 0 ne change aucune conclusion.
#
# Pourquoi il en faut un. APTED est cubique. Sur une page ou le modele part
# en boucle -- 288 lignes la ou la verite en a 20 -- il ne rend jamais la
# main. Mesure sur variants_encombre_preproc_chandra : l'evaluation se
# figeait a l'invoice 9, sans erreur ni message, et `eval_all.py` qui capture
# la sortie n'affichait RIEN. Un garde-fou sur la TAILLE plutot qu'un delai
# d'attente garde le score reproductible d'une machine a l'autre.
_RAPPORT_DEGENERE = 4.0

# En dessous de cette taille, APTED termine de toute facon : inutile de
# renoncer a un vrai calcul sur un petit tableau tres incomplet.
_TAILLE_MINI_GARDE = 120


def teds(pred_html: str, true_html: str, structure_only: bool = False) -> float:
    """TEDS score between two HTML tables. 0.0 if either one is empty."""
    pred_tree = html_to_tree(pred_html)
    true_tree = html_to_tree(true_html)
    if pred_tree is None or true_tree is None:
        return 0.0

    n_pred, n_true = pred_tree.n_nodes(), true_tree.n_nodes()
    grand = max(n_pred, n_true)

    # Le garde-fou ne joue QUE dans le sens couteux, celui ou la prediction
    # est trop grosse. Une prediction trop PETITE ne coute rien a APTED, et
    # son score est calculable : le zeroter par symetrie jetterait une
    # information exacte pour rien.
    if n_pred > _TAILLE_MINI_GARDE and n_pred > _RAPPORT_DEGENERE * n_true:
        return 0.0

    distance = APTED(pred_tree, true_tree, _Config(structure_only)).compute_edit_distance()

    # Le plancher a zero n'est pas cosmetique.
    #
    # La formule de PubTabNet normalise par max(n_pred, n_vrai), mais la
    # distance d'edition peut DEPASSER ce maximum : l'appariement doit
    # respecter l'ordre et la filiation, donc quand les deux grilles n'ont
    # rien a voir, renommer devient impossible et il faut tout supprimer puis
    # tout reinserer. On observe alors -0,011 -- une similarite negative, qui
    # ne veut rien dire et qui tire la moyenne sous le minimum atteignable.
    return max(0.0, 1.0 - distance / grand)


def diagnostic(pred_html: str, true_html: str) -> dict:
    """Taille des deux arbres et nature de l'echec, sans rien calculer.

    Deux echecs de forme, opposes, que le score seul confond en un 0,000 :

      emballe   la prediction est bien plus grosse que la verite -- le modele
                a boucle. C'est le cas que le garde-fou intercepte.
      tronque   elle est bien plus petite -- il n'a presque rien lu.

    Ils appellent des reponses differentes, d'ou l'interet de les nommer.
    """
    pred_tree = html_to_tree(pred_html)
    true_tree = html_to_tree(true_html)
    vide = {"n_pred": 0, "n_vrai": 0, "rapport": 0.0,
            "emballe": False, "tronque": False, "degenere": False}
    if pred_tree is None or true_tree is None:
        return vide

    n_pred, n_true = pred_tree.n_nodes(), true_tree.n_nodes()
    if not n_true:
        return vide
    emballe = (n_pred > _TAILLE_MINI_GARDE
               and n_pred > _RAPPORT_DEGENERE * n_true)
    tronque = n_pred * _RAPPORT_DEGENERE < n_true
    return {"n_pred": n_pred, "n_vrai": n_true, "rapport": n_pred / n_true,
            "emballe": emballe, "tronque": tronque,
            "degenere": emballe or tronque}


def rows_to_html(rows) -> str:
    """Serialise a list of rows (lists of cells) into an HTML table."""
    def esc(cell):
        return (str(cell).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    body = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in row) + "</tr>"
                   for row in rows)
    return f"<table><tbody>{body}</tbody></table>"
