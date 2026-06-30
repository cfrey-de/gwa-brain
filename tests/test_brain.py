"""Brain persistence + self-healing reconcile (the desync edge case)."""
from gwa.graph.brain import KnowledgeBrain
from gwa.models import Fact


def test_self_heal_reindex_after_qdrant_wipe(tmp_path, embedder):
    """If the Qdrant volume is wiped but ./data/brain.json survives (e.g.
    `docker compose down -v`), a restart must re-index facts from their persisted
    text so search keeps working — not silently return empty."""
    from qdrant_client import QdrantClient
    data_dir = str(tmp_path / "data")

    q1 = QdrantClient(location=":memory:")
    b1 = KnowledgeBrain(q1, embedder, data_dir=data_dir, collection="c")
    b1.add_facts([
        Fact("Nach 500 Stunden betraegt der Wasserstand 160 Zentimeter.", "d", "d#c0", page=1),
        Fact("Nach 100 Stunden betraegt der Wasserstand 180 Zentimeter.", "d", "d#c1", page=1),
    ])
    b1.save()
    assert b1.search("Wasserstand nach 500 Stunden", 5)

    # fresh, EMPTY Qdrant + the same surviving brain.json
    q2 = QdrantClient(location=":memory:")
    b2 = KnowledgeBrain(q2, embedder, data_dir=data_dir, collection="c")
    assert len(b2.facts) == 2
    hits = b2.search("Wasserstand nach 500 Stunden", 5)
    assert hits, "search must work after self-heal re-index"
    assert any("500" in f.text for f, _ in hits)


def test_reset_clears_everything(tmp_path, embedder):
    from qdrant_client import QdrantClient
    data_dir = str(tmp_path / "data")
    b = KnowledgeBrain(QdrantClient(location=":memory:"), embedder,
                       data_dir=data_dir, collection="c")
    b.add_facts([Fact("Das Gehaeuse ist robust.", "d", "d#c0", page=1)])
    b.register_doc("d", 1, "ts")
    b.save()
    assert b.brain_path.exists()
    b.reset()
    assert len(b.facts) == 0 and len(b.docs) == 0
    assert not b.brain_path.exists()
    assert b.search("Gehaeuse", 5) == []
