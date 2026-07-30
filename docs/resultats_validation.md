# Validation arithmétique — résultats

Une facture est massivement redondante, et cette redondance est exploitable
**sans vérité terrain** :

```
quantité × prix_unitaire = total_ligne      (une contrainte par ligne)
somme des totaux de ligne = Tổng tiền       (une contrainte globale)
```

C'est ce qui distingue cette mesure du TEDS : le TEDS dit *à quel point*
l'extraction est bonne, mais suppose qu'on connaisse la réponse. La
validation arithmétique, elle, fonctionne en production, sur des factures
dont personne ne connaît le contenu.

Reproduire :

```powershell
python src\eval_validation.py --run multipage_hunyuan
```

---

## 1. Détection des erreurs numériques

Sur 8 factures. « Signalée » = ligne remise à un relecteur humain.

| Modèle | Lignes | Fausses | Détectées | Rappel | Fausses alertes |
|---|---|---|---|---|---|
| **HunyuanOCR-1.5** | 215 | 12 | 12 | **100 %** | **0** |
| PaddleOCR-VL | 215 | 4 | 2 | 50 % | 0 |
| PP-StructureV3 | 185 | 127 | 95 | 75 % | 0 |

**Aucune fausse alerte, avec les trois modèles.** Chaque ligne signalée était
réellement fausse. C'est ce qui rend le dispositif utilisable : le relecteur
ne perd pas son temps sur des lignes correctes, donc il continuera à faire
confiance au signal.

**Le résultat exploitable** : avec HunyuanOCR, sur 215 lignes, **12 sont à
relire — soit 6 % — et elles contiennent 100 % des erreurs numériques**. On
passe d'un « TEDS 0,928, donc à peu près 7 % de cellules fausses quelque
part » à « voici les douze lignes à vérifier ».

---

## 2. Correction automatique

Quand une seule des trois valeurs manque, elle se déduit des deux autres.

| Modèle | Corrections | Exactes | Taux |
|---|---|---|---|
| PaddleOCR-VL | 68 | 66 | **97 %** |
| PP-StructureV3 | 35 | 3 | **9 %** |
| HunyuanOCR-1.5 | 0 | — | — |

Ce tableau porte l'enseignement le plus important, et il est contre-intuitif.

**PaddleOCR-VL perd fréquemment la colonne prix unitaire**, mais garde
quantité et total justes : la déduction retrouve la valeur dans 97 % des cas.
Ses 70 lignes fausses tombent ainsi à 4. La correction automatique est ici un
gain considérable, presque gratuit.

**Avec PP-StructureV3, la même mécanique est un piège** : ses sorties sont
tellement dégradées que les deux valeurs restantes sont souvent fausses
elles aussi. On déduit alors une troisième valeur fausse — et, pire, la ligne
devient arithmétiquement cohérente, donc **elle cesse d'être signalée**. La
correction transforme une erreur visible en erreur invisible.

**Conséquence de conception** : ne jamais corriger automatiquement sans
conditionner la correction à la qualité globale du document. Un seuil sur le
taux de lignes cohérentes de la facture suffirait à désactiver la correction
quand le modèle décroche.

---

## 3. Ce que l'arithmétique ne peut pas voir

| Modèle | Lignes au nom mal lu |
|---|---|
| HunyuanOCR-1.5 | 12 / 215 (6 %) |
| PaddleOCR-VL | 15 / 215 (7 %) |
| PP-StructureV3 | 76 / 185 (41 %) |

Exemples : « Xetoprofen 250mg » pour *Ketoprofen*, « Anoxicillin 500mg » pour
*Amoxicillin*, « Effectivitan 500mg » pour *Efferalgan*.

Ces erreurs sont hors de portée de l'arithmétique **par construction**, et
non par défaut d'implémentation : rien dans la facture ne permet de savoir
que « Xetoprofen » aurait dû se lire « Ketoprofen ». Les trois nombres de la
ligne peuvent être parfaitement justes.

Les détecter demanderait une source d'information extérieure — un
**dictionnaire de médicaments**, avec appariement flou sur les noms. C'est
une piste distincte et complémentaire : l'arithmétique couvre les nombres, un
dictionnaire couvrirait les libellés. Ensemble, ils couvriraient l'essentiel
du contenu d'une facture.

---

## Ce que ça change pour la conclusion

Avant, on pouvait dire : « l'extraction atteint 0,928 de TEDS ». C'est un bon
score, mais il ne dit pas si les 7 % d'erreurs restantes sont repérables — et
sur des factures médicales, c'est précisément la question qui décide de
l'utilisabilité.

Maintenant on peut dire : **les erreurs numériques sont intégralement
détectables sans vérité terrain, au prix de 6 % des lignes à relire, et sans
aucune fausse alerte.** Restent les erreurs de libellé, qui appellent un
dictionnaire.

## Limites

Même échantillon que le reste : 8 factures, un seul gabarit. La validation
suppose en outre que la facture contient bien les trois colonnes quantité /
prix unitaire / total — vrai pour ce format, à vérifier ailleurs.

Le taux de correction exacte de 97 % chez PaddleOCR-VL tient à un mode de
défaillance particulier (perte d'une colonne entière). Rien ne garantit qu'il
se reproduise sur d'autres documents.
