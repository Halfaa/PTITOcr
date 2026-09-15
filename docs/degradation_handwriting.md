# Handwriting under degradation — where Chandra breaks

**Question.** At what photo quality does handwriting recognition stop
working? The clean-page figures (Chandra 99.1% EN, 95.5% VN) say the model
works in the lab, and strictly nothing more.

Chandra OCR 2, English handwritten specimens, the 24 degradation steps of
`scripts/degrader.py`, 3 specimens per step. Metric: share of handwritten
fields found in the transcription (lenient — accents and punctuation
ignored), the same measure as `docs/resultats_handwriting.md`.

`niveau0` is the paired reference: the same three pages, through the same
writing code, with no degradation. It scores **100.0%**, which is what makes
every line below readable as an effect of the degradation alone.

---

## 1. The result in one line

**Photometric degradations cost nothing. Geometric ones break the model.**

| degradation | range tested | worst score |
|---|---|---|
| sensor noise | 500 → 8 photons at saturation | **100.0%** |
| underexposure | −2 → −6 stops | **100.0%** |
| JPEG | quality 25 → 3 | **97.2%** |
| motion blur | 6 → 37 px | **8.5%** |
| resolution | 1241 → 364 px wide | **18.3%** |

Three of the five degradations do not move the needle at all, across their
whole tested range. The two that do are the ones that destroy stroke
geometry.

---

## 2. What does not matter

### Noise — no effect, none

| step | photons at saturation | fields found |
|---|---|---|
| `niveau0` | — | 100.0% |
| `bruit1` | 500 | 100.0% |
| `bruit2` | 150 | 100.0% |
| `bruit3` | 50 | 100.0% |
| `bruit4` | 20 | 100.0% |
| `bruit5` | 8 | 100.0% |

Not a single field lost, down to 8 photons at saturation — a photograph so
noisy it looks broken. The prediction written before measuring said noise
would be "absorbed better than it looks"; it was absorbed entirely.

### Underexposure — no effect either

| step | stops under | fields found |
|---|---|---|
| `exposition1` | −2 | 100.0% |
| `exposition5` | −6 | 100.0% |

At −6 stops only 32 grey levels out of 256 survive the 8-bit quantisation
(measured in `docs/degradation.md`). Chandra reads the page anyway.

### JPEG — a rounding error

| step | quality | fields found |
|---|---|---|
| `jpeg1` | 25 | 100.0% |
| `jpeg2` | 10 | 100.0% |
| `jpeg3` | 3 | 97.2% |

2.8 points at quality 3, which is past the point where the encoder itself
saturates. **This removes a constraint from the capture specification**: no
need to fight messaging-app compression, only its resizing.

---

## 3. What breaks it

### Motion blur — the sharpest cliff

| step | blur length | as % of page width | at 200 dpi | fields found | score |
|---|---|---|---|---|---|
| `flou1` | 6 px | 0.36% | 0.8 mm | **97.2%** | 98.7 |
| `flou2` | 11 px | 0.67% | 1.4 mm | 73.2% | 90.6 |
| `flou3` | 17 px | 1.03% | 2.2 mm | 43.7% | 76.1 |
| `flou4` | 24 px | 1.45% | 3.0 mm | 15.5% | 55.2 |
| `flou5` | 37 px | 2.24% | 4.7 mm | 8.5% | 38.9 |

Interpolating between measured points: **90% of fields are still found at
about 7-8 px of shake, and half the fields are lost around 16 px.** In
physical terms, roughly **1 mm of camera shake across an A4 page costs a
quarter of the fields.**

The fall is steep but not a cliff: it loses about 25 points per step, which
means a blurred page degrades *gracefully* rather than collapsing. That
matters for a production rule — a confidence signal has something to work
with.

### Resolution — the same slope, one step later

