# Jeu de test à fonds encombrés

Demandé en réunion du 6 août : *un jeu avec de vrais fonds, des images avec
d'autres documents en arrière-plan*.

C'est l'attaque la plus directe contre le point faible connu du
prétraitement. Nos fonds actuels sont des HDR de bureau, moquette ou marbre :
**uniformes**. La détection de feuille y a la tâche facile — un seul grand
quadrilatère clair dans l'image. Sur un vrai bureau il y a d'autres papiers,
et rien ne garantit que le détecteur choisisse le bon.

---

## 1. Pourquoi des plans dans la scène 3D, et pas des HDR encombrés

Un HDR de bureau en désordre serait plus fidèle visuellement. Mais on ne
contrôlerait ni le nombre de distracteurs, ni leur position, ni leur
recouvrement — donc on ne pourrait pas répondre à **« à partir de combien de
feuilles ça casse »**, qui est la seule question réellement intéressante.

Et surtout, l'argument décisif : **le masque UV ne couvre que la feuille
cible**. Les parasites sont masqués pendant la passe UV, si bien que la
vérité terrain du recadrage reste **exacte au pixel**, même avec trois
documents dans l'image.

Aucune photographie réelle ne permet ça. C'est ce qui rend le jeu mesurable
plutôt que seulement illustratif, et c'est le même raisonnement qui a fait
choisir des factures synthétiques au départ.

---

## 2. Les choix de mise en scène

**Derrière la cible, jamais devant ni au travers.** Le recul se fait **le
long de l'axe de vue**, d'une distance calculée sur l'encombrement réel de la
cible projeté sur cet axe — donc sans dépendre d'aucune convention
d'orientation. Vérifié hors Blender : les trois parasites se placent à 0,82
d'une cible dont le demi-encombrement vaut 0,36, soit une marge du double du
nécessaire, tout en gardant 75 % de sa taille apparente.

**Texturés avec d'autres pages de facture.** Une feuille blanche ne
tromperait personne. Pour qu'un détecteur se trompe de façon plausible il
faut le cas difficile : même gabarit, même police, même tableau. C'est aussi
le cas réel — on photographie une facture au milieu d'autres factures.

**Tirage déterministe.** La graine dérive du nom de la texture cible, donc
deux rendus du même jeu donnent les mêmes parasites. Sans ça, comparer deux
versions du prétraitement « sur le même jeu » ne voudrait rien dire.

**Le témoin est conservé.** `-Parasites 0` reproduit exactement le jeu
actuel. Sans point de comparaison, un score bas ne prouverait rien.

---

## 3. Comment le produire

```powershell
cd ..\doc3D-renderer

# 1. VÉRIFIER D'ABORD — une seule image, quelques minutes
.\render_variants.ps1 -FolderId variants_encombre -Parasites -1 -Verifier

# 2. Un lot d'essai — 20 images
.\render_variants.ps1 -FolderId variants_encombre -Parasites -1 -Nombre 20

# 3. Le jeu complet, les 25 pages
.\render_variants.ps1 -FolderId variants_encombre -Parasites -1
```

`-Nombre N` limite le rendu aux N premières pages. Le découpage en factures
vient du PDF source, donc un lot partiel peut couper une facture au milieu —
vérifié pour 20 : les pages 1 à 20 forment **exactement dix factures
complètes** de deux pages, et les deux dernières (21-23, 24-25) sont
simplement absentes. Aucune facture tronquée, le lot est directement
comparable au jeu propre sur ces dix-là.

`-Parasites -1` tire **3 à 6** feuilles par image ; un entier positif en
impose un nombre fixe, ce qui sert à mesurer la dégradation par palier
(`-Parasites 1`, `3`, `6`…).

La plage est montée de 1-3 à 3-6 après le premier rendu : avec un seul
parasite, la moitié des images ressemblaient encore au jeu propre et la
question « à partir de combien ça casse » n'avait pas de matière. Six est une
limite pratique — au-delà, les feuilles se recouvrent au point que le fond
redevient une texture uniforme de papier, et le problème cesse d'être
« choisir le bon rectangle ».

