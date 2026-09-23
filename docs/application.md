# L'application — API et PWA

> **Code retiré du dépôt en septembre 2026.** `webapp/` et `src/api.py` sont
> dans `archive/retire_2026-09/`. Le prototype a fonctionné et ce document le
> décrit, mais il ne fait pas partie du rendu final : le rapport porte sur la
> lecture et la génération, pas sur l'interface. À restaurer depuis l'archive
> ou depuis l'historique git si le sujet revient.

Photo au téléphone, tableau vérifié et JSON en retour. C'est le livrable
« prototype UI/API » du sujet, prévu semaines 11–12.

```powershell
pip install fastapi "uvicorn[standard]" python-multipart
python src\api.py
```

Puis `http://localhost:8000`. Depuis un téléphone du même réseau,
`http://<ip-du-poste>:8000` — l'API écoute sur `0.0.0.0`.

---

## 1. Pourquoi une PWA et pas une application native

Une *Progressive Web App* s'installe depuis le navigateur, accède à l'appareil
photo, fonctionne sur Android comme sur iOS, et se met à jour sans magasin
d'applications. Pour un prototype de stage, c'est le seul format qui donne un
usage réel au téléphone sans deux développements séparés.

**Le calcul reste côté serveur.** Les modèles font 0,9 à 1 milliard de
paramètres et pèsent plusieurs gigaoctets : le téléphone prend la photo, le
serveur lit. Ça permet aussi de changer de modèle sans rien redéployer sur
les appareils.

Conséquence à assumer : sans réseau, l'application s'ouvre mais ne peut pas
extraire. Le service worker met en cache la coquille — page, manifeste,
icônes — et **jamais `/api/`** : servir une réponse d'API depuis le cache
afficherait les résultats de la facture précédente sur la photo courante,
ce qui est bien pire qu'une erreur réseau honnête.

---

## 2. Ce que l'interface montre

Le sujet demande une démonstration, pas seulement un résultat. Chaque étape
de la chaîne est donc exposée :

| étape | ce qui s'affiche |
|---|---|
| réception | les pages envoyées |
| prétraitement | le **quadrilatère détecté** superposé à la photo, son score, la méthode retenue, et l'image redressée |
| lecture | l'avancement page par page |
| fusion | pour chaque transition, fusionné ou séparé, et **les signaux qui l'ont décidé** |
| validation | chaque ligne colorée selon son statut (ok, corrigée, incohérente, incomplète) |
| choix adaptatif | la confiance de chaque lecture et celle qui a été retenue |

Le quadrilatère est transmis en **fractions de l'image**, pas en pixels :
l'affichage redimensionne selon la taille de l'écran, et des coordonnées en
pixels seraient fausses dès le premier redimensionnement.

---

## 3. Deux lectures, mais seulement quand il le faut

L'API applique la politique de `src/adaptive.py` : le tableau retenu est
celui dont la **cohérence arithmétique** est la meilleure — sans vérité
terrain, puisqu'en production il n'y en a pas. Mesuré sur 12 factures jamais
vues : **0,942 de TEDS**, contre 0,906 pour la lecture brute seule et 0,879
pour la prétraitée seule.

Le choix demande deux lectures, donc deux fois le temps de calcul. Les payer
systématiquement est inutile : sur ces mêmes 12 factures, la lecture brute
marquait déjà **1,00 de confiance sur 5 d'entre elles** — et c'est exactement
là où le prétraitement n'apportait rien.

L'API lit donc d'abord l'image brute, **note le résultat**, et ne paie la
seconde lecture que si ce score doute (seuil 0,95). C'est la même idée que la
politique adaptative, appliquée cette fois au temps de calcul.

```
deux_passes = "auto"      seconde lecture seulement si la première doute
              "toujours"  les deux, systématiquement
              "jamais"    une seule, le plus rapide
```

### La résolution, l'autre moitié du problème

Une photo de téléphone fait 3000 à 4000 px de large. Le coût d'un VLM croît
plus vite que linéairement avec le nombre de patches d'image : lire la photo
pleine résolution coûte plusieurs fois ce que coûte la même page à 1600 px,
pour un texte déjà parfaitement lisible à cette taille — nos mesures de
référence sont d'ailleurs faites sur des pages de 900×1200.

L'API ramène donc toute image au-dessus de 1600 px de côté long avant de la
donner au modèle.

### Ce qui reste à faire côté matériel

Le vrai levier n'est pas logiciel. PaddleOCR-VL fait 0,9 milliard de
paramètres — moins que HunyuanOCR, qui tourne déjà sur la RTX 3050 Ti à 87 s
la page. S'il tourne sur CPU, c'est que `paddlepaddle` a été installé à la
place de `paddlepaddle-gpu` :

```powershell
pip uninstall paddlepaddle
pip install paddlepaddle-gpu -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
python -c "import paddle; paddle.utils.run_check()"
```

Sur GPU, une page tombe de 230 s à quelques dizaines de secondes. Avec la
réduction de résolution et la seconde passe conditionnelle, une facture de
deux pages passe alors sous la minute.

**Kaggle ne peut pas servir de moteur.** Un notebook n'accepte aucune
connexion entrante, la session meurt au bout de 12 h et il n'existe pas
d'URL publique. Un tunnel est possible techniquement mais interdit en
pratique et ingérable pour une démonstration. Kaggle reste l'outil des
benchmarks par lots ; pour du service, il faut une machine qu'on contrôle —
le poste local, un serveur du laboratoire, ou une location horaire type
Vast.ai.

---

## 4. Deux modes

**Live.** Le modèle tourne vraiment. Compter 30 s à 3 min selon le modèle et
le nombre de pages, les deux lectures comprises.

**Rejeu.** L'interface rejoue un run déjà calculé de `results/`. Instantané.
C'est ce qu'il faut utiliser en réunion : personne ne regarde un écran figé
pendant trois minutes, et la chaîne reste montrable de bout en bout.

Le traitement tourne en tâche de fond et l'interface interroge l'état toutes
les 700 ms. Une requête HTTP de trois minutes se fait couper par à peu près
tous les intermédiaires réseau, et l'utilisateur ne verrait rien entre-temps.

---

## 5. L'API seule

Elle s'utilise sans l'interface, ce qui en fait un livrable indépendant.

```
POST /api/extract     images[] + modele    -> {id}
POST /api/replay      run_brut, run_pretraite, pages -> {id}
GET  /api/jobs/{id}                        -> état, étapes, résultat
GET  /api/runs                             -> runs disponibles pour le rejeu
GET  /api/health                           -> modèle actuellement chargé
```

Le modèle est chargé une fois et gardé en mémoire : le recharger coûte 30 à
90 s, le faire par requête rendrait l'application inutilisable.

---

## 6. Ce qui manque avant un usage réel

- **Regrouper les photos en documents.** L'interface suppose que les pages
  envoyées ensemble forment une facture. Sur le terrain, personne ne trie.
- **Contrôle qualité à la capture** : détecter flou et reflet pour redemander
  la photo pendant que l'utilisateur tient encore le document. C'est le
  moment où la correction coûte le moins cher.
- **Correction manuelle.** Les lignes douteuses sont signalées mais pas
  modifiables. Un TEDS de 0,94 laisse des cellules fausses ; sur des factures
  médicales, ça ne se livre pas sans relecture.
- **Authentification et chiffrement.** L'API est ouverte et en clair. Elle
  transporte des noms de patients — inacceptable au-delà d'un réseau local
  de démonstration.
