"""
Extraction of the header fields of an invoice (outside the table).

The table carries the line items; the header carries what the internship
subject explicitly asks for -- patient name, date, prescribing doctor. That
text sits OUTSIDE the <table>, in the free-text part of the OCR markdown.

Two difficulties make naive label matching useless here:

  1. diacritics are mangled ("Họ tên" read as "Hotēn", "Bác sỹ" as "Bac sy");
  2. spacing is unreliable -- PP-StructureV3 emits run-on text such as
     "Ngayxuathoa don:05/07/2011Hotēn:BuiHaiSu Tù Bac sy ke don:ThS.BS...".

So we search on a DE-ACCENTED, LOWERCASED copy that keeps the exact same
length as the original (one character in, one character out). Positions found
on that copy therefore map straight back to the raw text, which lets us
return the value with its original diacritics untouched.

Labels are matched with optional whitespace between every character, which
absorbs both missing and spurious spaces.
"""

import re
import unicodedata

# Field -> label variants found on these invoices. The first match wins, so
# the more specific variants come first.
FIELD_LABELS = {
    "invoice_date": ["ngay xuat hoa don", "ngay lap hoa don", "ngay xuat",
                     "ngay lap", "ngay hoa don"],
    "customer_name": ["ho va ten nguoi mua", "ho ten nguoi mua", "ho va ten", "ho ten"],
    "doctor": ["bac sy ke don", "bac si ke don", "bac sy", "bac si"],
    "address": ["dia chi"],
    "seller": ["nv ban hang", "nhan vien ban hang"],
    "payment_method": ["hinh thuc thanh toan"],
    "invoice_number": ["so ct"],
    "phone": ["so dt", "dien thoai"],
}


# Vietnamese "đ" is a distinct letter, not a "d" carrying a diacritic: NFKD
# leaves it untouched. Without this explicit mapping every label containing
# "đơn" ("hóa đơn", "kê đơn") silently fails to match.
_EXTRA = {"đ": "d", "Đ": "d", "ð": "d", "Ð": "d"}


def _deaccent_keep_length(text: str) -> str:
    """Strip diacritics WITHOUT changing the string length.

    unicodedata.normalize would change it (é -> e + combining accent), which
    would break the mapping back to the raw text. So we decompose character
    by character and keep only the base letter.
    """
    out = []
    for ch in text:
        if ch in _EXTRA:
            out.append(_EXTRA[ch])
            continue
        decomposed = unicodedata.normalize("NFKD", ch)
        base = "".join(c for c in decomposed if not unicodedata.combining(c))
        out.append(base[0] if base else ch)
    return "".join(out).lower()


def _label_pattern(label: str) -> str:
    """'ho ten' -> 'h\\s*o\\s*t\\s*e\\s*n', tolerant to any spacing."""
    letters = [re.escape(c) for c in label if not c.isspace()]
    return r"\s*".join(letters)


def _all_label_positions(flat: str):
    """Every label occurrence, to know where a value ends."""
    spans = []
    for field, variants in FIELD_LABELS.items():
        for variant in variants:
            for m in re.finditer(_label_pattern(variant), flat):
                spans.append((m.start(), m.end(), field))
    return sorted(spans)


def _best_label_match(variant, flat, text):
    """Find the occurrence of a label that is really a FIELD label.

    A field label is followed by a colon; the same words inside a sentence
    are not. That distinction matters because the footer of these invoices
    contains legal prose -- "theo chi dinh cua bac si dieu tri va phai trong
    thoi han 5 ngay" -- in which "bac si" occurs as an ordinary word. Taking
    the first match blindly filled the doctor field with "dieu tri va phai
    trong thoi han 5", a wrong value that nothing downstream can catch. An
    empty field is honest; a plausible-looking wrong one is not.

    So: prefer an occurrence followed by a colon, and only fall back to a
    bare one when no labelled occurrence exists -- some models drop the
    punctuation altogether.
    """
    pattern = _label_pattern(variant)
    fallback = None
    for m in re.finditer(pattern, flat):
        tail = text[m.end():m.end() + 4]
        if ":" in tail:
            return m
        if fallback is None:
            fallback = m
    return fallback


_NAME_FIELDS = {"doctor", "customer_name"}


def _looks_like_a_name(value: str) -> bool:
    """Reject a value that is running prose rather than a person's name.

    Vietnamese capitalises every syllable of a proper name, and these
    invoices carry legal prose in their footer -- "theo chi dinh cua bac si
    dieu tri va phai trong thoi han 5 ngay" -- in which "bac si" appears as
    an ordinary word. When the real doctor line is missing from the OCR, the
    label search used to land on that sentence and return "dieu tri va phai
    trong thoi han 5" as the doctor. A wrong value that looks plausible is
    worse than no value: nothing downstream can catch it, whereas an empty
    field is visibly empty.

    Requiring the colon of a real label would also work, but it costs true
    positives on models that drop punctuation -- PP-StructureV3 lost a
    doctor that way. Capitalisation separates the two cases without that
    price.
    """
    words = [w for w in re.split(r"[\s.]+", value) if w]
    if not words or len(words) > 8:
        return False
    upper = sum(1 for w in words if w[:1].isupper())
    return upper >= max(2, len(words) / 2)


