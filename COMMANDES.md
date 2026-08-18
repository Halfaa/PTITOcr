# Aide-mémoire des commandes

Tout se lance depuis `MedicalRecord\`. Les chemins d'images sont relatifs à ce
dossier, d'où les `..\doc3D-renderer\`.

---

## Le piège à connaître : deux venv incompatibles

`venv` et `venv_hunyuan` ne peuvent pas fusionner — PaddleOCR exige
`transformers` 4.x et `numpy < 2`, HunyuanOCR et GLM-OCR exigent
`transformers` ≥ 5.13.

| tu veux… | venv |
|---|---|
| prétraiter, évaluer, la démo de fusion | `venv` |
| PaddleOCR-VL, PP-StructureV3 | `venv` |
| HunyuanOCR, GLM-OCR, Chandra | `venv_hunyuan` |

```powershell
.\venv\Scripts\activate           # ou .\venv_hunyuan\Scripts\activate
deactivate                        # pour changer
```

Les scripts vérifient l'environnement au démarrage et échouent **en une
seconde** avec la commande de correction, plutôt qu'après trois minutes de
chargement de modèle. Si un message `WRONG ENVIRONMENT` apparaît, il dit quoi
faire.

---

## 1. Prétraiter des images

C'est la Phase 1 : trouver la feuille, la redresser, corriger l'éclairage.

```powershell
# Un dossier entier -> <dossier>_preprocessed
python src\preprocess.py --images-dir "..\doc3D-renderer\img\multipage_test"

# Vers un dossier choisi, avec le rapport visuel (fortement recommandé)
python src\preprocess.py --images-dir "..\doc3D-renderer\img\multipage_test" `
    --out "..\doc3D-renderer\img\mon_test" --debug
```

`--debug` écrit `_debug\` : avant/après côte à côte, avec le quadrilatère
détecté et son score. **C'est là qu'on voit un recadrage qui a mordu sur
l'en-tête** — un chiffre de TEDS ne le dira jamais.

### Une seule image

`preprocess.py` prend un dossier, pas un fichier. Le plus rapide est de
l'isoler :

```powershell
mkdir essai
copy "..\doc3D-renderer\img\multipage_test\page_1-*.png" essai\
python src\preprocess.py --images-dir essai --out essai_out --debug
```

### Les options qui servent vraiment

```powershell
--min-score 0.40      # accepte des détections moins sûres (défaut 0.55)
                      #   à monter si un recadrage coupe une page,
                      #   à baisser si des pages ne sont pas recadrées du tout
--pad 0.25            # marge de sécurité autour de la feuille (défaut 0.16)
                      #   la remonter est le premier réflexe si l'en-tête est rogné
--no-crop             # n'améliore que l'éclairage, sans redresser
--no-illumination     # désactive la correction d'éclairage
--binarize            # noir et blanc — dégrade les VLM, à ne garder que
                      #   pour comparer avec l'OCR classique
--min-long-side 0     # n'agrandit pas le recadrage (défaut : résolution source)
```

### Noter la qualité du recadrage

Contre les masques UV exacts produits par Blender — vérité terrain au pixel :

```powershell
python src\eval_preprocess.py --batch multipage_test
```

---

## 2. Faire lire une image par un modèle

```powershell
$IMG = "..\doc3D-renderer\img"

# --- venv ---
python scripts\bench_deformed.py --model paddleocr-vl --images-dir "$IMG\multipage_test" --output essai_paddle
python scripts\bench_deformed.py --model ppstructure  --images-dir "$IMG\multipage_test" --output essai_ppstruct

# --- venv_hunyuan ---
python scripts\bench_deformed.py --model hunyuan --images-dir "$IMG\multipage_test" --output essai_hunyuan
python scripts\bench_deformed.py --model glm     --images-dir "$IMG\multipage_test" --output essai_glm
python scripts\bench_deformed.py --model chandra --images-dir "$IMG\multipage_test" --output essai_chandra
```

**`--limit 1` avant tout le reste.** Une page suffit à savoir si le modèle
lit les diacritiques, et évite de découvrir au bout d'une heure qu'il rend du
charabia :

```powershell
python scripts\bench_deformed.py --model glm --images-dir "$IMG\multipage_test" `
    --limit 1 --output smoke_glm
```

