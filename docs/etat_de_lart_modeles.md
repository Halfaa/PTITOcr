# Quels modèles pour du vietnamien + anglais avec tableaux ?

État de l'art, juillet 2026. Objectif : identifier les modèles susceptibles de
mieux marcher que PaddleOCR-VL et PP-StructureV3 sur des **factures médicales
vietnamiennes photographiées**, avec sortie de tableau exploitable.

## Les contraintes qui filtrent tout

1. **Vietnamien + anglais.** Le vietnamien est une langue à diacritiques
   denses (ế, ữ, ợ) : c'est précisément là que nos mesures TEDS montrent que
   ça casse.
2. **Sortie tableau structurée** (HTML ou OTSL), pas juste du texte à plat —
   sinon `table_merge` n'a rien à recoller.
3. **4 Go de VRAM** (RTX 3050 Ti). C'est le filtre le plus brutal : il élimine
   d'emblée tout ce qui dépasse ~2 milliards de paramètres en bf16. Chandra
   OCR 2 (5 B) nous a déjà forcés au CPU, à ~15 min/image.
4. **Documents photographiés, pas scannés.** Nos images sont déformées et
   éclairées de façon inégale. Ce point s'est révélé décisif — voir §2.

---

## 1. Ce que disent les benchmarks *sur le vietnamien*

