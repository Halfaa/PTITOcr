# Module de prétraitement — résultats

Phase 1 du sujet : localisation du document, transformation perspective,
correction d'éclairage, débruitage. Code dans `src/preprocess.py`,
évaluation dans `src/eval_preprocess.py`.

```powershell
python src\preprocess.py --images-dir "..\doc3D-renderer\img\multipage_test" --debug
python src\eval_preprocess.py
```

---

## 1. Le résultat principal : la localisation classique ne fonctionne pas

On peut la noter **exactement**, ce qui est rare : `doc3D-renderer` écrit une
carte UV à côté de chaque rendu, et son premier canal est le masque de la
feuille. On dispose donc d'une vérité terrain au pixel près pour « où est le
papier », et on peut calculer l'IoU du quadrilatère détecté.

| Mesure | Valeur |
|---|---|
| Plafond des candidats | **0,51** |
| Ce que la sélection retient | **0,35** |
| Images avec un recadrage exploitable (IoU ≥ 0,7) | **0 / 17** |

Le plafond est le point important : c'est le meilleur IoU atteignable sur
**l'ensemble** des segmentations candidates, avant même de choisir. À 0,51,
aucun sélecteur, si parfait soit-il, ne donnerait un recadrage utilisable.
**Ce ne sont pas les critères de choix qui échouent, ce sont les
segmentations elles-mêmes.**

### Pourquoi

Aucun indice visuel ne sépare la feuille du fond de façon constante. Mesuré
sur nos rendus, en comparant la zone de la feuille (connue exactement) au
fond :

| Page | Luminosité | Saturation | Texture |
|---|---|---|---|
| page 1 | feuille plus **sombre** | feuille plus **saturée** | feuille plus **texturée** |
| page 4 | identique | feuille **moins** saturée | feuille **moins** texturée |

Tous les signes s'inversent. C'est logique : doc3D tire ses fonds d'images
naturelles au hasard, et rien ne garantit qu'un papier soit plus clair qu'un
plan de travail ou qu'un mur.

### Le piège qu'il faut connaître

La première version, fondée sur la détection de contours — l'approche
littérale de la Phase 1 du sujet — trouvait un quadrilatère sur 88 % des
images. Mais elle s'accrochait au **cadre du tableau**, pas au bord de la
feuille : sur une facture imprimée, le rectangle au contraste le plus fort
est le tableau, tandis que le bord du papier est ténu sur un fond clair.

Conséquence : le recadrage supprimait tout l'en-tête — nom d'hôpital,
patient, date, médecin. **Un module de prétraitement naïf aurait donc
aggravé la perte des champs que le sujet nomme explicitement**, tout en
paraissant fonctionner.

---

## 2. La politique retenue

**Toujours corriger la photométrie, ne recadrer que si la détection est
fiable.**

La correction d'éclairage — division par une copie fortement floutée — ne
peut rien perdre : elle annule le dégradé de luminosité sans toucher au
contenu. Elle donne visuellement d'excellents résultats sur ces rendus, dont
l'ombrage marqué est la principale différence résiduelle avec la page plate.

Le recadrage, lui, est irréversible. En dessous d'un score de confiance, le
module laisse la géométrie intacte et le signale (`enhanced only`). Mieux
vaut une image non redressée qu'une image amputée de son en-tête.

## 3. Sur la binarisation

Le sujet la demande, et c'était le bon choix à l'époque de Tesseract : l'OCR
classique travaille sur des images binaires. Les modèles VLM actuels
(PaddleOCR-VL, HunyuanOCR) sont entraînés sur des photographies naturelles et
font généralement **moins bien** sur une entrée binarisée, qui détruit
l'anticrénelage rendant les diacritiques vietnamiens lisibles.

Elle est donc implémentée mais désactivée par défaut (`--binarize`), pour que
le benchmark tranche plutôt qu'une hypothèse.

---

## 4. Ce que ça implique pour la suite

La localisation demande une **segmentation apprise**, pas des seuils.

