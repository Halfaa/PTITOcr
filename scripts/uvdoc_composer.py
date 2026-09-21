"""
Plaque nos documents sur de VRAIES deformations de papier (jeu UVDoc).

Pourquoi ce script plutot que leur `create_final.py`
-----------------------------------------------------
UVDoc a photographie de vraies feuilles blanches deformees, avec capture de
profondeur et lumiere structuree. Pour chaque prise ils publient une
`uvmap` : la correspondance exacte entre chaque pixel de la photo et sa
position sur la feuille a plat. La geometrie est donc entierement decouplee
du contenu -- on peut y faire passer n'importe quelle texture.

Leur `create_final.py` fait beaucoup plus que ca, et trois de ces choses nous
nuisent :

1. il redimensionne les textures a 488x712 par defaut (`--img-size`). Notre
   propre mesure de degradation fixe le plancher de lisibilite a 950 px de
   largeur de page ; a 488 px on mesurerait la resolution, pas la deformation ;
2. il ecrit des coordonnees monde en `.exr` via `imageio-freeimage`, qui se
   telecharge a l'import et s'installe mal sous Windows ;
3. il calcule grilles 3D, profondeur et retournements, dont on n'a aucun usage.

Ici on ne garde que `uvmap` + `rgb` + `seg`, a la resolution native.

Ce que ca produit, et pourquoi c'est l'oracle de dewarping
------------------------------------------------------------
Pour chaque echantillon on ecrit DEUX images du meme document :

    deforme/<texture>-<geometrie>.png   le document photographie, courbe
    plat/<texture>-<geometrie>.png      le meme, parfaitement a plat

Le second n'est pas une reconstruction : c'est la texture d'origine, donc le
resultat qu'un dewarping PARFAIT rendrait. Passer le modele sur les deux jeux
et comparer donne le **plafond** : ce que la correction geometrique peut
rapporter au maximum. Un dewarping reel se situera entre les deux, jamais
au-dessus.

Le nom `<texture>-<geometrie>` est voulu : `VeriteDir.get()` dans
`eval_handwriting.py` retombe deja sur `stem.split("-")[0]`, donc la verite
terrain de nos specimens est retrouvee sans rien modifier.

Quel paquet telecharger
-------------------------
`UVDoc_raw.zip` pese 22 Go et contient huit sous-dossiers dont on en utilise
trois. `UVDoc_benchmark.zip` publie deja `img_geom/`, `uvmap/` et `seg/` a la
resolution native -- c'est celui a prendre. `UVDoc_final.zip` a les memes
dossiers mais redimensionnes a 488x712, sous notre plancher de lisibilite :
il ne sert a rien ici.

Usage :
    python scripts/uvdoc_composer.py --raw ..\\UVDoc_benchmark \\
        --textures ..\\handwriting\\specimens --n 30
"""

import argparse
import json
import random
from pathlib import Path

import cv2
import numpy as np
from scipy.ndimage import binary_erosion, gaussian_filter

EXT = (".png", ".jpg", ".jpeg")


def _charger_mat(chemin: Path, cle: str):
    """Lit un .mat, v7.3 (HDF5) ou anterieur.

    UVDoc publie des .mat v7.3 que `scipy.io.loadmat` ne sait pas ouvrir.
    On essaie scipy d'abord parce qu'il est deja installe, et on ne tombe sur
    hdf5storage que si necessaire -- ca evite une dependance obligatoire.
    """
    try:
        from scipy.io import loadmat
        return loadmat(str(chemin))[cle]
    except (NotImplementedError, ValueError):
        import hdf5storage
        return hdf5storage.loadmat(str(chemin))[cle]


def _lire_image(chemin: Path) -> np.ndarray:
    """cv2.imread ne gere pas les chemins non-ASCII sous Windows."""
    data = np.fromfile(str(chemin), dtype=np.uint8)
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit(f"Image illisible : {chemin}")
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def _lire_image_ou_none(chemin: Path):
    """Comme `_lire_image`, mais rend None si le fichier manque ou est illisible."""
    if not chemin.exists():
        return None
    data = np.fromfile(str(chemin), dtype=np.uint8)
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def _ecrire_image(chemin: Path, img_rgb: np.ndarray) -> None:
    bgr = cv2.cvtColor(img_rgb.astype(np.uint8), cv2.COLOR_RGB2BGR)
    ok, buf = cv2.imencode(".png", bgr)
    if not ok:
        raise SystemExit(f"Encodage impossible : {chemin}")
    buf.tofile(str(chemin))


