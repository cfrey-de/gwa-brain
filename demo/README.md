# Demo dataset — fictional pump-station data

A small, **fictional, neutral** dataset for trying GWA Brain. Upload these documents, then
ask the questions below to see each behaviour — citations, struck near-neighbours, declared
gaps, and derivation trees.

> Everything here is invented — made-up products and numbers, with no company name. Nothing here refers to a real company, product, or dataset.

## The documents

| File | Suggested mode | What it demonstrates |
|---|---|---|
| `01_pump-station-p12_datasheet.txt` | factual | concrete facts; a numeric near-neighbour (500 h vs. 100 h) |
| `02_pump-station-p20_datasheet.txt` | factual | a second product → cross-document, entity-based near-neighbours |
| `03_quarterly-figures.txt` | derivation | a financial derivation tree (profit margin ← …) |
| `04_maintenance-policy.txt` | prose (or auto) | propositions from prose; good for honest gaps |
| `05_commissioning-report.txt` | derivation | a second, physical derivation tree (fill time ← …) |

(Mode = the dropdown in the UI, or the `mode` field on `POST /upload/stream`. `auto` works
for everything; pick `derivation` for docs 03 and 05 to get the deep tree.)

## Questions to try

**Cited facts**
- *What is the operating pressure of the P-12?* → 3.7 bar, cited to the P-12 data sheet.
- *What is the P-12 inlet made of?* → galvanised steel pipe.

**Struck near-neighbours (you see what was rejected, and why)**
- *What is the P-12 water level after 500 hours?* → **160 cm** is kept and cited; two
  look-alikes are **struck with a reason** — the P-12's **100-hour** figure (180 cm: same
  topic, different condition) and the **P-20's** 500-hour figure (210 cm: different product).

**Cross-document disambiguation (entity near-neighbour)**
- *How much does the P-12 weigh?* → 45 kg (the P-20's 60 kg should not be cited).
- *What is the operating pressure of the P-20?* → 5.2 bar.

**Honest gaps (what the documents don't answer)**
- *What is the noise level of the P-12 in decibels?* → declared as a **gap** (not in the docs).
- *What is the P-12 water level after 500 hours, and the noise level?* → one part answered,
  the other declared as a gap.

**Derivation trees (how a number follows from its inputs)**
- *What is the profit margin, and how is it derived?* → 16 %, with the tree
  `profit margin ← operating profit ← gross profit ← {revenue, cost of goods}`.
- *How long does tank T-7 take to fill?* → 20 minutes, with the tree
  `fill time ← net inflow ← {inflow, outflow}` and `fill time ← tank volume`.

**Prose / policy**
- *How often must a pump station be inspected?* → once a year.
- *How long is the warranty?* → two years from installation.
- *What happens if the operating pressure falls below the rated value?* → the station is
  taken out of service until it is repaired.

**Accumulation (memory across questions)**
- Ask several P-12 questions in a row. Facts that get cited gain weight and co-usage edges,
  so they rank higher for later, related questions — visible in `/graph`.

## How headings disambiguate entities (scope)

The data sheets above name their subject only in the **heading** (*"Pump Station P-12"*), not
in every sentence. GWA Brain attaches that heading to each fact as its **scope** and uses it
for matching (embedding, term filter, guard) — so *"What is the P-12 operating pressure?"*
finds *"the operating pressure of the pump is 3.7 bar"* even though the sentence never repeats
"P-12". The fact's stored text stays **verbatim**; the scope is a deterministic matching aid,
not an LLM rewrite. (Two pumps — P-12 and P-20 — are included so you can see the scope keep
them apart: ask each one's weight and you get 45 kg vs. 60 kg, correctly.)

## Load them quickly (API)

```bash
PORT=8000
for f in demo/01_*.txt demo/02_*.txt; do
  curl -fsS -X POST localhost:$PORT/upload/stream -F "file=@$f" -F "mode=factual" >/dev/null; done
curl -fsS -X POST localhost:$PORT/upload/stream -F "file=@demo/03_quarterly-figures.txt"   -F "mode=derivation" >/dev/null
curl -fsS -X POST localhost:$PORT/upload/stream -F "file=@demo/04_maintenance-policy.txt"   -F "mode=prose" >/dev/null
curl -fsS -X POST localhost:$PORT/upload/stream -F "file=@demo/05_commissioning-report.txt" -F "mode=derivation" >/dev/null
```

The text is English, but GWA Brain answers in the language of the question — ask in German
and you get a German answer citing the same (English) facts.
