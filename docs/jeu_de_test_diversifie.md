# Jeu de test diversifié

Le jeu multi-pages compte 8 factures issues d'**un seul gabarit**, où la
colonne STT redémarre à 1 à chaque facture. C'est exactement l'hypothèse
métier sur laquelle repose le signal le plus discriminant de la fusion : un
jeu qui la respecte partout ne peut pas la mettre en défaut.

```powershell
python gen_variants_json.py          # dans synthetic_invoice_generator\hospital_pharmacy
python create_latex_variants.py
```

---

## 1. Ce que le nouveau jeu fait varier

12 factures, 25 pages. Chaque facture porte un bloc `layout` que le gabarit
LaTeX lit ; la vérité terrain garde la même forme, donc **toutes les
évaluations existantes fonctionnent sans modification**.

| axe | valeurs | ce que ça attaque |
|---|---|---|
| `stt_mode` | `restart` / **`global`** | la numérotation continue d'une facture à l'autre |
| `continuation` | oui / non | sans marqueur, seule la numérotation peut trancher |
| `columns` | 5 / 6 / 7 | la détection d'en-tête suppose-t-elle un nombre fixe |
| `borders` | grid / horizontal / none | la détection de tableau s'appuie sur les filets |
| `total_row` | oui / non | sans elle, la clôture d'une facture n'est plus signalée |

Cinq factures sont en mode `global`, avec des départs de STT à 41, 70, 107 et
135.

---

## 2. Le défaut trouvé, et il est sérieux

`tests/test_merge_assumptions.py` construit des paires de tableaux **à la
main, sans OCR** : un échec y est un défaut d'algorithme, pas de modèle.

Le cas décisif : la facture A se termine au STT 40 avec sa ligne `Tổng tiền`,
la facture B — un autre document — commence au STT 41. L'algorithme les
**fusionnait**.

```python
strong_signal = (
    signals["table_b_has_continuation_marker"]
    or signals["index_continuity"]        # <- suffisait à lui seul
    ...
```

`table_a_ends_with_total` était bien calculé et bien vrai : le code *savait*
que la facture était close. Mais il n'était qu'un terme parmi d'autres, et
`index_continuity` passait outre.

C'est l'erreur que ce projet qualifie ailleurs de « bien plus grave » :
coller deux factures distinctes fabrique un tableau mêlant deux documents,
et **rien en aval ne peut le détecter** — la validation arithmétique
elle-même reste satisfaite, puisque chaque ligne boucle.

### Le correctif

Deux vetos, qui disent la même chose : le document affirme que le tableau
précédent est terminé.

```python
closed_by_document = (signals["table_b_restarts_at_1"]
                      or signals["table_a_ends_with_total"])
disqualified = closed_by_document and not signals["table_b_has_continuation_marker"]
```

Un marqueur de continuation sur B lève les deux, parce que c'est alors le
document qui affirme la continuation, au lieu de nous qui l'inférons.

**Zéro régression** : les cinq runs existants gardent 100 % de précision, et
PaddleOCR brut ses 93 % de F1.

---

## 3. Un défaut de la vérité terrain, aussi

`page_groups_from_pdf` regroupait les pages en repérant l'**absence** du
marqueur `Tiếp trang trước`. Or cinq factures du nouveau jeu n'en ont pas :
le regroupement de référence les aurait silencieusement collées.

Plus gênant sur le principe : la vérité terrain partageait alors un mode de
défaillance avec ce qu'elle mesure. **Elle notait l'algorithme de fusion en
utilisant l'un des signaux dont cet algorithme dépend.**

Le repère est désormais le bloc d'en-tête, que LaTeX imprime une fois par
facture et jamais sur une page de suite. Vérifié : il reproduit exactement le
même groupement sur le jeu d'origine.

---

## 4. Ce qui reste à faire

Les 25 pages sont rendues à plat dans `doc3D-renderer/img/variants_flat`
(1800×1269), prêtes pour un run OCR. Il manque :

- le passage par Blender pour obtenir les versions déformées, comparables au
  jeu actuel ;
- le run OCR proprement dit, et la mesure de la fusion sur ces mises en page.

Le chiffre à surveiller est la **précision** de la fusion, pas le rappel :
c'est elle que le mode `global` attaque.

---

## 5. Mode d'emploi

Toute la suite d'évaluation accepte désormais `--pdf` et `--gt-dir`, donc le
nouveau jeu se mesure sans rien modifier.

