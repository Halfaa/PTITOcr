# Mini-dataset de benchmark — reconnaissance de tableaux

10 images issues de TabRecSet (pages completes, avec texte/contexte autour du tableau,
pas des tableaux pre-recadres), selectionnees pour leur diversite : langue, style de
bordure, type de contenu, et quantite de texte environnant.

| # | Fichier | Langue | Style bordure | Contenu | Contexte autour |
|---|---------|--------|----------------|---------|------------------|
| 1 | `2istedsc.jpg` | EN | avec bordures | Page manuel scolaire (annonces + exercices) | Beaucoup (2 exercices sous le tableau) |
| 2 | `3046887202.jpg` | EN | sans bordures | Facture/ticket de caisse (photo reelle) | Beaucoup (en-tete, footer, paiement) |
| 3 | `9558143260.jpg` | EN | avec bordures | Liste de candidats electoraux, multi-sections | Beaucoup (titre + plusieurs sous-tableaux) |
| 4 | `685642856.jpg` | EN | avec bordures | Feuille d'exercice labo (questions + tableau) | Beaucoup (questions 1-3 avant le tableau) |
| 5 | `table_spider_00416.jpg` | EN/FR | avec bordures | Etiquette nutritionnelle (packaging produit) | Moyen (texte bilingue autour) |
| 6 | `7786418899_yjc.jpg` | ZH | avec bordures | Question d'examen chimie + QCM | Beaucoup (enonce + choix multiples) |
| 7 | `0_08ef...yf.jpg` | ZH | avec bordures | Exercice de maths + questions | Beaucoup |
| 8 | `7841115378_yf.jpg` | ZH | sans bordures | Exercice de maths + QCM | Beaucoup |
| 9 | `3876967706_ljh.jpg` | ZH | sans bordures | Page de cahier d'exercices (reponses 20-30) | Beaucoup (page dense en texte) |
| 10 | `26_059a...hl.jpg` | ZH | sans bordures | Question d'examen maths, tableau a trous | Beaucoup |

## Structure

- `images/` — les 10 images sources (pages completes)
- `td_annotation/` — verite terrain de **detection** (polygone de localisation du/des tableaux dans la page), format LabelMe
- `tsr_tcr_annotation/` — verite terrain de **structure + contenu** (cellules, texte), format LabelMe

Chaque fichier d'annotation porte le meme nom de base que son image (`<nom>.json`).

## Usage prevu

Pour chaque modele teste (PaddleOCR-VL, PP-StructureV3, Chandra OCR, ...) :
1. Faire tourner le modele sur les images de `images/`
2. Comparer sa detection au polygone de `td_annotation/` (localisation du tableau)
3. Comparer sa structure/contenu extrait aux cellules de `tsr_tcr_annotation/`

Source complete : TabRecSet (CurveTabSet), https://github.com/MaxKinny/TabRecSet
