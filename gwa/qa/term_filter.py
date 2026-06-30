"""Stufe B — the term-specificity filter: a deterministic backstop against numeric
near-neighbour substitution.

Semantic similarity can confuse near-facts: "180 cm after 100 hours" and
"160 cm after 500 hours" sit close in embedding space (~0.85). A strong embedder often
still ranks the right one first; but with a weaker model, longer facts, or closer values
that margin can vanish. This filter is the deterministic safeguard: it looks at the
SPECIFIC terms of each sub-requirement — numbers and their attached units/qualifiers —
and downgrades a candidate that shares the topic but carries a DIFFERENT number for that
qualifier (a "near neighbour").

It does NOT silently drop. It marks such a candidate off-target (on_target=False,
low term_score). The candidate still flows to the guard and is surfaced as a struck
candidate, so the decision path shows *why* it fell out.

Rationale mirrors the parent project's min_overlap=2 lexical guard: a single shared
token (often a stopword-ish qualifier) must not be enough to substitute one fact for
another.
"""
import re

_NUM = re.compile(r"\d+(?:[.,]\d+)?")
_TOK = re.compile(r"[a-zA-Z0-9äöüÄÖÜß]+")
# Stopwords for content-token overlap. Includes English AND German terms so the filter
# works on documents in either language (the matching logic is language-agnostic; this
# list just needs the function words of the languages you ingest — extend as needed).
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "at", "for", "is", "are",
    "was", "were", "be", "by", "with", "as", "that", "this", "it", "its", "from",
    "der", "die", "das", "und", "oder", "von", "zu", "im", "in", "auf", "bei", "für",
    "ist", "sind", "war", "den", "dem", "des", "ein", "eine", "einer", "mit", "wie",
    "nach", "aus", "an", "am", "als", "nicht", "auch", "noch", "wird", "werden",
    "betraegt", "beträgt", "liegt", "hat", "haben",
}

# words that, next to a number, mark it as a load-bearing quantity/condition
_QUAL = {
    "zyklen", "cycles", "zyklus", "cycle", "v", "volt", "volts",
    "celsius", "grad", "c", "prozent", "percent", "mm", "cm", "m", "km", "kg", "g",
    "mg", "stunden", "hours", "h", "minuten", "min", "sekunden", "s", "tage", "days",
    "jahre", "years", "monate", "months", "hz", "khz", "mhz", "wh", "kwh", "w", "kw",
    "bar", "pa", "kpa", "mpa", "ohm", "ma", "a", "nm", "k",
}


def content_tokens(text):
    return {t for t in _TOK.findall((text or "").lower()) if t not in _STOP and len(t) > 1}


def numbers(text):
    return {n.replace(",", ".") for n in _NUM.findall(text or "")}


def quantity_terms(text):
    """Set of (number, qualifier) pairs where a qualifier word sits right after the
    number (e.g. ('500','hours')). Captures the load-bearing conditions of a fact."""
    toks = _TOK.findall((text or "").lower())
    pairs = set()
    for i, t in enumerate(toks):
        if _NUM.fullmatch(t):
            num = t.replace(",", ".")
            for j in (i + 1, i - 1):  # qualifier may precede or follow ("after 500 hours")
                if 0 <= j < len(toks) and toks[j] in _QUAL:
                    pairs.add((num, toks[j]))
    return pairs


def _score_one(req: str, cand: str):
    """Return (term_score, on_target, covers, conflict) for one (requirement, candidate).

    - on_target : passes the STRICT filter (used for ranking/display).
    - covers    : the candidate plausibly addresses this requirement (LENIENT — used for
                  gap attribution, so prose facts the guard keeps aren't reported as gaps).
    - conflict  : numeric near-neighbour (shares the qualifier but a DIFFERENT number) —
                  the reliable substitution signal that the guard hard-vetoes.
    """
    rt, ct = content_tokens(req), content_tokens(cand)
    if not rt:
        return 0.0, False, False, False
    shared = rt & ct
    coverage = len(shared) / len(rt)

    r_nums, c_nums = numbers(req), numbers(cand)
    r_quant, c_quant = quantity_terms(req), quantity_terms(cand)

    if r_nums:
        if r_quant:
            # requirement carries number+unit conditions (e.g. "500 hours"): demand the
            # SAME (number, qualifier) pair — a bare match on a different qualifier
            # ("500 V") must NOT count, or near-fact substitution slips through.
            if r_quant & c_quant:
                return max(coverage, 0.6), True, True, False
            shared_quals = {q for _, q in r_quant} & {q for _, q in c_quant}
            if shared_quals:
                # same qualifier, different number -> the classic near neighbour
                return coverage * 0.2, False, False, True
            return coverage * 0.4, False, False, False
        # bare number with no recognized unit: fall back to number overlap
        if r_nums & c_nums:
            return max(coverage, 0.6), True, True, False
        on = coverage >= 0.75 and len(shared) >= 2
        return coverage * 0.5, on, on, False

    # non-numeric requirement: on_target strict (>=2 tokens), covers lenient (>=1 token)
    on = len(shared) >= 2 or coverage >= 0.5
    return coverage, on, len(shared) >= 1, False


def term_specificity_filter(candidates, sub_requirements):
    """Annotate each candidate: term_score, covers (lenient), on_target (strict),
    quantity_conflict (numeric near-neighbour). Mutates and returns `candidates`."""
    for c in candidates:
        best, covers, on_any, conflict_any = 0.0, [], False, False
        for idx, req in enumerate(sub_requirements):
            s, on, cov, conf = _score_one(req, c.fact.searchable)
            best = max(best, s)
            if cov:
                covers.append(idx)
            on_any = on_any or on
            conflict_any = conflict_any or conf
        c.term_score = best
        c.covers = covers
        c.on_target = on_any
        # veto only a pure near-neighbour: it conflicts somewhere and covers nothing
        c.quantity_conflict = conflict_any and not covers
    return candidates
