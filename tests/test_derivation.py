"""Derivation mode: steps with dependencies -> a real fact->fact DAG -> a deep tree."""
import json

from gwa.ingestion.ingest import ingest_collect
from gwa.llm import MockLLM
from gwa.qa.pipeline import ask


class _DerivLLM:
    """Returns a derivation (steps + depends_on) for the derivation-extract prompt;
    delegates every other role to the standard MockLLM (decompose/guard/formulate)."""
    _mock = MockLLM()

    def complete(self, role, system, user, temperature=None):
        if "derivation" in system.lower():
            return json.dumps({"steps": [
                {"id": "s1", "text": "Der Umsatz beträgt 100 Euro.", "depends_on": []},
                {"id": "s2", "text": "Die Kosten betragen 60 Euro.", "depends_on": []},
                {"id": "s3", "text": "Der Gewinn ist Umsatz minus Kosten und beträgt 40 Euro.",
                 "depends_on": ["s1", "s2"]},
                {"id": "s4", "text": "Die Marge ist Gewinn durch Umsatz und beträgt 40 Prozent.",
                 "depends_on": ["s3", "s1"]},
            ]}, ensure_ascii=False)
        return self._mock.complete(role, system, user, temperature)


def _doc(tmp_path):
    p = tmp_path / "Rechnung.txt"
    p.write_text("Umsatz 100, Kosten 60, Gewinn = Umsatz - Kosten, Marge = Gewinn / Umsatz.",
                 encoding="utf-8")
    return str(p), "Rechnung.txt"


def test_derivation_ingest_builds_dep_graph(brain, tmp_path):
    path, name = _doc(tmp_path)
    done = ingest_collect(path, name, brain, _DerivLLM(), extract_mode="derivation")
    assert done["new_facts"] == 4
    # map text -> id
    by_text = {f.text: fid for fid, f in brain.facts.items()}
    marge = next(i for t, i in by_text.items() if "Marge" in t)
    gewinn = next(i for t, i in by_text.items() if "Gewinn ist" in t)
    umsatz = next(i for t, i in by_text.items() if t.startswith("Der Umsatz"))
    kosten = next(i for t, i in by_text.items() if "Kosten betragen" in t)
    assert set(brain.deps[marge]) == {gewinn, umsatz}
    assert set(brain.deps[gewinn]) == {umsatz, kosten}


def test_derivation_subtree_is_transitive(brain, tmp_path):
    path, name = _doc(tmp_path)
    ingest_collect(path, name, brain, _DerivLLM(), extract_mode="derivation")
    marge = next(i for i, f in brain.facts.items() if "Marge" in f.text)
    sub = brain.dependency_subtree([marge])
    derived_texts = " ".join(n["text"] for n in sub["nodes"])
    assert "Gewinn" in derived_texts and "Umsatz" in derived_texts and "Kosten" in derived_texts
    assert all(n["status"] == "derived" for n in sub["nodes"])
    assert all(l["kind"] == "derives" for l in sub["links"])


def test_ask_produces_derives_links(brain, settings, tmp_path):
    path, name = _doc(tmp_path)
    ingest_collect(path, name, brain, _DerivLLM(), extract_mode="derivation")
    res = ask("Wie hoch ist die Marge?", brain, _DerivLLM(), settings)
    tree = res.dependency_tree
    assert any(l["kind"] == "derives" for l in tree["links"]), "expected a derivation chain"
    assert any(n["status"] == "derived" for n in tree["nodes"])


def test_reset_clears_deps(brain, tmp_path):
    path, name = _doc(tmp_path)
    ingest_collect(path, name, brain, _DerivLLM(), extract_mode="derivation")
    assert brain.deps
    brain.reset()
    assert brain.deps == {}
