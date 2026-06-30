"""All LLM prompts in one place. The prompts are English, but instruct the model to
produce output in the language of the input (so German documents/questions still yield
German facts and answers, English ones English, etc.).

Every prompt that produces machine-read output demands strict JSON; the user message
for the guard and the formulate step is itself JSON, which keeps the contract explicit
for the model and lets the deterministic MockLLM transform the same input under test.
"""
import json

# -- Ingestion (factual mode): chunk -> facts ---------------------------------
EXTRACT_SYSTEM = """\
Extract every concrete, self-contained fact from the following passage as a JSON list.

Rules:
- Each fact: one precise, complete sentence that stands on its own.
- Only what the text explicitly states — do not interpret, do not infer.
- Copy numbers, units and conditions exactly ("160 cm", "after 500 hours", "at 25 C").
- No summaries, no opinions, no headings.
- Write each fact in the SAME LANGUAGE as the source text.

Respond ONLY as JSON: {"facts": ["...", "..."]}
If there are no self-contained facts: {"facts": []}"""


# -- Ingestion (prose/narrative mode): text -> propositions --------------------
PROSE_EXTRACT_SYSTEM = """\
Extract the key statements from the following passage (prose, dialogue or verse) as a
JSON list — what the text asserts, depicts, or records as an action, promise or condition.

Rules:
- Each statement: one precise, self-contained declarative sentence in plain language.
- Only what the text states or directly depicts — no interpretation, no moral, no
  outside knowledge, no speculation.
- Capture conditions and commitments faithfully (who promises, demands or does what;
  under which condition something happens).
- Name the acting characters when the text names them.
- No overall summary — individual, checkable statements.
- Write each statement in the SAME LANGUAGE as the source text.

Respond ONLY as JSON: {"facts": ["...", "..."]}
If there are no statements: {"facts": []}"""


# -- Ingestion (derivation mode): text -> steps WITH dependencies --------------
DERIVATION_EXTRACT_SYSTEM = """\
The following text describes a derivation, calculation or step-by-step argument.
Extract it as ordered steps WITH their dependencies.

For each step:
- "id": a short identifier ("s1", "s2", ...), in order.
- "text": one precise, self-contained statement (an input quantity, an intermediate
  step, or a result) — only what the text says, with numbers/units exactly. Write it in
  the SAME LANGUAGE as the source text.
- "depends_on": the list of ids of EARLIER steps whose result/value this step directly
  uses. Input quantities have "depends_on": [].

Rules:
- Only what the text explicitly states — add nothing, interpret nothing.
- Add a dependency only when the step actually uses the earlier value.

Respond ONLY as JSON:
{"steps": [{"id": "s1", "text": "...", "depends_on": []}, ...]}
If no derivation is present: {"steps": []}"""


# -- Q&A step 1: question -> sub-requirements ---------------------------------
DECOMPOSE_SYSTEM = """\
Break the following question into the concrete pieces of information that must be
looked up — staying close to the wording of the question.

STRICT rules:
- Take ONLY what the question literally asks for. Invent NOTHING.
- Do NOT add definitions, formulas, conventions, units or methods that are not
  explicitly asked for (e.g. no "x 100 %", no "definition of X").
- No parenthetical explanations, no interpretation, no textbook knowledge.
- "how is X derived" / "how is X computed" / "why" is NOT a separate sub-question; it
  belongs to the piece of information about X.
- If the question asks for only ONE piece of information, return EXACTLY ONE
  sub-question (the question itself, briefly phrased). Decompose only for genuine
  multi-part questions (separately lookable pieces joined by "and"/a list) — then one
  brief sub-question per piece.
- Write the sub-questions in the SAME LANGUAGE as the question.

Examples:
- "What is the profit margin and how is it derived?"
  -> {"sub_requirements": ["profit margin"]}
- "Give the nominal voltage and the weight."
  -> {"sub_requirements": ["nominal voltage", "weight"]}

Respond ONLY as JSON: {"sub_requirements": ["...", "..."]}"""


# -- Q&A step 3: near-neighbour guard ----------------------------------------
GUARD_SYSTEM = """\
You are a strict guard. You are given sub-requirements and candidate facts. For EACH
candidate, decide whether it CONTENT-COVERS at least one sub-requirement — not just
whether it is topically similar.

Strictness:
- A candidate that hits the right quantity/condition (e.g. "after 500 hours") covers it.
- A topically close but content-wrong neighbour (e.g. "after 100 hours" when 500 is
  asked) does NOT cover it -> keep=false.
- When in doubt: keep=false. An honest gap beats a wrong citation.

The input is JSON with "requirements" and "candidates" (each with "id" and "text").
Respond ONLY as JSON:
{"verdicts": [{"id": "<id>", "keep": true|false, "reason": "<short>"}]}"""


def build_guard_user(requirements, candidates) -> str:
    return json.dumps({
        "requirements": list(requirements),
        "candidates": [{"id": c_id, "text": text} for c_id, text in candidates],
    }, ensure_ascii=False)


# -- Q&A step 6: formulate the grounded answer -------------------------------
FORMULATE_SYSTEM = """\
Answer the question using ONLY the verified facts listed below. Add nothing that is not
in these facts.

Rules:
- Every sentence of the answer carries a citation in square brackets, e.g.
  [Report_Q1.pdf, p. 4]. Use the "source" field of the respective fact.
- No claim without a citation. No general knowledge.
- If sub-questions are not covered, name them honestly as a gap at the end ("Not
  supported: ..."). Do not write around them.
- Answer in the SAME LANGUAGE as the question.

The input is JSON with "question", "facts" (each "text" and "source") and "gaps".
Answer as plain prose (not JSON)."""


def build_formulate_user(question, facts, gaps) -> str:
    return json.dumps({
        "question": question,
        "facts": [{"text": t, "source": s} for t, s in facts],
        "gaps": list(gaps),
    }, ensure_ascii=False)
