# Initialisation du depot git et premier commit.
#
# A lancer depuis MedicalRecord\ :
#     .\git_setup.ps1
#
# Le depot couvre MedicalRecord/ uniquement. doc3D-renderer/ et
# synthetic_invoice_generator/ sont des depots du labo, deja versionnes
# ailleurs : les inclure creerait des depots imbriques.

$ErrorActionPreference = "Stop"

function Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }

# --- Nettoyage des residus de l'ancienne arborescence ------------------
Step "Nettoyage"
foreach ($p in @("output_multipage_paddleocr_vl",
                 "benchmark_report_multipage_paddleocr_vl.html",
                 "__pycache__", "benchmark", "benchmark_deformed")) {
    if (Test-Path $p) {
        Remove-Item -Recurse -Force $p -ErrorAction SilentlyContinue
        Write-Host "  supprime : $p"
    }
}

# Verrou laisse par un git interrompu
if (Test-Path ".git\index.lock") {
    Remove-Item -Force ".git\index.lock"
    Write-Host "  verrou git libere"
}

# --- Depot -------------------------------------------------------------
Step "Depot"
if (-not (Test-Path ".git")) {
    git init
    Write-Host "  depot initialise"
} else {
    Write-Host "  depot deja present"
}

# Identite : indispensable pour commiter, a adapter si besoin
if (-not (git config user.name)) {
    git config user.name  "Halfaa"
    git config user.email "ero2bubule@gmail.com"
    Write-Host "  identite git configuree (locale a ce depot)"
}

# --- Premier commit ----------------------------------------------------
Step "Contenu a versionner"
git add -A
git status --short

$n = (git diff --cached --name-only | Measure-Object -Line).Lines
Write-Host "`n$n fichier(s) prets a etre commites." -ForegroundColor Green

Step "Commit"
git commit -m "Detection et fusion de tableaux multi-pages sur factures medicales

Chaine complete d'evaluation OCR pour factures vietnamiennes photographiees.

- table_merge.py : detection + fusion des tableaux coupes entre deux pages,
  par croisement de plusieurs signaux (marqueur de continuation, continuite
  de la colonne STT, similarite des entetes, presence d'une ligne Total).
  100 % de precision et de rappel sur 14 paires de pages, zero fusion a tort.

- teds.py / eval_teds.py : metrique TEDS et TEDS-Struct (PubTabNet), donc
  des chiffres comparables a la litterature. La fusion fait gagner +0,25 de
  TEDS, et ce pour les trois modeles testes.

- Comparaison sur 17 pages : HunyuanOCR-1.5 0,928 / PaddleOCR-VL 0,909 /
  PP-StructureV3 0,557. L'ecart TEDS vs TEDS-Struct montre que le goulot
  d'etranglement est la lecture des caracteres vietnamiens, pas la
  reconstruction de la grille.

- Deux venv incompatibles (PaddleOCR vs transformers 5.x), verifies au
  demarrage de chaque script."

Step "Termine"
git log --oneline -1
Write-Host @"

Pour pousser sur GitHub, cree d'abord un depot VIDE (sans README ni
.gitignore, sinon il faudra fusionner), puis :

    git remote add origin https://github.com/<utilisateur>/<depot>.git
    git branch -M main
    git push -u origin main

"@ -ForegroundColor Yellow