**SEA-Vision** (arXiv 2603.15409) est le benchmark le plus pertinent : 11
langues d'Asie du Sud-Est dont le vietnamien, 15 234 pages, 9 types de
documents, tableaux annotés avec leurs cellules fusionnées. Métrique : NED
(distance d'édition normalisée), **plus bas = meilleur**.

Colonne vietnamien (VI) :

| Modèle | Taille | VI (NED ↓) | Type |
|---|---|---|---|
| Qwen3-VL-32B | 32 B | **0.107** | généraliste |
| Qwen2.5-VL-72B | 72 B | 0.122 | généraliste |
| Gemini 2.5 Pro | — | 0.132 | propriétaire |
| **PaddleOCR-VL** | **0.9 B** | **0.148** | pipeline |
| dots.ocr | 3 B | 0.152 | expert |
| Dolphin-1.5 | — | 0.167 | pipeline |
| POINTS-Reader | — | 0.184 | expert |
| DeepSeek-OCR | 3 B | 0.216 | expert |
| GPT-4o | — | 0.244 | propriétaire |
| MinerU 2.5 | 1.2 B | 0.278 | pipeline |
| MonkeyOCR-pro-3B | 3 B | 0.370 | pipeline |
| MonkeyOCR-pro-1.2B | 1.2 B | 0.457 | pipeline |
| InternVL3.5-38B | 38 B | 0.587 | généraliste |

**Le résultat important pour nous : PaddleOCR-VL est 4e, avec 0.9 B de
paramètres.** Les trois modèles qui le battent font 32 B, 72 B, ou sont une
API propriétaire. À contrainte matérielle égale, notre choix initial était
donc le bon — c'est bon à écrire noir sur blanc dans le rapport.

Autre enseignement : **MinerU 2.5 et MonkeyOCR sont mauvais en vietnamien**
(0.278 et 0.457) alors qu'ils sont excellents en anglais. Ne pas les
considérer, malgré leur réputation.

---

## 2. Ce que disent les benchmarks *sur les documents photographiés*

C'est ici que ça devient intéressant, et ça recoupe directement notre mesure
TEDS-Struct.

**Wild-OmniDocBench** évalue sur des documents réels photographiés (courbés,
mal éclairés), par opposition à OmniDocBench qui utilise des scans propres.
Chiffres rapportés par Tencent (score global et score tableau, plus haut =
meilleur) :

| Modèle | Taille | OmniDoc global | Wild global | **Chute** | OmniDoc table | Wild table |
|---|---|---|---|---|---|---|
| **HunyuanOCR** | **1 B** | 94.10 | **85.21** | **−8.9** | 91.81 | **81.64** |
| Gemini 2.5 Pro | — | 88.03 | 80.59 | −7.4 | 85.71 | 78.56 |
| Qwen3-VL-235B | 235 B | 89.15 | 79.69 | −9.5 | 86.21 | 68.31 |
| dots.ocr | 3 B | 88.41 | 78.01 | −10.4 | 86.78 | 71.89 |
| DeepSeek-OCR | 3 B | 87.01 | 74.23 | −12.8 | 84.97 | 70.41 |
| **PaddleOCR-VL** | 0.9 B | 92.86 | 72.19 | **−20.7** | 90.89 | 74.24 |
| MinerU 2.5 | 1.2 B | 90.67 | 70.91 | −19.8 | 88.22 | 70.15 |

**PaddleOCR-VL est le modèle qui s'effondre le plus** en passant du scan
propre à la photo réelle : −20.7 points, contre −8.9 pour HunyuanOCR. Sur les
tableaux seuls, il passe de 90.89 à 74.24.

C'est exactement le phénomène que nous mesurons. Notre pipeline doc3D
fabrique des documents « wild » ; nos scores TEDS chutent ; et TEDS-Struct
nous disait déjà que le problème n'est pas la grille mais la lecture. Ces
chiffres externes confirment le diagnostic sur un tout autre jeu de données.

⚠️ Ces chiffres sont **auto-rapportés par Tencent** dans le README de leur
propre modèle. À prendre avec prudence, et à vérifier nous-mêmes — ce qui est
justement à notre portée puisque nous avons un jeu de test et une métrique.

---

## 3. Les candidats, un par un

### HunyuanOCR / HunyuanOCR-1.5 — *le candidat n° 1*

**1 milliard de paramètres**, VLM OCR de bout en bout (Tencent), open source.
Sait sortir les tableaux **directement en HTML** via un prompt dédié
(« 把图中的表格解析为 HTML »), ce qui s'enchaîne sans adaptation sur notre
`table_merge`. Plus de 100 langues, vietnamien explicitement pris en charge.
La version **1.5** (juillet 2026) ajoute 4K de résolution et annonce un
gain de vitesse de 6.4× en Transformers.

*Pourquoi lui* : le meilleur score tableau sur documents photographiés, à une
taille qui tient sur notre matériel.

*Le point à vérifier* : le README annonce **20 Go de VRAM pour vLLM**. C'est
la pré-allocation de vLLM, pas le besoin réel du modèle — 1 B en bf16 fait
environ 2 Go de poids. Le chemin Transformers a des chances de passer sur nos
4 Go, mais **c'est à tester avant de s'engager**, en gardant le repli CPU
(qui sera lent, mais 5× moins qu'avec Chandra).

### dots.ocr — *le repli sérieux*

3 B, meilleur modèle expert open source de SEA-Vision toutes langues
confondues (0.186 de moyenne), et 4e sur le vietnamien (0.152), au coude à
coude avec PaddleOCR-VL. Chute modérée sur les documents photographiés
(−10.4). Mais 3 B en bf16 ≈ 6 Go : **il faudra quantifier en 4 bits** pour
tenir sur la carte.

### Vintern-1B-v3.5 — *le spécialiste vietnamien*

1 B, développé spécifiquement pour le vietnamien (InternViT-300M + Qwen2-0.5B),
entraîné sur 3 M de paires image-question-réponse vietnamiennes, et annoncé
comme performant sur les factures et les tableaux. Taille idéale pour nos 4 Go.

*La réserve* : c'est un MLLM généraliste vietnamien, pas un modèle de parsing
documentaire. Il n'a pas de sortie tableau HTML garantie et n'apparaît dans
aucun des benchmarks de parsing ci-dessus. À traiter comme une **expérience**,
pas comme une solution — mais une expérience intéressante, parce que c'est le
seul modèle du lot réellement optimisé pour la langue.

### TRivia-3B — *le spécialiste tableau*

3 B, dérivé de Qwen2.5-VL-3B, entraîné spécifiquement pour la reconnaissance
de tableaux (OpenDataLab, décembre 2025). Dépasse UniTable de 27 points de
TEDS sur CC-OCR. Sort de l'OTSL, convertible en HTML.

*L'inconnue* : rien sur ses performances en vietnamien. Comme il ne fait *que*
du tableau, il faudrait le combiner avec un OCR séparé pour le texte — ce qui
complique le pipeline.

### Ce qu'il ne faut pas retenir

- **MinerU 2.5, MonkeyOCR** : très bons en anglais, mauvais en vietnamien.
- **InternVL3.5** : le pire des modèles testés en vietnamien (0.587).
- **Qwen3-VL-32B / Gemini 2.5 Pro** : meilleurs en absolu, hors d'atteinte
  matériellement (ou payants et non reproductibles pour un rapport).

---

## 4. Recommandation

**Tester HunyuanOCR-1.5 en priorité.** C'est le seul modèle qui coche les
trois cases à la fois : taille compatible avec 4 Go, sortie tableau HTML
native, et — surtout — robustesse démontrée sur les documents photographiés,
qui est notre point faible mesuré.

Le protocole est déjà en place : `scripts/bench_deformed.py` accepte un
nouveau modèle en ajoutant une branche dans `get_pipeline()`, et
`src/eval_teds.py` produira des chiffres directement comparables à ceux de
PaddleOCR-VL et PP-StructureV3.

Ordre suggéré :

1. **HunyuanOCR-1.5** — vérifier d'abord qu'il tient en VRAM sur une seule
   image avant de lancer un benchmark complet. *(fait : 0,928 puis 0,974 en
   adaptatif)*
2. **Chandra OCR 2** — écarté en semaine 2 pour cause de VRAM, remis au
   programme via un GPU loué. Voir [chandra_ocr2.md](chandra_ocr2.md) : c'est
   le seul modèle de la classe 5 B du comparatif, et sa licence n'a aucune
   restriction géographique, contrairement à celle de HunyuanOCR.
3. **Vintern-1B-v3.5** — si la sortie tableau est exploitable. Angle
   « modèle spécifiquement vietnamien » intéressant pour le rapport.
4. **dots.ocr en 4 bits** — si les précédents déçoivent.

---

## 5. Une piste connexe qui valide notre approche

Le papier **« Towards Real-World Document Parsing via Realistic Scene
Synthesis and Document-Aware Training »** (CVPR 2026, arXiv 2603.23885, même
équipe que HunyuanOCR) fait exactement ce que fait notre pipeline doc3D :
synthétiser des documents réalistes déformés pour améliorer le parsing sur
photos réelles.

C'est une référence à citer : elle montre que la démarche « générer des
fausses factures + les déformer en 3D » n'est pas un bricolage mais une
méthode validée par une publication en conférence majeure. Et elle ouvre une
suite naturelle — utiliser nos images synthétiques non plus seulement pour
*évaluer*, mais pour *affiner* un modèle.

---

## Sources

- [SEA-Vision: A Multilingual Benchmark for Document and Scene Text Understanding in Southeast Asia](https://arxiv.org/html/2603.15409) — tableau vietnamien, §6.2.1
- [HunyuanOCR (dépôt officiel Tencent)](https://github.com/Tencent-Hunyuan/HunyuanOCR) — chiffres OmniDocBench / Wild-OmniDocBench
- [HunyuanOCR-1.5: Making Lightweight OCR VLMs Faster and Better](https://arxiv.org/abs/2607.04884)
- [dots.ocr: Multilingual Document Layout Parsing in a Single Vision-Language Model](https://arxiv.org/html/2512.02498v1)
- [Vintern-1B: An Efficient Multimodal Large Language Model for Vietnamese](https://arxiv.org/abs/2408.12480) — [modèle v3.5](https://huggingface.co/5CD-AI/Vintern-1B-v3_5)
- [TRivia: Self-supervised Fine-tuning of Vision-Language Models for Table Recognition](https://arxiv.org/html/2512.01248v1) — [code](https://github.com/opendatalab/TRivia)
- [A Survey on Vietnamese Document Analysis and Recognition](https://arxiv.org/abs/2506.05061)
- [MinerU2.5: A Decoupled Vision-Language Model for Efficient High-Resolution Document Parsing](https://arxiv.org/pdf/2509.22186)
- [MORE: A Multilingual Document Parsing Benchmark](https://github.com/zimoqingfeng/MORE) — 149 langues, ICML 2026
- [Towards Real-World Document Parsing via Realistic Scene Synthesis and Document-Aware Training](https://arxiv.org/abs/2603.23885) — CVPR 2026
- [Vietnamese-OCR : fine-tuning PaddleOCR pour le vietnamien](https://github.com/vitmetmoi/Vietnamese-OCR)
