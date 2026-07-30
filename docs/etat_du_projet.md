# État du projet — 28 juillet 2026

Semaine 1 du stage. Ce document sert de point de reprise : ce qui est fait,
comment la chaîne fonctionne, et ce qui reste au regard du sujet.

---

## 1. Ce qui est fait

### Les données

Il n'existait pas de jeu de test avec vérité terrain pour des factures
médicales vietnamiennes photographiées. On en a fabriqué un.

Le générateur produit un JSON (patient, médecin, liste de médicaments), le
rend en LaTeX avec `longtable` — qui coupe automatiquement les tableaux trop
longs en répétant l'en-tête — puis en PDF et en PNG. Blender projette ensuite
chaque page sur un maillage 3D courbé avec fond et éclairage réalistes.

Résultat : **8 factures sur 17 pages**, dont neuf continuations réelles, avec
la vérité terrain exacte. C'est ce que ne donne aucune photo réelle.

### Les modèles comparés

Quatre modèles évalués sur le même jeu, dont trois complets.

| Modèle | Taille | Où il tourne | État |
|---|---|---|---|
| HunyuanOCR-1.5 | 1 B | GPU, ~87 s/page | 17 pages |
| PaddleOCR-VL | 0.9 B | CPU, ~230 s/page | 17 pages |
| PP-StructureV3 | — | CPU, ~60 s/page | 17 pages |
| Chandra OCR 2 | 5 B | CPU, ~900 s/page | en cours |

### Les trois résultats mesurés

**Qualité d'extraction du tableau** (TEDS, métrique standard PubTabNet) :

| Modèle | TEDS | TEDS-Struct | Écart |
|---|---|---|---|
| HunyuanOCR-1.5 | **0.928** | **0.949** | 0.020 |
| PaddleOCR-VL | 0.909 | 0.933 | 0.024 |
| PP-StructureV3 | 0.557 | 0.857 | **0.300** |

L'écart entre les deux colonnes est le résultat le plus instructif :
PP-StructureV3 reconstruit correctement la grille mais lit très mal les
caractères vietnamiens. Le goulot d'étranglement est l'OCR, pas la détection
de tableau.

**Fusion des tableaux multi-pages** — la contribution propre du stage,
répondant à la remarque de l'encadrante :

| Modèle | Précision | Rappel | Gain de TEDS |
|---|---|---|---|
| HunyuanOCR-1.5 | 100 % | 100 % | +0.260 |
| PP-StructureV3 | 100 % | 100 % | +0.132 |
| PaddleOCR-VL | 100 % | 88 % | +0.251 |

**Zéro fusion à tort** avec les trois modèles. C'est ce qui compte le plus :
coller deux factures différentes fabriquerait un tableau mêlant deux
documents, erreur bien plus grave et bien plus difficile à repérer en aval
qu'une continuation manquée.

**Validation arithmétique** — détection des erreurs *sans* vérité terrain :

Avec HunyuanOCR, sur 215 lignes, **12 sont à relire (6 %) et elles
contiennent 100 % des erreurs numériques**, sans aucune fausse alerte. C'est
ce qui rend un TEDS de 0,93 exploitable en pratique : on ne présente à un
relecteur que les lignes qui ne bouclent pas.

**Champs d'en-tête** — ce que TEDS ne mesure pas, et que le sujet nomme :

| Modèle | Hôpital | Patient | Date | Médecin | Global |
|---|---|---|---|---|---|
| HunyuanOCR | 8/8 | 5/8 | 6/8 | 6/8 | **78 %** |
| PaddleOCR-VL | 6/8 | 4/8 | 7/8 | 5/8 | 69 % |
| PP-StructureV3 | 2/8 | 2/8 | 3/8 | 2/8 | 28 % |

Nettement plus bas que les scores TEDS : les champs isolés en petits
caractères sont bien plus fragiles que le tableau, qui bénéficie de sa
redondance interne.

---

## 2. Comment la chaîne fonctionne

### Le principe

On fabrique de fausses factures dont on connaît déjà la réponse, on les abîme
volontairement pour qu'elles ressemblent à des photos, on les passe à l'OCR,
puis on recolle les tableaux coupés — et comme on connaît la réponse, on peut
chiffrer l'erreur.

### Les quatre phases

**Phase 0 — génération.** Faite une fois. JSON → LaTeX → PDF → PNG → Blender.

**Phase 1 — OCR, page par page.** Une commande par modèle. C'est la seule
étape coûteuse, et la seule qui touche au GPU. Reprenable : relancer réutilise
les pages déjà faites.

