# Audit de la chaîne de production — défaillances silencieuses

Revue ciblée des seuls modules qui tourneront en production, le 5 août 2026.
Les scripts d'évaluation, les bancs de test et les démos sont hors périmètre :
un bug qui ne s'exécute pas chez l'utilisateur n'est pas le même risque.

**Périmètre.** `preprocess.py` → `table_merge.py` → `invoice_parse.py` →
`invoice_validate.py` → `invoice_fields.py` → `adaptive.py` →
`invoice_export.py`, plus `api.py` qui les orchestre.

**Ce qu'on cherche.** Pas les plantages — ils se voient. Les cas où le code
produit un résultat **plausible et faux**, sans lever la moindre erreur.

---

## Ce qui a été trouvé et corrigé

### 1. Perdre un signal faisait MONTER la note de confiance

**Le plus grave, parce qu'il inversait une décision.**

`adaptive.confidence()` accorde 0,15 point pour « aucun trou dans la
numérotation ». Or `check_invoice` calculait les trous sur les STT
effectivement lus : quand la colonne STT n'était pas reconnue, la liste des
trous était vide — et le bonus tombait quand même.

Mesuré sur un tableau construit à la main, avec un trou de numérotation
**réel** :

| | confiance |
|---|---|
| STT lisible, le trou est vu | 0,600 |
| **même tableau**, en-tête STT illisible | **0,750** |

Abîmer la lecture rapportait 0,15. Et le biais n'était pas neutre : il
favorisait systématiquement la variante **prétraitée**, dont le défaut connu
est précisément d'abîmer les en-têtes. La politique adaptative choisissait
donc parfois une lecture parce qu'elle était trop dégradée pour être
contrôlée.

**Correctif.** `check_invoice` publie `index_available` (au moins deux STT
lisibles — avec un seul, aucune paire consécutive n'existe, donc aucune
preuve de continuité). `confidence` n'accorde le point que si le contrôle a
pu tourner.

Choix explicite : on ne **renormalise pas** les poids sur les signaux
disponibles. Ce serait récompenser la perte d'information encore plus fort.
Absence de preuve ne vaut ni preuve ni faute — elle ne rapporte rien et ne
coûte rien.

Après correctif, les quatre cas se classent comme ils doivent :

| | avant | après |
|---|---|---|
| complète, tout juste | 1,000 | 1,000 |
| tronquée à 1 ligne | 0,750 | 0,600 |
| trou visible, total faux | 0,600 | 0,600 |
| même table, STT illisible | **0,750** | **0,600** |

**Aucune régression** : les chiffres publiés sont inchangés (0,966 sur le
multi-pages, 0,977 = plafond sur le diversifié déformé).

### 2. `STT` lu `S/T` faisait disparaître toute la numérotation

`STT` est le libellé le plus **court** du tableau : perdre une lettre sur
trois fait chuter la similarité floue sous le seuil, là où la même perte sur
`Thành tiền` ne se voit pas. Chandra lit `S/T` — les 33 lignes de la facture 5
sortaient avec `index: null`, et avec elles la détection des lignes sautées.

**Correctif.** `s/t` et `st` ajoutés aux variantes, après vérification qu'ils
ne collisionnent avec aucun des cinq autres libellés de l'en-tête.

À l'honneur du code existant : `extraction.status` signalait déjà `partial`
avec `columns not found: index`. Le garde-fou fonctionnait ; c'est le champ
`review` qui, lui, mentait.

### 3. Le JSON livré ne distinguait pas « vérifié » de « invérifiable »

`numbering_gaps: []` sortait aussi bien pour une numérotation parfaite que
pour une numérotation illisible. Le consommateur du livrable final ne pouvait
pas faire la différence, et croyait vérifié ce qui n'avait pas pu l'être.

**Correctif.** Ajout de `numbering_checked` à côté de `numbering_gaps`.

