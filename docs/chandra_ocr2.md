# Chandra OCR 2 — pourquoi le mesurer, et à quoi s'attendre

Chandra OCR 2 (Datalab, 5 milliards de paramètres, dérivé de Qwen3.5) est le
quatrième modèle du protocole. Il avait été écarté en semaine 2 pour une
raison purement matérielle : 5 B ne tiennent pas dans les 4 Go de la RTX
3050 Ti, et le repli CPU tourne à **~15 min par image** — 17 pages font une
nuit de calcul, et les 109 pages du protocole complet, trois semaines.

D'où `kaggle/bench_kaggle_chandra.ipynb` : sur un T4 (16 Go), les poids
tiennent et la même page passe à une ou deux minutes.

---

## 1. Ce que Chandra apporte au comparatif

C'est le seul modèle du lot dans la **classe des 5 B**. Les trois autres
sont à 0,9–1 B, ou sans réseau de reconnaissance moderne du tout
(PP-StructureV3). Le comparatif répond donc jusqu'ici à « quel petit modèle
choisir », pas à « qu'est-ce qu'on gagne à en prendre un gros ».

C'est aussi le meilleur score public sur olmOCR-bench : **85,9 %**, devant
dots.ocr 1.5 (83,9) et olmOCR 2 (82,4). Si un modèle doit battre HunyuanOCR
sur nos factures, c'est celui-là.

---

## 2. La réserve, et elle est chiffrée

Le benchmark multilingue de Datalab donne, sur le **vietnamien** :

| modèle | vi |
|---|---|
| Datalab API | 85,0 % |
| Gemini 2.5 Flash | **89,5 %** |
| **Chandra 2** | 80,4 % |
| Chandra 1 | 81,6 % |
| GPT-5 Mini | 83,6 % |