```powershell
$PDF = "..\synthetic_invoice_generator\hospital_pharmacy\invoices_variants.pdf"
$GT  = "..\synthetic_invoice_generator\hospital_pharmacy\ground_truth_labels_variants"

# 1. OCR (sur Kaggle : kaggle\images_variants_flat.zip, 25 pages, 4,5 Mo)
python scripts\bench_deformed.py --model paddleocr-vl `
    --images-dir "..\doc3D-renderer\img\variants_flat" --output variants_paddleocr

# 2. Le chiffre qui compte : la PRECISION de la fusion
python src\eval_multipage_merge.py --run variants_paddleocr --pdf $PDF

# 3. Le reste
python src\eval_teds.py       --run variants_paddleocr --pdf $PDF --gt-dir $GT
python src\eval_fields.py     --runs variants_paddleocr --pdf $PDF --gt-dir $GT
python src\eval_validation.py --run variants_paddleocr --pdf $PDF --gt-dir $GT
```

Les pages sont rendues à plat : c'est volontaire pour ce premier passage. On
mesure ainsi l'effet des **mises en page** seules, sans le mélanger à celui de
la déformation. Le passage par Blender vient ensuite, sur le même contenu, ce
qui permet d'attribuer chaque écart à sa cause.

## 6. Ce que le test unitaire garantit déjà

`tests/test_merge_assumptions.py` couvre sept cas construits à la main. Il
tourne en une seconde, sans OCR ni modèle, et se lance depuis le dépôt :

```powershell
python tests\test_merge_assumptions.py
```

Un échec y désigne un défaut de logique. Le benchmark OCR, lui, mêle logique
et qualité de lecture : les deux niveaux sont complémentaires et il faut
garder les deux.

---

## 7. Résultats (3 août)

PaddleOCR-VL sur les 25 pages à plat, 28 s par page sur T4.

### La fusion tient

| | précision | rappel |
|---|---|---|
| jeu d'origine (8 factures, 1 gabarit) | 100 % | 100 % |
| **jeu diversifié (12 factures, 6 gabarits)** | **100 %** | **100 %** |

La ligne qui compte, dans le détail des décisions :

```
page 18 -> 19  predicted=no  expected=no  OK  [lastA=106 firstB=107 total_A=True]
```

STT 106 puis 107, parfaitement continu d'une facture à l'autre. Sans le veto
de clôture, c'était une fusion à tort — l'erreur que rien en aval ne détecte.

### Le jeu a d'abord cassé la mesure

Avant de mesurer quoi que ce soit, le nouveau jeu a mis au jour **trois
défauts dans le dispositif d'évaluation lui-même**, tous invisibles tant que
le gabarit restait unique.

| où | ce qui était supposé | conséquence |
|---|---|---|
| `page_groups_from_pdf` | toute page de suite porte un marqueur | 5 factures collées à la précédente |
| `ground_truth_continuations` | idem | précision annoncée à **58 %** au lieu de 100 % |
| `ground_truth_rows` | 6 colonnes, numérotation depuis 1 | 5 et 7 colonnes comparées à une référence à 6 ; numérotation continue comptée fausse cellule par cellule |

Le troisième était le plus coûteux, et le plus trompeur :

| facture | avant correction | après |
|---|---|---|
| 5 colonnes | 0,836 | **0,974** |
| 7 colonnes | 0,857 | **0,976** |
| numérotation continue | 0,896 | **0,994** |

On aurait conclu à une faiblesse du modèle sur les mises en page inhabituelles.
C'était la **référence** qui décrivait un document jamais imprimé.

Les deux premiers défauts partageaient une même faute de principe : la vérité
terrain s'appuyait sur le marqueur de continuation, c'est-à-dire sur **l'un
des signaux que l'algorithme mesuré utilise**. Un gabarit sans marqueur
cassait alors la mesure et l'objet mesuré en même temps, sans moyen de
distinguer les deux.

### TEDS

| | TEDS | TEDS-Struct | écart |
|---|---|---|---|
| 12 factures, 6 gabarits | **0,976** | **0,986** | **0,009** |

Les douze sont entre 0,962 et 0,997, et **aucun axe de mise en page ne se
détache** une fois la référence corrigée : ni le nombre de colonnes, ni les
filets, ni la numérotation continue. L'écart structure/contenu de 0,009 est
le plus faible jamais mesuré sur ce projet.

Une réserve à formuler explicitement : ces pages sont **à plat**, celles du
jeu d'origine sont déformées. Les 0,976 ne se comparent donc pas aux 0,909 de
PaddleOCR sur le jeu d'origine — la différence mêle mise en page et
déformation. Les comparaisons valables sont celles **internes** au jeu
diversifié, d'un gabarit à l'autre.

Le gain apporté par la fusion y est en revanche plus élevé qu'ailleurs :
**+0,340** contre +0,281 sur le jeu d'origine. C'est mécanique : cinq
factures n'ont pas de marqueur de continuation, donc la colonne « sans
fusion » — qui ne voit que la première page — y tombe à 0,43. Ça chiffre ce
que la fusion récupère quand le document ne signale rien.

Non-régression vérifiée sur le jeu d'origine : HunyuanOCR reste à 0,950.

---

## 8. Ce que ce jeu a coûté et rapporté

Une demi-journée. En retour, un défaut d'algorithme qui fabriquait
silencieusement des tableaux mêlant deux factures, et trois défauts de mesure
dont un faussait les scores de 12 points.

Le motif mérite d'être retenu pour le rapport : **un jeu de test issu d'un
seul gabarit ne valide pas seulement un algorithme trop peu, il valide aussi
son propre instrument de mesure trop peu.** Les deux se calibrent l'un sur
l'autre, et l'accord qui en résulte ne prouve rien.

---

## 9. Version déformée

Les 25 pages plates sont projetées sur des maillages courbés, avec fond et
éclairage réalistes — même traitement que le jeu d'origine, sur un contenu
différent.

```powershell
cd ..\doc3D-renderer
.\render_variants.ps1
```

Le script liste les textures, appelle Blender, et vérifie que le compte des
images rendues correspond au compte des pages.

Deux modifications ont été nécessaires, toutes deux rétrocompatibles :

- `generate_multipage_tex_csv.py` accepte `--source` et `--out`, au lieu de
  cibler `tex/multipage` en dur.
- `render_mesh_multipage.py` accepte un quatrième argument optionnel, le CSV
  des textures. Les arguments sont désormais lus après le `--` de Blender
  plutôt que par index négatif depuis la fin, ce qui rendait tout ajout
  impossible. Sans ce quatrième argument, le comportement est inchangé.

Le nom du fichier produit est `<page>-<maillage>.png`, donc **le numéro de
page survit au rendu** — et tout le regroupement en factures en dépend.

### Ce que la comparaison permet

Le même contenu existe maintenant en deux versions, plate et déformée. Un
écart entre les deux s'impute alors à la déformation seule, puisque la mise
en page est identique. Mesurer directement la version déformée aurait
mélangé les deux effets sans moyen de les séparer — c'est la raison d'être
de ce détour.

Les cartes UV produites par le rendu donnent en prime des **masques de
feuille exacts** sur ces 25 pages, donc de quoi évaluer le module de
prétraitement sur un second jeu.

---

## 10. Le coût de la déformation, isolé (3 août)

Même contenu, même mise en page, seule la déformation change. C'est le seul
endroit du projet où son coût s'observe sans être mêlé à autre chose.

| facture | à plat | déformé | Δ |
|---|---|---|---|
| 1 | 0,966 | 0,828 | −0,138 |
| 2 | 0,974 | 0,946 | −0,028 |
| 3 | 0,994 | 0,986 | −0,008 |
| 4 | 0,962 | 0,940 | −0,022 |
| 5 | 0,974 | 0,966 | −0,008 |
| 6 | 0,976 | 0,972 | −0,004 |
| 7 | 0,978 | 0,865 | −0,113 |
| 8 | 0,985 | 0,857 | −0,128 |
| 9 | 0,971 | 0,905 | −0,066 |
| 10 | 0,997 | 0,809 | −0,188 |
| 11 | 0,977 | 0,838 | −0,139 |
| 12 | 0,964 | 0,960 | −0,004 |
| **moyenne** | **0,976** | **0,906** | **−0,070** |

Sur les douze, la déformation coûte **−0,070 de TEDS** (0,976 → 0,906) et
seulement **−0,020 en structure** (0,986 → 0,966). L'écart entre les deux
est le chiffre parlant : la déformation abîme surtout la **lecture des
caractères**, pas la reconstruction de la grille.

Mais la moyenne cache l'essentiel : sept factures perdent moins de 0,03,
trois en perdent plus de 0,11. **L'effet n'est pas graduel, il est binaire** — soit la
page passe, soit elle décroche. C'est cohérent avec ce qu'on observait déjà
sur le prétraitement : les modèles encaissent une déformation modérée sans
broncher et lâchent d'un coup au-delà.

Et c'est un argument mesuré en faveur du prétraitement : il ne sert pas à
grappiller quelques millièmes sur les pages faciles, il sert à ramener les
pages décrochées dans le régime où le modèle fonctionne.

## 11. Un troisième défaut d'algorithme, trouvé par la version déformée

La version à plat donnait 100 % de précision. La version déformée est tombée
à 92 %, sur une fusion à tort :

```
page 15 -> 17  predicted=yes expected=no  [lastA=21 firstB=70 total_A=False]
```

L'OCR avait **entièrement perdu la page 16** — aucun tableau détecté — si
bien que l'algorithme comparait la page 15 à la page 17, deux factures
différentes. Le signal `table_b_starts_mid_numbering` s'est déclenché parce
que 70 > 1, sans aucune condition de proximité.

### Le mauvais correctif, puis le bon

Premier réflexe : exiger un écart faible entre le dernier indice de A et le
premier de B. **Ça casse trois continuations légitimes**, dont deux sur
PP-StructureV3 dont le rappel tombait de 100 % à 71 % — précisément les cas
où l'OCR a massacré la fin de A, c'est-à-dire ceux que ce signal existe pour
rattraper.

Le bon repère n'est pas le dernier indice **lu** dans A, mais celui que sa
**taille** prédit : `premier_indice_A + nombre_de_lignes_A`. Le nombre de
lignes survit là où les numéros ne survivent pas.

| cas | écart brut | écart attendu | vérité |
|---|---|---|---|
| A lue jusqu'à 7, B démarre à 17 | +10 | **−1** | continuation |
| A lue jusqu'à 12, B démarre à 20 | +8 | **−1** | continuation |
| A lue jusqu'à 19, B démarre à 18 | −1 | **−3** | continuation |
| A lue jusqu'à 21, B démarre à 70 | +49 | **+48** | factures distinctes |

L'écart brut mélange les quatre ; l'écart attendu les sépare nettement. Seuil
à 5.

### Résultat

| run | précision | rappel |
|---|---|---|
| HunyuanOCR (origine) | 100 % | 100 % |
| HunyuanOCR prétraité | 100 % | 100 % |
| PaddleOCR-VL prétraité | 100 % | 100 % |
| PP-StructureV3 | 100 % | 100 % |
| variantes à plat | 100 % | 100 % |
| **variantes déformées** | **100 %** | **100 %** |

PaddleOCR-VL sur images brutes reste à 88 % de rappel, inchangé et sans
rapport avec ce correctif.

---

## 12. Bilan du jeu diversifié

Une journée. En retour :

- **deux défauts d'algorithme** qui fabriquaient silencieusement des tableaux
  mêlant deux factures, dont un que seule la version déformée pouvait révéler ;
- **trois défauts de mesure**, dont un faussait les scores de 12 points ;
- un jeu à quatre branches : 8 factures d'un gabarit contre 12 de six
  gabarits, à plat et déformées, toutes à vérité terrain exacte.

Le motif à retenir pour le rapport : **chaque élargissement du jeu de test a
d'abord cassé l'instrument de mesure avant de mesurer quoi que ce soit.** Un
banc d'essai construit sur un seul gabarit ne valide pas seulement
l'algorithme trop peu — il valide aussi trop peu sa propre référence, et
l'accord entre les deux ne prouve rien.

---

## 13. Prétraiter dans le notebook plutôt que téléverser (3 août)

Le run déformé ci-dessus est **sans prétraitement**, il n'est donc pas
comparable aux 0,951 de PaddleOCR prétraité sur le jeu d'origine.

Plutôt que de prétraiter en local et de téléverser un second dataset, le
notebook le fait maintenant lui-même : il clone déjà le dépôt, donc
`src/preprocess.py` y est disponible. Deux raisons, et la première est la
plus importante.

**Le code de prétraitement est toujours celui du dépôt.** Des images
prétraitées téléversées se périment à la première modification du module,
sans que rien ne le signale — on mesurerait alors une version du
prétraitement qui n'existe plus. Ce piège a déjà failli se refermer entre les
versions v2 et v3 des images.

**Les deux lectures sortent de la même session.** C'est ce dont
`src/adaptive.py` a besoin : la politique choisit entre lecture brute et
lecture prétraitée, donc il lui faut les deux, sur les mêmes images.

```python
PASSES = ["raw", "preprocessed"]   # ou ["raw"] pour n'en faire qu'une
PREFIXE = "variants_warped"
```

Le notebook produit alors deux runs et deux archives, nommés
`<prefixe>_<passe>_<modèle>`. Un seul dataset d'images brutes suffit
désormais, quel que soit le nombre de variantes de prétraitement à comparer.

