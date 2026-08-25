"""
Vocabulaire realiste pour le tableau de suivi PHCN (page 9 du formulaire 27/BV1).

Les noms de technique viennent de la nomenclature OFFICIELLE du Bo Y te :
« Huong dan quy trinh ky thuat Phuc hoi chuc nang » (Quyet dinh 5737/QD-BYT,
22/12/2017), 120 techniques. On ne les invente pas -- un faux nom de
technique fausserait le test (un modele pourrait "deviner" juste parce que
le terme est plausible en vietnamien sans etre le bon terme medical).

Source : https://kcb.vn/upload/2005611/20210723//Quy-trinh-ky-thuat-PHCN-dot-2-QD-5737.2017-Bo-Y-te.pdf
(table des matieres, 120 techniques numerotees)

On ne reprend qu'un sous-ensemble : celles qui reviennent plausiblement
plusieurs fois dans le sejour d'un meme patient (physiotherapie generale,
electrotherapie, reeducation a la marche) plutot que les actes ponctuels
(pose de platre, injection de toxine botulique) qui n'apparaitraient qu'une
fois dans un vrai dossier.
"""

import random

# --- 1. Techniques PHCN, telles que nommees dans la nomenclature officielle ---
TECHNIQUES = [
    "Điều trị bằng điện vi dòng",
    "Điều trị bằng laser công suất thấp chiếu ngoài",
    "Kỹ thuật kích thích điện chức năng (FES)",
    "Điều trị chườm ngải cứu",
    "Thủy trị liệu có thuốc",
    "Điều trị bằng bồn tắm tương phản nóng - lạnh",
    "Điều trị bằng bồn xoa bóp thủy lực",
    "Kỹ thuật điều trị bằng máy ép khí ngắt quãng",
    "Tập vận động cột sống",
    "Kỹ thuật xoa bóp bằng máy",
    "Kỹ thuật xoa bóp toàn thân",
    "Kỹ thuật xoa bóp dẫn lưu",
    "Tập dưỡng sinh",
    "Kỹ thuật thư giãn",
    "Tập đi với gậy",
    "Tập với máy tập thăng bằng",
    "Kỹ thuật tập vận động trên máy chức năng",
    "Kỹ thuật tập sức bền có gắn theo dõi tim mạch",
    "Kỹ thuật tập mạnh cơ với máy Isokinetic",
    "Kỹ thuật tập đi trên máy chạy thảm lăn (Treadmill)",
    "Kỹ thuật kiểm soát tư thế (ngồi, bò, đứng, đi)",
    "Kỹ thuật tập thở với dụng cụ",
    "Kỹ thuật tập ngồi/đứng dậy từ sàn nhà",
    "Kỹ thuật tư vấn tâm lý cho người bệnh hoặc người nhà",
    "Kỹ thuật tập mạnh cơ đáy chậu (cơ sàn chậu) bằng dụng cụ",
]

# --- 2. Descriptions courtes de l'evolution (registre clinique PHCN generique) ---
# Vocabulaire generique et plausible -- pas de diagnostic invente attribue a
# une personne reelle.
DESCRIPTIONS = [
    "Cơ lực chi dưới cải thiện, còn hạn chế duỗi gối",
    "Bệnh nhân hợp tác tốt, mức độ đau giảm rõ",
    "Tầm vận động khớp vai tăng nhẹ so với buổi trước",
    "Còn co cứng cơ nhị đầu, tập kéo giãn thêm",
    "Dáng đi cải thiện, giảm lệch trọng tâm sang bên lành",
    "Thăng bằng đứng tĩnh tốt hơn, cần trợ giúp khi đi",
    "Sức cơ tứ đầu đùi 3/5, tiếp tục bài tập chủ động có trợ giúp",
    "Bệnh nhân mệt sau 15 phút tập, giảm cường độ buổi tới",
    "Biên độ gấp khuỷu cải thiện, chưa đau khi vận động",
    "Phù nề giảm, tiếp tục dẫn lưu bạch huyết",
    "Khả năng tự xoay trở trên giường tốt hơn",
    "Còn khó khăn khi đứng dậy từ ghế, cần một người trợ giúp",
]