### 4. `lines_to_check` pouvait ne désigner aucune ligne

Les lignes à relire étaient identifiées par leur STT. Sans STT lisible, le
champ sortait `[null, null, …]` : le JSON annonçait 31 lignes à relire **sans
dire lesquelles**. C'est le champ le plus utile du livrable, et il devenait
inexploitable exactement dans le cas où l'on en a le plus besoin.

**Correctif.** Chaque entrée porte désormais `position` (l'indice dans
`items`, qui existe toujours), `stt`, `status` et `detail`.

### 5. Les tableaux Markdown n'étaient pas exclus du texte libre

`extract_fields` retirait `<table>…</table>` avant de chercher les champs
d'en-tête — reste de l'époque où l'on croyait que tous les modèles rendaient
du HTML. `table_merge` a depuis appris à lire les tableaux en pipes ; ce
filtre-ci ne l'a jamais su.

Conséquence : une cellule contenant `Họ tên:` — un nom de médicament mal lu,
une ligne décalée — pouvait être servie comme nom de patient. Vérifié : sur un
tableau en pipes seul, `hospital_name` sortait égal à la **ligne d'en-tête du
tableau**.

**Correctif.** Les lignes entièrement délimitées par des barres sont retirées
elles aussi. Une phrase contenant un `|` isolé n'est pas touchée.

**Aucune régression** sur les scores de champs des sept runs mesurés.

---

### 6. Colonnes décalées d'un cran par un en-tête sur deux lignes

**Le plus grave des six, parce que les chiffres étaient JUSTES.**

Chandra rend un en-tête sur deux lignes avec `colspan`. La ligne d'en-tête
retenue décrit alors 5 colonnes pour des lignes de données qui en ont 6, et
tout le rapprochement par **position** glisse d'un cran :

```
en-tête   [STT, Tên…, Tên… (colspan=3), Đơn giá, Thành tiền]
données   [1,   Hydrocortisone 1%, tuýp, 1, 2900, 2900]
```

« Đơn giá » désignait donc la colonne des **quantités**, et « Thành tiền »
celle des prix unitaires. Résultat sur la facture 1 :

```json
{"name": "Hydrocortisone 1%", "quantity": 2900, "unit_price": 1, "total": 2900,
 "check": {"status": "corrected", "detail": "quantity inferred: 2900 / 1"}}
```

Et **la validation arithmétique confirmait** — 1 × 2900 = 2900 est vrai.
Vingt et une lignes sur trente-trois sont ainsi sorties marquées `corrected`,
avec des quantités de 75 000 boîtes de médicament. Aucune erreur levée : les
nombres étaient exacts, les colonnes fausses. C'est le pire profil de
défaillance qu'on ait rencontré, parce que le garde-fou lui-même validait.

**Correctif : `invoice_parse.repair_columns`.** Parmi les colonnes
numériques, on cherche le trio (quantité, prix, total) qui fait boucler le
plus de lignes. C'est la redondance arithmétique déjà utilisée ailleurs,
appliquée cette fois à *identifier* les colonnes plutôt qu'à détecter les
erreurs — et toujours **sans vérité terrain**. Sur un tableau normal
l'en-tête gagne et rien ne bouge : on n'écrase le rapprochement par en-tête
que si l'alternative est strictement meilleure et équilibre au moins la
moitié des lignes.

Trois pièges traités en chemin :

**La multiplication est commutative.** `(q, up, tot)` et `(up, q, tot)`
équilibrent identiquement : l'arithmétique ne peut pas distinguer « 6 boîtes
à 63 000 » de « 63 000 boîtes à 6 ». On départage sur les ordres de grandeur
— une pharmacie vend quelques unités à un prix qui se compte en milliers de
dongs. C'est une hypothèse métier explicite, au même titre que le
redémarrage du STT à 1, et elle est à revalider sur tout nouveau format.