def deformer(texture: np.ndarray, uvmap: np.ndarray) -> np.ndarray:
    """Fait passer la texture dans l'uvmap. Sortie a la taille de l'uvmap.

    UVDoc utilise `torch.nn.functional.grid_sample`. `cv2.remap` fait la meme
    chose, sans charger torch pour un echantillonnage bilineaire -- et sans
    materialiser la texture entiere en float32, ce qui compte sur des pages
    A4 a 1654 px.

    La conversion de convention n'est pas cosmetique. `grid_sample` avec
    `align_corners=False` lit une coordonnee normalisee g dans [-1, 1] a
    l'abscisse ((g + 1) * W - 1) / 2. Ici uv est dans [0, 1], donc g = 2u - 1
    et l'abscisse vaut u * W - 0.5. C'est ce demi-pixel qui aligne les centres
    de pixel ; l'oublier decale toute l'image d'un demi-pixel et emousse le
    texte, ce qui se verrait sur le score sans se voir a l'oeil.
    """
    h_t, l_t = texture.shape[:2]
    map_x = (uvmap[:, :, 0] * l_t - 0.5).astype(np.float32)
    map_y = (uvmap[:, :, 1] * h_t - 0.5).astype(np.float32)
    return cv2.remap(texture, map_x, map_y, cv2.INTER_LINEAR,
                     borderMode=cv2.BORDER_CONSTANT,
                     borderValue=(255, 255, 255)).astype(np.float32)


def echelle_pour(seg: np.ndarray, largeur_page: int) -> float:
    """Facteur qui amene le DOCUMENT a `largeur_page` pixels de large.

    On normalise sur la largeur du document, pas sur celle de l'image. Les
    captures UVDoc n'ont pas toutes la meme taille (1041 a 1462 px de large
    selon la prise), donc un facteur d'agrandissement constant produirait un
    jeu ou la resolution varie d'une page a l'autre -- alors que la reference
    plate, elle, est fixe. La resolution deviendrait un facteur parasite : on
    ne saurait plus si l'ecart mesure vient de la deformation ou du nombre de
    pixels, et c'est precisement la question qu'on pose.

    Deux contraintes fixent la valeur a demander :
      - au-dessus de 950 px, notre plancher de lecture mesure ;
      - sous ~3,8 Mpx par image, plafond au-dela duquel Chandra tombe en
        CUDA OOM sur un T4 de 16 Go (mesure : 3,80 Mpx passe, 4,06 casse).
    1400 px tient les deux avec de la marge.
    """
    colonnes = np.nonzero(seg.any(axis=0))[0]
    if colonnes.size == 0:
        raise ValueError("masque vide")
    return largeur_page / float(colonnes[-1] - colonnes[0] + 1)


def agrandir(geom, seg, uvmap, echelle: float):
    """Rend la scene a une resolution superieure a celle de la capture.

    Necessaire : les captures UVDoc, recadrees serre, font ~850-1050 px de
    large. Notre propre mesure de degradation place le plancher de lecture a
    950 px de largeur de PAGE. Tel quel, on mesurerait un melange de
    deformation et de resolution insuffisante, et on ne pourrait pas
    attribuer la perte a l'une ou a l'autre.

    Pourquoi c'est legitime : l'uvmap decrit une feuille de papier courbee,
    donc une surface LISSE. L'interpoler n'invente aucun detail geometrique,
    parce qu'il n'y en a pas a cette echelle. Et notre texture est native a
    1654 px : echantillonnee plus finement, elle rend un texte reellement
    plus net, pas un texte reagrandi.

    Ce qui est effectivement degrade, et qu'il faut dire : `geom` est une
    vraie photo, donc son ombrage, son grain et son flou d'objectif sont
    lisses par l'agrandissement. Les images sont donc un peu OPTIMISTES sur
    la photometrie. Ca ne touche pas ce qui porte les lettres -- la mesure de
    degradation a montre que bruit, exposition et JPEG ne coutent rien -- mais
    ces images ne valent pas pour etudier le bruit capteur.
    """
    if echelle == 1.0:
        return geom, seg, uvmap
    h, l = geom.shape[:2]
    taille = (int(round(l * echelle)), int(round(h * echelle)))
    return (
        cv2.resize(geom, taille, interpolation=cv2.INTER_CUBIC),
        # NEAREST : le masque est binaire, l'interpoler creerait des valeurs
        # intermediaires sur tout le contour de la feuille.
        cv2.resize(seg, taille, interpolation=cv2.INTER_NEAREST),
        cv2.resize(uvmap, taille, interpolation=cv2.INTER_LINEAR),
    )


