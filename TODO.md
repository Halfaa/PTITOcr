# TODO

État au 5 août 2026, semaine 3 du stage.

Rapporté à la timeline officielle, le travail est en avance : les semaines
1 à 8 sont bouclées, les semaines 9–10 à moitié, et le prototype des
semaines 11–12 existe déjà.

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

- [x] **Prototype PWA + API** (`src/api.py`, `webapp/`) — photo au téléphone,
      rendu JSON, chaque étape exposée. Livrable des semaines 11–12.
- [x] **Chandra OCR 2 sur GPU loué** (`kaggle/bench_kaggle_chandra.ipynb`) —
      quatrième modèle, cinq branches, protocole identique aux autres.
- [x] **Protocole d'évaluation unifié** (`scripts/eval_all.py`) — un seul
      point d'entrée pour les cinq évaluations, avec la bonne vérité terrain
      par jeu. C'est ce qui rend les colonnes comparables.
- [x] **Démonstration de la fusion** (`demo/demo_fusion.py`) — on glisse les
      pages, on voit les morceaux, les signaux de décision, puis le tableau
      reconstitué avec la provenance de chaque ligne.

### Les chiffres — tous re-mesurés le 5 août sous `scripts/eval_all.py`

Les valeurs antérieures de ce fichier (0,974 pour Hunyuan) venaient d'états
intermédiaires du code d'évaluation, améliorés depuis.

| | TEDS brut | TEDS adaptatif | champs | fusion |
|---|---|---|---|---|
| **Chandra OCR 2** | 0,916 | **0,966** *(plafond 0,967)* | **29/32** | 100 % / 100 % |
| HunyuanOCR-1.5 | **0,950** | 0,953 | 28/32 | 100 % / 100 % |
| PaddleOCR-VL | 0,909 | 0,951 | 24/32 | 100 % / 88 % |
| PP-StructureV3 | 0,557 | — | 9/32 | 100 % / 100 % |

Et sur le jeu diversifié — 12 factures, 6 gabarits, **jamais vu par les
algorithmes** :

| | Chandra | PaddleOCR-VL |
|---|---|---|
| à plat | **0,981** | 0,976 |
| déformé, adaptatif | **0,977** *(= plafond)* | 0,942 *(plafond 0,945)* |
| champs déformé | 46/48 | 44/48 |

Sur le jeu diversifié la politique adaptative atteint **exactement** le
plafond avec Chandra : la règle de décision ne perd plus rien.

**Le résultat le plus intéressant du comparatif n'est pas un modèle.** En
lecture brute, Hunyuan gagne ; c'est le prétraitement qui fait passer Chandra
devant (+0,050, le plus gros gain des trois). L'écart entre les deux meilleurs
modèles (0,013) est plus petit que ce qu'apporte la Phase 1.

---

## Demandé en réunion (6 août)

1. **Photos réelles** — imprimer puis photographier. Bloqué sur l'imprimante.
2. **Jeu à fonds encombrés** — ✅ **fait et mesuré**. La localisation de
   feuille s'effondre : IoU 0,84 → 0,37, et **0/20 pages exploitables contre
   22/25**. Le plafond tombe aussi (0,86 → 0,51), donc ce n'est pas le
   sélecteur mais la segmentation elle-même : seuillage et contours ne
   peuvent pas isoler une feuille au milieu d'autres feuilles. La suite
   logique est une **segmentation apprise**.
   Détail : [docs/fonds_encombres.md](docs/fonds_encombres.md).

   **Reste à faire :** passer Chandra dessus. Le notebook Kaggle est câblé
   (branches `variants_encombre_chandra` et `..._preproc_chandra`), le zip
   `kaggle/images_variants_encombre.zip` est prêt. La question ouverte n'est
   plus le recadrage mais la **lecture** : que produit le modèle quand on lui
   donne un recadrage *faux* plutôt qu'absent ? Le cas à craindre est un
   tableau cohérent mais issu d'une feuille parasite — la confiance
   arithmétique ne le verrait pas.

   **Avant de lancer**, compléter le jeu : il n'a que 20 pages, et pas les 20
   premières. Le tri par nom des textures a coupé les pages 5 à 9, ce qui
   ampute la facture 5. `-Depuis 20 -Nombre 5` la rétablit.

   *Ancienne note, conservée pour le contexte :*
   `doc3D-renderer/distracteurs.py`, option `-Parasites` dans
   `render_variants.ps1`. Blender n'étant pas dans l'environnement de
   développement, un rendu de vérification (`-Verifier`) est indispensable
   avant le jeu complet. Voir [docs/fonds_encombres.md](docs/fonds_encombres.md).
