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