Deux choses à noter. Le vietnamien est **sous la moyenne** de Chandra 2
(77,8 % sur 43 langues, mais 80,4 seulement ici alors que le français est à
93,7 et l'allemand à 94,8). Et **Chandra 2 régresse sur le vietnamien par
rapport à Chandra 1** (80,4 contre 81,6), alors qu'il progresse de 12 points
en moyenne.

Autrement dit : les gains de la version 2 ne sont pas allés vers notre
langue. Un modèle cinq fois plus gros que HunyuanOCR peut très bien ne pas
le battre ici, et ce serait un résultat en soi — pas un échec de mesure.

C'est le genre de prédiction qu'il vaut mieux écrire **avant** de lancer le
benchmark.

---

## 3. Licence — plus confortable que HunyuanOCR

| | code | poids | restriction géographique |
|---|---|---|---|
| PaddleOCR-VL | Apache 2.0 | Apache 2.0 | aucune |
| **Chandra 2** | Apache 2.0 | OpenRAIL-M modifiée | **aucune** |
| HunyuanOCR-1.5 | — | Tencent Community | **exclut l'UE, le R.-U. et la Corée du Sud** |

Les poids de Chandra sont libres pour la recherche, l'usage personnel et les
structures sous 2 M$ de revenus ou de levée, avec une clause de
non-concurrence vis-à-vis de l'API commerciale de Datalab. Un stage de
recherche académique entre dans ce cadre sans difficulté.

**Ce point est important pour Kaggle.** La licence Tencent définit un
Territoire qui exclut l'UE, et Kaggle ne permet pas de choisir la région de
la machine : y faire tourner HunyuanOCR est un risque juridique qu'on ne
peut pas lever. Chandra et PaddleOCR-VL n'ont pas ce problème. Sur ce
critère, Chandra est un candidat de déploiement plus sûr que le modèle qui
mène actuellement le classement.

---

## 4. Les cinq branches à produire

Pour que les chiffres soient comparables, Chandra doit passer **exactement**
par où sont passés les autres.

| run | jeu | prétraitement |
|---|---|---|
| `multipage_chandra` | 17 pages déformées, 8 factures | non |
| `multipage_preproc_chandra` | idem | oui |
| `variants_chandra` | 25 pages à plat, 12 factures | non |
| `variants_warped_chandra` | les mêmes, déformées | non |
| `variants_warped_preprocessed_chandra` | idem | oui |

Les branches brute et prétraitée vont **par paire** : `src/adaptive.py`
choisit entre les deux lectures, il lui faut les deux, produites dans les
mêmes conditions.

### Sur Kaggle

Le notebook `kaggle/bench_kaggle_chandra.ipynb` fait les cinq. Trois datasets
à attacher, tous zippés dans `kaggle/` :
`images_multipage_warped.zip`, `images_variants_flat.zip`,
`images_variants_warped.zip`. Le prétraitement est calculé **dans la
session**, à partir du `src/preprocess.py` du dépôt — des images prétraitées
téléversées se périmeraient à la première modification du module, sans que
rien ne le signale.

Une cellule d'étalonnage lit **une page**, chronomètre et projette le total
avant qu'on engage des heures de calcul. Une session Kaggle avec GPU est
coupée à 12 h et le quota hebdomadaire est de 30 h : si la projection
dépasse ~9 h, il faut couper `BRANCHES` en deux notebooks.

### En local, ensuite

```powershell
python scripts\eval_all.py --modele chandra
python scripts\eval_all.py --modele chandra --modele hunyuan --modele paddleocr
```

---

## 5. Deux détails techniques qui décident du temps de calcul

**Le dtype.** Chandra est publié en bf16, mais **bf16 n'a aucun support
matériel avant la compute capability 8.0**. Un T4 (7,5) ou un P100 (6,0)
accepte les tenseurs bf16 et les émule, plusieurs fois plus lentement que
fp16 — sans la moindre erreur pour dire pourquoi. `_load_chandra` choisit
donc fp16 en dessous de 8.0. Le risque qui motive bf16 est un risque
d'entraînement ; en inférence, les activations de Qwen3.5 restent largement
dans la plage fp16.

**Un seul GPU.** Kaggle donne deux T4 ; `device_map="auto"` étalerait les
5 B sur les deux, ajoutant un aller-retour PCIe à chaque passe avant pour
rien. 10 Go tiennent sur une carte, donc `device_map={"": 0}`.

Même logique pour l'attention : flash-attention 2 exige aussi 8.0, la
demander sur un T4 échoue au chargement. On demande `sdpa`, que PyTorch fait
retomber sur le meilleur noyau que la carte possède vraiment.

---

## 6. Résultats (5 août) — les prédictions face aux mesures

Les cinq branches ont tourné sur un T4 Kaggle, ~81 s/page en fp16. Protocole
unifié (`scripts/eval_all.py`), détail dans
`results/_evaluations/chandra_et_protocole_unifie.txt`.

### Multi-pages (8 factures, 17 pages déformées)

| | Chandra | Hunyuan | PaddleVL | PP-Struct |
|---|---|---|---|---|
| TEDS brut | 0,916 | **0,950** | 0,909 | 0,557 |
| TEDS prétraité | **0,966** | 0,879* | 0,951 | — |
| TEDS adaptatif | **0,966** | 0,953 | 0,951 | — |
| plafond | 0,967 | 0,955 | 0,955 | — |
| champs (adaptatif) | **29/32** | 28/32 | 24/32 | 9/32 |
| fusion P/R | 100/100 | 100/100 | 100/88 | 100/100 |
| arithmétique R/P | 80/100 | 100/100 | 50/100 | 75/100 |

\* le run prétraité de Hunyuan date d'une version antérieure du module de
prétraitement (IoU 0,79 au lieu de 0,90) : son adaptatif est un plancher.

### Jeu diversifié (12 factures, 6 gabarits)

| | Chandra | PaddleVL |
|---|---|---|
| à plat | **0,981** | 0,976 |
| déformé, brut | **0,944** | 0,906 |
| déformé, adaptatif | **0,977** (plafond 0,977) | 0,942 (plafond 0,945) |
| champs à plat | **47/48** | — |
| champs déformé (adaptatif) | **46/48** | 44/48 |

### Ce que les prédictions avaient anticipé — et pas

**Anticipé.** Sur pages déformées brutes, cinq fois plus de paramètres
n'achètent pas la première place : 0,916 contre 0,950 pour Hunyuan. C'est
cohérent avec son benchmark vietnamien (80,4 %, en régression sur Chandra 1).

**Pas anticipé.** Chandra est le modèle qui profite **le plus** du
prétraitement : +0,050 sur le jeu multi-pages, là où Hunyuan perdait sur son
ancien run prétraité. Aplanies et éclairées uniformément, ses lectures
prennent la tête partout : meilleur adaptatif multi-pages (0,966), meilleur
sur le diversifié à plat (0,981) comme déformé (0,977, **au plafond** — la
règle de décision ne perd rien).

### Deux défauts propres à Chandra

**En-têtes HTML malformés.** Des `colspan`/`rowspan` mal placés qui absorbent
une colonne — visibles dès la première page multi-pages. TEDS-Struct les
paie ; la fusion n'en souffre pas.

**Un raté arithmétiquement invisible.** Son rappel de validation est de 80 %,
et l'exemple manqué est instructif : une ligne décalée d'une colonne qui
*multiplie encore juste* (1700 × 6800 = 11 560 000). C'est le seul type
d'erreur numérique auquel la validation est structurellement aveugle — à
citer dans la section « échecs silencieux ».

---

## Sources

- [datalab-to/chandra-ocr-2 (Hugging Face)](https://huggingface.co/datalab-to/chandra-ocr-2) — benchmarks olmOCR et multilingue, licence, débit
- [Chandra, dépôt GitHub](https://github.com/datalab-to/chandra) — [benchmark 90 langues](https://github.com/datalab-to/chandra/blob/master/FULL_BENCHMARKS.md)
- [olmOCR-bench (AllenAI)](https://huggingface.co/datasets/allenai/olmOCR-bench)
