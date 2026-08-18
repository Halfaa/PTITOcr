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

---

## 7. Résultats OCR (12 août) — Chandra sur les 25 pages encombrées

Runs `variants_encombre_chandra` et `variants_encombre_preproc_chandra`,
protocole `scripts/eval_all.py`, mêmes 12 factures et même vérité terrain que
le jeu propre.

| | brut | prétraité | adaptatif | *rappel : jeu propre* |
|---|---|---|---|---|
| TEDS (avec fusion) | **0,604** | 0,313 | — | 0,944 / 0,906 |
| TEDS-Struct | 0,714 | 0,410 | — | 0,983 |
| TEDS par facture (`eval_adaptive`) | 0,261 | 0,167 | **0,257** | 0,944 / 0,906 / 0,977 |
| plafond adaptatif | | | 0,358 | 0,977 |
| champs d'en-tête | **62 %** | 15 % | 62 % | 96 % |
| fusion P / R | 67 / 46 % | 80 / 44 % | | 100 / 100 % |

Les deux lignes TEDS ne mesurent pas la même chose : `eval_teds` note le
tableau extrait, `eval_adaptive` note le tableau *analysé en facture*, plus
exigeant. Les comparer entre elles n'a pas de sens ; comparer chaque ligne
d'une colonne à l'autre, si.

### La prédiction se vérifie, y compris la plus inquiétante

Les trois issues envisagées au §6 se produisent, sur des pages différentes.

**La lecture brute tient à peu près, la prétraitée s'effondre.** 0,604 contre
0,313, et surtout 62 % contre **15 %** sur les champs d'en-tête. Sur un fond
encombré, le prétraitement ne dégrade pas la lecture : il la fait porter sur
autre chose.

**Deux pages font emballer le modèle.** Sur la facture 3, Chandra rend un
tableau d'une ligne et **2 470 colonnes** — 2 473 nœuds pour 212 attendus. Il
n'a pas mal lu, il a bouclé jusqu'à la limite de génération. C'est un mode
d'échec distinct, qu'aucun OCR meilleur ne corrige : il appelle un garde-fou
en sortie, qui refuse un tableau hors d'échelle au lieu de le transmettre.

**Et le pire cas est là.** Facture 4, lecture prétraitée : 11 lignes sur 11
arithmétiquement équilibrées, aucun trou de numérotation, **confiance 0,75** —
et 2 médicaments sur 21 en commun avec la vérité terrain. TEDS 0,000. La
validation arithmétique note la *cohérence* d'un tableau, jamais sa
*provenance* : une facture voisine bien recadrée boucle tout aussi bien que la
bonne.

### Conséquence sur la politique adaptative

Elle choisissait la lecture prétraitée en cas d'égalité de confiance, réglage
qui valait +0,010 TEDS quand il a été posé. Remesuré :

| jeu | départage « prétraité » | départage « brut » |
|---|---|---|
| multipage | 0,966 | **0,967** *(= plafond)* |
| variants_warped | 0,977 | 0,977 *(= plafond)* |
| variants_encombre | 0,154 | **0,257** |

Le départage vers la lecture brute n'est jamais moins bon et évite
l'effondrement : `adaptive.choose` a donc `prefer_table="raw"` par défaut.
L'asymétrie est structurelle — une lecture brute peut lire *mal*, elle ne peut
pas lire *ailleurs*.

Cela ne règle pas le fond. Le plafond adaptatif est à 0,358 : même un
sélecteur parfait resterait très bas, parce que les deux candidats sont
mauvais. Il faudrait un signal de confiance sur le **recadrage**, pas sur le
tableau.

### Trois défauts trouvés en produisant ces chiffres

**TEDS pouvait être négatif.** −0,011 sur la facture 3. La formule de
PubTabNet normalise par `max(n_pred, n_vrai)`, mais la distance d'édition peut
dépasser ce maximum quand les deux grilles n'ont rien de commun : l'appariement
doit respecter l'ordre et la filiation, donc renommer devient impossible et il
faut tout supprimer puis tout réinsérer. Une similarité négative tire la
moyenne sous son minimum atteignable. Plancher à 0 dans `src/teds.py`.