**`name` et `index` aussi étaient perdus.** Sur la facture 2, les lignes
sortaient exactes (`1 × 45 000 = 45 000`) mais **sans nom de médicament**.
Une ligne juste dont on ignore de quoi elle parle n'est pas exploitable. On
les retrouve par le contenu : `name` = la colonne la plus alphabétique,
`index` = une colonne d'entiers petits et croissants.

**La seconde ligne d'en-tête devenait une ligne de données**, sans montant ni
numéro, et remontait dans `lines_to_check` comme « trop de valeurs
manquantes ». Une ligne faite de libellés d'en-tête est désormais écartée.

#### Ce que ça change, mesuré

Facture 1 de `multipage_preproc_chandra` :

| | avant | après |
|---|---|---|
| `extraction.status` | `partial` | **`ok`** |
| total déclaré / recalculé | 4 104 930 / **773 010** | 4 104 930 / **4 104 930** |
| lignes justes | 0 / 33 | **32 / 32** |
| « corrections » fantaisistes | 21 | **0** |
| lignes à relire | 12 | **0** |

Sur l'ensemble du run brut, les lignes réellement fausses passent de **99 à
55**. Les factures 2 et 4, qui sortaient à 0 ligne juste sur 22 et 27, sont
maintenant à 21/22 et 23/27.

Le rappel de la validation arithmétique passe de 80 % à 60 % sur ce run —
**et c'est attendu** : son dénominateur a fondu. Il reste 55 lignes fausses
au lieu de 99, et celles qui subsistent sont majoritairement des erreurs de
**nom**, invisibles à l'arithmétique par construction. La précision reste à
100 % : aucune ligne correcte n'est signalée à tort.

**TEDS strictement inchangé** (0,916 sur `multipage_chandra`, 0,950 sur
`multipage_hunyuan`) : la réparation agit après l'extraction du tableau, pas
dessus. C'est précisément pour ça que le problème avait échappé au
benchmark — TEDS note le tableau, pas le JSON.

### 7. Le nom du patient perdu au dernier mètre

Signalé par Halfaa en lisant le rapport : *« si il manque le nom du patient
à chaque fois ça pose problème »*. Le champ sortait à 6/8, et deux causes
différentes se cachaient derrière ce chiffre.

**Un libellé non reconnu.** Le générateur tire le libellé du patient au
hasard parmi **quatre** formes — `Họ tên`, `Họ tên người mua`, `Họ và tên
người mua`, `Người mua` — et celui du médecin parmi quatre autres. La liste
de reconnaissance n'en connaissait que trois : `Người mua` seul manquait,
comme `BS kê đơn` et `Tên bác sĩ` côté médecin.

Sur la facture 3, le nom était **parfaitement lu par l'OCR** —
`Người mua: Trần Giang Chấn` — mais aucun libellé ne correspondait, donc le
champ sortait `null`. Une donnée présente, perdue au dernier mètre.

**Un nom servi à la place d'un autre.** Sur la facture 1 du run prétraité,
l'en-tête du document est sur deux colonnes ; Chandra l'a lu en travers et a
perdu le libellé `Họ tên:`. Le nom du **patient** s'est retrouvé collé
derrière `Bác sĩ kê đơn:`, tandis que le vrai médecin restait seul sur sa
ligne :

```
Bác sĩ kê đơn: Bùi Hải Su Tử      <- le patient
Địa chỉ:
Ths.BS. Ngô Fong Hà Mã            <- le médecin, orphelin
```

Le JSON livrait donc le nom du patient **comme nom du médecin**. Sur une
facture médicale, confondre le patient et le prescripteur n'est pas une
coquille — et une valeur fausse est plus dangereuse qu'une valeur manquante,
puisque rien en aval ne peut la rattraper.