Chaque run écrit `results\<nom>\pages\<image>\*.md` et un
`results\<nom>\report.html` **réécrit après chaque image** : une interruption
ne coûte qu'une page, et relancer réutilise ce qui est déjà fait. Pour tout
refaire, supprimer le dossier du run.

### Une seule image, sans passer par le banc

```powershell
python scripts\smoke_test_hunyuan.py --image "$IMG\multipage_test\page_1-concave_mesh_10001.png"
python scripts\smoke_test_hunyuan.py --image ... --prompt document_full   # garde en-têtes et pieds de page
python scripts\smoke_test_hunyuan.py --image ... --device cpu             # si la VRAM sature
```

---

## 3. Évaluer

### Tout, d'un coup — c'est la commande normale

```powershell
python scripts\eval_all.py --modele chandra
python scripts\eval_all.py --modele chandra --modele hunyuan --modele paddleocr --modele ppstructure
python scripts\eval_all.py --modele chandra --jeu multipage      # un seul jeu
python scripts\eval_all.py --modele chandra --complet            # journaux entiers
```

Elle enchaîne les cinq évaluations avec la **bonne vérité terrain pour chaque
jeu**. Le détail atterrit dans `results\_evaluations\<modele>.txt`, pour
qu'un chiffre du tableau reste traçable jusqu'à la ligne qui l'a produit.

Un nom de run inconnu de `eval_all.py` ne sera pas évalué : la correspondance
run → jeu → vérité terrain est déclarée dans `MODELES`, en haut du fichier.
C'est délibéré — c'est ce qui empêche de noter un run contre la mauvaise
vérité terrain, ce qui ne lève aucune erreur et produit des nombres qui ne
veulent rien dire.

### Une évaluation à la fois

```powershell
python src\eval_teds.py            --run essai_hunyuan     # TEDS et TEDS-Struct
python src\eval_multipage_merge.py --run essai_hunyuan     # précision/rappel de la fusion
python src\eval_fields.py  --runs essai_hunyuan --detail   # champs d'en-tête, --detail liste les ratés
python src\eval_validation.py --run essai_hunyuan          # validation arithmétique
python src\eval_adaptive.py --raw essai_hunyuan --preprocessed essai_preproc_hunyuan
```

**Sur le jeu diversifié**, il faut donner la vérité terrain — sinon les
scripts prennent celle du jeu multi-pages et les chiffres sont faux sans
qu'aucune erreur n'apparaisse :

```powershell
$PDF = "..\synthetic_invoice_generator\hospital_pharmacy\invoices_variants.pdf"
$GT  = "..\synthetic_invoice_generator\hospital_pharmacy\ground_truth_labels_variants"

python src\eval_teds.py       --run variants_chandra --pdf $PDF --gt-dir $GT
python src\eval_fields.py     --runs variants_chandra --pdf $PDF --gt-dir $GT
python src\eval_validation.py --run variants_chandra --pdf $PDF --gt-dir $GT
python src\eval_multipage_merge.py --run variants_chandra --pdf $PDF
```

C'est exactement ce que `eval_all.py` fait à ta place.

---

## 4. Regarder les résultats

```powershell
# La démo de fusion : on glisse les images, on voit les décisions
python demo\demo_fusion.py                       # -> http://localhost:8010

# L'application complète (PWA)
python src\api.py                                # -> http://localhost:8000

# Rapport visuel d'un run
start results\essai_hunyuan\report.html

# Rapport de fusion d'un run
python src\merge_multipage_results.py --run essai_hunyuan
start results\essai_hunyuan\merge_report.html

# Une facture précise, avant/après fusion
python src\report_merge_demo.py --run essai_hunyuan --invoice 5

```

### Les JSON de données extraites

**C'est le livrable final de la chaîne**, et il n'est pas produit
automatiquement par les runs : il faut le demander.

```powershell
# Toutes les factures d'un run -> results\<run>\json\invoice_N.json
python src\invoice_export.py --run multipage_chandra

# Une seule, affichée aussi dans le terminal
python src\invoice_export.py --run multipage_chandra --invoice 5 --print

# Jeu diversifié : le --pdf est OBLIGATOIRE, sinon le découpage en factures
# vient du jeu multi-pages et les pages atterrissent dans la mauvaise facture
$PDF = "..\synthetic_invoice_generator\hospital_pharmacy\invoices_variants.pdf"
python src\invoice_export.py --run variants_chandra --pdf $PDF
```

