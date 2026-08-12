"""
Adaptive extraction: read the page twice, keep what holds up.

Pre-processing improves table extraction and degrades header detection --
measured on both models, and no setting made the trade-off go away. Rather
than pick a side, this module reads each photograph in two variants (raw and
pre-processed) and decides per component which reading to keep.

The decision costs no ground truth, which is what makes it usable in
production. An invoice is arithmetically redundant: every line satisfies
quantity x unit_price = total, and the lines sum to the declared grand total.
An extraction that balances is very unlikely to be wrong; one that does not
has been caught. That is the same redundancy already used by
invoice_validate.py to flag lines for review -- here it is used to rank two
candidate readings.

Measured against the exact ground truth (which the policy never sees):

    PaddleOCR-VL    raw 0.909 TEDS, 22/32 fields
                    pre-processed 0.951, 14/32
                    adaptive 0.951, 24/32      ceiling 0.955

    HunyuanOCR-1.5  raw 0.950 TEDS, 25/32 fields
                    pre-processed 0.973, 25/32
                    adaptive 0.974, 28/32      ceiling 0.976

The adaptive policy beats BOTH single variants on BOTH metrics, and lands
within 0.004 of the best achievable choice.

Cost: one extra inference per page -- about 20 s on a T4. Nothing else in the
pipeline changes; the merge and the export take the chosen table as they
would any other.
"""

from dataclasses import dataclass, field
from typing import Optional

from invoice_fields import extract_fields
from invoice_parse import parse_table
from invoice_validate import check_invoice

# Fields the internship subject names explicitly. Order matters: it is the
# order in which sources are consulted, not a ranking of importance.
HEADER_FIELDS = ("hospital_name", "customer_name", "invoice_date", "doctor")


@dataclass
class Confidence:
    """How much an extraction agrees with itself, on a 0..1 scale."""

    score: float
    n_lines: int = 0
    n_consistent: int = 0
    total_ok: Optional[bool] = None
    n_gaps: int = 0
    index_available: bool = False

    def __str__(self):
        if not self.n_lines:
            return "no usable table"
        numbering = (f"{self.n_gaps} numbering gap(s)" if self.index_available
                     else "numbering unreadable")
        return (f"{self.score:.2f} "
                f"({self.n_consistent}/{self.n_lines} lines balance, "
                f"total {'ok' if self.total_ok else 'off'}, {numbering})")


# Weights. Deliberately not tuned: line consistency carries the most because
# it is an average over many independent checks, the grand total is a single
# check on the same data, and numbering continuity catches what arithmetic
# cannot -- a row the OCR dropped entirely still leaves the survivors
# balancing.
W_LINES, W_TOTAL, W_GAPS = 0.60, 0.25, 0.15


def confidence(table) -> Confidence:
    """Score an extracted table WITHOUT ground truth."""
    if table is None:
        return Confidence(0.0)
    invoice = parse_table(table)
    if not invoice.items:
        return Confidence(0.0)

    result = check_invoice(invoice)
    n = result["n_lines"]
    consistent = result["n_ok"] + result["n_corrected"]

    # Absence de preuve n'est pas preuve : un signal illisible ne rapporte
    # rien, il ne coute rien non plus. Le total suivait deja cette regle ;
    # la numerotation, non -- une colonne STT detruite valait le bonus plein
    # « aucun trou », si bien qu'abimer la lecture faisait MONTER la note
    # (0,600 -> 0,750 sur un tableau ou le trou est reel).
    #
    # On ne renormalise surtout pas les poids sur les signaux disponibles :
    # ca reviendrait a recompenser la perte d'information encore plus fort.
    score = (W_LINES * (consistent / n if n else 0.0)
             + W_TOTAL * (1.0 if result["total_ok"] else 0.0)
             + W_GAPS * (1.0 if (result["index_available"]
                                 and not result["index_gaps"]) else 0.0))

    return Confidence(score, n, consistent, result["total_ok"],
                      len(result["index_gaps"]),
                      result["index_available"])


# En dessous de cette part de lignes communes, les deux lectures ne decrivent
# pas le meme document. Le seuil est volontairement bas : deux lectures du
# MEME document, meme tres abimees, partagent bien plus du tiers de leurs
# noms de medicaments ; deux factures differentes n'en partagent presque
# aucun (mesure sur le jeu encombre : 2/21 pour la facture 4).
_SEUIL_CONCORDANCE = 0.30

# Sous ce nombre de lignes lisibles, la concordance n'est pas significative.
_MIN_LIGNES_CONCORDANCE = 3


def _nom_normalise(texte: str) -> str:
    return " ".join(str(texte).lower().split())