```powershell
python scripts\bench_deformed.py --model hunyuan --images-dir "..\doc3D-renderer\img\multipage_test" --output multipage_hunyuan
```

**Phase 2 — extraction et fusion.** *Ce n'est pas une commande.*
`table_merge.py` est une bibliothèque que chaque évaluation rappelle au
moment où elle en a besoin. Il n'existe pas de fichier intermédiaire
« tableaux fusionnés » sur le disque.

**Phase 3 — les évaluations.** Indépendantes, dans n'importe quel ordre.

```powershell
python src\eval_multipage_merge.py --run multipage_hunyuan   # détection des continuations
python src\eval_teds.py            --run multipage_hunyuan   # qualité d'extraction
python src\eval_validation.py      --run multipage_hunyuan   # validation arithmétique
python src\eval_fields.py                                    # champs d'en-tête, tous modèles
python src\invoice_export.py       --run multipage_hunyuan   # sortie JSON
```

### Deux vérités terrain distinctes

C'est le point méthodologique important.

Le **PDF source** sert à savoir quelles pages se continuent (marqueurs
`Tiếp trang trước`). L'utiliser plutôt que les sorties OCR évite de noter
l'algorithme sur les données qui l'ont inspiré.

Le **JSON du générateur** sert à savoir ce que la facture contient vraiment.
Il alimente TEDS, la validation et l'évaluation des champs.

### Le chemin des données

Une image PNG devient un `.md` contenant du HTML. `extract_tables()` en tire
des objets `Table`. `merge_table_sequence()` en fait un seul. `parse_table()`
le convertit en `LineItem` typés — c'est là que les nombres deviennent des
entiers. `check_invoice()` vérifie les égalités. `invoice_export.py` assemble
le JSON.

Chaque conversion peut perdre de l'information, et il est utile de savoir
laquelle : si l'OCR ne produit aucune balise `<table>`, tout s'arrête à
`extract_tables()` et aucune étape aval ne peut le rattraper.

### Les deux environnements

`venv` porte PaddleOCR, PP-StructureV3 et toutes les évaluations.
`venv_hunyuan` porte HunyuanOCR seul, avec transformers ≥ 5.13 incompatible
avec le premier. Chandra tourne hors venv, sur le Python système, sans
inconvénient — il est de toute façon limité au CPU.

Chaque script vérifie son environnement au démarrage et échoue en une seconde
plutôt qu'après plusieurs minutes de chargement de modèle.

---

## 3. Ce qui reste

Par ordre de valeur, et rapporté aux objectifs du sujet.

### Le module de prétraitement — livrable des semaines 3-4

C'est le livrable nommé le plus visiblement manquant, et celui qui donne son
titre au sujet. Le sujet demande OpenCV, détection de contours, transformation
perspective, binarisation.

L'**oracle de dewarping** est construit et les 17 pages redressées sont
prêtes ; il manque l'OCR dessus pour connaître le plafond. Ce chiffre dira
combien investir dans le module.

```powershell
python scripts\bench_deformed.py --model hunyuan --images-dir "..\doc3D-renderer\img\multipage_test_unwarped" --output multipage_unwarped_hunyuan
python src\eval_teds.py --run multipage_unwarped_hunyuan
```

Une piste connexe attend une réponse : **les champs patient et date
disparaissent sur certaines pages** alors qu'ils sont lus sur d'autres, à
mise en page identique. Ce n'est ni le prompt ni la mise en page — les deux
ont été testés et écartés. Reste la déformation. Si les champs reviennent sur
la page redressée, le dewarping ne fait pas qu'améliorer un score : il
récupère de l'information entièrement perdue, dont celle que le sujet nomme.

### Les photos réelles

Le sujet vise des photos de smartphone, PDF natifs exclus. Nos données sont
entièrement synthétiques.

L'idée la plus rentable : **imprimer les fausses factures et les
photographier**. On obtient de vraies conditions de capture tout en gardant
la vérité terrain exacte, ce qu'aucune photo de document réel ne permet. Et
ça valide le pipeline doc3D en comparant déformation simulée et réelle sur le
même contenu.

### Le jeu de test diversifié

8 factures, un seul gabarit. Il faudrait des variantes — nombre de colonnes
différent, styles de bordure, et surtout **un format où la colonne STT ne
redémarre pas à 1**, puisque c'est l'hypothèse métier sur laquelle repose le
signal le plus discriminant de la fusion.

### Les objectifs du sujet non couverts

- **NER** sur texte libre : partiellement couvert par l'extraction de champs,
  pas pour les entités en texte libre du type « Glucose : 110 mg/dL ».