| step | fraction of long side | page width | approx. dpi | fields found | score |
|---|---|---|---|---|---|
| `resolution1` | 0.75 | 1241 px | 150 | **100.0%** | 100.0 |
| `resolution2` | 0.55 | 910 px | 110 | 88.7% | 95.6 |
| `resolution3` | 0.40 | 662 px | 80 | 63.4% | 85.6 |
| `resolution4` | 0.30 | 496 px | 60 | 45.1% | 76.6 |
| `resolution5` | 0.22 | 364 px | 44 | 18.3% | 56.1 |

Interpolated thresholds: **90% of fields down to about 950 px of page width
(~115 dpi), half the fields lost around 540 px (~65 dpi).**

Note that 1241 px — a 25% reduction from the source — costs exactly nothing.
The specimens are generated at 200 dpi; the model does not need that.

---

## 4. A capture specification, in the form that transfers

This is the deliverable the study exists for. On English handwriting, with
Chandra, to keep **at least 90% of fields**:

- **sharpness**: motion blur under ~7 px at 200 dpi, i.e. about **0.4% of
  the page width**, about **0.9 mm** across an A4;
- **resolution**: at least **~950 px across the page** (~115 dpi);
- **noise, exposure, JPEG**: no constraint within the ranges tested. A dark,
  grainy, heavily compressed photograph reads as well as a clean one.

The practical consequence for a phone capture: what has to be controlled is
**holding still and not letting the image be downscaled**. Lighting is not
the problem.

---

## 5. Deformation — measured, with a reservation

The Vietnamese specimens projected onto curved meshes by Blender, 8 images,
against the same set read flat:

| | fields found | score |
|---|---|---|
| flat (30 specimens) | **95.6%** | 97.3 |
| warped (8 specimens) | **59.9%** | 80.8 |

−35.7 points: the largest single drop measured on handwriting, larger than
any photometric degradation and comparable to blur at 17 px.

**The reservation has to travel with the number.** Those 8 renders came out
rotated 90°, because of a texture-orientation bug found after they were
produced. The figure therefore measures deformation **and** orientation
together, and is a lower bound on what deformation alone costs. It should be
presented as such, not as the effect of warping.

---

## 6. Limits of this study

**Three specimens per step.** Each specimen carries 47 handwritten fields,
so each point rests on ~141 field observations — enough for the shape of the
curve, not for a precise threshold. The interpolated thresholds above are
indicative; the measured points are what is solid.

**English only.** The Vietnamese degradation set was generated but never
attached to the Kaggle run, so it has not been measured. That is the gap
that matters most: Vietnamese is the harder language on clean pages (95.5%
against 99.1%), and diacritics are exactly the kind of fine mark that blur
and downscaling destroy first. **The figures here are the optimistic case.**

**No comparison with printed invoices.** The prediction written before
measuring was that handwriting would break *earlier* than print. It cannot
be checked yet: `docs/degradation.md` holds the protocol and the
predictions, but the invoice degradation curve has never been measured.

**Synthetic pages.** Handwriting fonts, not real handwriting; degradations
applied in linear light, which is physically right but still a simulation of
a photograph rather than a photograph.

**GLM-OCR is still absent.** Its runs remain empty after the OOM fix — the
notebook has not been re-run.

---

## 7. A measurement incident worth recording

The first pass of this evaluation returned 9.5% everywhere, including on
`niveau0` — the undegraded reference — and identical values across
completely different degradations.

The cause was not the model but the scoring command: the language was
selected with `-match "_en"`, while the runs are named
`images-handwriting-**en**-degradation_...`, with hyphens. Every English
page was therefore scored against the **Vietnamese** ground truth of the
same specimen number.

Two things made it catchable. `niveau0` at 9.5% against 99.1% on the same
clean set is impossible if the score measures the image; and five noise
levels returning exactly the same number means the score is not reading the
image at all. Reading one transcription settled it in a minute: it was a
flawless English page.

The lesson is the one the project keeps relearning — **a paired reference
point is what makes a broken measurement visible.** Without `niveau0` in the
same run, the flat 9.5% would have looked like a model failure.
