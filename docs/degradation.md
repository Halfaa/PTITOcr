# Robustesse à la qualité d'image

**Question.** À partir de quelle qualité de photo la chaîne cesse-t-elle de
fonctionner ?

Aujourd'hui on n'en sait rien. Tous nos chiffres — 0,967 en adaptatif sur le
jeu multi-pages, 0,977 sur le diversifié — viennent de rendus Blender : mise
au point parfaite, éclairage maîtrisé, PNG sans perte. On sait que la chaîne
marche en laboratoire, et strictement rien de plus. C'est aussi, avant d'avoir
des photos réelles, le seul moyen de savoir si 0,97 est un chiffre robuste.

Le livrable n'est pas une note de plus, c'est une **spécification** : le point
de rupture de chaque dégradation dit ce qu'un contrôle qualité à la capture
doit refuser.

---

## 1. Le protocole

Base : les 8 pages des factures 1, 2, 6 et 7 du jeu `variants_warped`, donc
quatre factures **complètes** — le TEDS se calcule sur la facture
reconstituée, une page orpheline fausserait la mesure.

Les mêmes 8 pages à tous les paliers. La comparaison est donc **appariée** :
l'écart entre deux paliers ne peut pas venir d'un échantillon différent, ce
qui vaut beaucoup mieux, à effectif égal, que de tirer des pages au hasard à
chaque niveau.

