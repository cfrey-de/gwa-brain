"""M3 gate: accumulation is functional, not cosmetic.

Two things must hold:
  1. A fact cited in one answer is reused in a later answer (it persists, and its
     usage count grows) — facts from question N can support question N+k.
  2. Graph weight actually RE-RANKS retrieval: boosting a fact lifts it above an
     equal-cosine rival. If weight only thickened edges for the picture, this would
     fail (the "dismissible as caching" trap the parent project warns about).
"""
from gwa.config import Settings
from gwa.models import Fact
from gwa.qa.pipeline import ask
from gwa.qa.retriever import retrieve


def test_record_usage_grows_weight_and_co_usage_edge(brain, llm, settings):
    brain.add_facts([
        Fact("Der Zulauf besteht aus einem verzinkten Stahlrohr.", "Datenblatt", "Datenblatt#c0", page=1),
        Fact("Der Betriebsdruck der Pumpe betraegt 3.7 bar.", "Datenblatt", "Datenblatt#c1", page=1),
    ])
    res = ask("Welcher Zulauf und welcher Betriebsdruck?", brain, llm, settings)
    ids = [f["id"] for f in res.used_facts]
    assert len(ids) >= 2, "expected both facts kept"
    # co-cited facts gain a co-usage edge ...
    assert brain.graph.has_edge(ids[0], ids[1])
    # ... and each cited fact gains weight + a use
    for i in ids:
        assert brain.facts[i].uses >= 1
        assert brain.facts[i].weight > 1.0


def test_fact_reused_across_questions(brain, llm, settings):
    brain.add_facts([
        Fact("Das Wartungsintervall betraegt 2000 Betriebsstunden.", "Studie", "Studie#c0", page=1),
    ])
    fid = next(iter(brain.facts))
    ask("Wie hoch ist das Wartungsintervall in Betriebsstunden?", brain, llm, settings)
    assert brain.facts[fid].uses == 1
    # a second, differently-worded question reuses the SAME persisted fact
    res2 = ask("Welches Wartungsintervall hat die Anlage in Betriebsstunden?", brain, llm, settings)
    assert fid in [f["id"] for f in res2.used_facts]
    assert brain.facts[fid].uses == 2


def test_accumulation_reranks_retrieval(brain, llm):
    """The decisive test: boosting the naturally-second candidate lifts it to #1."""
    brain.add_facts([
        Fact("Die Probe erreicht Stufe drei.", "d", "d#c0", page=1),
        Fact("Die Probe erreicht Stufe vier.", "d", "d#c1", page=1),
    ])
    Q = ["Welche Stufe erreicht die Probe?"]

    no_accum = Settings()
    no_accum.accumulation_weight = 0.0
    base = retrieve(brain, Q, no_accum)
    assert len(base) == 2 and all(c.on_target for c in base)
    loser = base[1].fact            # naturally ranked second on cosine alone

    for _ in range(10):             # accumulate usage on the loser
        brain.record_usage([loser], "boost")

    with_accum = Settings()
    with_accum.accumulation_weight = 0.5
    after = retrieve(brain, Q, with_accum)
    assert after[0].fact.id == loser.id, "accumulation weight did not change ranking"


def test_weights_persist_across_reload(brain, llm, settings, qdrant, embedder, tmp_path):
    from gwa.graph.brain import KnowledgeBrain
    brain.add_facts([Fact("Das Gehaeuse ist robust.", "d", "d#c0", page=1)])
    fid = next(iter(brain.facts))
    brain.record_usage([brain.facts[fid]], "q")
    brain.save()
    # reload from brain.json into a fresh brain over the same data dir
    reloaded = KnowledgeBrain(qdrant, embedder, data_dir=str(tmp_path / "data"),
                              collection="test_facts")
    assert reloaded.facts[fid].weight == brain.facts[fid].weight
    assert reloaded.facts[fid].uses == 1
