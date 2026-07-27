# Résultats — factures multi-pages déformées

Trois modèles, 8 factures, 17 pages, jeu de test identique.
Images produites par `synthetic_invoice_generator` puis déformées en 3D par
`doc3D-renderer` (Blender), pour simuler des photos de documents.

Métrique : **TEDS** (Tree-Edit-Distance-based Similarity, Zhong et al. 2020,
PubTabNet) — la métrique standard de reconnaissance de tableaux, donc des
chiffres comparables à la littérature.

- **TEDS** : structure + contenu textuel
- **TEDS-Struct** : structure seule, texte des cellules ignoré

Reproduire :

```powershell
python src\eval_teds.py           --run multipage_hunyuan
python src\eval_multipage_merge.py --run multipage_hunyuan
```

---

## 1. Comparaison des trois modèles

| Modèle | Taille | TEDS | TEDS-Struct | Écart | Temps / page |
|---|---|---|---|---|---|
| **HunyuanOCR-1.5** | 1 B | **0.928** | **0.949** | 0.020 | ~87 s (GPU) |
| PaddleOCR-VL | 0.9 B | 0.909 | 0.933 | 0.024 | ~230 s (CPU) |
| PP-StructureV3 | — | 0.557 | 0.857 | **0.300** | ~60 s (CPU) |

**HunyuanOCR et PaddleOCR-VL sont au coude à coude** (0.928 contre 0.909).
L'écart est réel mais modeste, et sur 8 factures il faut se garder de le
surinterpréter.

**PP-StructureV3 décroche nettement**, et son profil d'erreur est différent :
un écart TEDS / TEDS-Struct de 0.300, contre 0.020 et 0.024 pour les deux
autres. Autrement dit il reconstruit correctement la grille (0.857) mais lit
très mal les caractères vietnamiens. C'est exactement la distinction que
TEDS-Struct sert à faire, et elle oriente le diagnostic : chez lui le
problème est l'OCR, pas la détection de tableau.

---

## 2. Ce qu'apporte la fusion multi-pages

Chaque facture est notée **deux fois contre la même vérité terrain** (la
facture complète) : une fois avec le seul tableau de la 1re page — ce que
produirait un pipeline qui ignore le problème — et une fois avec le tableau
reconstitué par `table_merge`.

| Modèle | TEDS sans fusion | TEDS avec fusion | Gain |
|---|---|---|---|
| HunyuanOCR-1.5 | 0.668 | 0.928 | **+0.260** |
| PaddleOCR-VL | 0.658 | 0.909 | **+0.251** |
| PP-StructureV3 | 0.424 | 0.557 | +0.132 |

Le gain est **du même ordre pour les trois modèles**, ce qui est rassurant :
l'algorithme de fusion n'est pas calibré sur un modèle particulier.

### Détail par facture (HunyuanOCR-1.5)

| Facture | Pages | TEDS sans | TEDS avec | Gain | Struct avec |
|---|---|---|---|---|---|
| 1 | 1–2 | 0.510 | 0.902 | +0.392 | 0.983 |
| 2 | 3–4 | 0.810 | 0.945 | +0.135 | 0.965 |
| 3 | 5–6 | 0.666 | 0.971 | +0.304 | 0.972 |
| 4 | 7–8 | 0.687 | 0.964 | +0.277 | 0.971 |
| 5 | 9–11 | 0.482 | 0.968 | **+0.486** | 0.972 |
| 6 | 12–13 | 0.862 | 0.947 | +0.086 | 0.969 |
| 7 | 14–15 | 0.572 | 0.972 | +0.400 | 0.976 |
| 8 | 16–17 | 0.759 | 0.759 | 0.000 | 0.783 |
| **Moyenne** | | **0.668** | **0.928** | **+0.260** | **0.949** |

La facture 5 est le cas le plus parlant : elle s'étale sur trois pages, et la
fusion la fait passer de 0.482 à 0.968.

La facture 8 est le seul échec : l'OCR n'a extrait **aucun tableau** de la
page 17, il n'y a donc rien à fusionner. C'est un échec de détection en
amont, hors de portée de l'algorithme.

---

## 3. Qualité de la détection de continuation

Évaluée paire de pages par paire de pages, contre une vérité terrain lue
directement dans le PDF source (marqueurs `Tiếp trang trước`) — et non dans
les sorties OCR, qui ont inspiré l'algorithme.

| Modèle | VP | FP | Ratés | Précision | Rappel | F1 |
|---|---|---|---|---|---|---|
| HunyuanOCR-1.5 | 7 | 0 | 0 | 100 % | 100 % | **100 %** |
| PP-StructureV3 | 7 | 0 | 0 | 100 % | 100 % | **100 %** |
| PaddleOCR-VL | 7 | 0 | 1 | 100 % | 88 % | 93 % |

**Zéro faux positif dans les trois cas.** C'est le point le plus important :
une fusion à tort fabrique un tableau qui mélange deux factures, une erreur
bien plus grave qu'une fusion manquée, et bien plus difficile à repérer en
aval.

---

## Limites à assumer

**Échantillon.** 8 factures, 17 pages, un seul générateur, une seule mise en
page. Les chiffres établissent que la chaîne fonctionne sur du bruit OCR
réel — pas qu'elle généralise à d'autres formats de facture.

**Hypothèse métier.** L'algorithme suppose que la colonne STT redémarre à 1 à
chaque facture. C'est le signal le plus discriminant, et celui qui rattrape
les cas où l'OCR a massacré la fin du tableau précédent. À revalider sur des
factures d'un autre format.

**Vérité terrain = tableau *logique*.** En-tête, lignes de médicaments, ligne
Total — pas les artefacts de mise en page (bannière, marqueurs de
continuation, en-têtes répétés). Ces artefacts sont précisément ce que la
fusion doit faire disparaître.

**Séparateurs de milliers neutralisés.** Le générateur choisit au hasard
entre `2900`, `2 900`, `2.900` et `2,900` : variable parasite du générateur,
pas difficulté de lecture. `--strict-numbers` désactive la normalisation.

**Temps non comparables.** HunyuanOCR tourne sur GPU, les deux autres sur
CPU. Les ~87 s contre ~230 s ne mesurent pas l'efficacité relative des
modèles.

---

## Un incident à retenir

Lors de la mise en route de HunyuanOCR, le modèle a produit **6842 caractères
de charabia** (syllabes de pinyin, tirets à répétition) sans lever la moindre
erreur, en 315 s. La cause : le processeur d'images utilisait le backend
torchvision, qui remplace le rééchantillonnage LANCZOS par BICUBIC et écarte
le prétraitement de celui du modèle original. Corrigé en forçant
`backend="pil"` (codé en dur dans `scripts/bench_deformed.py`).

Sans comparaison à une vérité terrain, ce run aurait produit un score TEDS
parfaitement calculé sur des données absurdes. C'est l'argument le plus
concret en faveur de tout le dispositif d'évaluation.
