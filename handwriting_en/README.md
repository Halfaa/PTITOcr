# Générateur de manuscrit synthétique (anglais) — Periodic Health Examination Record

Même architecture que `handwriting/` (page 9 PHCN, vietnamien), appliquée au
formulaire `health record_en.docx` fourni par Halfaa. Trois couches
indépendantes, comme prévu dans le README précédent : **police**,
**gabarit LaTeX**, **vocabulaire** — seules les deux premières changent ici.

**Périmètre : les deux premières pages exactement**, telles que Halfaa les a
recopiées intégralement pour corriger une première version qui mélangeait par
erreur des champs des pages 1-2 avec l'examen physique et la conclusion (des
pages bien plus loin dans le document). Couvert désormais : en-tête national,
bloc photo + identité (items 1-6), note sur la CCCD à puce, emploi (7-9),
emplois précédents (10, a/b), antécédents familiaux (11), tableau
antécédents personnels/maladies professionnelles (12, a-d), bloc de
signature de confirmation. La suite (I. MEDICAL HISTORY, II. PHYSICAL
EXAMINATION...) commence à la page 3 et n'est pas couverte par ce générateur.

## Installation (Windows)

Même prérequis que `handwriting/` : MiKTeX (pour `xelatex`, PATH à jour après
installation, "Install missing packages on-the-fly" activé dans MiKTeX
Console) et `pip install pymupdf` (rendu PDF → PNG, pas de poppler à
installer séparément). Détail complet : `../handwriting/README.md`.

Aucune police système à installer : Liberation Serif (texte imprimé) et les
7 polices manuscrites (voir ci-dessous) sont toutes embarquées dans `fonts/`
et chargées par chemin — voir `../handwriting/README.md`, section « Un bug
de moins (2) », pour l'échec intermittent que ça corrige sous Windows/MiKTeX.

```powershell
python generate_en.py --n 5                  # un style manuscrit au hasard par specimen
python generate_en.py --n 5 --police caveat   # un seul style pour tout le lot
python generate_en.py --lister-polices        # voir les styles disponibles
python generate_en.py --n 1 --seed 0 --police alex_brush --garder-tex
```

Chaque specimen n'utilise qu'**un seul** style manuscrit (cohérent avec
l'idée qu'un formulaire est rempli à la main par une seule personne) ; le
style choisi est enregistré dans `..._verite.json` (clé `"police"`) pour
pouvoir filtrer ou analyser les résultats par style ensuite.

## Polices manuscrites : 7 styles, pour tester la robustesse

Halfaa a suggéré [Brittany Signature](https://www.dafont.com/brittany-signature.font)
(dafont) pour un rendu plus proche d'une vraie signature que Caveat (une
écriture scolaire nette). Licence vérifiée avant tout essai : **usage
personnel uniquement, usage commercial interdit** sans achat d'une licence
« Corporate ». Incompatible avec la pratique du projet — toutes les polices
utilisées jusqu'ici sont en OFL, librement embarquables sans restriction.

Plutôt qu'une seule police de remplacement, le générateur propose maintenant
**7 styles manuscrits différents** (`--lister-polices` pour la liste), pour
pouvoir tester un modèle de lecture sur plusieurs écritures et pas seulement
sur celle qu'il connaît le mieux. Tous vérifiés sur le binaire (couverture
ASCII complète : lettres, chiffres, ponctuation) avant d'être retenus, sur
une douzaine de candidats comparés visuellement :

