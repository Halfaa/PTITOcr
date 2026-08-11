"""
Résumé chiffré d'un run, agrégé depuis les JSON de factures.

`invoice_export.py` produit un fichier par facture. Utile pour regarder une
facture, inutile pour répondre à « est-ce que ce run est bon ? ». Ce script
agrège et écrit `results/<run>/summary.json`.

Tout est en **trouvé / maximum atteignable** plutôt qu'en pourcentage seul.
Un « 88 % » ne dit pas s'il porte sur 8 ou sur 800 documents, et c'est
exactement la confusion qu'on veut éviter dans un rapport de stage.

Point important : ce résumé **n'utilise aucune vérité terrain**. Il mesure ce
que la chaîne a extrait et ce qu'elle sait de sa propre fiabilité — donc il
tourne aussi sur des factures réelles, là où TEDS ne peut pas. C'est le
pendant « production » des scripts d'évaluation.

    python src/summary_export.py --run multipage_chandra
    python src/summary_export.py --all
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from env_check import require as _require_env

_require_env("eval")

import argparse  # noqa: E402
import json  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

RACINE = Path(__file__).resolve().parent.parent

CHAMPS = ("hospital_name", "customer_name", "invoice_date", "doctor",
          "address", "invoice_number", "payment_method")


def _part(trouve, total):
    """Toujours le couple, jamais le pourcentage seul."""
    return {"found": trouve, "max": total,
            "rate": round(trouve / total, 3) if total else None}


def resumer(run: str) -> dict:
    dossier = RACINE / "results" / run / "json"
    fichiers = sorted(dossier.glob("invoice_*.json"),
                      key=lambda f: int("".join(c for c in f.stem if c.isdigit()) or 0))
    if not fichiers:
        raise SystemExit(
            f"Aucun JSON dans results/{run}/json.\n"
            f"Lance d'abord :  python src/invoice_export.py --run {run}")

    docs = [json.loads(f.read_text(encoding="utf-8")) for f in fichiers]
    n = len(docs)

    statuts = {}
    for d in docs:
        s = d["extraction"]["status"]
        statuts[s] = statuts.get(s, 0) + 1

    champs = {c: _part(sum(1 for d in docs if d["document"].get(c)), n)
              for c in CHAMPS}

    pages = sorted({p for d in docs for p in d["source"]["pages"]})

    lignes = sum(d["review"].get("n_lines", 0) for d in docs)
    lignes_ok = sum(d["review"].get("n_ok", 0) for d in docs)
    a_relire = sum(d["review"].get("n_to_check", 0) for d in docs)
    corrigees = sum(d["review"].get("n_auto_corrected", 0) for d in docs)

    # Les totaux ne sont vérifiables que si le total déclaré a été lu :
    # `consistent` vaut alors true/false, et null sinon. Compter les null
    # comme des échecs ferait passer une lecture impossible pour une erreur.
    avec_total = [d for d in docs
                  if d.get("totals") and d["totals"].get("consistent") is not None]
    totaux_ok = sum(1 for d in avec_total if d["totals"]["consistent"])

    # Idem pour la numérotation : « aucun trou » et « invérifiable » sont
    # deux choses différentes, et le JSON par facture les distingue depuis
    # l'audit du 5 août.
    verifiables = [d for d in docs if d["review"].get("numbering_checked")]
    sans_trou = sum(1 for d in verifiables if not d["review"].get("numbering_gaps"))

    montant = sum(d["totals"]["declared"] for d in docs
                  if d.get("totals") and d["totals"].get("declared"))

    return {
        "run": run,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "documents": {
            "invoices": n,
            "pages": len(pages),
            "pages_per_invoice": round(len(pages) / n, 2) if n else None,
            "multi_page_invoices": sum(1 for d in docs
                                       if len(d["source"]["pages"]) > 1),
            "extraction_status": statuts,
            "fully_ok": _part(statuts.get("ok", 0), n),
        },
        "header_fields": {
            **champs,
            "all_fields": _part(
                sum(1 for d in docs for c in CHAMPS if d["document"].get(c)),
                n * len(CHAMPS)),
        },
        "line_items": {
            "total": lignes,
            "arithmetically_ok": _part(lignes_ok, lignes),
            "auto_corrected": _part(corrigees, lignes),
            "to_review": _part(a_relire, lignes),
            "per_invoice_avg": round(lignes / n, 1) if n else None,
        },
        "grand_totals": {
            # Deux dénominateurs volontairement différents : « lisible » et
            # « juste » ne se confondent pas.
            "declared_readable": _part(len(avec_total), n),
            "consistent_when_readable": _part(totaux_ok, len(avec_total)),
            "sum_declared": montant,
        },
        "numbering": {
            "checkable": _part(len(verifiables), n),
            "no_gap_when_checkable": _part(sans_trou, len(verifiables)),
        },
        "reading": "Chaque bloc donne trouvé / maximum atteignable. Aucun "
                   "chiffre ici n'utilise de vérité terrain : ce résumé "
                   "mesure ce que la chaîne a extrait et ce qu'elle sait de "
                   "sa propre fiabilité, donc il vaut aussi sur des factures "
                   "réelles.",
    }


def afficher(r: dict) -> None:
    d, f, l = r["documents"], r["header_fields"], r["line_items"]
    print(f"\n{r['run']}")
    print(f"  {d['invoices']} factures, {d['pages']} pages "
          f"({d['multi_page_invoices']} multi-pages)")
    print(f"  extraction complète   {d['fully_ok']['found']}/{d['fully_ok']['max']}"
          f"   {d['extraction_status']}")
    print(f"  champs d'en-tête      {f['all_fields']['found']}/{f['all_fields']['max']}")
    for c in CHAMPS:
        print(f"     {c:<18}{f[c]['found']:>3}/{f[c]['max']}")
    print(f"  lignes                {l['total']}")
    print(f"     équilibrées        {l['arithmetically_ok']['found']}/{l['arithmetically_ok']['max']}")
    print(f"     corrigées          {l['auto_corrected']['found']}/{l['auto_corrected']['max']}")
    print(f"     à relire           {l['to_review']['found']}/{l['to_review']['max']}")
    g, num = r["grand_totals"], r["numbering"]
    print(f"  total lisible         {g['declared_readable']['found']}/{g['declared_readable']['max']}"
          f"   dont cohérent {g['consistent_when_readable']['found']}"
          f"/{g['consistent_when_readable']['max']}")
    print(f"  numérotation vérifiable {num['checkable']['found']}/{num['checkable']['max']}"
          f"   sans trou {num['no_gap_when_checkable']['found']}"
          f"/{num['no_gap_when_checkable']['max']}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--run", help="Un run précis.")
    p.add_argument("--all", action="store_true",
                   help="Tous les runs disposant de JSON, plus un "
                        "results/_summary.json comparatif.")
    args = p.parse_args()

    if not args.run and not args.all:
        p.error("il faut --run ou --all")

    runs = ([args.run] if args.run else
            sorted(d.parent.name for d in (RACINE / "results").glob("*/json")
                   if any(d.glob("invoice_*.json"))))

    resumes = []
    for run in runs:
        r = resumer(run)
        (RACINE / "results" / run / "summary.json").write_text(
            json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
        resumes.append(r)
        afficher(r)

    if args.all:
        comparatif = {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "runs": {r["run"]: r for r in resumes},
        }
        chemin = RACINE / "results" / "_summary.json"
        chemin.write_text(json.dumps(comparatif, ensure_ascii=False, indent=2),
                          encoding="utf-8")
        print(f"\nComparatif : results/_summary.json ({len(resumes)} runs)")
    else:
        print(f"\nÉcrit : results/{runs[0]}/summary.json")


if __name__ == "__main__":
    main()