3. **Comparatif avec / sans prétraitement** — ✅ fait, les données existaient
   déjà : [docs/avec_sans_pretraitement.md](docs/avec_sans_pretraitement.md).
4. **Cloud** — évoqué, à cadrer plus tard.

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

### 2. L'étude de dégradation d'image  ⭐ le meilleur rapport valeur/effort

Livrable des semaines 9–10, entièrement faisable sans imprimante et en
quelques heures : dégrader progressivement les mêmes pages (flou de bougé,
bruit ISO, compression JPEG, sous-exposition) et tracer la courbe de TEDS.

Ça répond à la question que l'encadrante posera : **à partir de quelle
qualité de photo la chaîne cesse-t-elle de fonctionner ?** Aujourd'hui on
sait seulement qu'elle marche sur des rendus Blender parfaits. Et ça donne
une spécification chiffrée au contrôle qualité à la capture, qui reste à
écrire.

C'est aussi le seul moyen, avant d'avoir des photos réelles, de savoir si
0,97 est un chiffre robuste ou un chiffre de laboratoire.

### 3. GLM-OCR — le seul modèle SOTA qui tienne en 4 Go

0,9 B, licence MIT, meilleur TableTEDS de tous les modèles évalués, et il
tourne **sur le poste** — pas de GPU loué, donc une PWA enfin utilisable.
Déjà câblé : `--model glm` dans `bench_deformed.py`, entrée `glm` dans
`eval_all.py`.

La réserve : le vietnamien n'est pas dans ses 8 langues officielles. Le smoke
test d'une page suffit à trancher, et un écart TEDS-Struct/TEDS supérieur à
0,15 signera un profil PP-StructureV3. Prédictions écrites avant mesure dans
[docs/glm_ocr.md](docs/glm_ocr.md).

### 4. NER sur texte libre

Partiellement couvert par l'extraction de champs étiquetés. Les entités en
texte libre (« Glucose : 110 mg/dL ») ne le sont pas — et le corpus actuel
n'en contient presque pas, il faudra enrichir le générateur pour que la tâche
ait un sens.

### 5. Anonymisation des données patient

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
n'a aucune de ces contraintes. **Chandra OCR 2** non plus (code Apache 2.0,
poids OpenRAIL-M modifiée, sans restriction géographique) — c'est pour ça
que ses benchmarks ont pu tourner sur Kaggle. Le choix du modèle est donc un
arbitrage à trois termes : précision, coût matériel (5 B ne tiennent pas dans
4 Go) et licence.

**Hypothèse métier de la fusion.** La colonne STT redémarre à 1 à chaque
facture. Un format numérotant en continu faisait fusionner deux factures
distinctes ; corrigé par le veto de clôture. Un second défaut, trouvé en
manipulant la démo le 5 août : deux **fragments** de factures différentes,
chacun portant un marqueur de continuation authentique, étaient recollés —
un marqueur prouve que B continue quelque chose, pas qu'il continue A.
Corrigé par le veto de numérotation contradictoire, avec garde de cohérence.
`tests/test_merge_assumptions.py` garde les dix cas. À revalider sur tout
nouveau format.

**Échantillon.** 20 factures, 7 gabarits, 42 pages, quatre modèles. La politique adaptative
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

**Dix-huit défaillances silencieuses** rencontrées à ce jour, aucune n'ayant levé
d'erreur. Documentées dans `docs/etat_du_projet.md`, et cinq de plus dans `docs/audit_pipeline.md` (revue ciblée des seuls modules de production, 5 août) — c'est l'argument le plus
concret en faveur de tout le dispositif d'évaluation, et ça mérite une section
du rapport.