**L'évaluation se figeait sans rien dire.** APTED est cubique ; sur l'arbre à
2 473 nœuds il ne rendait jamais la main, et comme `eval_all.py` capture la
sortie, le récapitulatif restait vide *sans message*. Deux garde-fous :
`src/teds.py` déclare dégénérée toute prédiction plus de 4× plus grosse que la
vérité — c'est une borne démontrable, `TEDS ≤ 1/rapport`, donc arrondir 0,25 à
0 ne change aucune conclusion — et `eval_all.py` abandonne une évaluation qui
dépasse dix minutes en le signalant.

**Un recadrage sur dix sort couché.** `_order_corners` ordonne les coins dans
le repère de l'*image* : pour une feuille posée de travers, le coin de plus
petite somme x+y n'est pas celui du *document*, et l'homographie rend une page
bien mise à plat mais tournée d'un quart de tour. Le quadrilatère est bon, la
mise à plat est bonne — **l'IoU ne peut donc pas le voir**, il ne compare que
des surfaces. Mesuré : 10 recadrages sur 25 ici, et **3 sur 25 dans le jeu
propre dont les chiffres sont publiés**. Ce n'est pas un effet du désordre,
c'était seulement assez rare pour passer inaperçu.

Non corrigé, délibérément : savoir que le texte est vertical ne dit pas dans
quel sens tourner, et l'heuristique classique du demi-tour (l'encre penche vers
le haut de la ligne) ne classe correctement que 21 pages témoins sur 25.
Tourner à l'aveugle mettrait une page sur six la tête en bas. `preprocess.py`
signale donc `texte_vertical` au lieu de parier.

### Ce qu'il faut retenir pour la réunion

Le fond encombré ne casse pas l'OCR — il casse la **localisation**, et tout ce
qui en dépend. Trois briques manquent, et ce sont trois briques *apprises* :

1. une segmentation de document (le plafond de recadrage est à 0,51) ;
2. un classifieur d'orientation (ambiguïté à 180°, insoluble par heuristique) ;
3. un signal de confiance sur le recadrage, pas seulement sur le tableau.

Voir [avec_sans_pretraitement.md](avec_sans_pretraitement.md) pour les
chiffres sur fonds propres.

---

## 8. Sonde de plafond (12 août) — SAM ne sauve pas le recadrage

`scripts/sonde_plafond.py`. Le 0,51 mesuré au §5 est une propriété du
**générateur de candidats**, pas du problème : changer de générateur change le
plafond, mieux choisir parmi les mêmes candidats ne le change pas. D'où cette
sonde, avant d'engager deux semaines sur une segmentation apprise.

| jeu | générateur | plafond | obtenu | +centralité | exploitables |
|---|---|---|---|---|---|
| encombré | actuel | 0,52 | 0,45 | 0,45 | 0/25 |
| encombré | SAM | 0,46 | 0,35 | 0,41 | 1/25 |
| encombré | actuel+SAM | **0,59** | 0,41 | 0,47 | 1/25 |
| propre | actuel | **0,87** | 0,81 | 0,83 | 22/25 |
| propre | SAM | 0,64 | 0,58 | 0,61 | 11/25 |
| propre | actuel+SAM | 0,86 | 0,67 | 0,72 | 15/25 |

FastSAM-s, image pleine résolution ramenée à 1024 px, seuillages inchangés à
480 px.

**La sélection n'est pas le maillon faible.** L'écart plafond − obtenu vaut
0,07 des deux côtés, sur un jeu où tout marche comme sur un jeu où rien ne
marche. Le tri prend presque toujours le meilleur candidat disponible ; c'est
le vivier qui s'effondre. Deuxième confirmation, par une voie indépendante de
celle du §5.

**SAM n'y change rien.** +0,07 de plafond sur l'encombré, pour un seuil
d'exploitabilité à 0,70 jamais atteint. Et sur le jeu propre il **dégrade** :
22 pages exploitables deviennent 15. Il n'entrera donc pas en production.

**Ce n'est pas une affaire de granularité**, contrairement à ce qu'on pouvait
craindre en voyant SAM faire moins bien à 1024 px qu'à 480. Le diagnostic de
couverture — aire du meilleur masque rapportée à l'aire réelle de la feuille —
donne, sur 173 masques par image :

| groupe | pages | IoU moyen |
|---|---|---|
| morceaux (<50 %) | 7 | 0,07 |
| bonne taille (50–100 %) | 12 | 0,62 |
| trop gros (>100 %) | 6 | 0,59 |

