# Corpus du projet — 14 jeux, 547 images

Tout ce qui a été produit ou collecté depuis le début du stage, recensé en
un seul endroit. `manifest.json` en est la version machine : une entrée par
image, avec sa famille, son jeu, sa résolution et le chemin de la vérité
terrain qui lui correspond.

```powershell
python dataset\build_manifest.py            # (re)construit manifest.json
python dataset\build_manifest.py --resume   # juste le tableau ci-dessous
python dataset\build_manifest.py --export corpus --zip   # copie unifiée à envoyer
```

**C'est un index, pas une copie.** Les images restent où elles sont : les
dupliquer coûterait 400 Mo dans un dépôt qui sait déjà les régénérer.
`--export` matérialise une copie unifiée quand il en faut vraiment une
(téléversement Kaggle, envoi à l'encadrante), en emportant la vérité
terrain avec elle.

---

## Les trois familles

| famille | jeux | ce qu'elle sert à mesurer |
|---|---|---|
| `facture` | 11 jeux, 477 images | la chaîne complète : localisation, dewarping, lecture de tableau, fusion multi-pages, validation arithmétique |
| `manuscrit` | 2 jeux, 60 images | la reconnaissance d'écriture manuscrite, VN et EN |
| `reel` | 1 jeu, 10 images | garde-fou : les seules photos non synthétiques du projet |

---

## Le détail

| jeu | images | UV | à quoi il sert |
|---|---|---|---|
| `multipage_test` | 17 | oui | jeu de référence historique, celui de tous les premiers chiffres |
| `multipage_flat_1800` | 17 | — | témoin haute résolution : le plafond de lecture sans déformation |
| `multipage_test_noillum` | 17 | — | isole l'effet de l'éclairage de celui de la déformation |
| `multipage_test_unwarped` | 17 | — | oracle de dewarping : plafond si le dépliage était parfait |
| `multipage_test_preprocessed_v3` | 17 | — | branche « prétraitée » du comparatif avec/sans |
| `variants_flat` | 25 | — | 12 factures, 6 gabarits : dépendance au gabarit |
| `variants_warped` | 25 | oui | les mêmes, déformées — le couple isole la déformation seule |
| `variants_encombre` | 25 | oui | 3 à 6 feuilles parasites : casse la localisation |
| `variants_encombre_recadre_contenu` | 25 | — | piste close (§18 `fonds_encombres.md`) : isole le tableau, coupe l'en-tête |
| `batch1` | 100 | oui | lot initial, une page par facture |
| `degradation` | 192 | — | 24 paliers × 8 pages : courbe de robustesse à la qualité photo |
| `handwriting_vi` | 30 | — | banc HTR vietnamien (fiche PHCN page 9) |
| `handwriting_en` | 30 | — | banc HTR anglais, 7 polices manuscrites |
| `tabrecset_sample` | 10 | — | photos réelles annotées, garde-fou contre le sur-ajustement au synthétique |

**Colonne UV** : les jeux marqués ont un masque de vérité terrain au pixel
près (`doc3D-renderer/uv/<jeu>`), ce qui permet de noter la localisation de
feuille exactement — c'est ce qui rend mesurable tout le travail de
recadrage.

---

## Trois régimes de vérité terrain, à ne pas confondre

C'est la distinction que `scripts/eval_all.py` existe pour protéger : donner
la mauvaise vérité à un jeu ne lève aucune erreur, ça sort juste des
nombres qui ne veulent rien dire.

**`par_facture`** (tous les jeux `facture`) — un JSON par facture, plusieurs
pages par facture. Le découpage pages → factures vient du PDF source, pas
des sorties OCR : le dériver de l'OCR reviendrait à noter l'algorithme de
fusion sur les données qui l'ont inspiré. Deux ensembles selon le jeu :
`ground_truth_labels_multipage` (8 factures) ou `ground_truth_labels_variants`
(12 factures).

**`par_page`** (jeux `manuscrit`) — un `*_verite.json` par specimen, écrit
par le générateur au moment du rendu, à côté de son image. Contient la
valeur exacte de chaque champ manuscrit, et pour l'anglais la police
utilisée (`police`), ce qui permet d'analyser les résultats par style
d'écriture.

**`tabrecset`** (jeu `reel`) — les annotations d'origine du jeu public,
détection (`td_annotation`) et structure/contenu (`tsr_tcr_annotation`).

---

## Régénérer ce qui manque

Le dépôt ne versionne pas les images : elles pèsent des centaines de Mo et
se reconstruisent. `build_manifest.py` liste en fin d'exécution les jeux
absents du disque plutôt que d'échouer.

| jeu | commande |
|---|---|
| rendus Blender | `doc3D-renderer/render_variants.ps1 -FolderId <jeu>` (`-Parasites -1` pour l'encombré) |
| prétraité | `python src/preprocess.py --images-dir <jeu> --out <jeu>_preprocessed --debug` |
| haute résolution | `python scripts/rendre_haute_resolution.py` |
| oracle de dewarping | `python scripts/dewarp_oracle.py` |
| dégradation | `python scripts/degrader.py --jeu variants_warped --zip` |
| manuscrit VN | `python handwriting/generate.py --n 30 --lignes 6 --seed 100` |
| manuscrit EN | `python handwriting_en/generate_en.py --n 30 --seed 100` |
| recadrage par contenu | `python scripts/recadrage_par_contenu_extraire.py` |

Les rendus Blender sont **reproductibles depuis le correctif de graine**
(`random.seed(zlib.crc32(nom_de_page))`) : deux rendus du même jeu donnent
les mêmes vues. Les jeux produits AVANT ce correctif ne sont pas appariés
d'un jeu à l'autre — détaillé dans `docs/fonds_encombres.md`.

---

## Ce que ce corpus ne contient pas, et pourquoi ça compte

**Aucune photo réelle de document médical vietnamien.** Tout le `facture` et
tout le `manuscrit` sont synthétiques : LaTeX pour le contenu, Blender pour
la déformation et l'éclairage, polices manuscrites pour l'écriture. C'est ce
qui rend la vérité terrain exacte au pixel — et c'est aussi la limite
principale des chiffres du projet.

**Pas de profondeur de champ.** Les rendus n'ont pas d'ouverture simulée,
donc les feuilles d'arrière-plan sont aussi nettes que la cible. Mesuré
(`docs/fonds_encombres.md` §16) : c'est ce qui rend le bord de la feuille
littéralement invisible, et donc le jeu encombré plus dur que la réalité.

**Une seule police manuscrite pour le vietnamien** (Playwrite VN), contre
sept pour l'anglais. L'effet de police est mesurable sur l'EN (jusqu'à
13 points d'écart entre polices) ; sur le VN on ne peut pas le mesurer.

**TabRecSet est le seul contrepoids réel**, et il ne fait que 10 images
annotées, dans d'autres langues. Toute conclusion tirée du synthétique reste
à confirmer sur de vraies photos.

---

## Licences

Les jeux synthétiques (`facture`, `manuscrit`) sont produits par ce projet à
partir de gabarits LaTeX et de polices libres — polices manuscrites en OFL,
sauf Homemade Apple en Apache 2.0 (détail dans `handwriting_en/README.md`),
Liberation Serif en OFL pour le texte imprimé.

`tabrecset_sample` provient du jeu public TabRecSet et reste soumis à sa
licence d'origine ; seul un échantillon de 10 images est versionné ici, le
jeu complet est ignoré par git (`data/TabRecSet/`).