| clé | police | registre |
|---|---|---|
| `caveat` | Caveat | écriture scolaire nette, cursive légère (l'ancien défaut) |
| `alex_brush` | Alex Brush | script fluide, proche d'une signature |
| `sacramento` | Sacramento | script fin et élégant |
| `patrick_hand` | Patrick Hand | impression à la main, propre et ronde |
| `shadows_into_light` | Shadows Into Light | écriture casual, trait épais |
| `reenie_beanie` | Reenie Beanie | griffonnage rapide, plus difficile à lire |
| `homemade_apple` | Homemade Apple | stylo-bille, irrégulier, très réaliste |

Écartés après comparaison visuelle (`Qwigley`, `Mrs Saint Delafield`,
`Herr Von Muellerhoff`, `Indie Flower`, `Architects Daughter`, `Gochi Hand`) :
soit trop proches d'un style déjà retenu, soit trop chargés en fioritures
pour rester lisibles comme texte de champ normal.

Licences : toutes OFL (`fonts/OFL-*.txt`) sauf **Homemade Apple**, en
**Apache License 2.0** (`fonts/APACHE2-HomemadeApple.txt`) — vérifié avant
inclusion (le fichier de licence de `@fontsource` ne dit pas "OFL" en tête,
contrairement aux six autres, donc lu en entier plutôt que supposé) ; Apache
2.0 reste une licence libre, y compris en usage commercial.

## Périmètre retenu

Le document complet fait 9 tableaux, dont une table de 32 à 37 lignes pour
l'examen par spécialité (cardio, respiratoire, ORL, dentaire...) — presque
entièrement des cases à cocher vides, et des sections (I. MEDICAL HISTORY,
II. PHYSICAL EXAMINATION, V. CONCLUSION) qui appartiennent à des pages
ultérieures. Ce générateur couvre exactement les deux premières pages :

- en-tête national (République socialiste du Vietnam, devise)
- bloc photo + identité, items 1 à 6 (nom, sexe, naissance, pièce d'identité,
  adresse, téléphone)
- note sur la CCCD à puce (dispense de ressaisie si déjà connectée à la
  base nationale de population)
- emploi actuel (7-9) et emplois précédents sur 10 ans (item 10, a/b —
  intitulé, durée, dates de début/fin)
- antécédents familiaux (11)
- tableau antécédents personnels / maladies professionnelles (item 12,
  4 lignes a-d, souvent partiellement vide — réaliste, la plupart des gens
  n'ont ni l'un ni l'autre)
- bloc de signature de confirmation (employé + personne ayant préparé le
  dossier)

Une première version avait mélangé par erreur des contenus d'examen physique
et de conclusion (pages bien plus loin dans le document) avec l'identité —
corrigé après que Halfaa a recopié texto le contenu réel des pages 1-2.
Extension naturelle si besoin : un second générateur pour la page 3 (examen
médical, constantes, classification), sur le même principe à trois couches.

## Vocabulaire

Ce formulaire porte surtout des données d'identité — pas de nomenclature
officielle à respecter pour un nom ou une adresse. Deux endroits restent
sourcés :

- item 12, colonne « Occupational disease name » : maladies professionnelles
  réellement indemnisées par l'assurance sociale vietnamienne (Thông tư
  15/2016/TT-BYT, remplacé depuis par le Thông tư 60/2025/TT-BYT) — silicose,
  bronchite, asthme et saturnisme professionnels y figurent explicitement
  (vérifié par recherche, pas inventé).
- la classification de santé (Type I à V, générateur précédent) vient du
  barème du Thông tư 14/2013/TT-BYT, traduite en anglais.

## Bug corrigé en cours de route

Le premier remplacement de jetons utilisait des mots nus (`HEIGHT`, `BMI`) :
`tex.replace("BMI", "27.9")` a remplacé **les deux** occurrences de « BMI »
dans `BMI: \hw{BMI}` — le libellé imprimé ET le jeton, produisant
« 27.9: 27.9 ». Idem pour `HEIGHT`/`WEIGHT`, dont le nom de champ ne
correspondait pas exactement à la clé du dictionnaire (`height_cm` vs
`HEIGHT`), laissant le jeton affiché tel quel. Corrigé en encadrant chaque
jeton de `@@...@@` (aucune collision possible avec du texte ordinaire) et en
ajoutant une vérification qui lève une erreur si un jeton survit — le même
bug se signalerait immédiatement au lieu de produire un rendu silencieusement
faux.

## Bug corrigé en cours de route (2) : les libellés imprimés en écriture manuscrite

Repéré par Halfaa sur un rendu réel : les titres de champs ("8. Workplace /
place of study", "Disease name", "Year detected"...) apparaissaient en
écriture manuscrite au lieu du texte imprimé normal. Cause : le gabarit
écrivait partout `\hw{@@TOKEN@@}` (accolade *après* la commande). Or `\hw`
n'est pas une macro à argument comme `\textbf{...}` — `\newfontfamily` en
fait une simple *déclaration* de police, comme `\bfseries`. `\hw{texte}`
exécute donc `\hw` (bascule vers Caveat pour tout le reste du groupe
englobant), puis ouvre un groupe séparé qui affiche juste "texte" sans rien
changer : la bascule de police **fuit vers tout ce qui suit**, jusqu'à la
prochaine vraie frontière de groupe (une cellule de tableau suivante,
typiquement) — d'où les libellés contaminés bien après le premier champ
manuscrit rencontré.

La syntaxe correcte est `{\hw texte}` (accolade *avant* la commande), qui
confine la bascule au groupe — c'est déjà ce que fait l'assistant Python
`hw()`, utilisé correctement dans le générateur vietnamien depuis le début.
Le bug ne touchait que ce générateur anglais, où le gabarit écrivait les
jetons `\hw{@@TOKEN@@}` en dur au lieu de passer par `hw()`. Corrigé par une
regex appliquée uniquement au corps du document (jamais au préambule, où
`\newfontfamily\hw{Caveat}[...]` a légitimement la forme `\hw{...}` et ne
doit pas être touché) : `\hw{X}` → `{\hw X}` partout dans le corps. Vérifié
visuellement après correction : tous les libellés sont redevenus imprimés,
seules les valeurs saisies restent manuscrites.