**Correctifs.** Les libellés manquants sont ajoutés, ordonnés du plus long au
plus court pour que `họ tên` n'attrape pas `họ tên người mua`. Et une règle :
si la valeur trouvée pour le médecin ne porte **aucun titre** alors que la
page contient une ligne isolée qui en porte un, c'est celle-là le médecin.
On ne devine rien — on prend la seule candidate que le document désigne
comme praticien, et s'il y en a plusieurs on ne tranche pas.

Le nom délogé n'est pas réaffecté au patient : deviner y serait moins sûr
qu'assumer le trou.

#### Effet, sur les cinq runs

| run | avant | après |
|---|---|---|
| `multipage_chandra` | 88 % | **91 %** |
| `multipage_preproc_chandra` | 84 % | **88 %** |
| `multipage_hunyuan` | 78 % | **84 %** |
| `multipage_paddleocr_vl` | 69 % | **72 %** |
| `multipage_ppstructure` | 28 % | **34 %** |

Tous les modèles y gagnent, ce qui est la signature d'un défaut côté chaîne
et non côté modèle.

Il reste deux pertes sur `customer_name`, et **aucune n'est imputable au
code** : sur la facture 3 le modèle a lu `Chấn` pour `Chồn`, sur la facture 5
il a purement et simplement sauté la ligne. La chaîne ne perd plus rien
qu'elle ait reçu.

#### Une leçon de méthode

`summary.json` compte les champs **trouvés**, `eval_fields` les champs
**justes**. Sur `doctor`, le résumé affichait 7/8 quand la vérité terrain en
donnait 6/8 : l'écart était exactement la valeur fausse. Un compteur de
couverture ne remplace pas un compteur d'exactitude, et les confondre aurait
laissé passer ce cas.

### 8. Le QR décodé après réduction, c'est-à-dire jamais

Signalé par Halfaa : *« les QR code et les signatures devraient s'afficher
dans le rapport »*. En creusant, un défaut de conception apparaît.

`api.py` ramène toute image au-dessus de `TAILLE_MAX_OCR` (1600 px) avant de
la donner au modèle — décision juste, le coût d'un VLM croît plus vite que
linéairement avec le nombre de patches. Mais **rien ne lisait le QR avant
cette réduction**, alors que c'est précisément là qu'il reste lisible.

#### Le chiffre qui tranche

Un décodeur QR a besoin d'environ **3 pixels par module** ; en dessous de 2,
aucune sur-résolution ne récupère l'information — elle n'est plus dans le
signal. Pour `https://example.com/`, un QR version 2 de 25×25 modules :

| taille du QR | px/module | verdict |
|---|---|---|
| 40 px | 1,6 | impossible |
| **67 px** (nos rendus à 900 px) | **2,7** | **à la limite** |
| 133 px (rendu à 1800 px) | 5,3 | confortable |
| ~285 px (photo de téléphone) | 11,4 | large |

Rendu **à plat depuis le PDF**, le QR à 67 px décode. Le même, passé par la
déformation 3D de Blender, ne décode plus. Il n'y avait aucune marge et le
gondolement l'a mangée. Réduire une photo de 4000 px à 1600 divise la taille
du QR par 2,5 : c'est jeter la marge qui fait toute la différence.

#### Correctifs

