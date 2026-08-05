# Demo folder — how to use it

Everything needed to present the work, in one place.

---

## Importing the report into Notion

**Use `REPORT.html`, not the Markdown.** In Notion: **Import → HTML**.

Notion's Markdown import **silently drops local images**, zip or no zip — it
only keeps images that already have a public URL. A report imported as `.md`
arrives stripped of its figures without any warning.

The HTML carries every figure inside it, encoded in the file, so nothing can
go missing. It also opens directly in a browser if Notion is unavailable.

`REPORT.md` is kept for GitHub and other tools that do resolve relative paths.
If the figures change, rebuild the HTML:

```powershell
python demo\build_html.py
```

---

## The multi-page merging demo

The single thing worth showing live. Drop the pages of an invoice, watch the
pieces the model actually returned, the decision taken at each transition
with the signals behind it, then the reassembled table — every row tinted by
the page it came from.

```powershell
cd ..
pip install fastapi "uvicorn[standard]" python-multipart
python demo\demo_fusion.py
```

Then `http://localhost:8010`.

**Replay is the default and is instant.** Images from the benchmark sets are
recognised by filename and their already-computed OCR is returned at once.
The merging itself runs live, in `src/table_merge.py` — the real algorithm
executes in front of the room, only the reading is pre-recorded. Say so; it
is a stronger claim than pretending otherwise.

The *Direct* mode runs the model for real, on a photo taken on the spot if
someone asks. Around 80 s per page — keep it for answering a question, not
for the walkthrough.

### Three drops worth doing, in this order

**`doc3D-renderer\img\multipage_test\page_1-*` and `page_2-*`** — one
invoice over two pages. Two tables in, one out, and the repeated header gone.

**`page_2-*` and `page_3-*`** — two *different* invoices, consecutive pages,
same pharmacy, same template. The banner turns red: `SÉPARÉ`. This is the
case that matters. A wrong merge fabricates a table mixing two documents,
and nothing downstream can detect it — the arithmetic validation itself
stays satisfied, since every line still balances.

**`doc3D-renderer\img\variants_warped\page_1-*` to `page_3-*`** — the
diversified set, where numbering runs on across invoices instead of
restarting. Both decisions appear on one screen: pages 1–2 merged, page 3
kept apart even though its numbering is continuous with what precedes it.
That one is decided by the closing veto, not by the numbering.

---

## Running the full pipeline demonstration

```powershell
cd ..
.\venv_hunyuan\Scripts\activate
pip install fastapi "uvicorn[standard]" python-multipart
python src\api.py
```

Then open `http://localhost:8000`. From a phone on the same network, use the
machine's IP instead of `localhost` — the API listens on `0.0.0.0`, and the
browser will offer to install the app.

### A five-minute run-through

**1. Start with Replay, not a live photo.** Click *Démonstration*. The default
pair is already a raw reading and its pre-processed counterpart from the
diversified set. Pages `1,2` is a two-page invoice, so the merging step is
visible.

Replay is instant. A live reading takes 30 s to 3 min, and nobody watches a
frozen screen in a meeting.

**2. Walk down the step list.** It is the whole argument in one column:
sheet located, model read, tables merged, arithmetic checked, reading chosen.

**3. Stop on "Décision de fusion".** This is the internship's own
contribution. The panel names the signals that decided each transition —
continuation marker, numbering continuity, closing total. Worth saying out
loud: *zero wrong merges across eight benchmark runs*.

**4. Stop on the line table.** Rows are coloured by arithmetic status. On 215
line items, 6 % are flagged and they contain 100 % of the numeric errors.
That is what makes the result reviewable in practice.

**5. Then, if there is time, a live photo.** Choose *1 seule lecture* for
speed. Point out that the detected sheet outline is drawn on the actual photo:
the localisation is not a black box.

### If a live run is needed and it is slow

- select **HunyuanOCR-1.5 (GPU)** — it already runs on the laptop GPU;
- select **1 seule lecture** — halves the work;
- one page rather than two.

---

## Files

| file | what it is |
|---|---|
| `REPORT.md` | full progress report, English, Notion-ready |
| `figures/` | all figures, generated from measured values |
| `artifacts/sample-invoice.json` | a real pipeline export, nothing hand-edited |
| `artifacts/merge-decisions.txt` | the merge evaluation, decision by decision |

`sample-invoice.json` is worth opening during the meeting: it carries an
explicit `extraction.status` and a `check` block per line. An empty invoice and
a failed extraction are not the same thing, and the format says which.

---

## Three numbers to remember

**100 % / 100 %** — multi-page merge precision and recall, zero wrong merges
across every run.

**0.966** — TEDS with Chandra OCR 2 and adaptive extraction on the multipage
set (ceiling 0.967); 0.977 on the deformed diversified set, exactly at the
ceiling. All models re-measured under one protocol, `scripts/eval_all.py`.

**6 %** — the share of lines a human needs to review, containing 100 % of the
numeric errors.

---

## The one caveat to state first

All data is synthetic: one generator, one deformation engine, no real
photograph yet. Saying it before being asked is better than being asked.

The mitigation is planned and specific — print the fake invoices and
photograph them, which preserves the exact ground truth that no real document
allows. It is blocked on printer access, not on method.
