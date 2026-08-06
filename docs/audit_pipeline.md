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

## Identifié, non corrigé

### En-têtes HTML sur deux lignes avec `colspan` / `rowspan`

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
