# GLM-OCR — the fifth candidate, and the least certain bet

GLM-OCR (Z.ai, March 2026, arXiv 2603.10910) is the next model to test. It is
already wired into the protocol: `scripts/bench_deformed.py --model glm` and
`scripts/eval_all.py --modele glm`. What remains is running it.

---

## 1. Why this one

**It fits in 4 GB.** 0.9 billion parameters, ~2 GB in bf16: it is the only
recent front-rank model that runs on the RTX 3050 Ti **without a rented
GPU**. Chandra required a Kaggle T4; GLM will run on the machine itself,
which changes everything for demoing in meetings and for the PWA.

**It is the best on tables.** That is where our figures are decided: GLM-OCR
claims the best TableTEDS and TableTEDS-S of all evaluated models, and first
place on OmniDocBench V1.5 with 94.62. Our main metric is a table TEDS — the
alignment is as direct as it gets.

**MIT licence.** More permissive still than Chandra's (modified OpenRAIL-M)
and PaddleOCR-VL's (Apache 2.0), and nothing like HunyuanOCR's Tencent
licence, which excludes the EU. No obstacle to deployment or to computing in
a region we do not choose.

**It is fast.** 0.67 images/s claimed, against our 81 to 230 s per page. Even
dividing that by ten on our hardware, it stays another order of magnitude —
and therefore a usable PWA, where the user currently waits several minutes.

---

## 2. The reservation, and it has to be faced

**Vietnamese is not among its official languages.** GLM-OCR lists eight:
Chinese, English, French, Spanish, Russian, German, Japanese, Korean. It
reads others by inheritance from the GLM-4V corpus, but with nobody having
measured it, and the announced performance covers mostly Chinese and
English.

Our difficulty, though, is not Vietnamese "in general", it is its
**diacritics**: `ộ`, `ế`, `ữ`, `đ`. They are what made PP-StructureV3 fall
apart — 0.857 structure against 0.557 content, a 0.300 gap that says only
one thing: the grid is right, the characters are wrong.

That is exactly the risk here, and it is measurable in one page.

### What we write down before measuring

As for Chandra, the prediction is recorded **before** the benchmark:

- **High TEDS-Struct** (≥ 0.95). It is a table model, trained for that, and
  an invoice's structure does not depend on the language.
- **Uncertain TEDS**, with two clear-cut outcomes rather than a middle
  ground: either the diacritics survive and it takes the lead, or they do
  not and we see a PP-StructureV3 profile again, with a Struct/TEDS gap
  above 0.15.
- **Header fields** more fragile than the table: they contain Vietnamese
  proper nouns, with no arithmetic redundancy to fall back on.

That last prediction is the most valuable: if the Struct/TEDS gap exceeds
0.15, **the protocol will have identified the cause without us reading a
single output**. That is what TEDS-Struct is for.

High variance is not a flaw in the test. The result is informative either
way: "a table-SOTA model fails on Vietnamese" is as publishable a conclusion
as the opposite, and it would strengthen the internship's central argument —
language is the real filter, not model size.

---

## 3. How to run it

The `glm_ocr` architecture is recent. A `KeyError: 'glm_ocr'` at load time
does not signal a code error but a `transformers` that is too old:

```powershell
.\venv_hunyuan\Scripts\activate
pip install git+https://github.com/huggingface/transformers.git
```

The smoke test first — one page, one minute, and we already know whether the
diacritics survive:

```powershell
python scripts\bench_deformed.py --model glm `
    --images-dir "..\doc3D-renderer\img\multipage_test" --limit 1 `
    --output smoke_glm
```

Then the five branches, under the same conditions as the other models:

```powershell
$IMG = "..\doc3D-renderer\img"
python scripts\bench_deformed.py --model glm --images-dir "$IMG\multipage_test"              --output multipage_glm
python scripts\bench_deformed.py --model glm --images-dir "$IMG\multipage_test_preprocessed" --output multipage_preproc_glm
python scripts\bench_deformed.py --model glm --images-dir "$IMG\variants_flat"               --output variants_glm
python scripts\bench_deformed.py --model glm --images-dir "$IMG\variants_warped"             --output variants_warped_glm

python scripts\eval_all.py --modele glm
python scripts\eval_all.py --modele glm --modele chandra --modele hunyuan
```

The run names are already declared in `scripts/eval_all.py`: producing them
is enough, the evaluation will find them.

---

## 4. A protocol choice to own

GLM-OCR's official chain is **two-stage**: PP-DocLayoutV3 analyses the
layout, then GLM-OCR recognises each block. That is only reachable through
their SDK.

`bench_deformed.py` calls **the model alone**, as for the other three.
Giving it a layout detector the others do not have would measure two things
at once and make the comparison unusable.

It is a choice that disadvantages the model, and the report has to say so.
If the model alone looks promising, measuring the full SDK becomes a
legitimate second experiment — but one to present as such, not as the same
one.

---

## 5. Where it sits in the priorities

After the image-degradation study, not before. The gap between our two best
models is 0.013 where pre-processing brings 0.050: a fifth model refines a
comparison already settled, whereas the degradation study answers a question
that has no answer at all today.

The nuance: GLM runs **locally**, so the smoke test costs a minute and can
happen while something else is running. If the diacritics survive, it
becomes the obvious deployment candidate — 0.9 B, MIT, fast, on the card we
already have — and it then jumps to the top of the list.

---

## Sources

- [GLM-OCR on Hugging Face](https://huggingface.co/zai-org/GLM-OCR) — architecture, benchmarks, MIT licence, `transformers` example
- [GLM-OCR Technical Report, arXiv 2603.10910](https://arxiv.org/abs/2603.10910)
- [Official repository and SDK](https://github.com/zai-org/GLM-OCR)
- [GLM-OCR vs PaddleOCR: 2026 benchmarks](https://decodethefuture.org/en/glm-ocr-explained/) — official languages, TableTEDS
- [PP-DocLayoutV3](https://huggingface.co/PaddlePaddle/PP-DocLayoutV3) — the SDK's layout stage
