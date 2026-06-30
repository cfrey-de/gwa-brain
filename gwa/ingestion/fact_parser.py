"""Chunk text -> list of atomic facts (LLM). Conservative: a parse failure or a
malformed response yields NO facts (never a hallucinated one).

Modes:
- "factual" : concrete facts only (numbers, units, conditions) — best for datasheets.
- "prose"   : propositions from narrative/prose/dialogue — for literature & reports.
- "auto"    : factual first; if a chunk yields nothing, retry with the prose prompt,
              so one brain handles both a datasheet and a Faust excerpt.
"""
from gwa.llm import extract_json
from gwa.qa.prompts import (DERIVATION_EXTRACT_SYSTEM, EXTRACT_SYSTEM,
                            PROSE_EXTRACT_SYSTEM)


def _extract(chunk_text: str, llm, system: str) -> list:
    try:
        raw = llm.complete("extract", system, chunk_text, temperature=0.0)
        data = extract_json(raw)
    except Exception as e:  # noqa: BLE001 — in doubt, extract nothing
        print(f"[fact_parser] extraction failed, skipping chunk: {e}")
        return []
    if not isinstance(data, dict):  # model emitted a top-level array/scalar
        return []
    facts, seen = [], set()
    for f in data.get("facts", []):
        if not isinstance(f, str):
            continue
        f = f.strip()
        key = f.lower()
        if len(f) >= 3 and key not in seen:
            seen.add(key)
            facts.append(f)
    return facts


def parse_facts(chunk_text: str, llm, mode: str = "auto") -> list:
    """Return a deduped list of fact strings extracted from one chunk."""
    if not chunk_text or not chunk_text.strip():
        return []
    if mode == "prose":
        return _extract(chunk_text, llm, PROSE_EXTRACT_SYSTEM)
    facts = _extract(chunk_text, llm, EXTRACT_SYSTEM)
    if not facts and mode == "auto":   # narrative text yields no concrete facts -> retry
        facts = _extract(chunk_text, llm, PROSE_EXTRACT_SYSTEM)
    return facts


def parse_steps(text: str, llm) -> list:
    """Derivation mode: return ordered steps [{id, text, depends_on:[ids]}], with
    dependencies restricted to earlier, existing step ids. Malformed -> []."""
    if not text or not text.strip():
        return []
    try:
        raw = llm.complete("extract", DERIVATION_EXTRACT_SYSTEM, text, temperature=0.0)
        data = extract_json(raw)
    except Exception as e:  # noqa: BLE001
        print(f"[fact_parser] derivation extraction failed: {e}")
        return []
    if not isinstance(data, dict):
        return []
    steps, seen_ids = [], set()
    for st in data.get("steps", []):
        if not isinstance(st, dict):
            continue
        sid, txt = st.get("id"), st.get("text")
        if not isinstance(sid, str) or not isinstance(txt, str) or len(txt.strip()) < 3:
            continue
        sid, txt = sid.strip(), txt.strip()
        if not sid or sid in seen_ids:
            continue
        deps = [d for d in st.get("depends_on", [])
                if isinstance(d, str) and d in seen_ids]  # only earlier, known ids
        seen_ids.add(sid)
        steps.append({"id": sid, "text": txt, "depends_on": deps})
    return steps