- **Anonymisation** des données patient (Phase 4) : non commencé.
- **Prototype UI/API** (semaines 11-12) : non commencé.
- **Métriques WER / F1** : on utilise TEDS, plus adapté aux tableaux — à
  justifier dans le rapport plutôt qu'à passer sous silence.

---

## 4. Les pièges rencontrés

Quatre défaillances **silencieuses** en une semaine, sans une seule erreur
levée. C'est l'argument le plus concret en faveur de tout le dispositif
d'évaluation, et ça mérite une section du rapport.

**Le backend d'image.** HunyuanOCR avec le backend torchvision produit 6842
caractères de charabia en 315 s, sans erreur. Cause : le rééchantillonnage
LANCZOS remplacé par BICUBIC. Corrigé par `backend="pil"`, codé en dur.

**Le prompt en anglais.** Le prompt officiel anglais, copié verbatim de la
documentation Tencent, déclenche l'analyse de mise en page au lieu du parsing.
Sortie parfaitement bien formée, répondant à une autre question. La doc n'a
pas tort : elle décrit vLLM et la version 1.0, nous utilisons transformers et
la 1.5.

**La lettre `đ`.** Le `đ` vietnamien est une lettre à part entière et NFKD ne
le décompose pas en `d`. Conséquence : `ĐVT` ne correspondait jamais au
mot-clé `dvt`, et **la colonne unité était perdue dans toutes les factures**
sans que rien ne le signale.

**Les colonnes inversées.** PP-StructureV3 a rendu une page avec les colonnes
de droite à gauche et sans en-tête ; l'export produisait alors une facture
vide. Il y a désormais un statut `extraction` explicite, parce qu'une facture
vide et une extraction ratée ne veulent pas dire la même chose.

**Le tableau en Markdown.** HunyuanOCR ne répond pas toujours en HTML : sur
certaines pages il rend le tableau en Markdown à pipes. `extract_tables()` ne
cherchait que `<table>` et jetait la page entière — contenu pourtant complet
et correct. Deux pages du benchmark disparaissaient ainsi, et avec elles la
continuation qu'elles portaient. Corrigé : le parseur accepte les deux
notations et les rend dans l'ordre du document. Le TEDS de référence de
HunyuanOCR passe de 0,928 à **0,950** rien qu'avec ce correctif.

Un même fil les relie : rien ne plante, tout paraît fonctionner, seule la
confrontation à une référence révèle le problème.

**Et un cas inverse : l'erreur bruyante mais fausse.** Un `pip install` a
remonté NumPy en 2.2, alors que paddlex exige NumPy 1.x — contrainte pourtant
déjà écrite dans `requirements.txt`. PaddleOCR intercepte l'`ImportError` et
la remplace par « *a dependency error occurred during pipeline creation* »,
qui ne nomme ni le paquet ni l'exception réelle. Les 17 pages du benchmark
échouaient donc à l'identique sur un message qui n'indiquait rien.

Deux corrections, l'une curative, l'autre préventive : `bench_deformed.py`
imprime désormais la trace complète à la première erreur, et `env_check.py`
vérifie le **plafond** de version de NumPy au démarrage, en une seconde,
plutôt qu'après le chargement du modèle. `scripts/diagnose_env.py` reproduit
un échec de pipeline avec sa trace intacte.

La leçon dépasse le cas : une contrainte inscrite dans `requirements.txt`
n'est pas appliquée rétroactivement. Un `pip install` ultérieur peut remonter
une dépendance transitive sans avertissement, et le fichier reste correct
pendant que l'environnement ne l'est plus.

---

## 5. Points de vigilance

**Échantillon.** 8 factures, un gabarit, un générateur. Les chiffres
établissent que la chaîne encaisse du bruit OCR réel — pas qu'elle généralise.

**Hypothèse métier de la fusion.** Le STT redémarre à 1 à chaque facture.
C'est le signal le plus discriminant et celui qui rattrape les cas où l'OCR a
massacré la fin du tableau précédent. À revalider sur tout nouveau format.

**Licence HunyuanOCR.** Licence communautaire Tencent, excluant l'Union
européenne, le Royaume-Uni et la Corée du Sud. Développement et déploiement
au Vietnam : conforme. Deux restrictions demeurent partout — interdiction
d'utiliser les sorties pour entraîner un autre modèle, et restrictions sur
les décisions automatisées en santé. PaddleOCR-VL, en Apache 2.0, n'a aucune
de ces contraintes pour 2 points de TEDS de moins : un critère de choix qui
ne se réduit pas à la précision.
