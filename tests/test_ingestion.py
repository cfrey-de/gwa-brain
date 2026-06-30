"""M1 gate: extraction -> facts -> Qdrant + NetworkX + atomic brain.json."""
import json

from gwa.ingestion.extractor import extract
from gwa.ingestion.ingest import ingest_collect, ingest_document


def test_extract_text_chunks(text_doc):
    path, name = text_doc
    chunks, pages = extract(path, name)
    assert pages is None  # text has no pages
    assert len(chunks) >= 1
    assert all(c.source_doc == name for c in chunks)
    assert chunks[0].paragraph is not None


def test_ingest_text_populates_brain(text_doc, brain, llm):
    path, name = text_doc
    done = ingest_collect(path, name, brain, llm)
    assert done["type"] == "done"
    assert done["new_facts"] >= 4              # four sentences -> >=4 facts
    assert len(brain.facts) == done["new_facts"]
    # every fact is a graph node with provenance
    for fid, fact in brain.facts.items():
        assert fid in brain.graph
        assert fact.source_doc == name
        assert fact.chunk_id.startswith(name)
    # doc registry + persisted brain.json
    assert name in brain.docs
    assert brain.brain_path.exists()
    data = json.loads(brain.brain_path.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert len(data["facts"]) == len(brain.facts)


def test_search_finds_specific_fact(text_doc, brain, llm):
    path, name = text_doc
    ingest_collect(path, name, brain, llm)
    hits = brain.search("Wasserstand nach 500 Stunden", top_k=5)
    assert hits, "search returned nothing"
    top_text = hits[0][0].text.lower()
    assert "500" in top_text and "160" in top_text  # the on-target fact ranks first


def test_collection_dim_matches_embedder(text_doc, brain, llm):
    path, name = text_doc
    ingest_collect(path, name, brain, llm)
    assert brain._dim == 256  # lexical embedder dimension, set lazily on first insert


def test_ingest_is_idempotent(text_doc, brain, llm):
    path, name = text_doc
    first = ingest_collect(path, name, brain, llm)
    n = len(brain.facts)
    second = ingest_collect(path, name, brain, llm)
    assert second["new_facts"] == 0      # same content -> no new facts (uuid5 dedup)
    assert len(brain.facts) == n


def test_ingest_stream_events(text_doc, brain, llm):
    path, name = text_doc
    events = list(ingest_document(path, name, brain, llm))
    assert events[0]["type"] == "start"
    assert events[-1]["type"] == "done"
    assert any(e["type"] == "chunk" for e in events)


def test_ingest_docx(docx_doc, brain, llm):
    path, name = docx_doc
    done = ingest_collect(path, name, brain, llm)
    assert done["new_facts"] >= 2
    assert any("3.7" in f.text or "bar" in f.text for f in brain.facts.values())


class _NonDictLLM:
    """Returns a top-level JSON array, not an object — must not crash parse_facts."""
    def complete(self, *a, **k):
        return '["fact one", "fact two"]'


def test_fact_parser_tolerates_non_dict_response():
    from gwa.ingestion.fact_parser import parse_facts
    assert parse_facts("Some chunk text here.", _NonDictLLM()) == []


def test_ingest_pdf(pdf_doc, brain, llm):
    path, name = pdf_doc
    chunks, pages = extract(path, name)
    assert pages == 1
    assert all(c.page == 1 for c in chunks)
    done = ingest_collect(path, name, brain, llm)
    assert done["new_facts"] >= 1
