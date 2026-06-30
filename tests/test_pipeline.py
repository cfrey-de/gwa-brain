"""M2 gate: end-to-end pipeline against mock facts -> structured QAResult with
used_facts, struck_facts (near neighbour surfaced), gaps, and cited answer."""
from gwa.ingestion.ingest import ingest_collect
from gwa.qa.pipeline import ask, run


def _ingest(text_doc, brain, llm):
    path, name = text_doc
    ingest_collect(path, name, brain, llm)
    return name


def test_pipeline_keeps_on_target_strikes_near_neighbour(text_doc, brain, llm, settings):
    name = _ingest(text_doc, brain, llm)
    res = ask("Wie hoch ist der Wasserstand nach 500 Stunden?", brain, llm, settings)

    kept_texts = " ".join(f["text"] for f in res.used_facts)
    struck_texts = " ".join(f["text"] for f in res.struck_facts)

    assert "500" in kept_texts and "160" in kept_texts          # on-target fact kept
    assert "100 Stunden" in struck_texts                         # near neighbour struck
    # the struck near neighbour carries an honest reason
    near = [f for f in res.struck_facts if "100 Stunden" in f["text"]][0]
    assert near["reason"]
    assert near["on_target"] is False


def test_answer_is_cited(text_doc, brain, llm, settings):
    name = _ingest(text_doc, brain, llm)
    res = ask("Wie hoch ist der Wasserstand nach 500 Stunden?", brain, llm, settings)
    assert res.answer
    assert f"[{name}" in res.answer          # every sentence cites its source


def test_uncovered_requirement_becomes_gap(text_doc, brain, llm, settings):
    name = _ingest(text_doc, brain, llm)
    # ask for something the document does not contain
    res = ask("Wie hoch ist der Wasserstand nach 500 Stunden und der Temperaturbereich?",
              brain, llm, settings)
    assert res.gaps, "expected an honest gap for the uncovered temperature part"
    assert any("temperatur" in g.lower() for g in res.gaps)


def test_result_shape_and_tree(text_doc, brain, llm, settings):
    name = _ingest(text_doc, brain, llm)
    res = ask("Wie hoch ist der Wasserstand nach 500 Stunden?", brain, llm, settings)
    d = res.to_dict()
    for key in ("question", "answer", "sub_requirements", "used_facts",
                "struck_facts", "gaps", "sources", "dependency_tree"):
        assert key in d
    tree = d["dependency_tree"]
    assert any(n["type"] == "answer" for n in tree["nodes"])
    assert any(n["status"] == "kept" for n in tree["nodes"])


class _IndexGuardLLM:
    """A guard that returns verdicts keyed by the SHORT index id (as a real model does),
    not the fact UUID. Verifies the guard matches verdicts by index, not by UUID."""
    def complete(self, role, system, user, temperature=None):
        return '{"verdicts": [{"id": "0", "keep": true, "reason": "covered"}, ' \
               '{"id": "1", "keep": false, "reason": "off-topic"}]}'


def test_guard_matches_verdicts_by_index():
    from gwa.models import Candidate, Fact
    from gwa.qa.guard import guard
    c0 = Candidate(fact=Fact("Nach 500 Stunden 160 Zentimeter.", "d", "d#c0", page=1))
    c1 = Candidate(fact=Fact("Der Zulauf ist aus Stahl.", "d", "d#c1", page=1))
    c0.on_target = c1.on_target = True
    c0.covers = c1.covers = [0]
    kept, struck = guard([c0, c1], ["Wasserstand nach 500 Stunden"], _IndexGuardLLM())
    assert c0 in kept and c0.reason == "covered"
    assert c1 in struck


def test_run_emits_ordered_events(text_doc, brain, llm, settings):
    name = _ingest(text_doc, brain, llm)
    events = []
    run("Wie hoch ist der Wasserstand nach 500 Stunden?", brain, llm, settings,
        emit=events.append)
    types = [e["type"] for e in events]
    assert types[0] == "decompose"
    assert "retrieve" in types
    assert types[-1] == "answer"
    assert any(t == "guard_keep" for t in types)
    assert any(t == "guard_strike" for t in types)


def test_scope_disambiguates_entity(brain, llm, settings):
    """Stufe 2: a fact whose subject lives only in the document heading (its `context`)
    is still matched for an entity question — and ranked above a same-text rival under a
    different heading. Without scope, the two facts are indistinguishable to the query."""
    from gwa.models import Fact
    brain.add_facts([
        Fact("The weight is 5 kilograms.", "dA", "dA#c0", context="Widget Alpha datasheet"),
        Fact("The weight is 8 kilograms.", "dB", "dB#c0", context="Widget Beta datasheet"),
    ])
    settings.top_k = 1
    res = ask("What is the weight of Widget Alpha?", brain, llm, settings)
    used = " ".join(f["text"] for f in res.used_facts)
    assert "5" in used and "8" not in used     # the Alpha-scoped fact, not Beta's
