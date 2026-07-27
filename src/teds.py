"""
TEDS -- Tree-Edit-Distance-based Similarity.

Metrique standard d'evaluation de la reconnaissance de tableaux, introduite
avec PubTabNet (Zhong et al., 2020, "Image-based table recognition: data,
model, and evaluation") et reprise dans les competitions ICDAR. L'interet
d'utiliser CETTE metrique plutot qu'un score maison : les chiffres obtenus
sont directement comparables a la litterature.

Principe
--------
Un tableau HTML est un arbre (table -> tr -> td, avec colspan/rowspan et le
texte dans les feuilles). On mesure le nombre minimal d'operations d'edition
(inserer / supprimer / renommer un noeud) pour transformer l'arbre predit en
l'arbre attendu, puis on normalise :

    TEDS = 1 - distance_edition / max(nb_noeuds_predit, nb_noeuds_vrai)

Resultat entre 0 (rien ne correspond) et 1 (identique).

Le cout de "renommage" d'une cellule n'est pas binaire : c'est la distance
d'edition normalisee entre les deux textes. Lire "Aspirin 300mq" au lieu de
"Aspirin 300mg" coute donc beaucoup moins cher que de rater la cellule.

Deux variantes
--------------
  TEDS         : structure + contenu textuel
  TEDS-Struct  : structure seule (le texte des cellules est ignore)

Les rapporter toutes les deux permet de separer deux erreurs de nature tres
differente : une grille mal reconstruite (colonnes fusionnees, lignes
decalees) et un texte mal lu (diacritiques vietnamiens abimes par la
deformation 3D). Un ecart important entre les deux scores dit laquelle des
deux domine.
"""

from html.parser import HTMLParser

from apted import APTED, Config
from apted.helpers import Tree  # noqa: F401  (dependance apted requise)


# --------------------------------------------------------------------------
# Representation en arbre
# --------------------------------------------------------------------------

class TableTree:
    """Noeud d'arbre de tableau, au format attendu par APTED."""

    def __init__(self, tag, colspan=1, rowspan=1, content=None, children=None):
        self.tag = tag
        self.colspan = colspan
        self.rowspan = rowspan
        self.content = content if content is not None else []
        self.children = children if children is not None else []

    def bracket(self):
        """Representation utilisee par APTED pour identifier le noeud."""
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
    """Couts d'edition. `structure_only` ignore le texte des cellules."""

    def __init__(self, structure_only=False):
        self.structure_only = structure_only

    @staticmethod
    def _normalized_levenshtein(a, b) -> float:
        """Distance d'edition entre deux chaines, ramenee entre 0 et 1."""
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
                    previous[j] + 1,            # suppression
                    current[j - 1] + 1,         # insertion
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
# HTML -> arbre
# --------------------------------------------------------------------------

class _TreeBuilder(HTMLParser):
    """Construit l'arbre TableTree a partir du premier <table> rencontre."""

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
            # th et td sont traites pareil : les modeles OCR ne distinguent
            # pas de facon fiable l'entete du corps du tableau.
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
    """Retourne l'arbre du premier tableau trouve, ou None."""
    builder = _TreeBuilder()
    builder.feed(html)
    return builder.root


# --------------------------------------------------------------------------
# Metrique
# --------------------------------------------------------------------------

def teds(pred_html: str, true_html: str, structure_only: bool = False) -> float:
    """Score TEDS entre deux tableaux HTML. 0.0 si l'un des deux est vide."""
    pred_tree = html_to_tree(pred_html)
    true_tree = html_to_tree(true_html)
    if pred_tree is None or true_tree is None:
        return 0.0

    distance = APTED(pred_tree, true_tree, _Config(structure_only)).compute_edit_distance()
    return 1.0 - distance / max(pred_tree.n_nodes(), true_tree.n_nodes())


def rows_to_html(rows) -> str:
    """Serialise une liste de lignes (listes de cellules) en tableau HTML."""
    def esc(cell):
        return (str(cell).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    body = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in row) + "</tr>"
                   for row in rows)
    return f"<table><tbody>{body}</tbody></table>"
