"""
Vocabulaire realiste (anglais) pour les DEUX PREMIERES PAGES du formulaire
"Periodic Health Examination Record" (version anglaise fournie par Halfaa,
health record_en.docx) : bloc administratif + antecedents, jusqu'a la
signature de confirmation. La suite du document (I. MEDICAL HISTORY,
II. PHYSICAL EXAMINATION, ...) est une page 3 et suivantes, hors perimetre
de ce generateur -- cf. README.

Pas de "nomenclature officielle" a respecter pour un nom ou une adresse ici.
Deux endroits gardent une source verifiable :

  - les maladies professionnelles listees a l'item 12 (colonne "Occupational
    disease name") viennent de la liste des maladies professionnelles
    indemnisees par l'assurance sociale vietnamienne (Thong tu 15/2016/TT-BYT,
    remplace depuis par le Thong tu 60/2025/TT-BYT) -- silicose, bronchite,
    asthme et saturnisme professionnels y figurent explicitement.
  - la classification de sante (Type I..V) vient du Thong tu 14/2013/TT-BYT,
    deja utilisee dans le generateur precedent.
"""

import random

PRENOMS = ["James", "Mary", "Robert", "Linda", "Michael", "Patricia",
           "David", "Jennifer", "William", "Elizabeth", "Richard", "Susan"]
NOMS = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia",
        "Miller", "Davis", "Rodriguez", "Martinez", "Wilson", "Anderson"]

OCCUPATIONS = ["Office worker", "Construction worker", "Primary school teacher",
               "Accountant", "Delivery driver", "Registered nurse",
               "Software engineer", "Factory worker", "Sales assistant",
               "Electrician"]

WORKPLACES = ["Song Hong Textile Co., Ltd.", "Thang Long Construction JSC",
              "Green Valley Elementary School", "Minh Phat Logistics",
              "Sunrise Electronics Factory", "Bach Mai General Hospital"]

STREETS = ["12 Elm Street", "45 Nguyen Trai Road", "8 Riverside Avenue",
           "230 Le Loi Boulevard", "5 Maple Lane", "77 Tran Hung Dao Street"]
CITIES = ["Hanoi", "Ho Chi Minh City", "Da Nang", "Hai Phong", "Can Tho"]

PREPARERS = ["Nurse Nguyen Thi Hoa", "Nurse Tran Van Minh", "Dr. Le Thi Lan",
             "Nurse Pham Van Hung", "Dr. Hoang Thi Mai"]

FAMILY_HISTORY = [
    "Father: hypertension. Mother: type 2 diabetes.",
    "No significant family history reported.",
    "Mother: breast cancer, diagnosed age 58.",
    "Father: coronary artery disease. No other family history.",
    "Sister: asthma since childhood.",
]

# Item 12, colonne "Disease name" (antecedent personnel, pas professionnel).
ITEM12_DISEASES = [
    "Hypertension", "Type 2 diabetes mellitus", "Chronic gastritis",
    "Seasonal allergic rhinitis", "Bronchial asthma",
    "Chronic viral hepatitis B",
]

# Item 12, colonne "Occupational disease name" -- liste des maladies
# professionnelles indemnisees par l'assurance sociale (Thong tu 15/2016/TT-BYT,
# maj Thong tu 60/2025/TT-BYT) : verifie via recherche, la circulaire couvre
# explicitement les pneumoconioses (silicose, coton...), la bronchite, l'asthme
# et le saturnisme professionnels.
OCCUPATIONAL_DISEASES = [
    "Occupational silicosis", "Occupational bronchitis",
    "Occupational asthma", "Occupational lead poisoning",
    "Byssinosis (cotton dust-induced lung disease)",
]

# Item 10 : postes precedents (10 dernieres annees). Reutilise OCCUPATIONS.
PREVIOUS_JOBS = OCCUPATIONS


def _id_number(rng):
    return "".join(str(rng.randint(0, 9)) for _ in range(12))


def _phone(rng):
    return "0" + "".join(str(rng.randint(0, 9)) for _ in range(9))


def _date(rng, annee_min, annee_max):
    return (f"{rng.randint(1,28):02d}/{rng.randint(1,12):02d}/"
            f"{rng.randint(annee_min, annee_max)}")