Et tout est déjà là pour la faire. Le dépôt
`realistic_hospital_invoice_creation`, fourni par le laboratoire, existe
précisément pour ça : entraîner un modèle de suppression de fond à base de
DeepLabV3. Et les cartes UV de doc3D fournissent des **masques
d'entraînement au pixel près**, en quantité illimitée — image déformée plus
masque exact, c'est exactement une paire d'entraînement.

L'entraînement peut se faire sur Kaggle avec GPU gratuit, ce qui contourne la
contrainte des 4 Go de VRAM.

## Limites

17 images, un seul générateur de fonds. Sur de vraies photos, la séparation
papier/fond est souvent plus nette qu'ici — les fonds de doc3D sont des
images naturelles quelconques, parfois aussi claires que du papier. Le
chiffre de 0,51 vaut pour ce jeu, et il faudra le revérifier sur les photos
réelles.

Ce serait d'ailleurs un test intéressant en soi : si la détection classique
marche sur de vraies photos et échoue sur les rendus doc3D, ça dirait que la
simulation est plus difficile que la réalité sur cet aspect précis.

---

## 5. Le verdict OCR (28 juillet)

Le module est maintenant jugé sur ce qui compte : le TEDS obtenu par
HunyuanOCR sur les images prétraitées, contre les images brutes.

| facture | brut | prétraité | Δ |
|---|---|---|---|
| invoice_1 | 0,902 | 0,936 | +0,034 |
| invoice_2 | 0,945 | 0,956 | +0,011 |
| invoice_3 | 0,971 | 0,963 | −0,008 |
| invoice_4 | 0,964 | 0,961 | −0,003 |
| **invoice_5** | **0,968** | **0,478** | **−0,490** |
| invoice_6 | 0,947 | 0,898 | −0,049 |
| invoice_7 | 0,972 | 0,958 | −0,014 |
| invoice_8 | 0,930 | 0,884 | −0,046 |
| **moyenne** | **0,950** | **0,879** | −0,071 |

La moyenne dit « le prétraitement fait perdre 7 points ». Le détail dit autre
chose : **sur 7 factures sur 8 c'est un match nul** (0,947 contre 0,937), et
la totalité de l'écart vient d'une seule page.

### La page 10, et pourquoi elle est instructive

Le recadrage y est excellent — la feuille est isolée, redressée, l'ombre
supprimée, l'image visiblement meilleure que l'originale. Et pourtant
HunyuanOCR y a produit une liste de texte sans structure, colonnes de prix
perdues, alors qu'il rendait un tableau complet sur la version brute et
déformée.

Ce n'est donc pas la qualité de l'image qui régresse, c'est le **format de
sortie du modèle qui bascule**. C'est le même phénomène que le tableau rendu
en Markdown : sur une entrée légèrement différente, HunyuanOCR change de mode
de réponse sans prévenir. La génération étant gloutonne (`do_sample=False`),
ce n'est pas de l'aléa — c'est une sensibilité réelle à l'entrée, et donc une
fragilité du modèle, pas du prétraitement.

### Ce qu'on peut et ne peut pas conclure

On ne peut pas conclure que le prétraitement dégrade l'OCR : l'écart repose
sur un seul événement, et cet événement s'explique par une bascule de format
du modèle sur une image objectivement meilleure.

On peut conclure qu'il ne l'améliore pas non plus, sur ce jeu. C'est
cohérent : les rendus doc3D sont déjà nets et bien éclairés. Le prétraitement
est fait pour des photos réelles — flou de bougé, ombres portées, angles
marqués — que nous n'avons pas encore.

**Le test décisif est PaddleOCR-VL sur le même jeu prétraité.** Si un second
modèle ne perd rien sur la page 10, la fragilité de HunyuanOCR est établie et
le prétraitement est disculpé.

---

## 6. Ce que l'évaluation des champs a révélé (28 juillet)

Deux résultats opposés, tirés du même run prétraité.