Les angles sont **répartis** autour de la cible, pas tirés indépendamment :
six tirages uniformes se seraient agglutinés d'un côté par pur hasard,
laissant le reste du champ vide. Vérifié sur six parasites — 342°, 46°,
115°, 182°, 261°, 321° — avec des reculs de 0,77 à 1,20 pour un
demi-encombrement de 0,36, et une taille apparente qui reste entre 67 et
76 % de la cible.

### Ce qu'il faut regarder sur l'image de vérification

**Les parasites sont visibles** dans `img/variants_encombre/`.

**Et le masque UV ne les contient pas** :

```powershell
python ..\MedicalRecord\src\eval_preprocess.py --batch variants_encombre
```

Si l'IoU s'effondre alors que le recadrage a l'air correct à l'œil, c'est que
les parasites ont fui dans le masque — la vérité terrain serait fausse, et
tous les chiffres qui en découlent avec elle. C'est exactement le type de
défaillance silencieuse que ce projet traque depuis le début.

### Le défaut le plus important : les rendus n'étaient pas reproductibles

Trouvé en cherchant à valider la vérité terrain, et il dépasse largement le
jeu à fonds encombrés.

`render_mesh_multipage.py` tire la **caméra**, la **carte HDR** et
l'**éclairage** du module `random` — sans jamais l'initialiser. Python le
sème sur l'entropie du système à l'import, donc **chaque lancement de Blender
produisait des vues différentes**, y compris pour la même page.

Sur un seul jeu, ça ne se voit pas : des vues aléatoires, c'est même ce qu'on
veut. Le problème apparaît dès qu'on compare deux jeux. « Les mêmes images,
seul le fond change » était **faux**.

C'est ce qu'a révélé le premier contrôle. Il comparait l'aire du masque de la
feuille cible entre le jeu propre et le jeu encombré, en supposant la vue
identique. Résultat : des écarts de **−41 % à +49 %**. Une fuite de parasites
dans le masque ne pourrait que l'**agrandir** — une variation dans les deux
sens ne s'explique que par une caméra différente.

**Correctif.** La graine est dérivée du nom de la page
(`random.seed(zlib.crc32(...))`) au début de `render_img`. Chaque page garde
une vue tirée au hasard, mais **toujours la même** — et deux jeux rendus
depuis les mêmes pages redeviennent comparables image par image.

> Les jeux rendus **avant** ce correctif ne sont pas appariés. Pour comparer
> proprement propre et encombré, il faut **re-rendre les deux** avec le code
> actuel. `variants_warped` inclus.

Et le contrôle de vérité terrain a été refait autrement : il ne compare plus
deux jeux mais examine **un seul masque**. La feuille cible étant un objet
unique, son masque est d'un seul tenant ; plusieurs taches séparées
signifient qu'autre chose a été rendu dans la passe UV. Ce contrôle-là ne
dépend d'aucune hypothèse d'appariement.

```powershell
python scripts\verifier_masque_uv.py --jeu variants_encombre
```

### Quatre autres défauts, trouvés aux essais précédents

**`ImportError: No module named 'distracteurs'`.** Blender lance le script
avec `--python`, ce qui ne met **pas** son dossier sur `sys.path` — un
comportement propre à Blender, puisqu'en Python normal le dossier courant y
serait. Corrigé par un `sys.path.insert` en tête de
`render_mesh_multipage.py`.

**Le tirage n'était pas reproductible entre deux lancements.** La graine
dérivait de `hash()` sur le nom de fichier, or `hash()` d'une chaîne est
**salé par processus** depuis Python 3.3. Deux rendus du même jeu auraient
donné des parasites différents — et comparer deux versions du prétraitement
« sur le même jeu » n'aurait plus rien voulu dire, sans qu'aucune erreur ne
le signale. Remplacé par `zlib.crc32`, vérifié avec trois `PYTHONHASHSEED`
différents.

**Les parasites traversaient la facture.** Ils étaient posés 0,012 plus bas
en Z. Deux raisons, et la seconde est la vraie : le maillage est courbé —
0,150 d'amplitude — donc 0,012 est douze fois trop petit, mais surtout l'axe
« épaisseur » dépend de la convention d'orientation appliquée à l'import de
l'OBJ. Deviner lequel de X, Y ou Z est le bon marchait par hasard ou pas du
tout. D'où le recul le long de l'axe de vue, où l'intersection devient
impossible par construction.

