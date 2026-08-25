# Générateur de manuscrit synthétique — page 9 (PHIẾU THỰC HIỆN KỸ THUẬT PHCN)

But : produire des specimens synthétiques de la page de suivi manuscrite du
formulaire 27/BV1, avec vérité terrain exacte, pour tester des modèles de
reconnaissance d'écriture manuscrite (HTR) vietnamienne.

## Installation (Windows)

Deux choses à installer avant `python generate.py`, en plus du dépôt lui-même :

1. **Une distribution LaTeX fournissant `xelatex`.** [MiKTeX](https://miktex.org/download)
   (installeur "Basic MiKTeX Installer") est le plus simple sous Windows.
   Après l'installation, **redémarrer PowerShell** pour que `xelatex` soit
   sur le PATH — sinon `FileNotFoundError: [WinError 2]`.

   Au premier lancement, MiKTeX va devoir installer quelques paquets
   (`fontspec`, `geometry`, `array`...). Par défaut il demande confirmation
   à chaque fois, ce qui bloque un script automatisé. Ouvrir **MiKTeX
   Console** → Settings → *"Install missing packages on-the-fly"* → **Yes**,
   avant de lancer `generate.py`. Ça ne prend que quelques secondes par
   paquet, une seule fois.

2. **PyMuPDF**, pour convertir le PDF en PNG (pas de deuxième binaire externe
   à installer — c'est tout l'intérêt) :
   ```powershell
   pip install pymupdf
   ```

Rien d'autre à installer comme police : Liberation Serif (texte imprimé) et
Playwrite VN (texte manuscrit) sont toutes les deux embarquées dans `fonts/`
et chargées par chemin, pas comme police système — voir la section
« Un bug de moins (2) » plus bas si `xelatex` se plaint d'une police
introuvable malgré tout.

```powershell
python generate.py --n 5
python generate.py --n 1 --seed 0 --garder-tex   # pour inspecter le .tex
```

Chaque specimen produit un `.pdf`, un `.png` (200 dpi) et un `..._verite.json`
donnant la valeur exacte de chaque champ (identité patient, et les 7 colonnes
de chaque ligne du tableau).

## La police : Playwrite VN

Deux polices manuscrites généralistes de Google Fonts ont été écartées après
vérification directe du binaire (méthode : lire la table `cmap`, pas la fiche
descriptive) :

| police | couverture vietnamienne mesurée |
|---|---|
| Caveat | 34/256 du bloc Latin Extended Additional — la plupart des combinaisons voyelle+ton manquent |
| Kalam | latin de base seulement, pas de bloc étendu |

**Playwrite VN** (Google Fonts, licence OFL, désignée par TypeTogether) est
retenue à la place. Ce n'est pas une police occidentale « vietnamisée » après
coup : c'est le modèle officiel de l'écriture cursive scolaire vietnamienne
(*mẫu chữ thảo tiếng Việt*), construit pour cet alphabet dès le départ.

Vérifié sur le fichier binaire : sur les 152 caractères vietnamiens
précomposés testés (toute lettre latine + diacritique vietnamien spécifique
— circonflexe/brève/corne — éventuellement empilé avec un ton), 148 sont
couverts ; les 4 signalés absents (Ṍ, ṍ, Ṹ, ṹ) sont des faux positifs du test
— deux tons superposés sur une même lettre, une combinaison qui n'existe pas
en vietnamien. **Couverture réelle : complète.** Confirmé aussi sur les mots
du formulaire lui-même (kỹ thuật, phục hồi chức năng, chẩn đoán, điều trị,
bệnh nhân — tous OK) et sur le rendu final (voir `generated/`).

Fichier : `fonts/PlaywriteVN.ttf` (converti depuis le `.woff` distribué par le
paquet npm `@fontsource/playwrite-vn`, lui-même un miroir direct de Google
Fonts). Licence : `fonts/OFL-PlaywriteVN.txt` (SIL Open Font License 1.1,
libre y compris usage commercial et modification).

## Le vocabulaire : `vocab_phcn.py`

Les noms de technique ne sont pas inventés : ils viennent de la nomenclature
**officielle** du Bộ Y tế — *Hướng dẫn quy trình kỹ thuật Phục hồi chức năng*
(Quyết định 5737/QĐ-BYT, 22/12/2017), 120 techniques. Un faux nom de
technique fausserait un test de généralisation : un modèle pourrait « deviner
juste » simplement parce que le terme sonne vietnamien, sans que ce soit
réellement le terme médical attendu. Sous-ensemble retenu : les techniques
plausibles en usage répété (kinésithérapie générale, électrothérapie,
rééducation à la marche) plutôt que les actes ponctuels (pose de plâtre,
injection de toxine botulique) qui n'apparaîtraient qu'une fois dans un vrai
dossier.

Les descriptions cliniques, noms de personnel et diagnostics sont génériques
et plausibles, jamais copiés d'un patient réel.

## En-tête complété (signalé par Halfaa)

L'en-tête laissait deux champs vides — de simples pointillés jamais remplis :
« Bộ Y tế/Sở Y tế: ....... » et « Buồng ...... Giường ...... ». Sur un vrai
formulaire, les deux sont renseignés à la main. Corrigé :

- ajout de `SO_Y_TE` (Sở Y tế Hà Nội, TP. Hồ Chí Minh, Hải Phòng, Đà Nẵng, ou
  Bộ Y tế pour un hôpital à gestion centrale) — champ purement administratif,
  pas besoin de nomenclature officielle ici ;
- la ligne d'en-tête « Buồng / Giường » réutilise désormais les mêmes
  `patient["buong"]`/`patient["giuong"]` déjà utilisés plus bas dans le corps
  du document (« Số buồng: ... Số giường: ... ») — même patient, même
  chambre, la même valeur manuscrite apparaît logiquement aux deux endroits.

## Un bug de moins

Le rendu PDF → PNG passait par `pdftoppm` (poppler), un deuxième binaire
externe à installer en plus de `xelatex` — et une deuxième source d'échec
Windows (`poppler` n'a pas d'installeur officiel, il faut le récupérer sur
GitHub et l'ajouter au PATH à la main). Remplacé par PyMuPDF, qui s'installe
avec `pip` comme n'importe quel paquet Python et ne demande rien de plus.

## Un bug de moins (2) : la police imprimée aussi embarquée

`\setmainfont{Liberation Serif}` chargeait jusqu'ici la police par son nom,
en supposant qu'elle est installée sur la machine qui compile. Ça a échoué
de façon intermittente chez Halfaa sous Windows/MiKTeX : sur un lot de 5
specimens compilés à la suite avec exactement le même réglage, 4 ont
réussi et le 5ᵉ a échoué avec « The font "Liberation Serif" cannot be
found ». Le nom existe, la police n'a pas changé entre les appels — le plus
probable est un aléa du cache de polices de XeTeX/Windows (MiKTeX a d'ailleurs
tenté de générer une police bitmap de secours, `miktex-makemf.exe`, signe
qu'il n'a pas trouvé la police attendue par la voie normale), pas un vrai
problème d'installation.

Correction : la police est maintenant embarquée dans `fonts/` (4 fichiers —
Regular, Bold, Italic, BoldItalic — extraits du paquet Debian
`fonts-liberation2`, licence OFL, `fonts/OFL-LiberationSerif.txt`) et chargée
par chemin, exactement comme Playwrite VN l'était déjà. Plus aucune police
système n'est requise pour ce générateur.

## Ce qui reste à faire

- **Vérité terrain au niveau du mot/de la boîte**, pas seulement de la
  cellule — nécessite d'extraire les positions via SyncTeX plutôt que de se
  contenter du texte. Utile si on veut évaluer la détection en plus de la
  lecture.
- **Variation du rendu** : une seule graisse (Playwrite VN ne propose que
  100–400 sur l'axe de graisse), une seule échelle. Le prochain test de
  robustesse devrait faire varier légèrement l'inclinaison et l'espacement
  entre mots pour simuler plusieurs scripteurs.
- **Bascule vers l'anglais** annoncée par Halfaa pour la suite : le
  générateur est déjà séparé en trois couches indépendantes (police, gabarit
  LaTeX, vocabulaire dans `vocab_phcn.py`) — passer à l'anglais ne touche que
  le vocabulaire et peut réutiliser une police manuscrite occidentale
  classique (Caveat convient très bien en anglais, c'est seulement le
  vietnamien qui lui pose problème).
