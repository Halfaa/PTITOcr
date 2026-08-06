"""
Export extracted invoices as structured JSON.

This is the deliverable named in the internship proposal ("an automated
extraction tool that generates structured JSON files"). It chains everything
built so far: OCR output -> table extraction -> multi-page merging -> typed
fields -> arithmetic validation -> JSON.

Design choice worth stating: the JSON carries the VALIDATION RESULT alongside
the data. A consumer must be able to tell an amount that adds up from one
that does not -- on medical invoices, shipping data without that distinction
would be misleading. Every line therefore has a `check` block, and the
document a `review` block listing what needs human eyes.

Usage:
    python src/invoice_export.py --run multipage_hunyuan
    python src/invoice_export.py --run multipage_hunyuan --invoice 1 --print
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_check import require as _require_env
_require_env("eval")


import argparse
import json
from datetime import datetime, timezone

from table_merge import extract_tables, merge_table_sequence  # noqa: E402
from invoice_parse import parse_table  # noqa: E402
from invoice_validate import check_invoice  # noqa: E402
from invoice_fields import extract_fields, coverage  # noqa: E402
from eval_teds import DEFAULT_PDF, page_groups_from_pdf  # noqa: E402


def load_invoice_pages(pages_dir: Path, page_numbers):
    """Return (tables, page_texts, kept_page_numbers) for one invoice."""
    tables, texts, kept = [], [], []
    for n in page_numbers:
        dirs = list(pages_dir.glob(f"page_{n}-*"))
        if not dirs:
            continue
        md = list(dirs[0].glob("*.md"))
        if not md:
            continue
        text = md[0].read_text(encoding="utf-8")
        found = extract_tables(text)
        if not found:
            # The page carries no table but may still hold header fields
            # (footer overflow pages, for instance).
            texts.append(text)
            kept.append(n)
            continue
        tables.append(max(found, key=lambda t: len(t.rows)))
        texts.append(text)
        kept.append(n)
    return tables, texts, kept


def build_invoice_json(run: str, invoice_no: int, tables, texts, pages) -> dict:
    """Assemble the JSON document for one invoice."""
    merged, _ = merge_table_sequence(tables, texts) if tables else ([], [])
    parsed = parse_table(merged[0]) if merged else None
    result = check_invoice(parsed) if parsed else None

    # Why an explicit extraction status: an invoice with zero lines can mean
    # two very different things -- no table was found, or a table was found
    # but its header could not be identified (PP-StructureV3 returned one
    # page with the columns mirrored right-to-left and no header row). A
    # consumer must be able to tell a genuinely empty result from a failed
    # one, so we never return silently empty data.
    if not merged:
        extraction = {"status": "no_table",
                      "reason": "OCR produced no <table> for this invoice"}
    elif not parsed.columns:
        extraction = {"status": "header_not_found",
                      "reason": f"table found ({len(merged[0].rows)} rows) but no "
                                f"header row could be identified -- columns "
                                f"cannot be mapped"}
    elif not parsed.items:
        extraction = {"status": "no_rows",
                      "reason": "header identified but no data row parsed"}
    else:
        missing = [f for f in ("index", "name", "quantity", "unit_price", "total")
                   if f not in parsed.columns]
        extraction = {"status": "ok"}
        if missing:
            extraction = {"status": "partial",
                          "reason": f"columns not found: {', '.join(missing)}"}

    # Header fields: taken from the first page, which is where they sit.
    fields = extract_fields(texts[0]) if texts else {}

    items = []
    if result:
        for check in result["checks"]:
            item = check.item
            entry = {
                "index": item.index,
                "name": item.name,
                "unit": item.unit,
                "quantity": item.quantity,
                "unit_price": item.unit_price,
                "total": item.total,
                "check": {"status": check.status},
            }
            if check.detail:
                entry["check"]["detail"] = check.detail
            if check.corrected_field:
                entry["check"]["corrected_field"] = check.corrected_field
                entry["check"]["corrected_value"] = check.corrected_value
                # The delivered value is the corrected one.
                entry[check.corrected_field] = check.corrected_value
            items.append(entry)

    doc = {
        "source": {
            "run": run,
            "invoice": invoice_no,
            "pages": pages,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
        "document": {
            "hospital_name": fields.get("hospital_name"),
            "customer_name": fields.get("customer_name"),
            "invoice_date": fields.get("invoice_date"),
            "doctor": fields.get("doctor"),
            "address": fields.get("address"),
            "invoice_number": fields.get("invoice_number"),
            "payment_method": fields.get("payment_method"),
            "_field_coverage": round(coverage(fields), 2),
        },
        "extraction": extraction,
        "items": items,
    }

    if result:
        computed = sum(i["total"] for i in items if i.get("total") is not None)
        doc["totals"] = {
            "declared": parsed.grand_total,
            "computed_from_lines": computed,
            "consistent": result["total_ok"],
        }
        # `lines_to_check` designe les lignes par leur STT, ce qui suppose que
        # la colonne STT a ete lue. Quand elle ne l'a pas ete, la liste sortait
        # remplie de `null` : le JSON annoncait 31 lignes a relire sans dire
        # LESQUELLES, et le champ le plus utile du livrable devenait inutile.
        # On donne donc aussi la position dans `items`, qui existe toujours.
        a_relire = [(i, c) for i, c in enumerate(result["checks"]) if c.is_suspect]
        doc["review"] = {
            "n_lines": result["n_lines"],
            "n_ok": result["n_ok"],
            "n_to_check": result["n_suspect"],
            "n_auto_corrected": result["n_corrected"],
            "lines_to_check": [
                {"position": i, "stt": c.item.index,
                 "status": c.status, "detail": c.detail}
                for i, c in a_relire
            ],
            "numbering_gaps": result["index_gaps"],
            # Sans ce drapeau, une numerotation PARFAITE et une numerotation
            # ILLISIBLE produisent toutes deux `numbering_gaps: []`. Le
            # consommateur du JSON -- qui est le livrable final -- ne peut pas
            # les distinguer, et croit verifie ce qui n'a pas pu l'etre.
            "numbering_checked": result["index_available"],
        }
    else:
        doc["totals"] = None
        doc["review"] = {"n_lines": 0, "note": "no table extracted"}

    return doc


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="multipage_hunyuan")
    parser.add_argument("--invoice", type=int, default=None,
                        help="Export a single invoice (default: all)")
    parser.add_argument("--out", default=None,
                        help="Output folder (default: results/<run>/json)")
    parser.add_argument("--print", dest="do_print", action="store_true",
                        help="Also print the JSON to stdout")
    # Sans cette option, un run du jeu diversifié était découpé en factures
    # selon le PDF du jeu multi-pages : aucune erreur levée, des JSON
    # produits, et des pages attribuées à la mauvaise facture. Le reste des
    # scripts d'évaluation accepte --pdf depuis le début ; celui-ci était le
    # dernier à ne pas le faire.
    parser.add_argument("--pdf", default=None,
                        help="PDF source, pour le découpage en factures. "
                             "Défaut : le jeu multi-pages. Pour le jeu "
                             "diversifié, passer invoices_variants.pdf.")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    pages_dir = root / "results" / args.run / "pages"
    out_dir = Path(args.out) if args.out else root / "results" / args.run / "json"
    out_dir.mkdir(parents=True, exist_ok=True)

    pdf = Path(args.pdf).resolve() if args.pdf else (root / DEFAULT_PDF).resolve()
    groups = page_groups_from_pdf(pdf)
    wanted = [args.invoice] if args.invoice else range(1, len(groups) + 1)

    print(f"Run: {args.run}\n")
    head = (f"{'invoice':<10}{'pages':<14}{'lines':>7}{'to check':>10}"
            f"{'fields':>9}{'total':>8}   {'extraction':<18}")
    print(head)
    print("-" * len(head))

    for k in wanted:
        if k < 1 or k > len(groups):
            print(f"No such invoice: {k}")
            continue
        tables, texts, pages = load_invoice_pages(pages_dir, groups[k - 1])
        if not texts:
            print(f"invoice_{k:<3}{'no OCR output':>40}")
            continue

        doc = build_invoice_json(args.run, k, tables, texts, pages)
        path = out_dir / f"invoice_{k}.json"
        path.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")

        review = doc["review"]
        totals = doc["totals"]
        total_flag = {True: "yes", False: "NO", None: "?"}[
            totals["consistent"] if totals else None]
        status = doc["extraction"]["status"]
        print(f"invoice_{k:<3}{str(pages):<14}{review.get('n_lines', 0):>7}"
              f"{review.get('n_to_check', 0):>10}"
              f"{doc['document']['_field_coverage']:>8.0%}{total_flag:>8}   "
              f"{status:<18}")

        if args.do_print:
            print(json.dumps(doc, ensure_ascii=False, indent=2))

    print(f"\nJSON written to: {out_dir.resolve()}")


if __name__ == "__main__":
    main()
