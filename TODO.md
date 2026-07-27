# TODO

État au 27 juillet 2026. Les deux tâches initiales (scoring numérique,
tableaux sur 2 pages) sont **terminées** — voir `docs/resultats_teds.md`.

---

## Fait

- [x] **Scoring numérique automatique** — TEDS + TEDS-Struct (`src/teds.py`,
      `src/eval_teds.py`), métrique standard PubTabNet, comparable à la
      littérature.
- [x] **Tableaux sur 2 pages** — détection + fusion (`src/table_merge.py`),
      100 % de précision et de rappel sur 14 paires de pages, zéro fusion à
      tort avec les trois modèles.
- [x] **Comparaison de 3 modèles** sur 17 pages : HunyuanOCR-1.5 (0.928),
      PaddleOCR-VL (0.909), PP-StructureV3 (0.557).
- [x] **État de l'art** des modèles vietnamien/anglais —
      `docs/etat_de_lart_modeles.md`.

---

## À faire — par ordre de valeur

### 1. Validation arithmétique  ⭐ le meilleur rapport effort/gain

Une facture est redondante : `quantité × prix_unitaire = total_ligne`, et la
somme des lignes = `Tổng tiền`. Chaque ligne porte donc sa propre
vérification, **sans vérité terrain**.

Deux usages : détecter les erreurs OCR en production (on ne présente à un
humain que les lignes qui ne bouclent pas), et parfois les corriger — deux
valeurs sur trois étant justes, la troisième se déduit.

À mesurer sur les données déjà disponibles : *quel pourcentage des cellules
fausses la validation attrape-t-elle ?* C'est le chiffre qui dira si un TEDS
de 0.928 est exploitable en pratique.

Effort : une demi-journée. Tout est déjà là (sorties OCR + vérité terrain).

### 2. Parsing en champs typés

Passer du `<table>` HTML à des objets `{nom, quantité, prix_unitaire,
total}`. Prérequis de la validation arithmétique et de tout usage applicatif.

Difficultés réelles, souvent sous-estimées : l'ordre des colonnes varie,
l'OCR fusionne parfois deux cellules, et il faut normaliser les nombres
(`2.900` / `2 900` / `2900`) comme les unités (`viên` / `Viên` / `vièn`).

### 3. Diversifier le jeu de test

8 factures, un seul gabarit. Générer des variantes : nombre de colonnes
différent, styles de bordure, factures sur 3 pages, et surtout **un format où
la colonne STT ne redémarre pas à 1** — c'est l'hypothèse métier sur laquelle
repose le signal le plus discriminant de la fusion.

Sans ça, un relecteur exigeant dira que l'algorithme est calibré sur son
propre générateur.

### 4. Tester le dewarping

TEDS-Struct montre que le goulot n'est pas la structure mais la lecture des
caractères. Redresser l'image avant l'OCR devrait donc faire remonter le
score — c'est la question de recherche ouverte par les mesures, et elle
rejoint les papiers mis en réserve.

Référence utile : *Towards Real-World Document Parsing via Realistic Scene
Synthesis and Document-Aware Training* (CVPR 2026, arXiv 2603.23885), qui
fait exactement ce que fait le pipeline doc3D — de quoi justifier la démarche
dans le rapport.

### 5. Comprendre les échecs de détection

Sur 17 pages, l'OCR n'extrait aucun tableau pour certaines (pages 6 et 11
selon le modèle). Ces continuations sont perdues avant la fusion. Déformation
trop forte ? contraste ? C'est un problème amont, potentiellement le plus
limitant à terme.

### 6. Tests unitaires

Les vérifications actuelles sont des scripts jetables. Une suite pytest sur
`table_merge` et `teds` protégerait contre les régressions si un seuil est
modifié plus tard, et rendrait les chiffres reproductibles par un tiers.

---

## Vers une application (hors périmètre du stage, mais utile à savoir)

Ce qui est construit — OCR + fusion — est le cœur scientifique, mais environ
un quart d'une application. Manquent, dans l'ordre du flux :

- **regrouper les photos en documents** : rien ne dit lesquelles forment une
  facture (ici c'est le nom de fichier `page_N` qui le donne) ;
- **ordonner les pages** ;
- **contrôle qualité à la capture** : détecter flou et reflet pour redemander
  la photo pendant que l'utilisateur tient encore le document ;
- **score de confiance par ligne** plutôt que par document, pour que la revue
  humaine porte sur 3 lignes et non sur 30.

Un TEDS de 0.928 signifie qu'environ 7 % des cellules sont fausses : sur des
factures médicales, ça ne se livre pas sans validation ni relecture.

---

## Points de vigilance

**Hypothèse métier de la fusion** : la colonne STT redémarre à 1 à chaque
facture. C'est le signal le plus discriminant, et celui qui rattrape les cas
où l'OCR a massacré la fin du tableau précédent. À revalider sur tout nouveau
format (cf. point 3).

**Deux venv incompatibles** : `venv` (PaddleOCR, évaluation) et
`venv_hunyuan` (HunyuanOCR, transformers ≥ 5.13). Les scripts vérifient
l'environnement au démarrage et échouent en une seconde si besoin.

**`backend="pil"` obligatoire pour HunyuanOCR** : avec le backend torchvision,
le modèle produit du charabia sans lever la moindre erreur. Panne silencieuse
déjà rencontrée, codée en dur dans `scripts/bench_deformed.py`.
