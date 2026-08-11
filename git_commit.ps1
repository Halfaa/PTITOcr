# Commit et push du travail du 28 juillet 2026.
#
# Trois commits thematiques plutot qu'un seul fourre-tout : l'historique d'un
# depot de recherche sert a retrouver QUAND une mesure a change et POURQUOI.
# Un commit unique de 30 fichiers ne repond a aucune des deux questions.
#
# Usage :  .\git_commit.ps1

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Etape($texte) { Write-Host "`n=== $texte" -ForegroundColor Cyan }

# --- Verifications ---------------------------------------------------------
if (-not (Test-Path ".git")) { throw "Pas de depot git ici : $PSScriptRoot" }
git rev-parse --abbrev-ref HEAD | ForEach-Object { Write-Host "Branche : $_" }

# --- Verrou orphelin -------------------------------------------------------
# git cree .git/index.lock le temps d'ecrire l'index, et le supprime ensuite.
# S'il subsiste, c'est soit qu'un git tourne encore, soit qu'un processus est
# mort en cours de route. On ne l'efface que dans le second cas : supprimer le
# verrou d'un git actif corromprait l'index.
$lock = ".git\index.lock"
if (Test-Path $lock) {
    $actifs = @(Get-Process git, git-lfs -ErrorAction SilentlyContinue)
    if ($actifs.Count -gt 0) {
        throw "index.lock present ET un processus git tourne (PID $($actifs.Id -join ', ')). " +
              "Attends qu'il finisse, ou ferme l'outil qui l'a lance (VS Code, GitHub Desktop)."
    }
    $age = [int]((Get-Date) - (Get-Item $lock).LastWriteTime).TotalMinutes
    Write-Host "Verrou orphelin trouve (ecrit il y a $age min), aucun git actif -> suppression" -ForegroundColor Yellow
    Remove-Item $lock -Force
}

Etape "Bruit de fins de ligne"
# Ces 20 fichiers n'ont aucun changement de contenu (verifie par
# `git diff --ignore-all-space`), seulement des CRLF a la place des LF.
# On les remet dans leur etat d'origine ; .gitattributes empeche la recidive.
git checkout -- data/ 2>$null
Write-Host "data/ restaure (changements de fins de ligne uniquement)"

# --- Commit 1 : pretraitement ---------------------------------------------
Etape "Commit 1/3 - module de pretraitement"
git add .gitattributes
git add src/preprocess.py src/eval_preprocess.py scripts/dewarp_oracle.py
git add docs/resultats_pretraitement.md
git commit -m @"
Module de pretraitement (Phase 1) et son evaluation

Localisation de la feuille, aplatissement par patch de Coons, correction
d'eclairage, debruitage. Evalue exactement contre les masques de feuille des
cartes UV de doc3D : IoU 0,90 sur 17 pages, 17/17 recadrages exploitables.

Trois defauts trouves par la mesure et corriges :

- GrabCut n'etait pas deterministe. Cinq appels identiques rendaient des
  aires de 0,504, 0,413, 0,021, 0,021, 0,021 : OpenCV initialise ses modeles
  de couleur par un k-means a graine aleatoire, jamais fixee. Le module
  n'etait donc pas reproductible et une partie des ecarts mesures etait du
  bruit. Corrige par cv2.setRNGSeed.

- GrabCut separait l'encre du reste, pas le papier du fond, sur les pages
  portant beaucoup de papier blanc : le contour rendu etait le cadre du
  tableau, et le recadrage supprimait l'en-tete. Un second avis avec l'encre
  effacee tranche, sur une regle verifiable -- effacer l'encre ne peut pas
  deplacer le bord de la feuille. IoU pages 8 et 12 : 0,24 -> 0,81 et
  0,38 -> 0,92.

- La correction d'eclairage ramenait le papier au blanc pur et ecretait avec
  lui les diacritiques, et elle detruisait la couleur sans que ce soit dit.

Resultat OCR (HunyuanOCR) : TEDS 0,950 sur images brutes, 0,973 sur images
pretraitees.
"@

# --- Commit 2 : extraction -------------------------------------------------
Etape "Commit 2/3 - extraction et evaluation"
git add src/table_merge.py src/teds.py src/eval_teds.py src/eval_multipage_merge.py
git add src/invoice_parse.py src/invoice_validate.py src/invoice_fields.py
git add src/invoice_export.py src/eval_fields.py src/eval_validation.py
git add src/merge_multipage_results.py src/report_merge_demo.py src/hunyuan_prompts.py
git add docs/resultats_validation.md
git commit -m @"
Extraction : tableaux Markdown, faux positifs, residus d'etiquette