24 lots au total — 1 référence + 23 paliers — soit 192 pages, environ 4 h 20
sur un T4. Lecture brute seulement : on mesure la robustesse de la **lecture**
à la qualité d'image. Doubler pour le prétraitement répondrait à une autre
question (la correction d'éclairage aggrave-t-elle le bruit ?) et mérite son
propre run, une fois connus les points de rupture.

### Les cinq dégradations

| | ce que ça simule | paliers |
|---|---|---|
| `flou` | bougé de la main pendant la pose | 3, 6, 9, 13, 20 px |
| `bruit` | montée en ISO en lumière faible | 500 → 8 photons à saturation |
| `exposition` | sous-exposition puis remontée | −2 à −6 diaphragmes |
| `resolution` | redimensionnement par une messagerie | 0,75 → 0,22 du côté long |
| `jpeg` | compression de l'appareil | qualité 25, 10, 3 |

### Trois choix physiques qui changent le résultat

**On travaille en lumière linéaire.** Un capteur intègre des photons, pas des
valeurs sRGB. Flouter ou bruiter directement les octets d'un PNG mélange des
grandeurs déjà passées par la gamma : le flou sort trop sombre et le bruit mal
réparti entre ombres et hautes lumières.

**Le bruit dépend du signal.** Bruit de grenaille (Poisson, donc plus fort là
où il y a de la lumière) plus bruit de lecture gaussien. Le réflexe habituel —
un bruit gaussien uniforme — épargne les blancs du papier, c'est-à-dire
précisément l'endroit où le bruit se voit.

**La sous-exposition détruit par la quantification.** Assombrir puis
ré-éclaircir est réversible à la virgule près ; ce qui ne l'est pas, c'est que
le capteur écrit 8 bits. On assombrit, on quantifie, on ajoute le bruit de
lecture, on ré-éclaircit. Mesuré : à −6 diaphragmes il ne reste que **32
niveaux de gris sur 256**.

---

## 2. Deux grilles, parce que la première était mal calibrée

La première échelle a été jetée après contrôle visuel
([figure 11](../demo/figures/11_paliers_degradation.png)). Deux défauts :

Le flou passait de lisible à illisible **entre deux paliers** — la rupture
n'était pas encadrée, donc la courbe n'aurait rien localisé.

Surtout, **à qualité JPEG 12 le texte restait parfaitement lisible.** Vérifié
ensuite en descendant plus bas : l'encodeur sature à 23,8 dB de PSNR, et entre
q=3 et q=1 plus rien ne bouge. Une page blanche à texte contrasté est
exactement ce que le JPEG compresse bien. Cinq paliers auraient donné une
courbe plate — 40 pages de GPU pour un non-résultat.

D'où deux corrections : le JPEG tombe à **trois** paliers, ce qui suffit à
établir que la compression seule n'est pas la menace ; et une cinquième
dégradation apparaît, la **résolution**, qui est ce qui tue réellement le
petit texte quand une photo transite par une messagerie.

La leçon vaut d'être notée : une échelle de dégradation se calibre en
regardant les images, pas en choisissant des nombres ronds.

---

## 3. Prédictions, écrites avant mesure

Comme pour Chandra et GLM-OCR, on consigne avant de mesurer.

**La résolution sera la plus brutale, et la rupture sera nette.** Un caractère
du corps du tableau fait environ 9 px de haut sur nos rendus. À 0,40 il en
reste 4, à 0,22 il en reste 2 — en dessous de 3 ou 4 px, aucun OCR ne lit quoi
que ce soit, et la chute devrait être une falaise plutôt qu'une pente.

**Le flou rompra vers 9–13 px.** L'ordre de grandeur qui compte est
l'épaisseur du trait, environ 2 px : un bougé de 9 px étale un trait sur
quatre fois sa largeur. À l'œil, le palier 3 est déjà à la limite.

**Le bruit sera mieux encaissé qu'il n'en a l'air.** Un VLM moderne est
entraîné sur des photographies réelles, souvent bruitées ; le bruit dégrade la
netteté mesurée mais laisse la structure du tableau intacte. On s'attend à ce
que le TEDS-Struct tienne bien après que le TEDS a chuté.

**La compression JPEG ne cassera rien**, sur toute l'échelle testée. Si cette
prédiction se vérifie, c'est un résultat utile en soi : il retire une
contrainte du cahier des charges de la capture.

**La sous-exposition tiendra plus longtemps qu'on ne le craint**, parce que la
correction d'éclairage du prétraitement... n'est justement pas dans la boucle
ici. En lecture brute, la rupture devrait arriver vers −5 diaphragmes, quand
il ne reste qu'une quarantaine de niveaux.

**Et la prédiction la plus intéressante, parce qu'elle est vérifiable
autrement :** les dégradations qui préservent la *structure* du tableau
(bruit, JPEG) devraient laisser un grand écart TEDS-Struct − TEDS, alors que
celles qui la détruisent (résolution, flou fort) devraient faire chuter les
deux ensemble. Si l'écart se comporte comme prévu, il devient un **indicateur
de la nature du problème**, exploitable sans vérité terrain.

---

## 4. Comment produire les chiffres

```powershell
# 1. Générer les 192 images (quelques minutes)
python scripts\degrader.py --jeu variants_warped

# Contrôler les paliers avant de dépenser du GPU
python scripts\degrader.py --jeu variants_warped --calibrer

# 2. L'archive Kaggle (252 Mo), puis Add Input -> Datasets, nom "degradation"
python scripts\degrader.py --jeu variants_warped --zip

# 3. Après le run : la courbe
python scripts\eval_degradation.py --figure
```

`--zip` plutôt que `Compress-Archive` : PowerShell 5.1 écrit les
sous-dossiers avec des antislashs et Kaggle refuse alors l'archive
(« contains a forbidden character in name »). C'est le premier zip du projet
à contenir des sous-dossiers.

Si le téléversement de 252 Mo est trop lent, `--pages 1,2,11,12` réduit à deux
factures : 96 images, moitié moins de GPU, et la courbe garde sa forme même si
chaque point devient plus bruité.

`eval_degradation.py` rend, pour chaque dégradation, le TEDS palier par palier
et le premier palier sous 0,70 — exprimé en **grandeur physique** (« le bougé
devient fatal au-delà de 9 px ») et non en numéro de palier, parce que c'est
la forme qui se transporte dans un cahier des charges.