### Le prétraitement récupère de l'information entièrement perdue

Sur la page 1, la sortie OCR de l'image **brute** ne contient pas le bloc
client / date / médecin. Pas mal lu : absent. Sur l'image **prétraitée** :

```
Ngày xuất hoa đơn: 05/07/2011
Họ tên: Bui Hai Sư Tử
Bác sỹ kèm: ThS.BS. Ngô Fong Hà Mã
```

C'est la réponse à la question laissée ouverte dans `etat_du_projet.md` :
« les champs patient et date disparaissent sur certaines pages… reste la
déformation ». **C'était bien la déformation.** Le prétraitement ne fait pas
qu'améliorer un score, il récupère des champs que le sujet nomme
explicitement.

### Mais il détruisait les diacritiques

| | hôpital | client | date | médecin |
|---|---|---|---|---|
| brut | 8/8 (**5 exacts**) | 5/8 (**3**) | 6/8 (2) | 6/8 (**3**) |
| prétraité v1 | 7/8 (**2 exacts**) | 5/8 (**1**) | 5/8 (2) | 5/8 (2) |

Le taux de récupération tient, mais les correspondances exactes s'effondrent,
13 → 7. `NHÀ THUỐC BỆNH VIỆN BẠCH DƯƠNG` revenait en `NHA THUOC BENIEVIEN
BACH DUONG`. C'est la colonne « exact » qui isole ce dégât — sans elle, la
métrique tolérante l'aurait masqué.

Deux causes identifiées dans `correct_illumination` et corrigées :

1. `cv2.divide(gray, background, scale=255)` ramène le papier au blanc pur et
   **écrête au blanc tout ce qui se trouve juste en dessous**. Un diacritique
   est exactement cela : une marque fine, peu contrastée, à quelques niveaux
   sous le papier. La cible est désormais 242, ce qui laisse 13 niveaux de
   marge.
2. La fonction renvoyait `GRAY2BGR` : elle **détruisait la couleur** sans que
   ce soit dit nulle part. Le gain est maintenant calculé sur la luminance et
   appliqué aux trois canaux.

S'y ajoute un **plancher de résolution** (`--min-long-side`, 1600 par défaut).
Le recadrage sur la feuille coûtait 40 à 70 % des pixels : les sorties
faisaient 384×431 à 718×888. À cette échelle un diacritique fait un ou deux
pixels. Le suréchantillonnage n'ajoute pas d'information, mais il donne au
modèle assez de pixels pour résoudre la marque — la même raison pour laquelle
l'OCR se fait à 300 dpi et non à 150.

Images régénérées dans `multipage_test_preprocessed_v2`. **Non encore
validées par un benchmark** : ce sont des hypothèses motivées par un dégât
mesuré, pas un résultat.

---

## 7. Les pages 8 et 12 : le recadrage collé au tableau (28 juillet)

Le rapport de debug signalait deux pages recadrées à moins de 25 % des pixels
source. Inspection : le quadrilatère épouse **le cadre du tableau**, et tout
l'en-tête — hôpital, patient, date, médecin — tombe hors du recadrage. C'est
le piège du §1, revenu par une autre porte.

### Ce qui ne marchait pas

Trois pistes essayées et **écartées sur mesure**, chacune contre les masques
UV exacts :

| piste | IoU moyen |
|---|---|
| référence | 0,79 |
| veto par le masque de texte | 0,78 |
| choix du candidat le plus grand contenant l'autre | 0,67 |
| choix par `_document_score` entre plusieurs flous | 0,79 |

Le veto par le texte se déclenche à tort sur les pages 2, 4 et 11, où la
détection était **bonne** — le masque morphologique compte le grain du fond
comme du texte, exactement le défaut déjà mesuré. Et `_document_score` ne
peut pas trancher : sur la page 8, le bon candidat marque 0,704 et le mauvais
0,708. Un tableau *est* un quadrilatère propre au format plausible.

### Deux causes réelles

