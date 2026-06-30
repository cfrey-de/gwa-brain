"""M2: the term-specificity filter (Stufe B) and the two-stage retriever.

The headline case is the near-neighbour substitution: a fact about 100 hours must
NOT satisfy a requirement about 500 hours, even though they are semantically close.
"""
from gwa.models import Candidate, Fact
from gwa.qa.retriever import retrieve
from gwa.qa.term_filter import (numbers, quantity_terms,
                                term_specificity_filter)


def _cand(text):
    return Candidate(fact=Fact(text=text, source_doc="d", chunk_id="d#c0", page=1))


def test_quantity_extraction():
    assert numbers("160 cm nach 500 Stunden") == {"160", "500"}
    assert ("500", "stunden") in quantity_terms("nach 500 Stunden")


def test_on_target_fact_passes():
    c = _cand("Der Wasserstand sinkt nach 500 Stunden auf 160 Zentimeter.")
    term_specificity_filter([c], ["Wasserstand nach 500 Stunden"])
    assert c.on_target is True
    assert 0 in c.covers


def test_near_neighbour_is_downgraded():
    # SAME qualifier (Stunden), DIFFERENT number (100 vs 500) -> off target
    c = _cand("Der Wasserstand betraegt nach 100 Stunden noch 180 Zentimeter.")
    term_specificity_filter([c], ["Wasserstand nach 500 Stunden"])
    assert c.on_target is False
    assert c.covers == []
    assert c.term_score < 0.3


def test_unrelated_fact_off_target():
    c = _cand("Der Zulauf besteht aus einem Stahlrohr.")
    term_specificity_filter([c], ["Wasserstand nach 500 Stunden"])
    assert c.on_target is False


def test_number_coincidence_with_wrong_qualifier_off_target():
    # same number (500) but a DIFFERENT qualifier (bar vs Stunden) must NOT match
    c = _cand("Der Betriebsdruck betraegt 500 bar.")
    term_specificity_filter([c], ["Wasserstand nach 500 Stunden"])
    assert c.on_target is False


def test_number_coincidence_unrelated_off_target():
    c = _cand("Das Projekt startete 2015 mit 500 Mitarbeitern.")
    term_specificity_filter([c], ["Wasserstand nach 500 Stunden"])
    assert c.on_target is False


def test_non_numeric_requirement_needs_real_overlap():
    c = _cand("Der Zulauf besteht aus einem verzinkten Stahlrohr.")
    term_specificity_filter([c], ["Zulauf Stahlrohr"])
    assert c.on_target is True


def test_retrieve_ranks_on_target_first(text_doc, brain, llm, settings):
    from gwa.ingestion.ingest import ingest_collect
    path, name = text_doc
    ingest_collect(path, name, brain, llm)
    cands = retrieve(brain, ["Wasserstand nach 500 Stunden"], settings)
    assert cands, "no candidates retrieved"
    top = cands[0]
    assert "500" in top.fact.text and "160" in top.fact.text
    assert top.on_target is True
    # the 100-hour near neighbour is present but off target
    near = [c for c in cands if "100 Stunden" in c.fact.text]
    assert near and near[0].on_target is False


def test_small_topk_keeps_on_target_covering_fact(text_doc, brain, llm, settings):
    """With a tight cap, an on-target covering fact must not be truncated by a
    higher-cosine off-target near-neighbour (which would cause a false gap)."""
    from gwa.ingestion.ingest import ingest_collect
    path, name = text_doc
    ingest_collect(path, name, brain, llm)
    settings.top_k = 1
    cands = retrieve(brain, ["Wasserstand nach 500 Stunden"], settings)
    assert len(cands) == 1
    assert cands[0].on_target is True
    assert "500" in cands[0].fact.text
