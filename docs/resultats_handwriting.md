# Benchmark HTR manuscrit — VN / EN (26 août)

Suite naturelle du pipeline factures : peut-on lire de l'écriture manuscrite
sur les mêmes formulaires médicaux, dans les deux langues du stage ? Deux
générateurs synthétiques (`handwriting/` pour la page 9 PHCN vietnamienne,
`handwriting_en/` pour les pages 1-2 du dossier anglais), 30 specimens par
langue, vérité terrain exacte au champ près (`*_verite.json`).

---

## 1. Modèles testés, et pourquoi ceux-là

Recherche faite avant de lancer quoi que ce soit : trois candidats,
choisis pour couvrir l'éventail taille/licence déjà établi sur les factures.

| modèle | taille | licence | statut |
|---|---|---|---|
| Chandra OCR 2 | 5 B | Apache 2.0 (code) / OpenRAIL-M modifiée (poids) | mesuré |
| PaddleOCR-VL | 0,9 B | Apache 2.0 | mesuré |
| GLM-OCR | 0,9 B | MIT | en attente (voir §4) |
| HunyuanOCR-1.5 | 1 B | Tencent (exclut UE/UK/Corée du Sud) | **écarté** |

GLM et HunyuanOCR partagent le même environnement (`transformers` récent),
donc le même notebook Kaggle. **HunyuanOCR est écarté** : sa licence exclut
l'UE et Kaggle ne permet pas de choisir la région de la machine — décidé
sans même le lancer, l'écart déjà large entre Chandra et PaddleOCR-VL sur ce
jeu ne justifie pas de composer avec cette contrainte.

---

## 2. Protocole de mesure

Contrairement aux factures, il n'existe pas d'extracteur de champs
structuré par modèle — chaque modèle rend une transcription libre de toute
la page, avec ses propres conventions de mise en page. `src/eval_handwriting.py`
pose donc une question plus modeste : **le texte attendu apparaît-il quelque
part dans la transcription**, exactement ou approximativement ? Trois
signaux (exact / lenient / score de similarité locale), détail dans le
docstring du script.

Champs numériques ou très courts (`"5"`, `"X"`) : recherche sur frontière de
mot, pour éviter qu'un chiffre isolé ne « matche » par hasard dans une page
dense en dates et téléphones.

---

## 3. Résultats (26 août)

30 specimens par jeu, champs manuscrits uniquement (le champ `khoa` du VN
est imprimé, pas manuscrit ; `sex` de l'EN est une case à cocher, pas du
texte — exclus de ce tableau, comptés à part dans le script).

| jeu | Chandra OCR 2 (5 B) | PaddleOCR-VL (0,9 B) |
|---|---|---|
| VN | **95,5 %** (score 97,2) | 78,2 % (score 84,8) |
| EN | **99,1 %** (score 99,7) | 90,3 % (score 97,5) |

Chandra domine nettement les deux langues, cohérent avec son avantage déjà
mesuré sur les factures à fond propre (§ `resultats_teds.md`). L'écart est
plus marqué en vietnamien : les diacritiques restent le point dur, pour les
deux modèles, mais PaddleOCR-VL en souffre visiblement plus.

### Ce qui reste manqué chez Chandra (VN, 4,5 %)

Inspection du détail : des quasi-échecs réels, pas un artefact de mesure —
scores 66 à 79, sur des descriptions longues partiellement mal lues (`mo_ta`,
`ky_thuat`) et quelques noms propres ou noms de département (`so_y_te`).
Rien à corriger côté script ici.

---

## 4. Deux bugs trouvés en traitant ces résultats

### GLM-OCR : OOM systématique, 30/30 sur les deux langues

Erreur CUDA identique sur chaque specimen : tentative d'allocation de
23,43 GiB. Cause : nos specimens font 1654×2339 px (~200 dpi), alors que
GLM n'avait tourné jusqu'ici que sur les images factures, 900×1200 — 3,6×
moins de pixels. `_glm_predict` (dans `scripts/bench_deformed.py`) passait
le chemin de l'image brute au processeur sans redimensionnement ; GLM-OCR
n'a ni tuilage ni sous-échantillonnage intégré côté encodeur visuel,
contrairement à Chandra et Hunyuan qui encaissent nos images sans y
toucher.