**GrabCut n'était pas déterministe.** Cinq appels identiques sur la même
image donnaient des aires de 0,504, 0,413, 0,021, 0,021, 0,021. OpenCV
initialise ses modèles de couleur par un k-means à graine aléatoire, jamais
fixée. Le module n'était donc pas reproductible, et une partie des écarts
mesurés jusqu'ici était du bruit. Corrigé par `cv2.setRNGSeed`.

**GrabCut séparait l'encre du reste, pas le papier du fond.** Sur une page
portant beaucoup de papier blanc, ses deux classes de couleur convergent vers
« encre » et « non-encre » ; le contour rendu est alors le tableau. Le module
prétendait déjà éviter ça — son docstring dit vouloir « blurring away the
printed text » — mais il se contentait de réduire à 480 px, ce qui n'efface
pas le texte.

### Le correctif

Un second avis avec l'encre effacée (médiane 15), et une règle qui énonce
quelque chose de **vérifiable** plutôt que de réglé : effacer l'encre ne peut
pas déplacer le bord de la feuille, donc les deux lectures doivent
concorder. Si la seconde est nettement **plus grande**, la première était
imbriquée dans l'imprimé.

| | rapport d'aire |
|---|---|
| pages où la détection était déjà juste | ×1,00 à ×1,76 |
| page 12 (collée au tableau) | ×2,40 |
| page 8 (collée au tableau) | ×4,51 |

Le seuil est à ×2,0, dans le trou. Le second passage tourne à **1 itération**
(la question posée est grossière) et n'est réessayé que s'il s'effondre — un
contour plausible est un verdict, même quand il dit « rien à corriger ».

### Résultat

| | avant | après |
|---|---|---|
| IoU moyen (17 pages, masques UV) | 0,79 | **0,90** |
| page 8 | 0,24 | **0,81** |
| page 12 | 0,38 | **0,92** |
| recadrages exploitables (IoU ≥ 0,7) | 15/17 | **17/17** |

Aucune page dégradée. Reste à mesurer ce que l'OCR en fait.

---

## 8. Le verdict OCR de la v2 : le prétraitement paie (28 juillet)

| HunyuanOCR | TEDS | TEDS-Struct | Écart |
|---|---|---|---|
| images brutes | 0,950 | 0,973 | 0,023 |
| prétraitées v1 | 0,879 | 0,914 | 0,035 |
| **prétraitées v2** | **0,973** | **0,985** | **0,012** |

Le prétraitement passe de nuisible à bénéfique : **+0,023 de TEDS** sur les
images brutes, et l'écart structure/contenu tombe à 0,012, le plus faible
jamais mesuré. Les huit factures dépassent 0,95 après fusion, contre cinq
auparavant. La facture 5, celle qui s'effondrait en v1 à 0,478, atteint 0,973.

Ce qui a changé entre v1 et v2 tient en trois points, tous mesurés :
localisation corrigée (IoU 0,79 → 0,90), écrêtage au blanc supprimé, couleur
conservée.

### Les champs d'en-tête

| | hôpital | client | date | médecin | global |
|---|---|---|---|---|---|
| brut | 8/8 (5 exacts) | 5/8 (3) | 6/8 (2) | 6/8 (3) | 78 % |
| prétraité v1 | 7/8 (2) | 5/8 (1) | 5/8 (2) | 5/8 (2) | 69 % |
| prétraité v2 | 7/8 (**4**) | 5/8 (0) | 6/8 (2) | 6/8 (**5**) | 75 % |

Trois points de moins que le brut, mais la lecture par colonne est plus
instructive : le champ médecin passe de 3 à **5 correspondances exactes**, le
meilleur des trois runs, et le total d'exactes remonte de 7 (v1) à 11.

Deux défauts restent visibles dans les valeurs extraites :

- `NHÀ THUỐC…` devient `HÀ THUỐC…` sur la facture 1 — **le recadrage rogne le
  N initial**. C'est la page au recadrage le plus serré (24 % des pixels
  source). La marge de 8 % y est insuffisante.
