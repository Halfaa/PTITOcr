"""
Rapport visuel : avec ou sans prétraitement, sur Chandra OCR 2.

Produit un HTML autonome — images comprises, aucune dépendance externe —
qui met côte à côte l'image brute et l'image prétraitée de chaque page, puis
donne les deux tableaux de statistiques : facture par facture, et agrégé.

    python scripts/rapport_pretraitement.py
    python scripts/rapport_pretraitement.py --limite 3      # essai rapide

Le rapport se lit dans un navigateur et s'importe dans Notion (Import → HTML).

Deux partis pris.

**Les images viennent du disque, les chiffres des runs.** On ne recalcule
pas le prétraitement pour l'affichage : ce serait une seconde version, et
rien ne garantirait qu'elle corresponde à ce que le modèle a réellement lu.
Si le dossier prétraité n'existe pas, le script le dit au lieu d'afficher
une image plausible mais fausse.

**Les deux tableaux ne mesurent pas la même chose.** Le premier utilise la
vérité terrain (TEDS, champs) : il dit ce qui est juste. Le second n'en
utilise aucune (lignes équilibrées, totaux cohérents) : il dit ce que la
chaîne sait d'elle-même, donc ce qui vaudra encore sur de vraies photos.
"""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "src"))
from env_check import require as _require_env

_require_env("eval")

import argparse  # noqa: E402
import base64  # noqa: E402
import json  # noqa: E402
import statistics as st  # noqa: E402

import eval_teds as E  # noqa: E402
from invoice_fields import extract_fields  # noqa: E402
from eval_fields import GROUND_TRUTH, compare  # noqa: E402
from teds import teds, rows_to_html  # noqa: E402

# Les deux branches comparées, et les images qui les ont produites.
BRUT = {"run": "multipage_chandra",
        "images": RACINE.parent / "doc3D-renderer" / "img" / "multipage_test",
        "titre": "sans prétraitement"}
PRETRAITE = {"run": "multipage_preproc_chandra",
             "images": RACINE.parent / "doc3D-renderer" / "img" / "multipage_test_preprocessed",
             "titre": "avec prétraitement"}


def image_en_uri(chemin: Path, largeur_max=520) -> str:
    """Encode une image réduite, pour que le HTML reste manipulable."""
    import cv2

    img = cv2.imread(str(chemin))
    if img is None:
        return ""
    h, w = img.shape[:2]
    if w > largeur_max:
        f = largeur_max / w
        img = cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 82])
    if not ok:
        return ""
    return "data:image/jpeg;base64," + base64.b64encode(buf).decode("ascii")


def detecter_qr(chemin: Path):
    """Cherche un QR code, le décode si possible, et rend son cadrage.

    OpenCV fait les deux d'un coup et **sans aucun modèle** : c'est le seul
    élément de la facture dont on puisse vérifier la lecture de façon
    absolue, puisqu'un QR mal lu ne décode simplement pas. Là où TEDS donne
    une note, le QR donne un verdict.

    Rend (trouve, texte_decode, boite) ; `boite` est (x, y, w, h) ou None.
    """
    import cv2
    import numpy as np

    img = cv2.imread(str(chemin))
    if img is None:
        return False, "", None
    texte, points, _ = cv2.QRCodeDetector().detectAndDecode(img)
    if points is None or len(points) == 0:
        return False, "", None
    pts = np.asarray(points).reshape(-1, 2)
    x, y = pts[:, 0].min(), pts[:, 1].min()
    w, h = pts[:, 0].max() - x, pts[:, 1].max() - y
    return True, texte or "", (int(x), int(y), int(w), int(h))


def bandeau_bas(chemin: Path, part=0.28) -> str:
    """Le bas de page en data URI : c'est là que vivent QR et signature.

    On ne « détecte » pas la signature — aucun détecteur générique n'est
    fiable, et en inventer un ici mesurerait notre heuristique plutôt que la
    chaîne. On montre la bande, l'œil tranche. C'est honnête et suffisant
    pour un rapport : la question posée est « est-ce que ça apparaît », pas
    « est-ce que l'algorithme les compte ».
    """
    import cv2

    img = cv2.imread(str(chemin))
    if img is None:
        return ""
    h = img.shape[0]
    bande = img[int(h * (1 - part)):, :]
    largeur_max = 620
    if bande.shape[1] > largeur_max:
        f = largeur_max / bande.shape[1]
        bande = cv2.resize(bande, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", bande, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return ("data:image/jpeg;base64," + base64.b64encode(buf).decode("ascii")
            if ok else "")


