# Real Vietnamese handwriting — the number, and the failure mode behind it

Chandra OCR 2 · 250 real handwritten lines · metric = CER / WER
· published CRNN baseline for reference

> This closes the biggest caveat of the previous handwriting report, which
> ended on *"synthetic pages, handwriting fonts — not real handwriting, not
> real photographs"*. Every figure before this one came from LaTeX pages
> rendered with handwriting fonts. These are photographs of text written by
> people.

---

## 1. What changed, and why the metric changed with it

| | previous reports | this one |
|---|---|---|
| images | rendered A4 forms | photographed lines |
| writing | handwriting *fonts* | **real handwriting** |
| metric | share of fields found | **CER / WER** |

The dataset (`vn_handwritten_images`, 1838 lines, Vietnamese addresses) is
made of isolated **lines**, not forms. There is no field to look for, so the
field-presence metric does not apply. We switched to character and word error
rate — what the HTR literature reports — which also makes the result
comparable to a published baseline for the first time in this project.

---

## 2. The headline

| | CER | WER |
|---|---|---|
| **Chandra OCR 2** (5 B, not trained on this data) | **6.84%** | **19.01%** |
| CRNN trained on this dataset (published) | 4.80% | 15.66% |

```
CER   Chandra  ███████████████████████████████████████  6.84
      CRNN     ████████████████████████████             4.80

WER   Chandra  ███████████████████████████████████████  19.01
      CRNN     ████████████████████████████████         15.66
```

**Two points behind a specialist that was trained on this exact data, with no
training at all.** That is the result.

Sentence error rate is 80% (50/250 lines exactly right), which sounds alarming
and is not: these are long addresses, and one wrong character loses the whole
line. On lines this long, SER is the least informative of the three numbers.

One thing worth noting — corpus CER (6.84%) and mean-per-line CER (6.80%) are
nearly identical. Errors are therefore **not** concentrated in a few short
lines; the number describes the whole set.

---

## 3. Where the errors actually are

Three normalisations, each removing one class of difference, measured on the
same 250 lines:

| measurement | CER | what the step removes |
|---|---|---|
| raw | 6.84% | — |
| tone placement canonicalised | 6.51% | −0.33 · `hoà` vs `hòa` |
| diacritics stripped | 4.99% | −1.52 more · accent errors |
| ↳ what remains | **4.99%** | **wrong letters** |

```
wrong letters        ██████████████████████████████  73%
accent errors        ███████████                     22%
tone-mark convention ██                               5%
```

**Three quarters of the errors are letters, not accents.** This is the
opposite of PaddleOCR-VL on invoices, which substituted CJK characters
whenever it was unsure of a diacritic. Chandra's Vietnamese diacritic handling
is not the bottleneck here.

The defensible figure to quote is **6.51%** — the raw 6.84% includes a
spelling convention, not a reading error (see §5).

---

## 4. The failure mode: it invents plausible addresses

The worst lines are not noise. They are **real Vietnamese place names
substituted for the ones actually written**:

| written | read as |
|---|---|
| Quận **Hà Đông, Hà Nội** | Quận **Hồ Chí Minh, Hồ Chí Minh** |
| Xã **Lình Huỳnh**, Huyện **Hòn Đất**, **Kiên Giang** | Xã **Vĩnh Thụy**, Huyện **Hòa Hát**, Tỉnh **Gia Long** |
| Quận **Ngô Quyền, Hải Phòng** | Quân **Ngõ Đại, Hai Phụng** |
| Thôn **Hòa Sơn**, Xã **Cao Thượng** | Thôn **Hồn Sơn**, **Kỉ Lục** Thượng |

"Hà Đông, Hà Nội" → "Hồ Chí Minh, Hồ Chí Minh" is the giveaway. That is not a
visual confusion between similar shapes; it is a prior over what an address
usually says.

**Why a CRNN cannot fail this way.** A CRNN decodes frame by frame through a
CTC head — there is no language model with the freedom to swap in a different
city. Chandra generates text autoregressively, so when the handwriting is
ambiguous it falls back on the most probable continuation. The capability that
makes it good at layout is the same one that makes it invent.

**Why this matters more than the CER.** The target documents are medical:
patient names, dates, dosages, amounts. Garbage output is detectable —
a plausible wrong dosage is not. A model that degrades into nonsense is safer
in this setting than one that degrades into fluent fiction.