Les trois modes coexistent. Et surtout, **même là où le masque a la bonne
taille, l'IoU plafonne à 0,62** : SAM ne se contente pas de mal découper, il ne
désigne pas la bonne feuille. Avec 173 candidats par image, si la feuille
était proprement segmentée, l'un d'eux dépasserait 0,90.

### Un piège de méthode, rencontré ici

La première version du diagnostic comparait la couverture **moyenne** (69 %) à
un seuil unique et concluait « les masques ont la bonne taille ». Faux : cette
moyenne mélangeait 7 pages à 15 % et 6 pages à 130 %, deux échecs opposés qui
s'annulent. Une statistique de position ne veut rien dire sur une distribution
bimodale. Le script compte désormais les groupes.

### Le témoin qui manquait : 0,70 est-il seulement atteignable ?

Contrôle jamais fait, et il aurait dû l'être en premier. Tous les générateurs
rendent un `minAreaRect`, un **rectangle tourné**. Or une feuille photographiée
de biais et gondolée n'est pas un rectangle : le meilleur rectangle qui
l'englobe garde forcément du fond à l'intérieur. Comparer nos scores à 0,70
n'a donc de sens que si 0,70 est dans le domaine du possible.

`--oracle` donne au scoring le contour **exact** de la feuille, pris dans la
vérité terrain. Il triche par construction ; il ne mesure pas une détection,
il mesure le plafond de la **représentation**.

| jeu | plafond ORACLE | notre plafond | écart | obtenu |
|---|---|---|---|---|
| propre | 0,86 | **0,86** | **0,00** | 0,83 |
| encombré | 0,85 | 0,52 | **0,33** | 0,45 |

Les deux lignes se répondent, et chacune dit une chose différente.

**Sur le jeu propre, notre générateur atteint EXACTEMENT le plafond de forme.**
0,86 contre 0,86 : aucun générateur, appris ou non, ne peut proposer un meilleur
rectangle sur ce jeu. C'est un résultat plus fort que ce qu'on avait écrit
jusqu'ici — le module de prétraitement n'est pas « bon », il est **optimal pour
la représentation qu'on lui a donnée**. Tout ce qui reste (0,86 → 0,83) est de
la sélection, et la prime de centralité en récupère la moitié.

**Sur le jeu encombré, l'écart de 0,33 est une pure perte de détection.** Ni la
forme du candidat, ni la métrique, ni le jeu de test — trois explications
commodes désormais écartées. Cela valide de poursuivre sur la détection, et
notamment sur le front-end de texte, seule piste dont on sait qu'elle a été
mal alimentée plutôt que réfutée.

**Et le 0,86 lui-même est une limite qu'on s'impose.** Il ne vient pas des
images mais du `minAreaRect` : une feuille gondolée vue de biais n'est pas un
rectangle. Passer à un quadrilatère libre, ou à la mise à plat par courbes que
`curved_flatten` sait déjà faire, rendrait ces 0,14 sur les deux jeux. À
relativiser cependant : sur fond propre la chaîne sort déjà 0,977 de TEDS en
adaptatif, donc ces 0,14 d'IoU n'ont presque plus de valeur en lecture. C'est
une réserve pour le jour où le recadrage sera le facteur limitant.

### La prime de centralité : retenue par la sonde, rejetée par la chaîne

Épisode instructif, gardé ici parce que l'erreur est facile à refaire.

L'idée tenait debout : on photographie ce qu'on vise, donc la bonne feuille
est la plus centrée — et c'est le seul indice qui ne suppose pas un fond
différent du papier. La sonde lui donnait +0,016 d'IoU sur le jeu propre et
0,000 sur l'encombré : jamais négative, on l'a donc activée en production.

Mesurée ensuite sur la **chaîne complète**, verdict inverse :

| jeu | sans prime | avec prime |
|---|---|---|
| propre | 0,84 | 0,84 |
| encombré | **0,40** | 0,32 *(recadrages 20/25 → 15/25)* |

La cause est une interaction que la sonde ne pouvait pas voir. La prime est
**multiplicative**, et `detect_document_quad` compare le score à un seuil
**absolu** (`min_score`). Elle ne se contente donc pas de réordonner les
candidats : elle les fait passer sous le seuil, et la chaîne renonce à
recadrer. Sur le jeu encombré elle a rejeté cinq pages, dont les pages 5 et
24 qui sortaient à 0,63 — **les deux meilleurs recadrages du jeu**.