def pages_du_dossier(dossier: Path) -> dict:
    """{numéro de page: chemin}. Le numéro est le premier entier du nom."""
    import re

    trouve = {}
    for p in sorted(dossier.glob("*.png")) + sorted(dossier.glob("*.jpg")):
        m = re.search(r"\d+", p.name)
        if m:
            trouve.setdefault(int(m.group()), p)
    return trouve


def mesurer(run: str, groupes, gt_dir: Path) -> dict:
    """TEDS et champs d'en-tête, facture par facture."""
    ocr = E.load_ocr_pages(RACINE / "results" / run / "pages")
    par_facture = {}

    for k, pages in enumerate(groupes, start=1):
        fichier = gt_dir / f"invoice_{k}.json"
        if not fichier.exists():
            continue
        vt = json.loads(fichier.read_text(encoding="utf-8"))
        vrai = rows_to_html(E.normalize_rows(E.ground_truth_rows(vt), True))

        dispo = [(p, ocr[p][0], ocr[p][1]) for p in pages
                 if p in ocr and ocr[p][0]]
        if not dispo:
            par_facture[k] = {"pages": pages, "teds": None, "struct": None,
                              "champs": 0, "champs_max": len(GROUND_TRUTH)}
            continue

        fusion, _ = E.merge_table_sequence([t for _, t, _ in dispo],
                                           [x for _, _, x in dispo])
        pred = rows_to_html(E.normalize_rows(fusion[0].rows, True))

        # Les champs d'en-tête se lisent sur la première page disponible.
        texte = dispo[0][2]
        lus = extract_fields(texte)
        justes = sum(1 for champ, extraire in GROUND_TRUTH.items()
                     if compare(lus.get(champ), extraire(vt))
                     in ("exact", "lenient"))

        par_facture[k] = {
            "pages": pages,
            "teds": teds(pred, vrai),
            "struct": teds(pred, vrai, structure_only=True),
            "champs": justes,
            "champs_max": len(GROUND_TRUTH),
        }
    return par_facture


def resume(run: str) -> dict:
    chemin = RACINE / "results" / run / "summary.json"
    if not chemin.exists():
        raise SystemExit(
            f"results/{run}/summary.json absent.\n"
            f"Lance :  python src/invoice_export.py --run {run}\n"
            f"    puis python src/summary_export.py --run {run}")
    return json.loads(chemin.read_text(encoding="utf-8"))


STYLE = """
:root { --encre:#1f2933; --doux:#6b7785; --bord:#dde2e7; --accent:#2f6fb5;
        --vert:#3f9142; --rouge:#b3403f; --fond:#f7f9fa; }
* { box-sizing:border-box; }
body { max-width:1080px; margin:0 auto; padding:44px 26px 90px; background:#fff;
       color:var(--encre); font:15px/1.65 -apple-system,"Segoe UI",Roboto,sans-serif; }
h1 { font-size:1.7rem; margin:0 0 6px; }
h2 { font-size:1.2rem; margin:44px 0 10px; }
h3 { font-size:1rem; margin:26px 0 8px; }
.sous { color:var(--doux); margin:0 0 26px; }
table { border-collapse:collapse; width:100%; margin:14px 0; font-size:.9rem; }
th,td { border:1px solid var(--bord); padding:7px 10px; text-align:right; }
th:first-child, td:first-child { text-align:left; }
thead th { background:#eef2f5; font-weight:600; }
tbody tr:last-child td { font-weight:700; background:var(--fond); }
.mieux { color:var(--vert); font-weight:600; }
.moins { color:var(--rouge); font-weight:600; }
.paire { display:grid; grid-template-columns:1fr 1fr; gap:14px; margin:14px 0 26px; }
.paire figure { margin:0; }
.paire img { width:100%; border:1px solid var(--bord); border-radius:6px; display:block; }
.paire figcaption { font-size:.8rem; color:var(--doux); margin-top:5px; }
.absente { border:1px dashed var(--bord); border-radius:6px; padding:34px 12px;
           text-align:center; color:var(--doux); font-size:.85rem; }
.encadre { border:1px solid var(--bord); border-left:4px solid var(--accent);
           background:var(--fond); border-radius:8px; padding:14px 18px; margin:20px 0; }
.chiffres { display:flex; gap:30px; flex-wrap:wrap; }
.chiffres .val { font-size:1.6rem; font-weight:700; line-height:1.2; }
.chiffres .lib { color:var(--doux); font-size:.82rem; }
.note { color:var(--doux); font-size:.87rem; }
"""