**Et ils sortaient d'un blanc uniforme.** `primitive_plane_add` ne crée pas
forcément de couche UV en 2.79 ; sans elle, la sortie UV du nœud TexCoord
vaut (0,0,0) et **toute la surface échantillonne un seul texel** — la marge
blanche de la facture, en l'occurrence. La texture était pourtant bien
chargée : rien ne signalait le problème. Remplacé par les coordonnées
**générées**, qui mappent la boîte englobante sans dépendre d'aucune couche
UV. Un avertissement est désormais imprimé si une texture ne se charge pas,
parce qu'un parasite blanc passe inaperçu à l'œil et fausse tout le jeu.

> **Le rendu complet reste à valider.** Blender n'est pas dans
> l'environnement de développement : l'ordre des passes est vérifié
> statiquement (image → masquage → UV → WC) et le placement simulé avec un
> faux `bpy` doté d'une vraie algèbre vectorielle, mais seul un rendu réel
> prouvera que les parasites portent bien leur texte et que le masque UV les
> exclut.

---

## 4. Mesurer, ensuite

Trois branches, comme pour le reste du protocole :

```powershell
$IMG = "..\doc3D-renderer\img"
python scripts\bench_deformed.py --model chandra --images-dir "$IMG\variants_encombre" --output variants_encombre_chandra
python src\preprocess.py --images-dir "$IMG\variants_encombre" --out "$IMG\variants_encombre_preprocessed" --debug
python scripts\bench_deformed.py --model chandra --images-dir "$IMG\variants_encombre_preprocessed" --output variants_encombre_preproc_chandra
python scripts\eval_all.py --modele chandra
```

Les noms de runs sont à déclarer dans `MODELES`, en haut de
`scripts/eval_all.py`, sinon ils ne seront pas évalués — c'est délibéré.

Et `--debug` sur le prétraitement n'est pas optionnel ici : le rapport
avant/après montre **quel** quadrilatère a été retenu. C'est là qu'on verra
si le détecteur a choisi la bonne feuille, ce qu'aucun chiffre agrégé ne
dira.

---

## 5. Résultats (6 août) — la prédiction se réalise, et au-delà

**La vérité terrain est saine.** Les 20 masques UV sont d'un seul tenant :
les parasites sont bien exclus de la passe UV. Ce qui suit est donc un vrai
résultat, pas un artefact de rendu.

![Fonds encombrés](../demo/figures/09-fonds-encombres.png)

| | plafond | obtenu | recadrages | IoU ≥ 0,7 | plafond ≥ 0,7 |
|---|---|---|---|---|---|
| fond propre (25 pages) | 0,86 | **0,84** | 25/25 | **22/25** | 24/25 |
| fond encombré (20 pages) | 0,51 | **0,37** | 15/20 | **0/20** | **0/20** |

### Ce que ces chiffres disent vraiment

**Le plafond s'effondre aussi.** C'est le point décisif, et il va plus loin
que la prédiction. Le plafond est le meilleur IoU atteignable sur
*l'ensemble* des segmentations candidates, avant même de choisir. Il passe de
0,86 à 0,51.

Sur le jeu encombré, l'écart entre le plafond (0,51) et ce que le sélecteur
retient (0,49 sur les 15 pages recadrées) est de **0,02**. Autrement dit :
**le sélecteur fait déjà presque le meilleur choix possible**. Ce ne sont pas
les critères de décision qui échouent, ce sont les segmentations elles-mêmes.
Aucun réglage de `_document_score`, aucun seuil, aucune pondération ne
rattraperait ça.

**Et pas une seule page n'est récupérable.** Zéro sur vingt ont un plafond
≥ 0,7, contre 24/25 sur fond propre. Même un sélecteur parfait, omniscient,
ne produirait aucun recadrage exploitable.

**Le détecteur refuse de recadrer 5 fois sur 20**, et c'est le bon réflexe :
sous le seuil de confiance, il rend l'image brute plutôt qu'un recadrage
douteux. Ces cinq-là comptent 0,00 dans la moyenne, ce qui explique l'écart
entre 0,37 et les 0,49 des pages effectivement recadrées.

