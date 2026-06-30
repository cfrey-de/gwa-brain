"""Stufe C — the near-neighbour guard (the configured chat LLM).

Division of labour with Stufe B: the term filter catches QUANTITY substitution (wrong
number for a shared qualifier); the guard catches SEMANTIC non-entailment the numbers
can't (wrong entity, negation, topic drift). A candidate flagged as a numeric
near-neighbour by Stufe B (quantity_conflict) is hard-vetoed here regardless of the
LLM — "in doubt = strike" — and surfaced as a struck candidate with its reason (never
hidden). Every other candidate is decided by the LLM (keep/strike).

A single-model guard by default (the same chat model). An OPTIONAL cross-model guard
(guard_cross) can be enabled; when present, a candidate must survive BOTH to be kept
(conservative). The guard is a conservative, UNMEASURED product guard — not a validated
one (see README).
"""
from gwa.llm import extract_json
from gwa.qa.prompts import GUARD_SYSTEM, build_guard_user


def _verdicts(llm, sub_requirements, candidates):
    # Use short integer indices as ids, NOT the long fact UUIDs: LLMs (especially
    # reasoning models) don't reliably echo a 36-char UUID, which would make every
    # verdict unmatchable and strike valid facts. Index i maps back to candidates[i].
    pairs = [(str(i), c.fact.searchable) for i, c in enumerate(candidates)]
    user = build_guard_user(sub_requirements, pairs)
    try:
        raw = llm.complete("guard", GUARD_SYSTEM, user, temperature=0.0)
        data = extract_json(raw)
    except Exception as e:  # noqa: BLE001 — guard failure strikes everything (conservative)
        print(f"[guard] verdict parse failed -> strike all: {e}")
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(v.get("id")): v for v in data.get("verdicts", []) if isinstance(v, dict)}


def guard(candidates, sub_requirements, llm, guard_cross=None):
    """Partition candidates into (kept, struck). Mutates status/reason on each."""
    if not candidates:
        return [], []
    primary = _verdicts(llm, sub_requirements, candidates)
    secondary = _verdicts(guard_cross, sub_requirements, candidates) if guard_cross else None

    kept, struck = [], []
    for i, c in enumerate(candidates):
        if c.quantity_conflict:
            # reliable numeric near-neighbour (wrong number for a shared qualifier):
            # hard veto, the one thing Stage B is genuinely good at. Everything else
            # (incl. non-numeric / prose candidates) goes to the LLM guard below.
            c.status = "struck"
            c.reason = "off-target: different quantity/condition than asked (Stage B)"
            struck.append(c)
            continue
        v = primary.get(str(i), {"keep": False, "reason": "no verdict -> gap"})
        keep = bool(v.get("keep"))
        reason = v.get("reason", "")
        if keep and secondary is not None:
            v2 = secondary.get(str(i), {"keep": False})
            if not bool(v2.get("keep")):
                keep = False
                reason = "cross-model strike: " + (v2.get("reason", "") or "not confirmed")
        c.status = "kept" if keep else "struck"
        c.reason = reason
        (kept if keep else struck).append(c)
    return kept, struck