→ This is the argument for the verification layer the project already built:
arithmetic validation on invoices, and `src/qualite_capture.py` at capture
time. **Chandra's output should never be treated as read without a check.**

### Measured, not just observed

The 1838 labels form a lexicon of Vietnamese addresses. Every substituted word
can be tested against it, and against its distance from the word that was
actually written.

| of 439 word substitutions | | |
|---|---|---|
| lands on a real word of the corpus | 300 | 68.3% |
| ↳ within 2 characters of the truth | 232 | 77.3% of those |
| ↳ **further than 2 characters** | **68** | **22.7% of those** |

**Why the first number alone proves nothing.** Vietnamese is dense: nearly
every legal syllable carrying a valid tone *is* a word. Getting one accent
wrong therefore lands on a real word without any language model being
involved. `hưng → hùng`, `bình → bính`, `thạnh → thành` are misreadings that
happen to be words.

**The distance is what discriminates.** A neighbour at one or two characters
is consistent with bad reading. A distant real word is not — the pixels cannot
produce it. That leaves **68 substitutions, 15.5% of all of them**, that
require a prior about what the sentence should say.

And they are not random. The furthest ones replace a word with another word
**from the same semantic slot**:

| written | read as | both are |
|---|---|---|
| tổ | phường | administrative units |
| lương | huyện | administrative units |
| dương | nguyễn | surnames |
| quỳnh | nguyễn | surnames |
| quyền | đại | given-name syllables |

A CTC decoder cannot do this. Category-consistent substitution is the
signature of a language model filling a gap it cannot see.

> Remaining caveat: the lexicon is built from the dataset's own labels, so it
> covers addresses well and nothing else. A hallucinated word from outside
> this domain would be counted as a reading error, which makes 15.5% a
> **lower bound**.

---

## 5. Two Unicode traps, both of which would have faked the result

Neither of these changes a single letter, and both inflate CER badly.

**NFC vs NFD.** `ệ` can be one code point or `e` plus two combining marks.
They look identical. Had the model emitted one form and the ground truth the
other, every accented character would have counted as two errors — a 4% CER
would have read above 30%. Both sides are normalised to NFC before comparison.

**Tone-mark placement.** Vietnamese admits two conventions on diphthongs:
`hoà` (mark on the second vowel) and `hòa` (on the first). Both are correct
and both are in use — the dataset writes `Thanh Hoá`, Chandra returns
`Thanh Hóa`. Same word, counted as two errors.

`canoniser_tons()` moves the tone to a fixed position **on both sides**. It
does not try to decide which spelling is right — the question is meaningless,
since the tone belongs to the syllable and not to a particular vowel. Two
spellings of one word become one word; two different words stay different.
Circumflex, breve and horn are left alone: `â` is not `a`, `ư` is not `u`.

Measured cost of ignoring this: **0.33 CER points**, ~5% of all errors.

---

## 6. How to reproduce

```powershell
# Kaggle (GPU): kaggle/bench_kaggle_lignes.ipynb
#   250 lines sampled from 1838, seed 12345
#   sample list + labels travel inside the results zip

Expand-Archive lignes_vn_chandra.zip -DestinationPath results -Force
python src\eval_lignes.py --run lignes_vn_chandra `
    --labels results\lignes_vn_chandra\labels_echantillon.json --detail
```

The sampled filenames are stored in `echantillon.json` next to the results. A
sample that cannot be replayed makes every later comparison meaningless, so it
ships with the numbers rather than beside them.

---

## 7. Limits of these numbers

| limit | consequence |
|---|---|
| **no train/test split in the public archive** | the CRNN's 4.80% was measured on *its* test split, which we do not have. Two measurements on different partitions of the same set — the order of magnitude is informative, a few tenths are not |
| **"zero-shot" cannot be fully verified** | this is a public dataset; we know Chandra was not fine-tuned on it, but we cannot rule out that it appeared in pretraining. The gap may be flattering |
| 250 of 1838 lines | >10 000 characters, so CER is stable to a few tenths; WER and especially SER are noisier |
| addresses only | proper nouns and toponyms — the vocabulary that most invites a language model to guess. Medical fields (dosages, dates, numbers) may behave differently, in either direction |
| hallucination lexicon is address-only | a hallucinated word from another domain counts as a reading error, so 15.5% is a lower bound |
| single model | no second data point on this set yet. PaddleOCR-VL (0.9 B) runs locally and would test whether its diacritic weakness reappears on real handwriting |
