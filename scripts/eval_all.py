"""
Toutes les évaluations d'un modèle, en une commande.

Pourquoi ce script existe. Les chiffres publiés dans `docs/` viennent de cinq
scripts différents, chacun avec ses options, et chaque jeu d'images a sa
propre vérité terrain. Comparer deux modèles suppose donc que les deux ont
été mesurés avec exactement les mêmes arguments — et c'est précisément ce
qu'une suite de commandes tapées à la main ne garantit pas. Passer
`--gt-dir` du jeu multi-pages à un run sur le jeu diversifié ne lève aucune
erreur : les évaluations tournent, sortent des nombres, et ces nombres ne
veulent rien dire.

Ici la correspondance run -> jeu -> vérité terrain est écrite une fois, dans
`JEUX` et `MODELES`. Ajouter un modèle, c'est ajouter une entrée : le
protocole, lui, ne bouge pas.

    python scripts/eval_all.py --modele chandra
    python scripts/eval_all.py --modele chandra --modele hunyuan
    python scripts/eval_all.py --modele chandra --complet   # journaux entiers

Le détail de chaque évaluation est écrit dans results/_evaluations/, pour
qu'un chiffre du tableau récapitulatif reste traçable jusqu'à la ligne qui
l'a produit.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
GEN = RACINE.parent / "synthetic_invoice_generator" / "hospital_pharmacy"

# --------------------------------------------------------------------------
# Les jeux d'images, et la vérité terrain qui va avec.
#
# `pdf` sert au découpage en factures (quelles pages appartiennent à quelle
# facture) ; `gt` contient le contenu attendu. Ce sont deux vérités terrain
# distinctes et c'est délibéré : dériver le découpage des sorties OCR
# reviendrait à noter l'algorithme de fusion sur les données qui l'ont
# inspiré.
JEUX = {
    "multipage": {
        "titre": "8 factures, 17 pages déformées, un seul gabarit",
        "pdf": GEN / "invoices_multipage_xelatex.pdf",
        "gt": GEN / "ground_truth_labels_multipage",
    },
    "variants_flat": {
        "titre": "12 factures, 25 pages à plat, 6 gabarits",
        "pdf": GEN / "invoices_variants.pdf",
        "gt": GEN / "ground_truth_labels_variants",
    },
    "variants_warped": {
        "titre": "les mêmes 12 factures, déformées",
        "pdf": GEN / "invoices_variants.pdf",
        "gt": GEN / "ground_truth_labels_variants",
    },
}

# --------------------------------------------------------------------------
# Les runs de chaque modèle, par jeu : (lecture brute, lecture prétraitée).
#
# Les noms ne sont pas réguliers d'un modèle à l'autre — ils ont été choisis
# au fil des semaines. Les figer ici plutôt que de les reconstruire par
# convention évite de renommer a posteriori des runs déjà cités dans docs/.
MODELES = {
    "chandra": {
        "titre": "Chandra OCR 2 (5 B)",
        "runs": {
            "multipage": ("multipage_chandra", "multipage_preproc_chandra"),
            "variants_flat": ("variants_chandra", None),
            "variants_warped": ("variants_warped_chandra",
                                "variants_warped_preprocessed_chandra"),
        },
    },
    "hunyuan": {
        "titre": "HunyuanOCR-1.5 (1 B)",
        "runs": {
            "multipage": ("multipage_hunyuan", "multipage_preproc_hunyuan"),
        },
    },
    "paddleocr": {
        "titre": "PaddleOCR-VL (0,9 B)",
        "runs": {
            "multipage": ("multipage_paddleocr_vl", "multipage_preproc3_paddleocr"),
            "variants_flat": ("variants_paddleocr", None),
            "variants_warped": ("variants_warped_paddleocr",
                                "variants_warped_preprocessed_paddleocrvl"),
        },
    },
    "ppstructure": {
        "titre": "PP-StructureV3",
        "runs": {
            "multipage": ("multipage_ppstructure", None),
        },
    },
}


# --------------------------------------------------------------------------

def lancer(script: str, *args) -> str:
    """Exécute une évaluation et rend sa sortie.

    On passe par un sous-processus plutôt que par un import : les scripts
    d'évaluation appellent `env_check.require`, qui termine le processus
    quand l'environnement ne convient pas. Importé, un `sys.exit` tuerait
    tout le récapitulatif au lieu de signaler une seule évaluation en échec.
    """
    r = subprocess.run([sys.executable, script, *map(str, args)],
                       cwd=RACINE, capture_output=True, text=True)
    return r.stdout + ("\n[stderr]\n" + r.stderr if r.returncode else "")


def cherche(motif: str, texte: str, groupes: int = 1):
    m = re.search(motif, texte, re.M)
    if not m:
        return None if groupes == 1 else (None,) * groupes
    return m.group(1) if groupes == 1 else m.groups()


def existe(run) -> bool:
    return bool(run) and (RACINE / "results" / run / "pages").is_dir()


def evaluer_run(run: str, jeu: dict, journal: list) -> dict:
    """TEDS, fusion, champs et validation arithmétique pour un run."""
    pdf, gt = jeu["pdf"], jeu["gt"]
    mesures = {"run": run}

    sortie = lancer("src/eval_teds.py", "--run", run, "--pdf", pdf, "--gt-dir", gt)
    journal.append((f"eval_teds --run {run}", sortie))
    mesures["teds"] = cherche(r"^TEDS\s+([\d.]+)", sortie)
    mesures["struct"] = cherche(r"^TEDS-Struct\s+([\d.]+)", sortie)
    mesures["teds_sans_fusion"] = cherche(r"^MEAN\s+([\d.]+)", sortie)

    sortie = lancer("src/eval_multipage_merge.py", "--run", run, "--pdf", pdf)
    journal.append((f"eval_multipage_merge --run {run}", sortie))
    p, r_, f1 = cherche(r"^Precision (\d+)%\s+Recall (\d+)%\s+F1 (\d+)%", sortie, 3)
    mesures["precision"], mesures["rappel"], mesures["f1"] = p, r_, f1

    sortie = lancer("src/eval_fields.py", "--runs", run, "--pdf", pdf, "--gt-dir", gt)
    journal.append((f"eval_fields --runs {run}", sortie))
    mesures["champs"] = cherche(rf"^{re.escape(run)}\s+.*?(\d+)%\s*$", sortie)

    sortie = lancer("src/eval_validation.py", "--run", run, "--pdf", pdf, "--gt-dir", gt)
    journal.append((f"eval_validation --run {run}", sortie))
    vr, vp = cherche(r"^Recall (\d+)%\s+Precision (\d+)%", sortie, 2)
    mesures["valid_rappel"], mesures["valid_precision"] = vr, vp

    return mesures


def evaluer_adaptatif(brut: str, pretraite: str, jeu: dict, journal: list) -> dict:
    """La politique adaptative, qui a besoin des DEUX lectures."""
    sortie = lancer("src/eval_adaptive.py", "--raw", brut,
                    "--preprocessed", pretraite,
                    "--pdf", jeu["pdf"], "--gt-dir", jeu["gt"])
    journal.append((f"eval_adaptive --raw {brut} --preprocessed {pretraite}", sortie))

    # eval_adaptive compte les champs en fraction ("28/32") là où eval_fields
    # les donne en pourcentage. On convertit pour que la colonne reste
    # comparable d'une ligne à l'autre du même tableau.
    fraction = cherche(r"^\s+adaptive\s+TEDS [\d.]+\s+fields (\d+)/(\d+)", sortie, 2)
    champs = (f"{round(100 * int(fraction[0]) / int(fraction[1]))}"
              if fraction and fraction[0] else None)

    return {
        "run": "adaptatif",
        "teds": cherche(r"^\s+adaptive\s+TEDS ([\d.]+)", sortie),
        "champs": champs,
        "champs_fraction": "/".join(fraction) if fraction and fraction[0] else None,
        "plafond": cherche(r"ceiling \(perfect choice, hindsight only\): ([\d.]+)", sortie),
    }


LARGEURS = [("run", 40), ("TEDS", 8), ("Struct", 8), ("sans fus.", 10),
            ("champs", 8), ("fusion P/R", 12), ("arithm. R/P", 12)]


def ligne(m: dict) -> str:
    def v(x, suffixe=""):
        return f"{x}{suffixe}" if x is not None else "--"

    cellules = [
        m["run"],
        v(m.get("teds")),
        v(m.get("struct")),
        v(m.get("teds_sans_fusion")),
        v(m.get("champs"), "%"),
        (f"{m['precision']}/{m['rappel']}%" if m.get("precision") else "--"),
        (f"{m['valid_rappel']}/{m['valid_precision']}%"
         if m.get("valid_rappel") else "--"),
    ]
    return "".join(c.ljust(w) if i == 0 else c.rjust(w)
                   for i, (c, (_, w)) in enumerate(zip(cellules, LARGEURS)))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--modele", action="append", required=True,
                   choices=sorted(MODELES), help="Répétable.")
    p.add_argument("--jeu", action="append", choices=sorted(JEUX),
                   help="Limiter à certains jeux. Défaut : tous.")
    p.add_argument("--complet", action="store_true",
                   help="Afficher les journaux entiers en plus du tableau.")
    args = p.parse_args()

    jeux_voulus = args.jeu or list(JEUX)
    dossier_journaux = RACINE / "results" / "_evaluations"
    dossier_journaux.mkdir(parents=True, exist_ok=True)

    for cle in args.modele:
        modele = MODELES[cle]
        journal = []
        print(f"\n{'=' * 90}\n{modele['titre']}\n{'=' * 90}")

        for nom_jeu in jeux_voulus:
            paire = modele["runs"].get(nom_jeu)
            if not paire:
                continue
            brut, pretraite = paire
            jeu = JEUX[nom_jeu]

            presents = [r for r in (brut, pretraite) if existe(r)]
            absents = [r for r in (brut, pretraite) if r and not existe(r)]
            if not presents:
                print(f"\n-- {nom_jeu} : aucun run présent "
                      f"({', '.join(absents)})")
                continue

            print(f"\n-- {nom_jeu} — {jeu['titre']}")
            if absents:
                print(f"   (absent de results/ : {', '.join(absents)})")
            entete = "".join(t.ljust(w) if i == 0 else t.rjust(w)
                             for i, (t, w) in enumerate(LARGEURS))
            print(entete)
            print("-" * len(entete))

            for run in presents:
                print(ligne(evaluer_run(run, jeu, journal)))

            if existe(brut) and existe(pretraite):
                a = evaluer_adaptatif(brut, pretraite, jeu, journal)
                print(ligne(a))
                if a.get("plafond"):
                    # L'écart au plafond est le chiffre qui compte : il dit si
                    # c'est la règle de décision qui limite, ou les deux
                    # lectures qu'on lui donne à choisir.
                    ecart = (f"  (écart {float(a['plafond']) - float(a['teds']):+.3f})"
                             if a.get("teds") else "")
                    print(f"{'  plafond (choix parfait, a posteriori)':<40}"
                          f"{a['plafond']:>8}{ecart}")
                if a.get("champs_fraction"):
                    print(f"{'  champs adaptatifs':<40}"
                          f"{a['champs_fraction']:>8} retrouvés")

        chemin = dossier_journaux / f"{cle}.txt"
        chemin.write_text(
            "\n\n".join(f"{'#' * 78}\n# {titre}\n{'#' * 78}\n{sortie}"
                        for titre, sortie in journal),
            encoding="utf-8")
        print(f"\nJournal détaillé : results/_evaluations/{cle}.txt")

    print("\nLecture des colonnes.")
    print("  TEDS / Struct  contenu + structure, puis structure seule ; un écart")
    print("                 large désigne la lecture des caractères, pas la grille")
    print("  sans fus.      TEDS de la 1re page seule — ce que vaudrait la chaîne")
    print("                 sans recollage multi-pages")
    print("  champs         part des champs d'en-tête retrouvés")
    print("  fusion P/R     précision et rappel de la détection de continuation ;")
    print("                 la précision prime, une fusion à tort mélange deux")
    print("                 factures et rien en aval ne peut la voir")
    print("  arithm. R/P    rappel et précision de la validation arithmétique")


if __name__ == "__main__":
    main()
