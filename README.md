# MedicalRecord — détection & extraction de tableaux sur documents médicaux

Stage IMT / PTIT — encadrement Thanh-Ha DO.
Objectif : évaluer des modèles OCR/structure sur des factures médicales
vietnamiennes photographiées, et traiter le cas des **tableaux qui s'étendent
sur plusieurs pages**.

---

## Arborescence

```
MedicalRecord/
├── README.md              ← ce fichier
├── TODO.md                ← ce qu'il reste à faire
├── requirements.txt
├── venv/
│
├── src/                   ← code de recherche (la contribution)
│   ├── table_merge.py              algo de détection + fusion des tableaux coupés
│   ├── merge_multipage_results.py  applique l'algo à un run de results/
│   ├── eval_multipage_merge.py     chiffre la fusion (précision / rappel / F1)
│   ├── teds.py                     métrique TEDS + TEDS-Struct
│   ├── eval_teds.py                score les sorties OCR contre la vérité terrain JSON
│   ├── invoice_parse.py            tableau HTML → champs typés
│   ├── invoice_validate.py         validation arithmétique (qté × prix = total)
│   ├── eval_validation.py          mesure ce que la validation détecte
│   └── report_merge_demo.py        rapport HTML de démonstration de la fusion
│
├── scripts/               ← lanceurs de benchmark (à exécuter à la main)
│   ├── bench_tabrecset_paddleocr_vl.py
│   ├── bench_tabrecset_ppstructure.py
│   ├── bench_tabrecset_chandra.py
│   ├── bench_deformed.py           benchmark sur les images déformées doc3D
│   └── legacy/                     scripts d'exploration du début, gardés pour référence
│
├── data/
│   ├── tabrecset_sample/  10 images réelles + annotations (mini-dataset de départ)
│   │   ├── images/  td_annotation/  tsr_tcr_annotation/
│   ├── TabRecSet/         dataset complet (volumineux)
│   └── Facture_pharmacie_fictive_structure_complete.pdf
│
├── results/               ← un dossier par run de benchmark
│   └── <nom_du_run>/
│       ├── pages/<nom_image>/   sorties brutes du modèle (json, md, image annotée)
│       ├── report.html          rapport visuel image ↔ extraction
│       └── merge_report.html    (multipage seulement) décisions de fusion
│
└── docs/
    ├── summary_paddleocr_vl.md      synthèse du benchmark PaddleOCR-VL
    ├── summary_ppstructure.md       synthèse du benchmark PP-StructureV3
    └── notes_benchmark_tabrecset.md
```

**Tous les scripts résolvent leurs chemins depuis la racine du projet** : on peut
les lancer depuis n'importe quel répertoire, il n'y a plus de `cd` piégeux.

---

## Les runs présents dans `results/`

| Run | Données | Modèle | Statut |
|---|---|---|---|
| `tabrecset_paddleocr_vl` | 10 images réelles | PaddleOCR-VL | terminé |
| `tabrecset_ppstructure` | 10 images réelles | PP-StructureV3 | terminé |
| `tabrecset_chandra` | 10 images réelles | Chandra OCR 2 (CPU) | partiel (~15 min/image) |
| `deformed_batch1_paddleocr_vl` | fausses factures déformées 3D | PaddleOCR-VL | 14 images |
| `multipage_paddleocr_vl` | factures multi-pages déformées | PaddleOCR-VL | 5 pages |
| `multipage_ppstructure` | factures multi-pages déformées | PP-StructureV3 | 17 pages (complet) |
| `_premiers_tests` | — | — | bacs à sable du tout début |

---

## Commandes usuelles

Depuis `MedicalRecord/`, venv activé :