- Les diacritiques cèdent sur la **dernière syllabe** : `Sư Tử` → `Sư Từ`,
  `SONG NGƯ` → `SONG NGU`, `Phượng` → `Phương`. D'où 0 exact sur le nom du
  client alors que 5 sur 8 sont récupérés.

### Un faux positif corrigé au passage

Sur deux factures, le champ médecin contenait
`điều trị và phải trong thời hạn 5` — une phrase du **pied de page légal**
(« …selon la prescription du médecin traitant, dans un délai de 5 jours »),
dans laquelle `bác sĩ` apparaît comme mot courant. Quand la vraie ligne du
médecin manque dans la sortie OCR, la recherche d'étiquette tombait dessus.

Une valeur fausse mais plausible est pire qu'une valeur absente : rien en aval
ne peut la rattraper, alors qu'un champ vide se voit. Le filtre retenu
s'appuie sur une règle de la langue — **le vietnamien capitalise chaque
syllabe d'un nom propre**, la prose non. Exiger le deux-points de l'étiquette
marchait aussi, mais coûtait un vrai champ à PP-StructureV3, qui omet la
ponctuation.

---

## 9. Confirmation inter-modeles, et la marge de recadrage (30 juillet)

PaddleOCR-VL passe sur le meme jeu pretraite, sur GPU Kaggle (35 s/page
contre 230 s sur le CPU local).

| TEDS | images brutes | pretraitees v2 | gain |
|---|---|---|---|
| HunyuanOCR-1.5 | 0,950 | **0,973** | +0,023 |
| PaddleOCR-VL | 0,909 | **0,949** | +0,040 |

**Le pretraitement aide les deux modeles.** L'affirmation change de nature :
ce n'est plus « il arrange HunyuanOCR », c'est « il ameliore l'extraction de
tableau ». Fusion inchangee : 100 % de precision et de rappel, zero fusion a
tort.

### Mais il coute des champs d'en-tete

| champs | brut | pretraite v2 |
|---|---|---|
| HunyuanOCR | 78 % | 75 % |
| PaddleOCR-VL | 69 % | **41 %** |

Chute brutale chez PaddleOCR : l'hopital tombe de 6/8 a 2/8. Verification
faite, le nom est **totalement absent** de la sortie sur les pages
concernees, pas meme dans un tableau. Or HunyuanOCR, sur la meme image,
lisait `HA THUOC BENH VIEN BACH DUONG` -- avec le N initial en moins.

Meme cause, deux symptomes : le recadrage coupe le bord de la feuille,
HunyuanOCR lit la ligne abimee, PaddleOCR l'ecarte entierement. Un modele a
l'analyse de mise en page plus stricte est plus fragile a un texte tronque
qu'a un texte deforme.

### Choisir la marge : l'IoU est le mauvais critere

Elargir la marge fait entrer du fond, donc **baisse** l'IoU -- alors que
c'est exactement ce qu'on veut faire. Le critere utile est le **rappel de la
feuille**, la part des pixels de papier restant dans le recadrage.

| marge | pages ou le rappel >= 0,98 | IoU moyen |
|---|---|---|
| 8 % | 11/17 | 0,86 |
| 12 % | 14/17 | 0,82 |
| **16 %** | **16/17** | 0,77 |
| 20 % | 16/17 | 0,73 |

A 8 %, le recadrage amputait plus de 2 % de la feuille sur **6 pages sur
17**. La marge par defaut passe a 16 %.

Le compromis se lit dans l'asymetrie des couts, pas dans les chiffres bruts :
inclure du fond n'a aucun cout mesure, tandis qu'une feuille coupee fait
perdre un champ entier. Une metrique symetrique comme l'IoU ne peut pas
exprimer ca -- c'est pourquoi elle ne devait pas arbitrer seule.

A revalider par un benchmark : ces 16 % sont motives par une mesure
geometrique, pas encore par un score OCR.