Deux leçons. La première est générale : une pondération censée exprimer une
*préférence* entre candidats devient un critère d'*admission* dès qu'elle
multiplie un score comparé à un seuil. La seconde porte sur la méthode : la
sonde mesure un sous-ensemble de la chaîne, et un gain qu'elle annonce doit
être confirmé par `eval_preprocess`, jamais publié sur sa seule foi. D'où
l'option `--sans-centralite`, qui permet l'A/B à jeu constant.

La prime est retirée de la production. `_prime_centralite` reste dans le
code, pour la sonde et pour cette note.

### Bilan des générateurs : la voie non apprise est épuisée

| générateur | plafond, jeu encombré |
|---|---|
| seuillages + GrabCut (actuel) | 0,52 |
| SAM / FastSAM | 0,46 – 0,56 |
| blocs de texte, morphologie | 0,33 |
| blocs de texte, DBNet appris | 0,43 |
| **toutes unions confondues** | **0,59** |
| *témoin ORACLE* | *0,85* |

Quatre familles d'indices indépendantes — photométrie, segmentation générique
d'objets, morphologie de texte, détection de texte apprise — butent toutes
entre 0,33 et 0,59 quand 0,85 est atteignable. Ce n'est plus une série de
maladresses, c'est une limite de la classe de méthodes.

**La segmentation apprise sur nos masques UV n'est donc plus un pari, c'est la
conclusion.** Et elle arrive avec trois choses qu'on n'avait pas au début de
la journée : la certitude que 0,85 est atteignable, la preuve que l'écart est
bien de la détection, et des étiquettes au pixel près, gratuites et en
quantité illimitée.

### Ce que la sonde a tranché, et ce qu'elle n'a pas tranché

Tranché : **une segmentation générique n'est pas la réponse.** SAM est
entraîné à découper des objets du monde ; une feuille posée sur d'autres
feuilles n'en est pas un pour lui.

Non tranché : un modèle entraîné **spécifiquement** sur nos masques UV. L'échec
de SAM ne prouve pas qu'il échouerait — il montre seulement que la compétence
ne se transfère pas gratuitement. L'argument des étiquettes gratuites au pixel
près tient toujours, mais on sait maintenant que la tâche est réellement
difficile sur ce type de scène, ce qui change le pari.

Reste aussi une réserve inscrite au §7 : nos rendus **n'ont pas de profondeur
de champ**. Sur une vraie photo, les feuilles du fond seraient floues — indice
très discriminant que ce jeu ne fournit pas, et que SAM comme un modèle
entraîné exploiteraient. Notre scène est donc plus dure que la réalité.

---

## 9. La réponse : un signal de provenance, et il était gratuit (12 août)

Le problème reformulé n'est pas « trouver la feuille », c'est « **ne jamais
lire un autre document sans le savoir** ». Sous cette forme, la solution
n'exige aucun entraînement : le signal de provenance manquant existe déjà
dans la chaîne.

**L'asymétrie qui rend le test possible.** La lecture brute voit la scène
entière — la facture cible est *forcément* dans son champ, et son tableau
principal (le plus grand) est presque toujours le bon. La lecture prétraitée,
elle, peut porter sur n'importe quelle feuille. Si leurs contenus ne se
recoupent pas, c'est le recadrage qui est parti ailleurs.

`adaptive.concordance()` compare donc les **noms de médicaments** des deux
lectures (similarité tolérante, SequenceMatcher ≥ 0,7, parce que le même nom
lu deux fois porte des dégâts OCR différents — et les noms plutôt que les
nombres, parce que deux factures de la même pharmacie partagent des prix
ronds, presque jamais leurs listes de produits). Sous 30 % de lignes communes,
la lecture prétraitée est écartée avant même l'arbitrage par confiance.

Mesuré sur les fusions du jeu encombré :

| facture | concordance | verdict |
|---|---|---|
| 4 (le pire cas du §7) | — | prétraitée **écartée**, TEDS 0,000 → 0,762 |
| 3, 12 | — | prétraitée **écartée**, +0,306 et +0,163 |
| 7 | élevée | conservée — et elle est réellement meilleure (0,276 contre 0,158) |
| 5 | 0,92 | même document, lecture prétraitée fidèle |
| 2 | 0,75 | même document — échec *structurel*, hors périmètre du test |
| jeux propres | 0,56–0,92 | jamais déclenché : multipage 0,967 et diversifié 0,977, inchangés |