def concordance(table_a, table_b) -> Optional[float]:
    """Les deux tableaux decrivent-ils le MEME document ?

    C'est le signal de provenance qui manquait. La confiance arithmetique
    note la coherence interne d'un tableau -- elle ne peut pas voir qu'un
    recadrage parti sur une feuille voisine a produit une facture parfaite
    mais etrangere (11/11 lignes equilibrees, confiance 0,75, et 2
    medicaments sur 21 en commun avec la verite : facture 4 du jeu a fonds
    encombres).

    L'asymetrie qui rend le test possible : la lecture BRUTE voit la scene
    entiere, la facture cible est forcement dans son champ, et son tableau
    principal -- le plus grand -- est presque toujours le bon. La lecture
    pretraitee, elle, peut porter sur n'importe quelle feuille. Si leurs
    contenus ne se recoupent pas, c'est le recadrage qui est parti ailleurs.

    On compare les noms de medicaments, pas les nombres : deux factures de la
    meme pharmacie partagent des prix ronds, presque jamais leurs listes de
    produits. La similarite est tolerante (SequenceMatcher >= 0,7) parce que
    les memes noms lus deux fois portent des degats OCR differents.

    Rend None quand le test n'est pas significatif (trop peu de lignes d'un
    cote ou de l'autre) : l'appelant retombe alors sur l'arbitrage normal.
    """
    from difflib import SequenceMatcher

    if table_a is None or table_b is None:
        return None
    noms_a = [_nom_normalise(i.name) for i in parse_table(table_a).items if i.name]
    noms_b = [_nom_normalise(i.name) for i in parse_table(table_b).items if i.name]
    if len(noms_a) < _MIN_LIGNES_CONCORDANCE or len(noms_b) < _MIN_LIGNES_CONCORDANCE:
        return None

    communs = 0
    for nom in noms_b:
        if any(SequenceMatcher(None, nom, autre).ratio() >= 0.7
               for autre in noms_a):
            communs += 1
    return communs / len(noms_b)


@dataclass
class Choice:
    """What the policy kept, and why."""

    table: object = None
    table_source: str = ""
    fields: dict = field(default_factory=dict)
    field_sources: dict = field(default_factory=dict)
    confidences: dict = field(default_factory=dict)
    # None : test non significatif ; sinon la part des lignes pretraitees
    # retrouvees dans la lecture brute.
    concordance: Optional[float] = None
    provenance_rejetee: bool = False


def choose(candidates, prefer_table="raw",
           field_order=("raw", "preprocessed")):
    """Pick the best table and the best value for each header field.

    `candidates` maps a source name to (table, page_texts):

        {"raw": (table_a, [md_page1, md_page2]),
         "preprocessed": (table_b, [...])}

    Two independent decisions, because the two components fail
    independently:

    TABLE -- highest confidence wins. On a tie, `prefer_table` breaks it :
    quand les deux lectures bouclent parfaitement, l'arithmetique ne peut
    plus les separer et il faut un depart arbitraire.

    Il pointait vers la lecture PRETRAITEE, ce qui valait alors +0,010 TEDS.
    Remesure sur Chandra, avec les jeux dont on dispose aujourd'hui :

        jeu                 depart "preprocessed"   depart "raw"
        multipage                       0,966           0,967  (= plafond)
        variants_warped                 0,977           0,977  (= plafond)
        variants_encombre               0,154           0,257

    Le depart vers la lecture brute n'est jamais moins bon, et il evite un
    effondrement. La raison est asymetrique : un mauvais recadrage produit un
    tableau qui BOUCLE quand meme -- il est arithmetiquement parfait, il
    porte simplement sur le mauvais bout de papier. La facture 4 du jeu
    encombre en est l'exemple : 11 lignes sur 11 equilibrees, aucun trou de
    numerotation, confiance 0,75... et 2 medicaments sur 21 en commun avec la
    verite terrain. La lecture brute, elle, ne peut pas se tromper de
    document : au pire elle lit mal, jamais ailleurs.

    C'est aussi la limite de fond de cette politique, a dire telle quelle :
    la confiance note la COHERENCE d'un tableau, pas sa PROVENANCE. Aucun
    reglage du depart ne la corrigera ; il faudrait un signal sur le
    recadrage lui-meme.

    HEADER FIELDS -- first non-empty value in `field_order`. There is no
    arithmetic to check a patient name against, so redundancy cannot rank
    these; what the measurements DO establish is that the raw image is more
    reliable for them (8/8 hospital names against 5/8). A field missing from
    the first source is taken from the second, which is where the gain comes
    from: 24/32 against 22 and 14 for the single variants.
    """
    result = Choice()

    for name, (table, _) in candidates.items():
        result.confidences[name] = confidence(table)

    # Verification de PROVENANCE, avant l'arbitrage par confiance.
    #
    # La confiance ne sait comparer que des coherences internes, et un
    # recadrage parti sur une feuille voisine produit un tableau
    # parfaitement coherent. On ecarte donc d'abord toute lecture pretraitee
    # dont le contenu ne recoupe pas celui de la lecture brute -- qui, elle,
    # ne peut pas s'etre trompee de scene.
    en_lice = dict(candidates)
    if "raw" in candidates and "preprocessed" in candidates:
        result.concordance = concordance(candidates["raw"][0],
                                         candidates["preprocessed"][0])
        if (result.concordance is not None
                and result.concordance < _SEUIL_CONCORDANCE):
            result.provenance_rejetee = True
            del en_lice["preprocessed"]

    best = max(((n, result.confidences[n]) for n in en_lice),
               key=lambda kv: (kv[1].score, kv[0] == prefer_table))
    result.table_source = best[0]
    result.table = candidates[best[0]][0]

    for name in HEADER_FIELDS:
        for source in field_order:
            if source not in candidates:
                continue
            for text in candidates[source][1]:
                value = extract_fields(text).get(name)
                if value:
                    result.fields[name] = value
                    result.field_sources[name] = source
                    break
            if name in result.fields:
                break
        result.fields.setdefault(name, None)

    return result
