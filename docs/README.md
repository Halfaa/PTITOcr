# Index des documents

Dix-huit documents écrits au fil du stage, dans l'ordre où les questions se
sont posées. Cet index dit lequel lire pour quelle question, et **lesquels
sont périmés** — parce qu'un chiffre juste au moment où il a été écrit
peut avoir été remesuré depuis.

Trois états :

- **à jour** — les chiffres et conclusions valent aujourd'hui
- **historique** — vrai à sa date, dépassé depuis ; gardé pour la trace
- **réserve** — piste étudiée puis close, ou candidat écarté

---

## Par où commencer

| document | état | pour quelle question |
|---|---|---|
| [`../dataset/README.md`](../dataset/README.md) | à jour | quels jeux d'images existent, contre quelle vérité terrain les noter |
| [`resultats_teds.md`](resultats_teds.md) | à jour | les chiffres principaux : quel modèle lit le mieux nos factures |
| [`audit_pipeline.md`](audit_pipeline.md) | à jour | où la chaîne de production peut échouer *sans le dire* |
| [`etat_du_projet.md`](etat_du_projet.md) | **historique** | état au 28 juillet (semaine 1) — utile comme point de départ, plus comme état réel |

---

## Modèles : candidats, prédictions, licences

| document | état | contenu |
|---|---|---|
| [`etat_de_lart_modeles.md`](etat_de_lart_modeles.md) | historique | état de l'art juillet 2026 des modèles VN+EN avec tableaux. **Réserve : HunyuanOCR y figure comme candidat, il est depuis écarté** (licence Tencent, exclut l'UE) |
| [`chandra_ocr2.md`](chandra_ocr2.md) | à jour | pourquoi mesurer Chandra, prédictions écrites avant mesure, licence OpenRAIL-M |
| [`glm_ocr.md`](glm_ocr.md) | **en cours** | le pari GLM-OCR (0,9 B, MIT). Mesure toujours pas faite : le premier passage a échoué en OOM sur nos images manuscrites, correctif appliqué, relance en attente |
| [`summary_paddleocr_vl.md`](summary_paddleocr_vl.md) | historique | tout premier benchmark, sur les 10 images TabRecSet uniquement |
| [`summary_ppstructure.md`](summary_ppstructure.md) | historique | idem pour PP-StructureV3 |
| [`notes_benchmark_tabrecset.md`](notes_benchmark_tabrecset.md) | à jour | comment le mini-jeu TabRecSet a été choisi (10 images réelles) |

---

## Résultats de mesure

| document | état | contenu |
|---|---|---|
| [`resultats_teds.md`](resultats_teds.md) | à jour | TEDS des modèles sur les factures multi-pages déformées |
| [`resultats_pretraitement.md`](resultats_pretraitement.md) | à jour | Phase 1 du sujet : localisation, perspective, éclairage, débruitage |
| [`avec_sans_pretraitement.md`](avec_sans_pretraitement.md) | à jour | le comparatif demandé en réunion : le prétraitement aide-t-il vraiment |
| [`resultats_validation.md`](resultats_validation.md) | à jour | validation arithmétique : détecter une erreur de lecture sans vérité terrain |
| [`degradation.md`](degradation.md) | à jour | à partir de quelle qualité de photo la chaîne casse (24 paliers) |
| [`resultats_handwriting.md`](resultats_handwriting.md) | à jour | banc HTR manuscrit VN/EN : Chandra 95,5 / 99,1 %, PaddleOCR-VL 78,2 / 90,3 % |
| [`resultats_handwriting_en.md`](resultats_handwriting_en.md) | à jour | version anglaise courte du précédent, à envoyer telle quelle |

---

## Jeux de test : conception et limites

| document | état | contenu |
|---|---|---|
| [`jeu_de_test_diversifie.md`](jeu_de_test_diversifie.md) | à jour | pourquoi 6 gabarits et 12 factures plutôt qu'un seul gabarit |
| [`fonds_encombres.md`](fonds_encombres.md) | à jour | le plus gros document du projet (18 sections) : le jeu à feuilles parasites, et **onze tentatives de recadrage qui échouent toutes**. Les §11, §16 et §18 sont les conclusions ; le reste est le chemin qui y mène |

---

## Application

| document | état | contenu |
|---|---|---|
| [`application.md`](application.md) | à jour | le livrable API + PWA prévu semaines 11-12 |

---

## Réserves qui traversent plusieurs documents

**HunyuanOCR est écarté.** Sa licence communautaire Tencent exclut l'UE, le
Royaume-Uni et la Corée du Sud, et Kaggle ne permet pas de choisir la région
de la machine. Il apparaît pourtant comme candidat ou comme colonne de
tableau dans une douzaine de documents antérieurs à cette décision
(`etat_du_projet.md`, `resultats_teds.md`, `resultats_pretraitement.md`,
`etat_de_lart_modeles.md`...). Les chiffres qui y figurent restent valides —
ils ont bien été mesurés — mais le modèle ne fait plus partie du roster.

**Le recadrage sur scène encombrée est une piste close.** Onze familles de
méthodes, un plafond d'IoU qui ne dépasse jamais 0,59 pour un atteignable
mesuré à 0,85. Conclusion au §11 puis §16-§18 de `fonds_encombres.md` : le
bord de la feuille est *invisible* dans nos rendus (blanc sur blanc, sans
profondeur de champ), et la bonne réponse n'est pas un meilleur recadrage
mais un lecteur qui segmente lui-même — ce que PaddleOCR-VL fait déjà.

**Les rendus antérieurs au correctif de graine ne sont pas appariés.**
`render_mesh_multipage.py` tirait caméra et éclairage sans initialiser
`random` : deux rendus du même jeu donnaient des vues différentes. Corrigé
depuis (`random.seed(zlib.crc32(...))`), mais toute comparaison image par
image entre deux jeux rendus avant ce correctif est invalide. Détail dans
`fonds_encombres.md` §3.