extract_tables() ne cherchait que <table>. Or HunyuanOCR rend parfois le
tableau en Markdown a pipes : la page entiere etait jetee, contenu pourtant
complet et correct, marqueur de continuation inclus. Deux pages du benchmark
disparaissaient ainsi. Le TEDS de reference de HunyuanOCR passe de 0,928 a
0,950 rien qu'avec ce correctif.

Champs d'en-tete : le champ medecin contenait 'dieu tri va phai trong thoi
han 5' sur deux factures -- une phrase du pied de page legal ou 'bac si'
apparait comme mot courant. Quand la vraie ligne manque dans la sortie OCR,
la recherche d'etiquette tombait dessus. Une valeur fausse mais plausible est
pire qu'une valeur absente : rien en aval ne peut la rattraper. Filtre fonde
sur une regle de la langue, le vietnamien capitalisant chaque syllabe d'un
nom propre.

Ajoute aussi le retrait du residu d'etiquette quand l'OCR abime la forme
longue ('Bac sy ke don' lu 'Bac sy kem').
"@

# --- Commit 3 : environnement et outillage ---------------------------------
Etape "Commit 3/3 - environnement et outillage"
git add src/env_check.py scripts/diagnose_env.py scripts/bench_deformed.py
git add scripts/bench_tabrecset_chandra.py scripts/bench_tabrecset_paddleocr_vl.py
git add scripts/bench_tabrecset_ppstructure.py scripts/smoke_test_hunyuan.py
git add kaggle/ README.md docs/etat_du_projet.md
git commit -m @"
Environnement : plafond NumPy, traces exploitables, notebook Kaggle

PaddleOCR intercepte l'ImportError de NumPy 2.x et la remplace par 'a
dependency error occurred during pipeline creation', qui ne nomme ni le
paquet ni l'exception reelle ; les 17 pages du benchmark echouaient donc a
l'identique sur un message n'indiquant rien. La contrainte etait pourtant
deja ecrite dans requirements.txt -- mais un fichier de dependances n'est pas
applique retroactivement, et un pip install ulterieur peut remonter une
dependance transitive sans avertir.

env_check verifie desormais un plafond de version en plus d'un plancher,
bench_deformed imprime la trace complete a la premiere erreur, et
scripts/diagnose_env.py reproduit un echec de pipeline avec sa trace intacte.

Ajoute kaggle/bench_kaggle.ipynb : l'inference OCR est la seule etape qui
touche au GPU, les evaluations restent en local.
"@

# --- Commit 4 : livrables legers ------------------------------------------
Etape "Commit 4/4 - livrables"
# 256 Ko au total. Le .gitignore ecarte les rapports lourds (report.html fait
# 25 Mo, images en base64) mais garde ceux qu'on montre.
git add results/multipage_hunyuan/merge_report.html
git add results/multipage_hunyuan/json results/multipage_paddleocr_vl/json
git add results/multipage_ppstructure/json
git commit -m @"
Livrables : exports JSON des trois modeles et rapport de fusion

Les exports portent un bloc 'extraction' explicite (no_table, header_not_found,
no_rows, partial, ok) : une facture vide et une extraction ratee ne veulent
pas dire la meme chose, et PP-StructureV3 a produit le cas -- une page rendue
colonnes inversees et sans en-tete donnait un JSON vide d'apparence normale.
"@

# --- Doublon signale, pas commite -----------------------------------------
if (Test-Path "results\multipage_hunyuan\demo_merge_invoice5.html") {
    Write-Host "`nNon commite : results\multipage_hunyuan\demo_merge_invoice5.html" -ForegroundColor Yellow
    Write-Host "  2,4 Mo, et ne differe de demo_fusion_invoice5.html (deja versionne)"
    Write-Host "  que de 155 octets. C'est le meme livrable regenere. A supprimer,"
    Write-Host "  ou a committer en remplacement de l'ancien si c'est la bonne version."
}

# --- Push ------------------------------------------------------------------
Etape "Push"
git push

Etape "Etat final"
git log --oneline -5
git status --short
Write-Host "`nTermine." -ForegroundColor Green
