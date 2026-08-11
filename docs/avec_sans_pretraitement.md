# Avec ou sans prétraitement — ce que disent les mesures

Demande de l'encadrante en réunion du 6 août : *essayer sans prétraitement,
pour comparer*.

La réponse existe déjà. Chaque modèle a été mesuré sur les **mêmes pages**,
lues deux fois : image brute et image prétraitée. Ce document rassemble les
chiffres, et surtout ce qu'ils impliquent.

Reproduire :

```powershell
python scripts\eval_all.py --modele chandra --modele hunyuan --modele paddleocr
```

---

## 1. Le résultat en une ligne

**Le prétraitement n'est bon ni à garder ni à retirer. Il faut le choisir
page par page.**

| modèle | sans prétraitement | avec | adaptatif |
|---|---|---|---|
| HunyuanOCR-1.5 | **0,950** | 0,879 | 0,953 |
| PaddleOCR-VL | 0,909 | 0,951 | 0,951 |
| Chandra OCR 2 | 0,916 | **0,966** | 0,966 |

![Avec et sans prétraitement](../demo/figures/08-with-without-preprocessing.png)

Il aide PaddleOCR-VL (+0,042) et Chandra (+0,050). Il **dégrade** HunyuanOCR
(−0,071). Un même traitement, trois effets différents : il n'existe donc pas
de bonne réponse globale à la question « faut-il prétraiter ? ».

*Réserve à mentionner :* le run prétraité de HunyuanOCR date d'une version
antérieure du module (IoU 0,79 contre 0,90 aujourd'hui). Son chiffre est un
plancher, pas un verdict. Le rejouer avec le code actuel est une mesure à
faire.

---

## 2. Pourquoi ça se compense — et ce que la moyenne cache

Le prétraitement fait deux choses en même temps, et elles ne vont pas dans
le même sens.

**Il aplanit la page**, ce qui aide la lecture du tableau : sur les factures
déformées, la grille se reconstruit mieux.

**Il recadre**, et le recadrage mord parfois sur l'en-tête. Les champs
d'en-tête le paient :

| | sans | avec |
|---|---|---|
| Chandra, jeu diversifié déformé | **72/84** | 62/84 |
| PaddleOCR-VL, multi-pages | **43/56** | 30/56 |

C'est le même geste qui produit les deux effets. Aucun réglage n'a fait
disparaître le compromis — `--pad`, `--min-score` et le seuil de confiance
ont tous été balayés, sans exception mesurée.

**Et l'effet est binaire, pas graduel.** Sur les douze factures du jeu
diversifié déformé, le prétraitement fait :

- gagner franchement sur la facture 1 (0,829 → 0,965) : la page brute avait
  décroché, il la récupère ;
- s'effondrer sur les factures 9 et 12 (0,905 → 0,509 et 0,960 → 0,580) : le
  recadrage y a mordu.

Une moyenne de ces deux comportements ne décrit **aucune** page réelle. C'est
précisément ce qu'une comparaison « avec ou sans » ne peut pas montrer, et
c'est l'argument central en faveur de la politique adaptative.

---

## 3. Pourquoi l'adaptatif n'est pas un compromis mou

`src/adaptive.py` lit chaque page dans les deux variantes, note les deux
lectures **sans vérité terrain** — par la redondance arithmétique de la
facture — et garde la meilleure.

Sur les douze factures du jeu diversifié, que la politique n'avait jamais
vues :

| | TEDS | champs |
|---|---|---|
| brut seul | 0,906 | 42/48 |
| prétraité seul | 0,879 | 24/48 |
| **adaptatif** | **0,942** | **44/48** |
| *plafond (choix parfait, a posteriori)* | *0,945* | |

Elle **bat les deux variantes prises seules, sur les deux métriques**. Avec
Chandra elle atteint **0,977, soit exactement le plafond** : la règle de
décision ne perd plus rien du tout.

Le point qui rend ça défendable : la confiance calculée sans vérité terrain
**voit** les désastres. Sur les factures 9 et 12, elle donne 1,00 au brut
contre 0,75 au prétraité — et le TEDS réel confirme après coup.

---

## 4. Ce que ça coûte

Une seconde lecture par page, soit environ le double de temps de calcul.

`src/api.py` ne la paie pas systématiquement : il lit d'abord l'image brute,
**note le résultat**, et ne déclenche la seconde lecture que si ce score
doute (seuil 0,95). Sur les douze factures du jeu diversifié, la lecture
brute marquait déjà 1,00 de confiance sur cinq d'entre elles — exactement là
où le prétraitement n'apportait rien.

---

## 5. Ce que cette comparaison ne dit pas encore

Tous ces chiffres viennent de rendus Blender sur des fonds **unis** :
moquette, marbre, plan de travail. La détection de feuille y a la tâche
facile — un seul grand quadrilatère clair dans l'image.

Le jeu à **fonds encombrés** demandé en réunion attaque précisément cette
facilité. Avec d'autres documents autour de la feuille cible, le détecteur
aura plusieurs rectangles blancs candidats, et rien ne garantit qu'il
choisisse le bon.

**Prédiction, écrite avant mesure** : c'est là que le prétraitement devrait
le plus se dégrader, et donc là que l'écart entre « avec », « sans » et
« adaptatif » devrait être le plus large. Si la politique adaptative tient
sur ce jeu, c'est le résultat de généralisation le plus fort du stage. Si
elle ne tient pas, il faudra un signal de confiance sur le **recadrage
lui-même**, et pas seulement sur le tableau extrait.

Voir `docs/fonds_encombres.md`.