# --- 3. Noms genériques (vietnamiens courants) pour le personnel ---
NOMS_KTV = [
    "Nguyễn Thị Hoa", "Trần Văn Nam", "Lê Thị Mai", "Phạm Văn Hùng",
    "Đỗ Thị Lan", "Hoàng Văn Tùng", "Vũ Thị Ngọc", "Bùi Văn Sơn",
]
NOMS_BS = [
    "BS. Nguyễn Văn An", "BS. Trần Thị Bích", "BS. Lê Văn Cường",
    "BS. Phạm Thị Dung", "BS. Hoàng Văn Đức",
]
NOMS_PATIENT = [
    ("Nguyễn Văn Thành", 1958, "Nam"), ("Trần Thị Bảy", 1972, "Nữ"),
    ("Lê Văn Hòa", 1965, "Nam"), ("Phạm Thị Sen", 1980, "Nữ"),
    ("Đỗ Văn Kiên", 1991, "Nam"), ("Hoàng Thị Yến", 1969, "Nữ"),
]
CHAN_DOAN = [
    "Di chứng tai biến mạch máu não liệt nửa người trái",
    "Thoái hóa cột sống thắt lưng, đau thần kinh tọa",
    "Gãy cổ xương đùi phải đã phẫu thuật kết hợp xương",
    "Chấn thương tủy sống ngực D10 liệt hai chi dưới",
    "Viêm quanh khớp vai phải",
]

# --- 4. Sở Y tế / Bộ Y tế de tutelle -- champ d'en-tete laisse vide jusqu'ici
# (juste des pointilles), alors qu'il est normalement rempli a la main ou
# tamponne sur un vrai formulaire.
SO_Y_TE = [
    "Sở Y tế Hà Nội", "Sở Y tế TP. Hồ Chí Minh", "Sở Y tế Hải Phòng",
    "Sở Y tế Đà Nẵng", "Bộ Y tế",
]


def _tuoi(nam_sinh, nam_hien_tai=2026):
    return nam_hien_tai - nam_sinh


def tirer_patient(rng):
    ten, nam_sinh, gioi = rng.choice(NOMS_PATIENT)
    return {
        "ten": ten, "nam_sinh": nam_sinh, "gioi": gioi,
        "tuoi": _tuoi(nam_sinh),
        "khoa": "Phục hồi chức năng",
        "buong": str(rng.randint(1, 12)),
        "giuong": str(rng.randint(1, 8)),
        "chan_doan": rng.choice(CHAN_DOAN),
        "so_y_te": rng.choice(SO_Y_TE),
    }


def tirer_lignes(rng, n):
    """n lignes du tableau de suivi, avec des dates qui avancent."""
    lignes = []
    jour, mois = rng.randint(1, 20), rng.randint(1, 12)
    heure = rng.choice([7, 8, 9, 14, 15, 16])
    for _ in range(n):
        lignes.append({
            "ngay_gio": f"{heure}h{rng.choice(['00','15','30','45'])} "
                        f"{jour:02d}/{mois:02d}",
            "mo_ta": rng.choice(DESCRIPTIONS),
            "ky_thuat": rng.choice(TECHNIQUES),
            "thoi_gian": str(rng.choice([15, 20, 30, 45, 60])),
            "nguoi_thuc_hien": rng.choice(NOMS_KTV),
            "bs_chi_dinh": rng.choice(NOMS_BS),
            "xac_nhan": rng.choice(["Đã ký", "Đồng ý", "X"]),
        })
        # avance d'un jour de temps en temps, comme un vrai suivi
        if rng.random() < 0.6:
            jour += 1
            if jour > 28:
                jour = 1
                mois = mois % 12 + 1
    return lignes


if __name__ == "__main__":
    rng = random.Random(0)
    print(tirer_patient(rng))
    for l in tirer_lignes(rng, 3):
        print(l)