def composer(geom: np.ndarray, seg: np.ndarray, uvmap: np.ndarray,
             texture: np.ndarray, force_ombre: float = 0.75) -> np.ndarray:
    """Combine la photo de la feuille blanche et notre texture deformee.

    `geom` est une VRAIE photo : elle porte les ombres reelles, le flou
    d'objectif et le bruit capteur de la prise. C'est tout l'interet par
    rapport a notre rendu Blender, que les rapports signalent comme le « cas
    optimiste ». On multiplie la texture par cette photo pour en heriter.

    Le masque vient de `seg`, la segmentation publiee par les auteurs. Leur
    code deduit le masque des pixels exactement gris dans la texture deformee,
    ce qui est fragile : un document reellement gris a cet endroit y ferait un
    trou.
    """
    masque = (seg > 0.5).astype(np.uint8)
    masque_erode = binary_erosion(masque).astype(np.uint8)[..., None]

    deformee = deformer(texture, uvmap)
    # Les bords du masque melangent document et fond : on les repousse d'un
    # pixel plutot que de laisser une frange sombre le long de la feuille.
    deformee = deformee * masque_erode + 255 * (1 - masque_erode)

    # Leger flou : sans lui, le reechantillonnage laisse un crenelage que le
    # modele lit comme du bruit de trait.
    floue = np.empty_like(deformee)
    for c in range(3):
        floue[:, :, c] = gaussian_filter(deformee[:, :, c], 0.5)

    produit = floue.astype(float) * geom.astype(float) / 255
    a = force_ombre * masque_erode
    return np.clip(produit * a + geom * (1 - a), 0, 255)


def reperer(racine: Path) -> dict:
    """Localise rgb / uvmap / seg, quel que soit le paquet UVDoc utilise.

    Trois archives publiees, trois arborescences, et elles ne se valent pas :

      UVDoc_raw        samples/{rgb,uvmap,seg}/    22 Go, resolution native
      UVDoc_benchmark  {img_geom,uvmap,seg}/       resolution native aussi :
                       `--benchmark_set` passe par crop_tight_fn et ne
                       redimensionne rien
      UVDoc_final      {img_geom,uvmap,seg}/       REDIMENSIONNE a 488x712 par
                       defaut -- sous notre plancher de 950 px, donc inutile
                       pour mesurer autre chose que la resolution

    On accepte les trois et on laisse le controle de largeur, en fin de
    traitement, dire si le paquet choisi convient.
    """
    for base, nom_rgb in ((racine / "samples", "rgb"), (racine, "img_geom")):
        rgb, uv, seg = base / nom_rgb, base / "uvmap", base / "seg"
        if rgb.is_dir() and uv.is_dir() and seg.is_dir():
            return {"rgb": rgb, "uvmap": uv, "seg": seg}
    raise SystemExit(
        f"Arborescence UVDoc non reconnue sous {racine}.\n"
        "Attendu samples/{rgb,uvmap,seg}/ (raw) ou {img_geom,uvmap,seg}/ "
        "(benchmark, final).")


def geometries(dossiers: dict) -> list:
    return sorted(p.stem for p in dossiers["rgb"].iterdir()
                  if p.suffix.lower() in EXT)