```powershell
# Benchmark sur les images déformées (reprend un run interrompu sans réinférence)
python scripts\bench_deformed.py --model ppstructure `
       --images-dir "..\doc3D-renderer\img\multipage_test" --limit 6 `
       --output multipage_ppstructure

# Fusion des tableaux multi-pages sur un run existant
python src\merge_multipage_results.py --run multipage_ppstructure

# Évaluation chiffrée de la fusion (précision / rappel / F1)
python src\eval_multipage_merge.py --run multipage_ppstructure

# Qualité d'extraction TEDS, et gain apporté par la fusion
python src\eval_teds.py --run multipage_ppstructure
```

Le rapport de benchmark est réécrit **après chaque image** : une interruption
ne fait perdre au maximum qu'une image, et relancer la même commande reprend
là où ça s'était arrêté.

---

## Résultats

Trois modèles, 8 factures, 17 pages, même jeu de test. Détail complet et
limites dans `docs/resultats_teds.md`.

| Modèle | TEDS | TEDS-Struct | Gain de la fusion | F1 détection |
|---|---|---|---|---|
| **HunyuanOCR-1.5** | **0.928** | **0.949** | +0.260 | **100 %** |
| PaddleOCR-VL | 0.909 | 0.933 | +0.251 | 93 % |
| PP-StructureV3 | 0.557 | 0.857 | +0.132 | 100 % |

Trois enseignements. HunyuanOCR et PaddleOCR-VL sont au coude à coude ;
PP-StructureV3 décroche, et son écart TEDS / TEDS-Struct de 0.300 (contre
0.02 pour les deux autres) montre que son problème est la lecture des
caractères vietnamiens, pas la reconstruction de la grille. Enfin la fusion
apporte un gain du même ordre pour les trois modèles, donc elle n'est pas
calibrée sur l'un d'eux — et **zéro faux positif partout**, ce qui compte
plus que le rappel : fusionner deux factures à tort est bien plus grave que
manquer une continuation.

**Validation arithmétique** — détail dans `docs/resultats_validation.md`.
Une facture se vérifie elle-même (`qté × prix = total`, somme des lignes =
`Tổng tiền`), donc **sans vérité terrain**. Avec HunyuanOCR : sur 215 lignes,
12 sont à relire (6 %) et elles contiennent **100 % des erreurs numériques**,
avec **zéro fausse alerte**. C'est ce qui rend un TEDS de 0,93 exploitable en
pratique.

Deux réserves. Les erreurs de **libellé** échappent par construction à
l'arithmétique (« Xetoprofen » pour *Ketoprofen*) : il faudrait un
dictionnaire de médicaments. Et la **correction automatique** n'est sûre que
si le modèle est bon — 97 % de corrections exactes avec PaddleOCR-VL, mais
9 % avec PP-StructureV3, où elle rend les erreurs invisibles en les rendant
cohérentes.

**Hypothèse métier assumée** par l'algorithme : la colonne STT redémarre à 1
à chaque nouvelle facture. C'est le signal le plus discriminant (« B commence
à 20 → la numérotation vient forcément d'ailleurs »), et c'est lui qui
rattrape les cas où l'OCR a massacré la fin du tableau précédent. À
revalider sur des factures d'un autre format.

---

## Pipeline amont (hors de ce dossier)

Les images de test sont produites par les deux repos voisins :

1. `../synthetic_invoice_generator/` → génère les fausses factures
   vietnamiennes (JSON de vérité terrain → LaTeX → PDF → PNG), version
   mono-page et version multi-pages (`longtable`).
2. `../doc3D-renderer/` → applique la déformation 3D + fonds réalistes
   (Blender 2.79, à lancer sur la machine locale). Sortie : `img/<batch>/`.

---

## Nettoyage restant

Deux dossiers vides (`benchmark/`, `benchmark_deformed/`) et `__pycache__/`
n'ont pas pu être supprimés automatiquement (fichiers verrouillés côté
Windows) — à supprimer à la main. `data/TabRecSet/` : le dataset complet est
resté à la racine pour la même raison, à déplacer dans `data/` quand il n'est
plus ouvert par un autre programme.
