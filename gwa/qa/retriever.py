"""Two-stage retrieval (Stufe A broad semantic search + Stufe B term-specificity)
plus the accumulation re-rank that makes graph weight functional, not cosmetic.

final_score = (1 - w) * (0.6*cosine + 0.4*term_score) + w * normalized_graph_weight

So a frequently co-cited fact (higher weight) outranks an equal-cosine newcomer, and
an off-target near-neighbour (low term_score) sinks. `w` = settings.accumulation_weight.
"""
from gwa.models import Candidate
from gwa.qa.term_filter import term_specificity_filter


def _broad_search(brain, sub_requirements, top_k):
    """Union of per-sub-requirement Qdrant searches, keeping the best cosine per fact."""
    seen: dict[str, Candidate] = {}
    queries = sub_requirements or [""]
    for req in queries:
        for fact, score in brain.search(req, top_k):
            c = seen.get(fact.id)
            if c is None:
                seen[fact.id] = Candidate(fact=fact, score=score)
            elif score > c.score:
                c.score = score
    return list(seen.values())


def _apply_accumulation(candidates, weight):
    if not candidates:
        return
    ws = [c.fact.weight for c in candidates]
    wmin, wmax = min(ws), max(ws)
    span = (wmax - wmin) or 1.0
    for c in candidates:
        base = 0.6 * c.score + 0.4 * c.term_score
        nw = (c.fact.weight - wmin) / span
        c.final_score = (1.0 - weight) * base + weight * nw


def retrieve(brain, sub_requirements, settings):
    """Return candidates sorted by final_score (best first), capped at top_k."""
    candidates = _broad_search(brain, sub_requirements, settings.top_k)
    term_specificity_filter(candidates, sub_requirements)
    _apply_accumulation(candidates, settings.accumulation_weight)
    # on_target first, then by score: a covering fact must never be truncated by a
    # higher-cosine off-target near-neighbour that the guard would strike anyway —
    # otherwise gap_check would report a false gap for a fact we actually retrieved.
    candidates.sort(key=lambda c: (c.on_target, c.final_score), reverse=True)
    return candidates[: settings.top_k]