**`src/qrcode_lecture.py`** — nouveau module. Il ne rend jamais `None` :
l'absence de QR est une information, pas une erreur. Et il distingue trois
situations que confondre serait trompeur : *aucun QR sur ce document* (normal,
le gabarit n'en met que sur certaines factures), *QR repéré mais trop petit*
(→ rapprocher l'appareil), *QR repéré mais illisible* (→ flou, reflet, page
gondolée).

**`api.py`** lit le QR **à la réception**, sur l'image telle qu'elle arrive,
avant le prétraitement et avant la réduction. Le résultat voyage jusqu'au
JSON final via `travail.qr`.

**`scripts/rendre_haute_resolution.py`** produit le jeu à 1800 px et mesure
le plafond. Résultat : **5/5 QR décodés à 1800 px contre 4/5 à 900 px**, et
surtout deux fois plus de marge avant que la déformation ne détruise le
motif.

#### Ce que ça vaut au-delà du QR

Le QR est le seul élément du document dont la lecture se vérifie de façon
**absolue** — il décode ou il ne décode pas, et le code correcteur du
standard rend un faux positif quasi impossible. Partout ailleurs on mesure
des degrés.

Ça en fait un **capteur de qualité de capture** : un QR qui décode prouve que
la résolution et la netteté suffisent à cet endroit de la page. C'est
exactement ce qu'il manquait au contrôle qualité à la capture, qui figure
au TODO depuis le début — et le message rendu (« rapprocher l'appareil »)
s'adresse à l'utilisateur pendant qu'il tient encore le document, au seul
moment où la correction est gratuite.

#### La leçon de méthode

Nos rendus à 900 px sont **quatre fois plus petits** qu'une photo de
téléphone. Pour le texte du tableau ça ne se voyait pas — les modèles
redescendent de toute façon à 1600 px. Pour les petits éléments, ça décidait
de tout. Un jeu de test peut être irréaliste sur un axe qu'aucune des
métriques suivies ne regarde.

### 9. La signature : un résultat négatif, mesuré

Demandé en même temps que le QR. La réponse est différente, et c'est le
raisonnement qui compte plus que le code.

**Trois détecteurs écrits, trois échecs mesurés** contre la vérité terrain
exacte (la boîte de l'image intégrée dans le PDF source) :

| approche | résultat |
|---|---|
| composantes d'encre du quart bas-droit, filtre sur le remplissage | 3/5, et le bloc de notes légales désigné à tort |
| bande verticale exacte (x connu du gabarit), filtre sur la hauteur | **IoU 0,22, 2/8** |
| taux d'encre dans la zone du pied de page | **les plages se recouvrent entièrement** |

Le troisième échec est le plus net : sur les pages porteuses d'une signature
le taux d'encre va de 0,0003 à 0,135 ; sur les pages qui n'en portent pas, de
0,0017 à 0,032. Évident après coup — sur une page de continuation, la colonne
`Thành tiền` occupe exactement cette région.

Et la vérité terrain elle-même est ambiguë : la boîte du PDF est le **cadre**
de l'image, marges transparentes comprises, alors que l'encre occupe une zone
plus petite et plus basse. Une détection correcte y marque un IoU médiocre.
Mesurer ce détecteur revenait à mesurer un désaccord de définition.

#### Ce qu'on fait à la place

La signature n'a pas besoin d'être *décodée*, seulement d'être **préservée et
montrée** pour qu'un humain la vérifie. C'est une exigence de conservation,
pas de reconnaissance.

Et la position se déduit de la **structure du document**, pas d'un détecteur :
le gabarit ne met une signature que sur la **dernière page d'une facture** —
information que le recollage multi-pages fournit déjà. `invoice_export.py
--images-dir` découpe donc la zone de cette page-là et l'écrit dans
`results/<run>/signatures/invoice_N.png`, avec dans le JSON un champ qui dit
explicitement ce qu'il est :

```json
"signature": {"fichier": "invoice_5.png", "page": 11, "encre": 0.0475,
  "note": "zone découpée sur la dernière page de la facture, pas une
           détection : aucun algorithme n'a authentifié cette signature,
           elle est fournie pour relecture humaine"}
```

#### Ce qui reste hors périmètre, et pourquoi le dire

Comparer une signature à une référence est un domaine de recherche à part
entière, demande une base de signatures connues, et n'est pas dans le sujet.
Sur un document médical, une signature est en outre une **donnée
personnelle** : l'extraire et l'archiver relève de la Phase 4 anonymisation,
pas de l'extraction. À cadrer avec l'encadrante avant d'aller plus loin.

#### La leçon

Trois détecteurs mesurés puis écartés valent mieux qu'un détecteur livré sans
mesure. Le premier cas produit un résultat ; le second produit un chiffre qui
décrit l'heuristique de son auteur plutôt que le document.

---

## Identifié, non corrigé

### Développer `colspan` dans le parseur HTML

Essayé, puis retiré. Développer les `colspan` rend la ligne d'en-tête plus
fidèle au HTML, mais fabrique des cellules que la vérité terrain n'a pas :
TEDS de Chandra passait de 0,916 à **0,903**. Et ça ne réglait pas le
problème, l'en-tête de Chandra décrivant de toute façon 7 colonnes pour 6 de
données — le modèle hallucine un en-tête de groupe dupliqué.

Le problème n'est donc pas la largeur de l'en-tête mais le rapprochement des
colonnes, et il est traité là où il se pose (§6).

### En-têtes sur deux lignes, cas résiduels

Chandra rend parfois :

```html
<tr><th rowspan="2">STT</th><th rowspan="2">Tên…</th><th colspan="3">Tên…</th></tr>
<tr><th>ĐVT</th><th>Số lượng</th><th>Đơn giá</th></tr>
```

`_find_header_index` choisit **une seule** ligne d'en-tête et retient la
seconde : `STT`, `name` et `total` disparaissent. Sur la facture 1 de
`multipage_chandra`, les colonnes détectées sont `{unit: 0, quantity: 1,
unit_price: 2}` — décalées d'un cran.

Ce n'est **pas silencieux** : `extraction.status` vaut `partial` avec
`columns not found: index, name, total`, et les 31 lignes partent en
`incomplete`. Le garde-fou fait son travail, la donnée est marquée douteuse.

Le correctif propre suppose que le parseur HTML **développe** `colspan` et
`rowspan` avant de chercher l'en-tête, puis fusionne les lignes d'en-tête
consécutives. C'est une vraie évolution de `table_merge`, à faire avec des cas
de test dédiés — pas un correctif d'audit.

Impact chiffré : ça touche la lecture **brute** de Chandra, pas la prétraitée.
La politique adaptative écarte déjà ces lectures, et c'est une partie de
l'explication du +0,050 qu'apporte le prétraitement à ce modèle.

---

## Ce qui a résisté à l'examen

- **`parse_number`** — retire tout ce qui n'est pas chiffre, donc insensible
  aux quatre conventions de séparateur de milliers. Rend `None` sur une
  cellule vide plutôt que `0`, ce qui évite de fabriquer des lignes à zéro.
- **`check_line`** — ne corrige que lorsqu'une seule valeur manque, et se
  contente de signaler quand les trois sont présentes et incohérentes.
  L'équation seule ne dit pas *laquelle* est fausse ; le code ne prétend pas
  le savoir.
- **`extraction.status`** — quatre états distincts (`no_table`,
  `header_not_found`, `no_rows`, `partial`). Une facture vide et une
  extraction ratée ne se confondent pas.
- **`totals.consistent`** — vaut `null`, et non `false`, quand le total n'a
  pas pu être lu. La bonne distinction.
- **`table_merge`** — les deux vetos de clôture et le veto de fragment
  orphelin sont couverts par dix cas construits à la main.

---

## Effet de bord assumé

Le correctif n°1 fait perdre 0,15 aux lectures dont la numérotation est
illisible. Elles passent donc sous `SEUIL_DEUXIEME_PASSE` (0,95) dans
`api.py` et **déclenchent la seconde lecture**.

C'est voulu. Le prix est quelques secondes de calcul sur ces pages ; le gain
est qu'on ne livre plus comme sûre une extraction dont un tiers des contrôles
n'a pas pu tourner.

---

## Reproduire

```powershell
python tests\test_merge_assumptions.py
python scripts\eval_all.py --modele chandra --modele hunyuan
python src\invoice_export.py --run multipage_chandra
```