Chaque `invoice_N.json` contient :

| clé | contenu |
|---|---|
| `source` | run, numéro de facture, pages d'origine, horodatage |
| `document` | hôpital, patient, date, médecin, adresse, n° de facture, mode de paiement, plus `_field_coverage` |
| `extraction` | `ok` / `partial` / `failed` — **une facture vide et une extraction ratée ne sont pas la même chose** |
| `items` | une entrée par ligne : `index`, `name`, `unit`, `quantity`, `unit_price`, `total`, et un bloc `check` par ligne |
| `totals` | total déclaré, total recalculé depuis les lignes, et leur cohérence |
| `review` | nombre de lignes à relire, lesquelles, et les trous de numérotation |

`review.lines_to_check` est ce qui rend le résultat exploitable en pratique :
sur 215 lignes, 6 % sont signalées et elles contiennent 100 % des erreurs
numériques. C'est le champ à montrer en réunion.

### Le résumé chiffré d'un run

`invoice_export.py` fait un fichier par facture ; celui-ci agrège.

```powershell
python src\summary_export.py --run multipage_preproc_chandra
python src\summary_export.py --all      # tous les runs + results\_summary.json
```

Écrit `results\<run>\summary.json` : nombre de factures et de pages, statuts
d'extraction, **chaque champ d'en-tête en trouvé/max** (`hospital_name 8/8`,
`payment_method 2/8`…), lignes équilibrées / corrigées / à relire, totaux
lisibles et cohérents, numérotation vérifiable et sans trou.

Tout est en **trouvé / maximum atteignable**, jamais en pourcentage seul : un
« 88 % » ne dit pas s'il porte sur 8 documents ou sur 800.

Et surtout, **aucun de ces chiffres n'utilise de vérité terrain**. Ce résumé
mesure ce que la chaîne a extrait et ce qu'elle sait de sa propre fiabilité —
il tournera donc aussi sur de vraies factures, là où TEDS ne peut pas.

Les sorties **brutes** du modèle, elles, sont dans
`results\<run>\pages\<image>\*.md` — du Markdown ou du HTML selon le
modèle. PaddleOCR ajoute un `*_res.json` qui lui est propre (boîtes,
scores) ; les modèles VLM n'en produisent pas, ils ne rendent que du texte.
```

---

## 5. Vérifier que la logique n'a pas régressé

```powershell
python tests\test_merge_assumptions.py    # 10 cas construits à la main, 1 seconde
python demo\explain_teds.py               # ce que TEDS récompense et punit
```

`test_merge_assumptions.py` ne charge aucun modèle : un échec y est un défaut
d'**algorithme**, pas de lecture. À lancer après toute retouche de
`table_merge.py`.

---

## 6. Régénérer le jeu de test

```powershell
cd ..\synthetic_invoice_generator\hospital_pharmacy
python gen_variants_json.py          # les JSON de vérité terrain
python create_latex_variants.py      # LaTeX -> PDF -> PNG