def trouver_textures(racine: Path) -> list:
    """Nos documents, a plat ou ranges un par sous-dossier.

    Le generateur manuscrit ecrit `generated/specimen_000/specimen_000.png`,
    un dossier par specimen ; les jeux degrades sont a plat. On accepte les
    deux, et on ne garde qu'un fichier par nom : un meme specimen presente
    deux fois fausserait l'appariement texture/geometrie sans rien signaler.
    """
    if not racine.is_dir():
        raise SystemExit(f"{racine} n'est pas un dossier.")
    par_stem = {}
    for p in sorted(racine.rglob("*")):
        if p.is_file() and p.suffix.lower() in EXT:
            par_stem.setdefault(p.stem, p)
    return [par_stem[k] for k in sorted(par_stem)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True,
                    help="Dossier UVDoc decompresse (raw, benchmark ou final).")
    ap.add_argument("--textures", required=True,
                    help="Dossier de nos documents (specimens, factures).")
    ap.add_argument("--sortie", default="../datasets/uvdoc_compose")
    ap.add_argument("--n", type=int, default=30, help="Nombre d'echantillons.")
    ap.add_argument("--graine", type=int, default=12345)
    ap.add_argument("--force-ombre", type=float, default=0.75,
                    help="0 = aucune ombre, 1 = ombrage de la photo en entier.")
    ap.add_argument("--refaire", action="store_true",
                    help="Recomposer meme ce qui existe deja.")
    ap.add_argument("--largeur-page", type=int, default=1400,
                    help="Largeur du DOCUMENT, en pixels, identique des deux "
                         "cotes. Au-dessus du plancher de lecture (950 px) et "
                         "sous le plafond memoire de Chandra sur T4 "
                         "(~3,8 Mpx par image).")
    args = ap.parse_args()

    racine = Path(args.raw)
    textures = trouver_textures(Path(args.textures))
    if not textures:
        raise SystemExit(f"Aucune image dans {args.textures}")

    dossiers = reperer(racine)
    geoms = geometries(dossiers)
    print(f"{len(geoms)} geometries ({dossiers['rgb']}), "
          f"{len(textures)} textures")

    sortie = Path(args.sortie)
    (sortie / "deforme").mkdir(parents=True, exist_ok=True)
    (sortie / "plat").mkdir(parents=True, exist_ok=True)
    (sortie / "uv").mkdir(parents=True, exist_ok=True)

    alea = random.Random(args.graine)
    # Chaque texture est appariee a une geometrie tiree au sort. Le tirage est
    # reproductible : sans graine fixe, deux mesures ne portent pas sur les
    # memes images et ne se comparent pas.
    paires = [(textures[i % len(textures)], alea.choice(geoms))
              for i in range(args.n)]

    manifeste = []
    for i, (texture_p, geom_id) in enumerate(paires, start=1):
        nom = f"{texture_p.stem}-{geom_id}"

        # Reprise : composer une page coute quelques secondes et une trentaine
        # depasse la plupart des delais d'execution. Le tirage etant
        # reproductible, ce qui est deja ecrit est exactement ce qu'on
        # reecrirait -- on le garde et on reprend la suite.
        #
        # On RELIT les deux images au lieu de tester leur existence. Un
        # processus tue entre les deux ecritures laisse un PNG tronque, que
        # `exists()` accepte : la paire serait sautee et le jeu contiendrait
        # une image illisible, decouverte seulement au moment du benchmark.
        if not args.refaire:
            paire = [_lire_image_ou_none(sortie / c / f"{nom}.png")
                     for c in ("deforme", "plat")]
            if all(x is not None for x in paire):
                manifeste.append({
                    "nom": nom, "texture": texture_p.name,
                    "geometrie": geom_id,
                    "taille_deforme": list(paire[0].shape[:2][::-1]),
                    "taille_plat": list(paire[1].shape[:2][::-1])})
                print(f"  [{i}/{len(paires)}] {nom}  deja compose")
                continue

        try:
            geom = _lire_image(dossiers["rgb"] / f"{geom_id}.png")
            uvmap = np.asarray(
                _charger_mat(dossiers["uvmap"] / f"{geom_id}.mat", "uv"),
                dtype=np.float32)
            seg = np.asarray(
                _charger_mat(dossiers["seg"] / f"{geom_id}.mat", "seg"),
                dtype=np.float32)
        except Exception as e:
            print(f"  [{i}/{len(paires)}] {nom} : {type(e).__name__} {e}")
            continue

        texture = _lire_image(texture_p)
        geom, seg, uvmap = agrandir(
            geom, seg, uvmap, echelle_pour(seg, args.largeur_page))
        img = composer(geom, seg, uvmap, texture, args.force_ombre)

        _ecrire_image(sortie / "deforme" / f"{nom}.png", img)

        # La reference « plat » est ramenee a la MEME largeur de page que la
        # version deformee. Garder la texture native (1654 px) donnerait a la
        # reference un avantage de resolution, et l'ecart mesure melangerait
        # deformation et finesse -- ce qu'on cherche justement a separer.
        h_t, l_t = texture.shape[:2]
        plat = cv2.resize(
            texture,
            (args.largeur_page, int(round(h_t * args.largeur_page / l_t))),
            interpolation=cv2.INTER_AREA)
        _ecrire_image(sortie / "plat" / f"{nom}.png", plat)
        np.savez_compressed(sortie / "uv" / f"{nom}.npz", uv=uvmap)

        manifeste.append({"nom": nom, "texture": texture_p.name,
                          "geometrie": geom_id,
                          "taille_deforme": list(img.shape[:2][::-1]),
                          "taille_plat": list(texture.shape[:2][::-1])})
        print(f"  [{i}/{len(paires)}] {nom}  {img.shape[1]}x{img.shape[0]}")

    (sortie / "manifeste.json").write_text(json.dumps(
        {"graine": args.graine, "raw": str(racine),
         "force_ombre": args.force_ombre, "echantillons": manifeste},
        ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"\n{len(manifeste)}/{len(paires)} composes -> {sortie}")
    if manifeste:
        l = manifeste[0]["taille_deforme"][0]
        print(f"Largeur des images deformees : {l} px "
              f"({'au-dessus' if l >= 950 else 'SOUS'} le plancher de 950 px)")
    print("\nRegarde deforme/ avant d'engager un run : orientation, cadrage, "
          "et surtout que le texte soit lisible a l'oeil.")


if __name__ == "__main__":
    main()
