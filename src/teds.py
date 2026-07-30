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

def teds(pred_html: str, true_html: str, structure_only: bool = False) -> float:
    """TEDS score between two HTML tables. 0.0 if either one is empty."""
    pred_tree = html_to_tree(pred_html)
    true_tree = html_to_tree(true_html)
    if pred_tree is None or true_tree is None:
        return 0.0

    distance = APTED(pred_tree, true_tree, _Config(structure_only)).compute_edit_distance()
    return 1.0 - distance / max(pred_tree.n_nodes(), true_tree.n_nodes())


def rows_to_html(rows) -> str:
    """Serialise a list of rows (lists of cells) into an HTML table."""
    def esc(cell):
        return (str(cell).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    body = "".join("<tr>" + "".join(f"<td>{esc(c)}</td>" for c in row) + "</tr>"
                   for row in rows)
    return f"<table><tbody>{body}</tbody></table>"