def _tirer_job_precedent(rng, annee_min, annee_max):
    annee_debut = rng.randint(annee_min, annee_max - 1)
    duree_ans = rng.randint(0, 4)
    duree_mois = rng.randint(0, 11)
    annee_fin = min(annee_debut + duree_ans, annee_max)
    return {
        "nom": rng.choice(PREVIOUS_JOBS),
        "annees": duree_ans,
        "mois": duree_mois,
        "depuis": _date(rng, annee_debut, annee_debut),
        "jusque": _date(rng, annee_fin, annee_fin),
    }


def _item10(rng, naissance_an):
    """0 a 2 emplois precedents, le plus recent d'abord -- champ souvent
    vide en pratique chez un jeune actif a son premier poste."""
    annee_min = max(naissance_an + 18, 2016)
    annee_max = 2026
    n = rng.choices([0, 1, 2], weights=[35, 40, 25])[0]
    postes = [_tirer_job_precedent(rng, annee_min, annee_max) for _ in range(n)]
    out = {}
    for lettre, idx in (("a", 0), ("b", 1)):
        if idx < len(postes):
            j = postes[idx]
            out[f"prev_job_{lettre}"] = j["nom"]
            out[f"prev_job_{lettre}_years"] = str(j["annees"])
            out[f"prev_job_{lettre}_months"] = str(j["mois"])
            out[f"prev_job_{lettre}_from"] = j["depuis"]
            out[f"prev_job_{lettre}_to"] = j["jusque"]
        else:
            for suffixe in ("", "_years", "_months", "_from", "_to"):
                out[f"prev_job_{lettre}{suffixe}"] = ""
    return out


def _item12(rng, naissance_an):
    """Table 4 lignes (a-d) x 2 paires de colonnes. La plupart des cases
    restent vides sur un vrai formulaire -- rarement plus d'une maladie
    personnelle notee, une maladie professionnelle est rare."""
    annee_min = max(naissance_an + 15, 1995)
    n_perso = rng.choices([0, 1, 2], weights=[50, 35, 15])[0]
    n_pro = rng.choices([0, 1], weights=[82, 18])[0]
    maladies_perso = rng.sample(ITEM12_DISEASES, k=min(n_perso, len(ITEM12_DISEASES)))
    maladies_pro = rng.sample(OCCUPATIONAL_DISEASES, k=min(n_pro, len(OCCUPATIONAL_DISEASES)))

    out = {}
    for i, lettre in enumerate(("a", "b", "c", "d")):
        if i < len(maladies_perso):
            out[f"disease_{lettre}_name"] = maladies_perso[i]
            out[f"disease_{lettre}_year"] = str(rng.randint(annee_min, 2025))
        else:
            out[f"disease_{lettre}_name"] = ""
            out[f"disease_{lettre}_year"] = ""
        if i < len(maladies_pro):
            out[f"disease_{lettre}_occ_name"] = maladies_pro[i]
            out[f"disease_{lettre}_occ_year"] = str(rng.randint(annee_min, 2025))
        else:
            out[f"disease_{lettre}_occ_name"] = ""
            out[f"disease_{lettre}_occ_year"] = ""
    return out


def tirer_patient(rng):
    prenom, nom = rng.choice(PRENOMS), rng.choice(NOMS)
    sexe = "Female" if prenom in ("Mary", "Linda", "Patricia", "Jennifer",
                                  "Elizabeth", "Susan") else "Male"
    naissance_an = rng.randint(1955, 2002)
    exam_day, exam_month = rng.randint(1, 28), rng.randint(1, 12)

    p = {
        "full_name": f"{prenom} {nom}",
        "sex": sexe,
        "dob": f"{rng.randint(1,28):02d}/{rng.randint(1,12):02d}/{naissance_an}",
        "age": 2026 - naissance_an,
        "id_number": _id_number(rng),
        "id_issue_date": _date(rng, 2015, 2024),
        "id_issue_place": rng.choice(CITIES),
        "address": f"{rng.choice(STREETS)}, {rng.choice(CITIES)}",
        "phone": _phone(rng),
        "occupation": rng.choice(OCCUPATIONS),
        "workplace": rng.choice(WORKPLACES),
        "work_start": _date(rng, 2010, 2023),
        "family_history": rng.choice(FAMILY_HISTORY),
        "preparer": rng.choice(PREPARERS),
        "confirm_place": rng.choice(CITIES),
        "confirm_day": str(exam_day),
        "confirm_month": str(exam_month),
        "confirm_year": "2026",
    }
    p.update(_item10(rng, naissance_an))
    p.update(_item12(rng, naissance_an))
    return p


if __name__ == "__main__":
    rng = random.Random(0)
    import json
    print(json.dumps(tirer_patient(rng), indent=2, ensure_ascii=False))