def _drop_label_residue(value: str) -> str:
    """Remove the tail of a label that OCR mangled beyond recognition.

    Labels come in variants ("Bác sỹ kê đơn", "Bác sỹ"), and we try the long
    ones first. But when OCR misreads the long form -- "Bác sỹ kê đơn" read as
    "Bác sỹ kèm" -- only the short variant matches, and the leftover of the
    label is returned as part of the value: "kèm: ThS.BS. Ngô Fong Hà Mã".

    A label always ends with a colon and a value essentially never contains
    one. So a colon in the first few characters marks label residue, and
    everything up to it can be dropped. The window is kept short so that a
    legitimate value containing a colon further along is left alone.
    """
    colon = value.find(":")
    if 0 <= colon <= 15:
        return value[colon + 1:].strip(" \t:.-")
    return value


def extract_fields(text: str) -> dict:
    """Return {field: value or None} from the free text of a page.

    Only the text OUTSIDE tables is considered: a value found inside a table
    would be a line item, not a header field.
    """
    text = re.sub(r"<table.*?</table>", " ", text, flags=re.S)
    # Les tableaux Markdown doivent disparaitre au meme titre que les <table>.
    # Ne retirer que le HTML etait un reste de l'epoque ou l'on croyait que
    # tous les modeles rendaient du HTML : `table_merge` a du apprendre a lire
    # les tableaux en pipes, mais ce filtre-ci ne l'a jamais su. Une cellule
    # contenant « Ho ten: ... » -- un nom de medicament mal lu, une ligne de
    # tableau decalee -- pouvait donc etre servie comme nom de patient, et une
    # ligne de separation comme nom d'hopital. Verifie : sur un tableau en
    # pipes seul, `hospital_name` sortait egal a la ligne d'en-tete.
    #
    # On ne retire qu'une ligne ENTIEREMENT delimitee par des barres : une
    # phrase contenant un « | » isole n'est pas une ligne de tableau.
    text = re.sub(r"^[ \t]*\|.*\|[ \t]*$", " ", text, flags=re.M)
    text = re.sub(r"<[^>]+>", " ", text)
    flat = _deaccent_keep_length(text)

    all_spans = _all_label_positions(flat)
    found = {}

    for field, variants in FIELD_LABELS.items():
        if field in found:
            continue
        for variant in variants:
            match = _best_label_match(variant, flat, text)
            if not match:
                continue
            start = match.end()
            # Skip the separator (":" and surrounding spaces)
            while start < len(text) and text[start] in " :\t":
                start += 1
            # The value stops at the next label, a line break, or 80 chars.
            end = len(text)
            for s, _e, _f in all_spans:
                if s > start:
                    end = min(end, s)
                    break
            newline = text.find("\n", start)
            if newline != -1:
                end = min(end, newline)
            end = min(end, start + 80)

            value = text[start:end].strip(" \t:.-")
            value = _drop_label_residue(value)
            if field in _NAME_FIELDS and not _looks_like_a_name(value):
                continue
            if value:
                found[field] = value
                break
        found.setdefault(field, None)

    # The date generator emits three shapes: "25/03/2010", "25-03-2010" and
    # "Ngày 25 tháng 3 năm 2010". Matching the label is not enough -- keep
    # only the part that actually looks like a date.
    if found.get("invoice_date"):
        raw = found["invoice_date"]
        m = (re.search(r"\d{1,2}\s*[/-]\s*\d{1,2}\s*[/-]\s*\d{2,4}", raw)
             or re.search(r"\d{1,2}\s+\w+\s+\d{1,2}\s+\w+\s+\d{4}", _deaccent_keep_length(raw)))
        found["invoice_date"] = raw[m.start():m.end()].strip() if m else None

    # The hospital name carries no label, so it has to be recognised rather
    # than located. Position alone is not enough: taking "the first heading
    # or first non-empty line" assumes the model reads the page top-down,
    # and that assumption broke on the pre-processed images, where
    # PaddleOCR-VL emits the TABLE first and the header afterwards. The name
    # was still there; it simply was not first, and the extractor returned
    # "Ghi chu" or "Xem them thong tin" -- fragments of the footer.
    #
    # These establishments all name themselves: "BENH VIEN X" (hospital),
    # "NHA THUOC ..." (pharmacy), "PHONG KHAM ..." (clinic). Matching on that
    # is robust to reading order. Position stays as the fallback, for a
    # document whose title we do not recognise.
    raw_title = ""
    for line in text.split("\n"):
        if re.search(r"benh\s*vien|nha\s*thuoc|phong\s*kham|trung\s*tam\s*y\s*te",
                     _deaccent_keep_length(line)):
            raw_title = line.strip().lstrip("#").strip()
            break
    if not raw_title:
        heading = re.search(r"^#+\s*(.+)$", text, re.M)
        raw_title = heading.group(1) if heading else next(
            (ln for ln in text.split("\n") if ln.strip()), "")
    # Some models emit the whole page header on a single line: cut at the
    # first labelled field so we keep the name alone.
    title_flat = _deaccent_keep_length(raw_title)
    cut = len(raw_title)
    for s, _e, _f in _all_label_positions(title_flat):
        cut = min(cut, s)
    found["hospital_name"] = raw_title[:cut].strip(" \t:.-") or None

    return found


def coverage(fields: dict) -> float:
    """Share of fields actually found -- a simple completeness indicator."""
    if not fields:
        return 0.0
    return sum(1 for v in fields.values() if v) / len(fields)
