# TODO

État au 3 août 2026, semaine 2–3 du stage.

Rapporté à la timeline officielle, le travail est en avance : les semaines
1 à 6 sont bouclées, les semaines 7–8 et 9–10 le sont à moitié.

---

## Fait, et mesuré

- [x] **Scoring numérique** — TEDS et TEDS-Struct (`src/teds.py`), métrique
      standard PubTabNet, comparable à la littérature.
- [x] **Fusion de tableaux multi-pages** (`src/table_merge.py`) — 100 % de
      précision et de rappel, zéro fusion à tort sur les cinq runs.
- [x] **État de l'art** vietnamien/anglais — `docs/etat_de_lart_modeles.md`.
- [x] **Validation arithmétique** (`src/invoice_validate.py`) — 100 % des
      erreurs numériques attrapées, zéro fausse alerte.
- [x] **Module de prétraitement** (`src/preprocess.py`) — IoU 0,90 contre les
      masques UV exacts, 17/17 recadrages exploitables.
- [x] **Extraction adaptative** (`src/adaptive.py`) — bat les deux variantes
      prises seules, à 0,004 du choix parfait.
- [x] **Jeu de test diversifié** (`gen_variants_json.py`) — 12 factures,
      25 pages, 5 en numérotation continue, à plat et déformées, mesuré.
- [x] **Export JSON** avec statut d'extraction explicite.

### Les chiffres

| | TEDS | champs | fusion |
|---|---|---|---|
| HunyuanOCR adaptatif | 0,974 | 28/32 | 100 % / 100 % |
| PaddleOCR-VL adaptatif | 0,951 | 24/32 | 100 % / 100 % |
| PP-StructureV3 | 0,557 | 9/32 | 100 % / 100 % |

Et sur le jeu diversifié — 12 factures, 6 gabarits, **jamais vu par les
algorithmes** :

| | TEDS | champs | fusion |
|---|---|---|---|
| à plat | 0,976 | — | 100 % / 100 % |
| déformé, adaptatif | **0,942** | 44/48 | 100 % |

Le plafond du choix parfait était à 0,945 : la règle de décision n'est plus
le maillon faible.

---

## À faire — par ordre de valeur

### 1. Les photos réelles  ⭐ le plus urgent

La timeline les place semaines 9–10, mais elles ont une contrainte physique :
il faut **imprimer les fausses factures et les photographier**. Ça ne se
rattrape pas en codant un week-end, et c'est la critique que tout relecteur
fera en premier — les données sont à 100 % synthétiques.

L'astuce est qu'on garde la vérité terrain exacte, ce qu'aucune photo de
document réel ne permet. Et ça valide le pipeline doc3D en comparant
déformation simulée et réelle sur le même contenu.

### 2. Le prototype PWA

Photo au téléphone, rendu immédiat. Le calcul reste côté serveur, donc l'API
sert aussi de livrable indépendant. À afficher : le quadrilatère détecté, les
cadres de l'OCR, la décision de fusion, et les lignes surlignées selon leur
statut de validation.

### 3. NER sur texte libre

Partiellement couvert par l'extraction de champs étiquetés. Les entités en
texte libre (« Glucose : 110 mg/dL ») ne le sont pas — et le corpus actuel
n'en contient presque pas, il faudra enrichir le générateur pour que la tâche
ait un sens.

### 4. Anonymisation des données patient

Phase 4 du sujet, non commencée. À discuter avec l'encadrante : la politique
d'usage de HunyuanOCR interdit par ailleurs les décisions automatisées en
santé.

---

## Ce qui manque pour en faire une application

Le cœur scientifique — OCR, fusion, validation — représente environ un quart
d'une application réelle. Manquent, dans l'ordre du flux :

- **regrouper les photos en documents** : rien ne dit lesquelles forment une
  même facture (ici c'est le nom de fichier `page_N` qui le donne) ;
- **ordonner les pages** ;
- **contrôle qualité à la capture** : détecter flou et reflet pour redemander
  la photo pendant que l'utilisateur tient encore le document ;
- **score de confiance par ligne** plutôt que par document, pour que la revue
  humaine porte sur 3 lignes et non sur 30.

Un TEDS de 0,97 laisse environ 3 % de cellules fausses : sur des factures
médicales, ça ne se livre pas sans relecture.

---

## Points de vigilance

**Licence HunyuanOCR.** Licence communautaire Tencent, excluant l'Union
européenne, le Royaume-Uni et la Corée du Sud. Développement et déploiement
au Vietnam : conforme. Attention aux plateformes de calcul dont on ne choisit
pas la région — Kaggle et Colab en font partie. PaddleOCR-VL, en Apache 2.0,
n'a aucune de ces contraintes pour 2 points de TEDS de moins.

**Hypothèse métier de la fusion.** La colonne STT redémarre à 1 à chaque
facture. Un format numérotant en continu faisait fusionner deux factures
distinctes ; corrigé par le veto de clôture, et `tests/test_merge_assumptions.py`
garde le cas. À revalider sur tout nouveau format.

**Échantillon.** 20 factures, 7 gabarits, 42 pages. La politique adaptative
tient sur un jeu qu'elle n'a jamais vu, ce qui est un vrai indice de
généralisation — mais toutes les données restent **synthétiques**, issues d'un
seul générateur et d'un seul moteur de déformation. Aucune photo réelle à ce
jour.

**Deux venv incompatibles.** `venv` (PaddleOCR, évaluation) et `venv_hunyuan`
(HunyuanOCR, transformers ≥ 5.13). Les scripts vérifient l'environnement au
démarrage et échouent en une seconde plutôt qu'après le chargement du modèle.

**`backend="pil"` obligatoire pour HunyuanOCR.** Avec le backend torchvision,
le modèle produit du charabia sans lever la moindre erreur. Codé en dur dans
`scripts/bench_deformed.py`.

**Sept défaillances silencieuses** rencontrées à ce jour, aucune n'ayant levé
d'erreur. Documentées dans `docs/etat_du_projet.md` — c'est l'argument le plus
concret en faveur de tout le dispositif d'évaluation, et ça mérite une section
du rapport.