cd ..\..\doc3D-renderer
.\render_variants.ps1                # déformation 3D sous Blender
```

Fond encombré — 3 à 6 feuilles parasites autour de la cible :

```powershell
.\render_variants.ps1 -FolderId variants_encombre -Parasites -1
.\render_variants.ps1 -FolderId variants_encombre -Parasites -1 -Verifier   # 1 image d'essai
```

**Piège de `-Nombre`.** Les textures sont triées par *nom*, donc l'ordre est
`page_1, page_10..page_19, page_2, page_20..page_25, page_3, page_4,
page_5..page_9`. `-Nombre 20` ne rend pas les pages 1 à 20 — il coupe les
pages 5 à 9, ce qui ampute la facture 5 sans que rien ne le signale. Le bilan
affiche maintenant les numéros rendus et les absents ; `-Depuis` complète :

```powershell
.\render_variants.ps1 -FolderId variants_encombre -Parasites -1 -Depuis 20 -Nombre 5
```

Étude de dégradation — jusqu'où la chaîne tient-elle ?

```powershell
python scripts\degrader.py --jeu variants_warped --calibrer   # contrôler les paliers
python scripts\degrader.py --jeu variants_warped --zip        # 192 images + l'archive
# ... run Kaggle ...
python scripts\eval_degradation.py --figure
```

**Ne pas utiliser `Compress-Archive`** pour cette archive-là. PowerShell 5.1
écrit les sous-dossiers avec des antislashs, alors que la spécification ZIP
impose la barre oblique : Kaggle refuse l'import avec « contains a forbidden
character in name ('\\') ». D'où l'option `--zip`, qui écrit l'archive
correctement et vérifie qu'aucune entrée ne contient d'antislash. C'est le
premier zip du projet à avoir des sous-dossiers, les précédents étaient plats.

Toujours `--calibrer` d'abord, et regarder les images : la première grille de
paliers était inutilisable (texte encore lisible au JPEG le plus dur), ce
qu'aucun nombre ne disait. Détail dans [docs/degradation.md](docs/degradation.md).

Sonde de plafond — le recadrage peut-il marcher sur fond encombré ?

```powershell
python scripts\sonde_plafond.py --jeu variants_encombre        # sans SAM
python scripts\sonde_plafond.py --jeu variants_encombre --sam
python scripts\sonde_plafond.py --jeu variants_warped --sam    # non-régression
```

Deux colonnes à ne pas confondre : le **plafond** dépend du générateur de
candidats, l'**obtenu** du scoring. Un plafond qui ne bouge pas malgré SAM
signifie que les candidats ne contiennent toujours pas la feuille, et qu'il
faut une segmentation apprise. SAM va dans un venv séparé — surtout pas dans
`venv`, épinglé numpy<2 pour PaddleOCR :

```powershell
python -m venv venv_sam ; venv_sam\Scripts\activate
python -m pip install --upgrade pip
pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install --no-cache-dir ultralytics "opencv-python<4.12"
```

Deux épingles qui comptent. `opencv-python<4.12` : les 5.x rendent `None` sur
un `.exr` **sans lever d'erreur**, la sonde ne lirait plus les masques UV. Et
le torch CPU explicite : la roue CUDA par défaut pèse 2,4 Go contre 200 Mo,
pour un modèle de 23 Mo qui tourne très bien sur processeur.

Si pip sort `THESE PACKAGES DO NOT MATCH THE HASHES`, c'est un téléchargement
tronqué, pas une compromission : `--no-cache-dir` évite de recycler le wheel
incomplet, et mettre pip à jour règle le reste.

Vérité terrain du recadrage — chaque masque UV doit être d'un seul tenant,
sinon les parasites ont fui dans la passe UV et l'IoU mesuré est faux :

```powershell
python ..\MedicalRecord\scripts\verifier_masque_uv.py --jeu variants_encombre
```

---

## 7. Le rapport et les figures

```powershell
python demo\build_html.py            # REPORT.md -> REPORT.html autonome
```

**Dans Notion : Import → HTML**, jamais le Markdown. L'import Markdown de
Notion supprime silencieusement les images locales, zip ou pas.

---

## 8. Environnement

```powershell
python scripts\diagnose_env.py                            # ce qui est installé, et où
python -c "import torch; print(torch.cuda.is_available())"
nvidia-smi
```

### Erreurs déjà rencontrées, et leur cause

| message | cause |
|---|---|
| `a dependency error occurred during pipeline creation` | `numpy >= 2` dans le venv Paddle → `pip install "numpy<2"` |
| `KeyError: 'glm_ocr'` | `transformers` trop ancien → `pip install git+https://github.com/huggingface/transformers.git` |
| sortie d'HunyuanOCR en charabia | backend torchvision au lieu de `pil` — codé en dur, ne pas y toucher |
| `PDX has already been initialized` | l'écho d'une **première** erreur ; la vraie cause est plus haut dans le log |
| CUDA out of memory | `--device cpu`, ou baisser la résolution |

---

## 9. Git

```powershell
.\git_quick.ps1 "message de commit" src/ docs/     # ajoute, commite, pousse
.\git_quick.ps1 "message"                          # tout ce qui a changé
```

Le script neutralise un `index.lock` orphelin, qui bloque git sans rien dire
quand un processus Windows a gardé le dépôt ouvert.
