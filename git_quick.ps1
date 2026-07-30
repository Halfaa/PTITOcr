# Commit + push rapide d'un correctif.
#
# Usage :  .\git_quick.ps1 "message de commit" fichier1 [fichier2 ...]
#          .\git_quick.ps1 "message"                  # commite tout le suivi

param(
    [Parameter(Mandatory = $true)][string]$Message,
    [Parameter(ValueFromRemainingArguments = $true)][string[]]$Fichiers
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# --- Verrou orphelin -------------------------------------------------------
# git cree .git/index.lock le temps d'ecrire l'index et le supprime ensuite.
# S'il subsiste sans processus git actif, c'est un residu : on l'efface. S'il
# y a un git en cours, on s'arrete -- lui retirer son verrou corromprait
# l'index.
$lock = ".git\index.lock"
if (Test-Path $lock) {
    $actifs = @(Get-Process git, git-lfs -ErrorAction SilentlyContinue)
    if ($actifs.Count -gt 0) {
        throw "Un processus git tourne (PID $($actifs.Id -join ', ')). Attends, ou ferme VS Code / GitHub Desktop."
    }
    Write-Host "Verrou orphelin supprime" -ForegroundColor Yellow
    Remove-Item $lock -Force
}

if ($Fichiers) { git add -- $Fichiers } else { git add -u }

# Rien a committer : on le dit et on sort sans erreur.
git diff --cached --quiet
if ($LASTEXITCODE -eq 0) {
    Write-Host "Aucune modification a committer." -ForegroundColor Yellow
    exit 0
}

git commit -m $Message
git push

Write-Host "`nPousse :" -ForegroundColor Green
git log --oneline -1
