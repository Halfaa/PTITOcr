# GLM-OCR — le cinquième candidat, et le pari le plus incertain

GLM-OCR (Z.ai, mars 2026, arXiv 2603.10910) est le prochain modèle à tester.
Il est déjà câblé dans le protocole : `scripts/bench_deformed.py --model glm`
et `scripts/eval_all.py --modele glm`. Reste à le faire tourner.

---

## 1. Pourquoi lui

**Il tient dans 4 Go.** 0,9 milliard de paramètres, ~2 Go en bf16 : c'est le
seul modèle récent de premier plan qui tourne sur la RTX 3050 Ti **sans GPU
loué**. Chandra a demandé un T4 Kaggle ; GLM tournera sur le poste, ce qui
change tout pour la démonstration en réunion et pour la PWA.

**Il est le meilleur sur les tableaux.** C'est là que nos chiffres se jouent :
GLM-OCR revendique les meilleurs TableTEDS et TableTEDS-S de tous les modèles
évalués, et la première place d'OmniDocBench V1.5 avec 94,62. Notre métrique
principale est un TEDS de tableau — l'alignement est aussi direct qu'il peut
l'être.

**Licence MIT.** Plus permissive encore que celles de Chandra (OpenRAIL-M
modifiée) et de PaddleOCR-VL (Apache 2.0), et sans commune mesure avec la
licence Tencent de HunyuanOCR, qui exclut l'UE. Aucun frein au déploiement ni
au calcul dans une région imposée.

**Il est rapide.** 0,67 image/s annoncé, contre nos 81 à 230 s la page. Même
en divisant ce chiffre par dix sur notre matériel, ça reste un autre ordre de
grandeur — et donc une PWA utilisable, là où l'utilisateur attend
actuellement plusieurs minutes.

---

## 2. La réserve, et il faut la regarder en face

**Le vietnamien n'est pas dans ses langues officielles.** GLM-OCR en annonce
huit : chinois, anglais, français, espagnol, russe, allemand, japonais,
coréen. Il en lit d'autres par héritage du corpus GLM-4V, mais sans que
personne ne l'ait mesuré, et les performances annoncées portent surtout sur
le chinois et l'anglais.

Or notre difficulté n'est pas le vietnamien « en général », ce sont ses
**diacritiques** : `ộ`, `ế`, `ữ`, `đ`. Ce sont elles qui ont fait décrocher
PP-StructureV3 — 0,857 de structure pour 0,557 de contenu, un écart de 0,300
qui ne dit qu'une chose : la grille est bonne, les caractères sont faux.

C'est exactement le risque ici, et il est mesurable en une page.

### Ce qu'on écrit avant de mesurer

Comme pour Chandra, la prédiction est consignée **avant** le benchmark :

- **TEDS-Struct élevé** (≥ 0,95). C'est un modèle de tableaux, entraîné pour
  ça, et la structure d'une facture ne dépend pas de la langue.
- **TEDS incertain**, deux issues franches plutôt qu'un entre-deux : soit les
  diacritiques passent et il prend la tête, soit elles ne passent pas et on
  revoit un profil PP-StructureV3 avec un écart Struct/TEDS supérieur à 0,15.
- **Champs d'en-tête** plus fragiles que le tableau : ils contiennent des noms
  propres vietnamiens, sans redondance arithmétique pour rattraper.

Cette dernière prédiction est celle qui a le plus de valeur : si l'écart
Struct/TEDS dépasse 0,15, **le protocole aura identifié la cause sans qu'on
ait à lire une seule sortie**. C'est ce que TEDS-Struct sert à faire.

Une variance élevée n'est pas un défaut du test. Le résultat est informatif
dans les deux sens : « un modèle SOTA sur les tableaux échoue sur le
vietnamien » est une conclusion aussi publiable que l'inverse, et elle
renforcerait l'argument central du stage — la langue est le vrai filtre, pas
la taille du modèle.

---

## 3. Comment le lancer

L'architecture `glm_ocr` est récente. Un `KeyError: 'glm_ocr'` au chargement
ne signale pas une erreur de code mais un `transformers` trop ancien :

```powershell
.\venv_hunyuan\Scripts\activate
pip install git+https://github.com/huggingface/transformers.git
```

Le smoke test d'abord — une page, une minute, et on sait déjà si les
diacritiques survivent :

```powershell
python scripts\bench_deformed.py --model glm `
    --images-dir "..\doc3D-renderer\img\multipage_test" --limit 1 `
    --output smoke_glm
```

Puis les cinq branches, dans les mêmes conditions que les autres modèles :

```powershell
$IMG = "..\doc3D-renderer\img"
python scripts\bench_deformed.py --model glm --images-dir "$IMG\multipage_test"              --output multipage_glm
python scripts\bench_deformed.py --model glm --images-dir "$IMG\multipage_test_preprocessed" --output multipage_preproc_glm
python scripts\bench_deformed.py --model glm --images-dir "$IMG\variants_flat"               --output variants_glm
python scripts\bench_deformed.py --model glm --images-dir "$IMG\variants_warped"             --output variants_warped_glm

python scripts\eval_all.py --modele glm
python scripts\eval_all.py --modele glm --modele chandra --modele hunyuan
```

Les noms de runs sont déjà déclarés dans `scripts/eval_all.py` : les produire
suffit, l'évaluation les trouvera.

---

## 4. Un choix de protocole à assumer

La chaîne officielle de GLM-OCR est **en deux étages** : PP-DocLayoutV3
analyse la mise en page, puis GLM-OCR reconnaît chaque bloc. Ce n'est
accessible que par leur SDK.

`bench_deformed.py` appelle **le modèle seul**, comme pour les trois autres.
Lui adjoindre un détecteur de mise en page dont les autres ne disposent pas
mesurerait deux choses à la fois et rendrait la comparaison inutilisable.

C'est un choix qui le désavantage, et il faut le dire dans le rapport. Si le
modèle seul se montre prometteur, mesurer le SDK complet devient une seconde
expérience légitime — mais à présenter comme telle, pas comme la même.

---

## 5. Où il se place dans les priorités

Après l'étude de dégradation d'image, pas avant. L'écart entre nos deux
meilleurs modèles est de 0,013 quand le prétraitement en apporte 0,050 : un
cinquième modèle affine une comparaison déjà tranchée, tandis que l'étude de
dégradation répond à une question sans aucune réponse aujourd'hui.

La nuance : GLM tourne **en local**, donc le smoke test coûte une minute et
peut se faire pendant que tourne autre chose. Si les diacritiques passent, il
devient le candidat de déploiement évident — 0,9 B, MIT, rapide, sur la carte
qu'on a déjà — et il remonte alors tout en haut de la liste.

---

## Sources

- [GLM-OCR sur Hugging Face](https://huggingface.co/zai-org/GLM-OCR) — architecture, benchmarks, licence MIT, exemple `transformers`
- [GLM-OCR Technical Report, arXiv 2603.10910](https://arxiv.org/abs/2603.10910)
- [Dépôt et SDK officiels](https://github.com/zai-org/GLM-OCR)
- [GLM-OCR vs PaddleOCR : benchmarks 2026](https://decodethefuture.org/en/glm-ocr-explained/) — langues officielles, TableTEDS
- [PP-DocLayoutV3](https://huggingface.co/PaddlePaddle/PP-DocLayoutV3) — l'étage de mise en page du SDK
