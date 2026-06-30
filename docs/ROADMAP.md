# GWA Brain — Roadmap / possible enhancements

Honest, **not-yet-implemented** ideas. Nothing here is a commitment; each note says *why*
and *where it would go* in the code.

## Configurable chunk overlap (ingestion)

**Status:** not implemented. **Where:** `_pack()` in `gwa/ingestion/extractor.py`;
new setting in `gwa/config.py`.

Today, chunking is **non-overlapping**: `_pack()` fills paragraph units up to ~300 tokens
(`TARGET_TOKENS`) and then flushes with a hard reset (`buf, tok = [], 0`) — no token
carry-over between consecutive chunks. Boundaries fall on **paragraphs**.

This is mostly fine here because the retrieval/embedding unit is the **atomic fact** (each
extracted fact is embedded individually in `brain.add_facts`, not the raw chunk), so the
classic RAG problem that overlap solves — "a passage straddles a chunk boundary and
retrieval misses it" — is largely sidestepped.

The **residual risk is at the extraction step**, which sees one chunk at a time: if the
information needed to form a single self-contained fact spans a chunk boundary (subject at
the end of chunk N, value at the start of N+1), the per-chunk extractor may produce an
incomplete fact or miss it. Paragraph-aligned boundaries already reduce this (a fact rarely
spans a paragraph break).

**Proposed:** an optional `GWA_CHUNK_OVERLAP` (in tokens, or in trailing paragraph units)
that carries the tail of chunk N into the head of chunk N+1, so the extractor sees the
boundary context. Mainly useful for **dense tables / continuous prose** without clear
paragraph breaks.
- In `_pack()`: instead of resetting the buffer to empty on flush, retain the last *K*
  units/tokens as the start of the next buffer; deduplicate the extracted facts (the
  `uuid5`-by-text dedup in `add_facts` already absorbs facts that appear in both chunks).
- Derivation mode is **exempt** — `_ingest_derivation` already extracts over the whole
  document at once, so cross-chunk dependencies resolve there.

## Evaluation / benchmark (toward a research write-up)

**Status:** not done.

The system ships **no measured numbers of its own**: the figures in the README come from
the parent project's different (compiler-keyed) domain, and the guard is explicitly
labelled UNMEASURED. To support a paper-worthy claim, the natural next step is a small,
focused benchmark around the **term-specificity filter**:

- a dataset of **numeric near-neighbour distractors** (same qualifier, different number),
- measured against 2–3 baselines (vanilla RAG, Self-RAG / CRAG),
- on citation accuracy, near-neighbour discrimination, and abstention/gap quality,
- with the term-filter and the guard **ablated** (on/off) to isolate each effect.

See *The guard, honestly* and *Related work & references* in the README for context.

## Multi-level section scope (deeper contextual extraction)

**Status:** document-level scope **shipped** (Stufe 2); a multi-level hierarchy is future.
**Where:** `gwa/ingestion/extractor.py` (`_doc_heading`, `Chunk.context`), `gwa/models.py`
(`Fact.context` / `Fact.searchable`).

Shipped: the document **heading** is attached to each fact as its `context` (scope) and used
**deterministically** for matching (embedding, term filter, guard) — so "the operating
pressure is 3.7 bar" under a "Pump Station P-12" heading answers "What is the **P-12**
operating pressure?" without the LLM rewriting the sentence. The stored fact text stays
verbatim; the scope is metadata, not an invented subject.

Future: parse the full **heading hierarchy** (title → section → subsection) instead of only
the top-level title, so a fact inherits its *nearest* section scope — for long documents
with many sections under one title.

## Executable provenance: derivation tree → grounded business logic

**Status:** **prototype shipped** (`gwa/codegen.py`, `tests/test_codegen.py`); productionization
is future. **Where:** `gwa/codegen.py`; the `deps` DAG built in `gwa/graph/brain.py`.

The `depends_on` DAG GWA Brain already extracts is a dataflow graph. `gwa/codegen.py` turns it
into runnable Python — one pure function per derived quantity, each docstring citing its source
clause — and auto-generates a **grounding check**: every node must reproduce the value the
*document itself states* (the document is the test oracle). This lifts provenance from
*attested* (Stufe 2 — "the text says A = B / C") to *executable* (a function that recomputes A
on new inputs), **derived from documents**, and kept only if it reproduces the stated numbers —
"guarded, not trusted", one level up. On the demo trees it regenerates `profit_margin` (= 16 %)
and `fill_time_in_minutes` (= 20 min) and verifies both against the source values;
`test_grounding_guard_catches_wrong_logic` shows the check *fails* when the logic is corrupted.

Run it: `python -m gwa.codegen demo/brain.json "profit margin"`.

**Empirical finding (`gwa/codegen_synth.py`, `research/hard_phrasing/`):** on naturally phrased
docs the derivation extractor normalises facts to *result-only* statements ("Gross profit is EUR
200,000") and keeps the dependency DAG but **drops the operator** — so the heuristic parser finds
nothing. The operator is nonetheless recoverable **without reading prose**: search
{+,−,×,÷} × operand-order × {raw, percent-as-ratio} × {result, result/100} for the combination
that reproduces the *stated* value. The document's own number doesn't just verify the code, it
**synthesises the formula**. On the hard-phrasing set this uniquely recovers **5/5** operators
(incl. `vat = net × rate/100` and `total = net + vat`) with **no LLM**; genuine ties (e.g. 2+2 == 2×2)
are flagged for an LLM/text tie-breaker — the honest place the model earns its keep.
Run: `python -m gwa.codegen_synth research/hard_phrasing/brain.json margin total`.

**Honest scope / next steps:**
- Oracle-guided synthesis covers binary arithmetic; the LLM tie-breaker (for flagged ambiguities)
  and non-arithmetic/conditional logic are the next increments. The assert-against-the-document
  -value remains the guard throughout.
- **Arithmetic** only today; **conditional / policy logic** ("interval ≥ 2000 h unless
  temperature > X") would extend it toward decision tables / DMN.
- A UI affordance ("generate code") on a rendered derivation tree.
- Relation to prior work: this is the *executable* end VeriGraph occupies (re-executable
  evidence DAG) and what PoT/PAL do per question — the twist is synthesizing **reusable** logic
  *from documents* and verifying it against the document's own asserted values.

## Guard robustness on truncated / malformed responses

**Status:** partially addressed. **Where:** `gwa/qa/guard.py`, `gwa/llm.py`, `gwa/config.py`.

The main cause of guard failures with **reasoning models** was a too-small token cap: the
model spent its budget on internal reasoning and returned empty content
(`finish_reason=length`), which the guard treats as "strike all" → a false gap. Fixed by
raising the default `GWA_MAX_TOKENS` (2048 → 8192; it's a ceiling, you pay only for tokens
generated). Remaining hardening (future): tolerant partial-JSON parsing and/or a single
retry, so a genuinely malformed response can't sink a whole question, and guarding very large
candidate sets in batches.