**Ce que le garde change vraiment.** Sur ce jeu, le départage `prefer="raw"`
attrapait déjà les factures 3, 4 et 12 — mais par chance : leurs confiances
étaient à égalité (0,75 contre 0,75 pour la facture 4), et l'égalité se
départage vers le brut. Qu'une seule ligne parasite de plus fasse monter la
confiance prétraitée à 0,76, et le tableau étranger passait. Le garde rend ce
cas **impossible par construction**, quelle que soit la confiance : c'est la
différence entre un accident évité et un accident impossible.

**Ce qu'il ne couvre pas, dit clairement.** La facture 2 lit le bon document
mais le structure si mal que son TEDS est nul, avec une confiance pourtant
supérieure au brut. C'est un échec de *cohérence structurelle*, pas de
*provenance* — un autre garde-fou (tableau hors d'échelle, déjà présent dans
`teds.py` côté évaluation) devra exister côté production.

### Les trois étages de la réponse, du plus sûr au plus ambitieux

1. **Provenance par concordance** — fait, mesuré, en production dans
   `adaptive.choose()`. Coût : zéro inférence de plus.
2. **Segmentation par le texte, pas par le papier** — implémentée, pas encore
   concluante. `candidats_texte()` dans `scripts/sonde_plafond.py`, option
   `--texte`.

   L'idée : un document est un *bloc de texte cohérent*, pas une zone claire.
   Deux mots appartiennent à la même feuille s'ils sont proches, de même
   corps et de **même inclinaison** — ce dernier critère est le discriminant
   fort, puisque chaque feuille posée sur le bureau a sa propre rotation là
   où sa luminance est identique à celle des voisines. Graphe de voisinage,
   composantes connexes, une enveloppe convexe par bloc.

   Le regroupement fait son travail — 1 à 3 blocs par image, là où sont les
   feuilles. **C'est la détection des mots qui ne suit pas** : le front-end
   morphologique (gradient + Otsu + fermeture) trouve 26 à 138 mots par page
   quand une facture en contient plus de trois cents, et sur deux pages sur
   dix il n'en trouve pas assez pour former le moindre bloc. L'idée n'est
   pas invalidée, elle est mal alimentée.

   Deux réglages mesurés au passage, contre-intuitifs tous les deux. La
   détection doit tourner à **1400 px et non aux 480 px de travail** — à 480,
   sur une scène encombrée où la feuille cible n'occupe qu'un quart du cadre,
   un caractère fait deux pixels et il ne reste que 5 mots par page. Et le
   noyau de fermeture doit rester **petit** : k=5 rend 138 mots, k=27 en rend
   63, parce qu'élargir ne recolle pas mieux les mots, ça fusionne des
   colonnes entières du tableau.

   Testée avec les deux front-ends, morphologique et appris (`--dbnet`,
   détecteur DBNet de PaddleOCR). Le verdict ne bouge pas :

   | front-end de détection des mots | plafond seul | plafond en union |
   |---|---|---|
   | morphologie | 0,33 | 0,54 |
   | DBNet, coordonnées faussées | 0,37 | 0,53 |
   | DBNet, coordonnées correctes | **0,43** | **0,54** |

   Le détecteur appris fait bien mieux que la morphologie *seul* (0,43 contre
   0,33), ce qui confirme que le front-end était le maillon faible. Mais
   **l'union ne bouge pas** : les blocs de texte n'apportent pas de candidat
   que les seuillages n'avaient pas déjà. La piste est donc close.

   **Un piège rencontré en chemin, et qui déborde de cette piste.** Par
   défaut, `PaddleOCR()` fait tourner en amont un classifieur d'orientation
   (`PP-LCNet_x1_0_doc_ori`) **et un dewarping (`UVDoc`)**. La détection se
   fait donc sur une image redressée, et les polygones rendus sont dans le
   repère de *cette* image — pas dans le nôtre. On récupère des boîtes
   parfaitement valides, simplement au mauvais endroit, et rien ne le signale.
   Il faut passer `use_doc_orientation_classify=False` et
   `use_doc_unwarping=False`.
3. **Segmentation apprise sur nos masques UV.** Le pari à deux semaines,
   désormais éclairé : l'échec de SAM montre que la compétence ne se
   transfère pas, pas qu'elle ne s'apprend pas — un modèle entraîné sur nos
   rendus apprendrait précisément ce que SAM n'a pas, la *définition de la
   cible* (la feuille centrée dominante). À décider avec l'encadrante.