### Ce que ça implique

Le seuillage et les contours, qui suffisaient sur un fond uni, **ne peuvent
pas isoler une feuille au milieu d'autres feuilles**. C'est logique après
coup : ces indices reposent sur « la grande zone claire au milieu d'un fond
différent », et un bureau couvert de papiers n'a plus de fond différent.

La voie qui reste est une **segmentation apprise** — un modèle entraîné à
reconnaître *un document*, pas *une zone claire*. C'est exactement la
conclusion que le texte d'aide de `eval_preprocess.py` annonçait comme
lecture d'un plafond bas, écrit bien avant ce jeu de test.

### Réserve de méthode

Les deux jeux ont été rendus **avant** le correctif de graine, donc avec des
caméras différentes : la comparaison vaut au niveau du jeu, pas image par
image. Vingt-cinq contre vingt vues tirées de la même distribution, un écart
de 0,47 sur l'IoU obtenu — l'ordre de grandeur ne laisse guère de place au
hasard des cadrages, mais un re-rendu apparié le confirmerait proprement.

### Le jeu encombré n'a que vingt pages, et pas les vingt premières

`generate_multipage_tex_csv.py` trie les textures par **nom**. L'ordre est
donc `page_1, page_10..page_19, page_2, page_20..page_25, page_3, page_4`,
puis `page_5..page_9` en toute fin. Un `-Nombre 20` ne rend pas les pages 1 à
20 : il rend les vingt premières de *cette* liste, et laisse tomber les pages
5 à 9.

Conséquence sur le découpage en factures :

| facture | pages | état |
|---|---|---|
| 1, 2, 6 → 12 | — | complètes |
| 3 (5-6), 4 (7-8) | — | absentes, sans conséquence |
| **5** (9-10) | page 9 manquante | **amputée** |

Les deux factures absentes ne coûtent rien : ce qui n'est pas mesuré n'est
pas noté. La facture 5, elle, est le cas nuisible — elle *est* évaluée, sur
sa seule page de continuation, et sort un score bas qu'on lirait volontiers
comme une faiblesse du modèle. Aucune erreur n'est levée, c'est précisément
ce qui la rend dangereuse.

Deux garde-fous ont été ajoutés. `render_variants.ps1` affiche désormais les
**numéros** de page rendus et la liste des absentes, et accepte `-Depuis`
pour compléter un rendu partiel. La cellule de détection du notebook Kaggle
accepte 20 pages mais imprime en clair quelle facture est amputée.

Pour compléter le jeu, depuis `doc3D-renderer` :

```powershell
.\render_variants.ps1 -FolderId variants_encombre -Parasites -1 -Depuis 20 -Nombre 5
```

---

## 6. Prédictions, écrites avant mesure

Comme pour Chandra et GLM-OCR, on consigne avant de mesurer.

**Le recadrage va chuter, plus que le TEDS.** La détection de feuille est le
maillon exposé ; la lecture du tableau, une fois la bonne feuille recadrée,
ne devrait pas souffrir. On s'attend donc à voir l'IoU baisser franchement
alors que le TEDS de la branche **brute** reste stable — celle-ci ne dépend
pas du recadrage.

**Le prétraitement devrait passer de bénéfique à nuisible.** Il apporte
+0,050 à Chandra sur nos fonds propres. Sur un fond encombré, recadrer la
mauvaise feuille ne dégrade pas la lecture : elle la rend **absurde**. Si
cette prédiction se vérifie, l'écart entre « avec », « sans » et
« adaptatif » sera le plus large jamais mesuré sur ce projet.

**Et c'est là que la politique adaptative se joue.** Elle note une lecture
par la cohérence arithmétique du tableau extrait. Une feuille parasite bien
recadrée donnerait un tableau *cohérent* — celui d'une autre facture. La
confiance ne le verrait pas.

Si cette dernière prédiction se réalise, il faudra un signal de confiance sur
le **recadrage lui-même**, et pas seulement sur le tableau. Ce serait le
résultat le plus important du jeu : une limite de la méthode actuelle,
identifiée par une expérience conçue pour la chercher.

Voir [avec_sans_pretraitement.md](avec_sans_pretraitement.md) pour les
chiffres de référence sur fonds propres.