**Corrigé** : redimensionnement à 1200 px de grand côté avant l'appel
(`GLM_MAX_LONG_SIDE`), via une copie temporaire puisque le processeur ne
prend qu'un chemin de fichier dans le message, pas un objet image. Le
notebook Kaggle est à relancer (tâche #31) — les runs précédents n'ayant
produit aucun `.md`, la reprise se fait à zéro sans rien nettoyer.

### `eval_handwriting.py` : les balises HTML de Chandra cassaient le score

Chandra rend les tableaux en HTML brut dans le Markdown, avec un `<br/>`
entre deux lignes d'une même cellule — typiquement le champ `ngay_gio`
(« 15h00<br/>12/07 »), alors que la vérité terrain attend un espace
(« 15h00 12/07 »). Le normaliseur ne retirait aucune balise : un champ
correctement lu comptait comme manqué. Trouvé en inspectant à la main le
premier score VN de Chandra (77,7 %), où *presque tous* les `ngay_gio` de
chaque specimen ressortaient comme ratés — un motif trop régulier pour être
une vraie erreur de lecture.

**Corrigé** par `_sans_html()`, qui retire toute balise (pas seulement
`<br/>` : PaddleOCR-VL encadre chaque cellule de `<td style='...'>`, Chandra
ajoute parfois `<i>...</i>` — inoffensifs aujourd'hui mais potentiellement
pas demain). Effet mesuré : Chandra VN passe de **77,7 % à 95,5 %**.
PaddleOCR-VL ne bouge quasiment pas (78,2 % → 78,2 %), il n'utilisait pas de
`<br/>` dans ses cellules — c'était bien un artefact du rendu Chandra, pas
un problème général de méthode.

---

## 5. Deux observations qualitatives, sur les pires specimens de chaque langue

Inspection visuelle du rapport HTML de PaddleOCR-VL (images + transcription
côte à côte), sur le pire score de chaque jeu.

### VN — hallucinations CJK, pas un problème de lisibilité

`specimen_005` (police unique, Playwrite VN) : l'écriture est parfaitement
lisible à l'œil, ce qui écarte une explication par la forme des lettres.
Pourtant PaddleOCR-VL insère par endroits des caractères **chinois et
coréens** au lieu du texte attendu : « liệt nửa người trái » devient
« liết n**其一** người trái », « Đồng ý » devient « Đông **너** ». Quand le
modèle est incertain sur un diacritique vietnamien, il semble retomber sur
un token CJK plutôt que sur une lettre latine fausse — cohérent avec la
réserve déjà notée pour GLM-OCR (le vietnamien hors de ses langues
officielles), mais observé ici sur PaddleOCR-VL.

### EN — l'effet de police est net et mesurable

Score par police, sur les 30 specimens EN (PaddleOCR-VL) :

| police | n | moyenne |
|---|---|---|
| homemade_apple | 3 | **79,6 %** |
| reenie_beanie | 6 | 88,9 % |
| patrick_hand | 7 | 91,4 % |
| shadows_into_light | 6 | 91,5 % |
| caveat | 3 | 91,7 % |
| sacramento | 4 | 92,4 % |
| alex_brush | 1 | 92,6 % |

Homemade Apple (« irrégulier, très réaliste » selon sa propre description
dans `handwriting_en/README.md`) décroche nettement des six autres, de façon
cohérente sur ses trois occurrences (71 %, 83 %, 85 %). Sur le pire cas
(`specimen_019`), le **T majuscule cursif** de cette police est visiblement
ambigu : « Thang » → « Zhang », « Tran » (adresse) → « Iran », « Tran »
(signature) → « Jan » — trois lectures différentes de la même lettre sur la
même page. Une vraie ambiguïté visuelle du glyphe, pas une confusion
systématique à sens unique.

À vérifier une fois Chandra et GLM disponibles sur ces mêmes specimens : si
Homemade Apple reste le point faible sur les trois modèles, c'est un signal
sur la police plutôt que sur un modèle en particulier.

---

## 6. Reste à faire

- Relancer GLM-OCR (tâche #31) après le correctif de redimensionnement.
- Compléter le tableau à trois modèles, VN et EN.
- Vérifier si l'effet Homemade Apple et les hallucinations CJK se
  reproduisent sur Chandra et GLM, ou sont spécifiques à PaddleOCR-VL.