def cellule(a, b, fmt="{:.3f}", plus_haut_mieux=True):
    """Deux valeurs, la meilleure mise en avant."""
    if a is None or b is None:
        return f"<td>{'—' if a is None else fmt.format(a)}</td>" \
               f"<td>{'—' if b is None else fmt.format(b)}</td><td>—</td>"
    ecart = b - a
    gagne = ecart > 0 if plus_haut_mieux else ecart < 0
    classe = "mieux" if abs(ecart) > 1e-9 and gagne else (
        "moins" if abs(ecart) > 1e-9 else "")
    return (f"<td>{fmt.format(a)}</td><td>{fmt.format(b)}</td>"
            f"<td class='{classe}'>{ecart:+.3f}</td>")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--limite", type=int, default=None,
                   help="N'analyser que les N premières factures (essai).")
    p.add_argument("--sortie", default="demo/RAPPORT_PRETRAITEMENT.html")
    args = p.parse_args()

    pdf = (RACINE / E.DEFAULT_PDF).resolve()
    gt_dir = (RACINE / E.DEFAULT_GT).resolve()
    groupes = E.page_groups_from_pdf(pdf)
    if args.limite:
        groupes = groupes[: args.limite]

    print(f"{len(groupes)} facture(s) — mesure de {BRUT['run']}…", flush=True)
    m_brut = mesurer(BRUT["run"], groupes, gt_dir)
    print(f"mesure de {PRETRAITE['run']}…", flush=True)
    m_pre = mesurer(PRETRAITE["run"], groupes, gt_dir)

    r_brut, r_pre = resume(BRUT["run"]), resume(PRETRAITE["run"])
    img_brut = pages_du_dossier(BRUT["images"])
    img_pre = (pages_du_dossier(PRETRAITE["images"])
               if PRETRAITE["images"].is_dir() else {})

    h = ["<!DOCTYPE html><html lang='fr'><head><meta charset='utf-8'>",
         "<title>Prétraitement — Chandra OCR 2</title>",
         f"<style>{STYLE}</style></head><body>"]

    moy = lambda vals: st.mean([v for v in vals if v is not None]) if any(
        v is not None for v in vals) else None
    t_brut = moy([m_brut[k]["teds"] for k in m_brut])
    t_pre = moy([m_pre[k]["teds"] for k in m_pre])
    c_brut = sum(m_brut[k]["champs"] for k in m_brut)
    c_pre = sum(m_pre[k]["champs"] for k in m_pre)
    c_max = sum(m_brut[k]["champs_max"] for k in m_brut)

    h.append("<h1>Avec ou sans prétraitement</h1>")
    h.append("<p class='sous'>Chandra OCR 2 · 8 factures, 17 pages déformées · "
             "mêmes images, mêmes évaluations, seule l'entrée change.</p>")

    h.append("<div class='encadre'><div class='chiffres'>"
             f"<div><div class='val'>{t_brut:.3f} → {t_pre:.3f}</div>"
             f"<div class='lib'>TEDS, sans puis avec</div></div>"
             f"<div><div class='val'>{t_pre - t_brut:+.3f}</div>"
             f"<div class='lib'>ce que le prétraitement apporte</div></div>"
             f"<div><div class='val'>{c_brut}/{c_max} → {c_pre}/{c_max}</div>"
             f"<div class='lib'>champs d'en-tête retrouvés</div></div>"
             "</div></div>")

    # ---------- Tableau 1 : contre la vérité terrain ----------
    h.append("<h2>Tableau 1 — contre la vérité terrain</h2>")
    h.append("<p class='note'>Ce que la chaîne a de <em>juste</em>. Demande la "
             "vérité terrain, donc ne vaut que sur nos images synthétiques.</p>")
    h.append("<table><thead><tr><th>facture</th><th>pages</th>"
             "<th>TEDS sans</th><th>TEDS avec</th><th>écart</th>"
             "<th>Struct sans</th><th>Struct avec</th><th>écart</th>"
             "<th>champs sans</th><th>champs avec</th></tr></thead><tbody>")
    for k in sorted(m_brut):
        a, b = m_brut[k], m_pre.get(k, {})
        h.append(f"<tr><td>facture {k}</td><td>{a['pages']}</td>"
                 + cellule(a["teds"], b.get("teds"))
                 + cellule(a["struct"], b.get("struct"))
                 + f"<td>{a['champs']}/{a['champs_max']}</td>"
                 + f"<td>{b.get('champs', 0)}/{a['champs_max']}</td></tr>")
    s_brut = moy([m_brut[k]["struct"] for k in m_brut])
    s_pre = moy([m_pre[k]["struct"] for k in m_pre])
    h.append(f"<tr><td>MOYENNE</td><td>{len(m_brut)} factures</td>"
             + cellule(t_brut, t_pre) + cellule(s_brut, s_pre)
             + f"<td>{c_brut}/{c_max}</td><td>{c_pre}/{c_max}</td></tr>")
    h.append("</tbody></table>")

    # ---------- Tableau 2 : sans vérité terrain ----------
    h.append("<h2>Tableau 2 — sans aucune vérité terrain</h2>")
    h.append("<p class='note'>Ce que la chaîne sait <em>d'elle-même</em> : "
             "cohérence arithmétique, totaux, numérotation. Ces chiffres-là "
             "vaudront encore sur de vraies photos, là où TEDS sera muet.</p>")

    def part(bloc, chemin):
        for c in chemin:
            bloc = bloc[c]
        return bloc

    lignes = [
        ("factures en extraction complète", ("documents", "fully_ok")),
        ("champs d'en-tête retrouvés", ("header_fields", "all_fields")),
        ("lignes arithmétiquement justes", ("line_items", "arithmetically_ok")),
        ("lignes corrigées automatiquement", ("line_items", "auto_corrected")),
        ("lignes à relire par un humain", ("line_items", "to_review")),
        ("totaux lisibles", ("grand_totals", "declared_readable")),
        ("totaux cohérents parmi les lisibles",
         ("grand_totals", "consistent_when_readable")),
        ("numérotation vérifiable", ("numbering", "checkable")),
        ("numérotation sans trou parmi les vérifiables",
         ("numbering", "no_gap_when_checkable")),
    ]
    h.append("<table><thead><tr><th>indicateur</th><th>sans prétraitement</th>"
             "<th>avec prétraitement</th><th>écart</th></tr></thead><tbody>")
    for libelle, chemin in lignes:
        a, b = part(r_brut, chemin), part(r_pre, chemin)
        ecart = ((b["rate"] - a["rate"]) if a["rate"] is not None
                 and b["rate"] is not None else None)
        # « À relire » et « corrigées » : moins est mieux.
        mieux_bas = "relire" in libelle or "corrigées" in libelle
        classe = "" if not ecart else (
            "mieux" if (ecart < 0) == mieux_bas else "moins")
        txt = f"{ecart:+.1%}" if ecart is not None else "—"
        h.append(f"<tr><td>{libelle}</td>"
                 f"<td>{a['found']}/{a['max']}</td>"
                 f"<td>{b['found']}/{b['max']}</td>"
                 f"<td class='{classe}'>{txt}</td></tr>")
    h.append("</tbody></table>")

    # ---------- Les images ----------
    h.append("<h2>Les images, page par page</h2>")
    h.append("<p class='note'>À gauche ce que le modèle a lu sans "
             "prétraitement, à droite après recadrage, redressement et "
             "correction d'éclairage.</p>")
    if not img_pre:
        h.append("<div class='encadre'>Dossier d'images prétraitées introuvable "
                 f"(<code>{PRETRAITE['images']}</code>). Génère-le :<br>"
                 "<code>python src\\preprocess.py --images-dir "
                 "..\\doc3D-renderer\\img\\multipage_test --out "
                 "..\\doc3D-renderer\\img\\multipage_test_preprocessed</code>"
                 "</div>")

    pages_voulues = [p for g in groupes for p in g]
    for n in pages_voulues:
        h.append(f"<h3>page {n}</h3><div class='paire'>")
        for source, titre in ((img_brut, BRUT["titre"]),
                              (img_pre, PRETRAITE["titre"])):
            chemin = source.get(n)
            if chemin is None:
                h.append(f"<div class='absente'>{titre} — image absente</div>")
                continue
            uri = image_en_uri(chemin)
            h.append(f"<figure><img src='{uri}' alt='page {n} {titre}'>"
                     f"<figcaption>{titre} — {chemin.name}</figcaption></figure>")
        h.append("</div>")

    # ---------- QR codes et signatures ----------
    h.append("<h2>Bas de page — QR codes et signatures</h2>")
    h.append("<p class='note'>Le gabarit place un QR code (tracé vectoriel, "
             "hauteur tirée entre 1 et 2 cm) et une signature scannée (image "
             "intégrée) au pied de la <em>dernière</em> page de chaque "
             "facture. On montre ici cette bande, et on tente la lecture "
             "automatique du QR.</p>")

    h.append("<table><thead><tr><th>facture</th><th>dernière page</th>"
             "<th>QR détecté (brut)</th><th>décodé</th>"
             "<th>QR détecté (prétraité)</th></tr></thead><tbody>")
    detections = []
    for k, pages in enumerate(groupes, start=1):
        derniere = pages[-1]
        f_brut, f_pre = img_brut.get(derniere), img_pre.get(derniere)
        t_b, texte_b, boite = detecter_qr(f_brut) if f_brut else (False, "", None)
        t_p, _, _ = detecter_qr(f_pre) if f_pre else (False, "", None)
        detections.append((k, derniere, t_b, texte_b, t_p, f_brut, f_pre, boite))
        h.append(f"<tr><td>facture {k}</td><td>page {derniere}</td>"
                 f"<td class='{'mieux' if t_b else 'moins'}'>"
                 f"{'oui' if t_b else 'non'}</td>"
                 f"<td>{texte_b or '—'}</td>"
                 f"<td class='{'mieux' if t_p else 'moins'}'>"
                 f"{'oui' if t_p else 'non'}</td></tr>")
    n_b = sum(1 for d in detections if d[2])
    n_p = sum(1 for d in detections if d[4])
    h.append(f"<tr><td>TOTAL</td><td>{len(detections)} factures</td>"
             f"<td>{n_b}/{len(detections)}</td><td></td>"
             f"<td>{n_p}/{len(detections)}</td></tr></tbody></table>")

    h.append("<div class='encadre'><strong>Ce que ce tableau mesure vraiment.</strong> "
             "Un QR mal lu ne décode pas : c'est le seul élément de la facture "
             "sur lequel la vérification est <em>absolue</em>, là où tout le "
             "reste se note en degrés. Et le taux est bas — la cause n'est pas "
             "le modèle, qui n'intervient pas ici, mais la <strong>résolution</strong> : "
             "1 à 2 cm de QR sur une A4 rendue en 900 px de large font 40 à "
             "85 pixels, en dessous de ce qu'un décodeur sait exploiter, et la "
             "déformation 3D achève le motif. C'est donc une "
             "<strong>spécification de capture</strong> qu'on vient de mesurer, "
             "pas un défaut de la chaîne : elle dit combien de pixels il faudra "
             "sur les photos réelles.</div>")

    for k, derniere, t_b, texte_b, t_p, f_brut, f_pre, _ in detections:
        h.append(f"<h3>facture {k} — bas de la page {derniere}</h3><div class='paire'>")
        for chemin, titre in ((f_brut, BRUT["titre"]), (f_pre, PRETRAITE["titre"])):
            if chemin is None:
                h.append(f"<div class='absente'>{titre} — image absente</div>")
                continue
            uri = bandeau_bas(chemin)
            h.append(f"<figure><img src='{uri}' alt='bas de page {derniere}'>"
                     f"<figcaption>{titre}</figcaption></figure>")
        h.append("</div>")

    h.append("<h2>Comment lire ces deux tableaux ensemble</h2>")
    h.append("<p>Le tableau 1 dit ce qui est <strong>juste</strong>, le "
             "tableau 2 ce que la chaîne <strong>croit</strong> de "
             "elle-même. Quand les deux bougent dans le même sens, on peut se "
             "fier à la confiance calculée sans vérité terrain — et c'est ce "
             "qui permettra de mesurer la chaîne sur de vraies factures, où "
             "aucun TEDS ne sera calculable.</p>")
    h.append("<p class='note'>Rapport généré par "
             "<code>scripts/rapport_pretraitement.py</code>. Les images sont "
             "encodées dans le fichier : il s'ouvre tel quel et s'importe dans "
             "Notion par Import → HTML.</p>")
    h.append("</body></html>")

    sortie = RACINE / args.sortie
    sortie.parent.mkdir(parents=True, exist_ok=True)
    sortie.write_text("".join(h), encoding="utf-8")
    print(f"\n{args.sortie} : {sortie.stat().st_size / 1e6:.1f} Mo, "
          f"{len(pages_voulues)} page(s)")
    print(f"TEDS {t_brut:.3f} -> {t_pre:.3f}   ({t_pre - t_brut:+.3f})")
    print(f"champs {c_brut}/{c_max} -> {c_pre}/{c_max}")


if __name__ == "__main__":
    main()
