"""Ingestion orchestration: document -> chunks -> facts -> brain, as a generator of
progress events (consumed by the SSE upload endpoint and, drained, by tests)."""
from datetime import datetime, timezone

from gwa.ingestion.extractor import extract
from gwa.ingestion.fact_parser import parse_facts, parse_steps
from gwa.models import Fact


def _now():
    return datetime.now(timezone.utc).isoformat()


def ingest_document(path, filename, brain, llm, extract_mode="auto"):
    """Yield events: start -> chunk* -> done. Mutates `brain` (caller serializes writes)."""
    chunks, pages = extract(path, filename)
    yield {"type": "start", "file": filename, "pages": pages}

    if extract_mode == "derivation":
        new_total = yield from _ingest_derivation(chunks, filename, brain, llm)
    else:
        new_total = 0
        for ch in chunks:
            fact_strs = parse_facts(ch.text, llm, mode=extract_mode)
            facts = [Fact(text=t, source_doc=filename, chunk_id=ch.chunk_id,
                          page=ch.page, paragraph=ch.paragraph,
                          context=ch.context or "") for t in fact_strs]
            new_total += brain.add_facts(facts)
            yield {"type": "chunk", "page": ch.page, "chunk": ch.index + 1,
                   "total_chunks": len(chunks), "facts": fact_strs}

    brain.register_doc(filename, new_total, _now())
    brain.save()
    yield {"type": "done", "new_facts": new_total,
           "brain_total": len(brain.facts), "doc": filename}


def _ingest_derivation(chunks, filename, brain, llm):
    """Treat the whole document as one derivation so step dependencies resolve across it.
    Returns the number of new facts; yields one chunk event with the step texts."""
    full_text = "\n".join(ch.text for ch in chunks)
    page = chunks[0].page if chunks else None
    ctx = (chunks[0].context if chunks else "") or ""
    steps = parse_steps(full_text, llm)
    local2fact = {}
    facts = []
    for i, st in enumerate(steps):
        f = Fact(text=st["text"], source_doc=filename,
                 chunk_id=f"{filename}#s{i}", page=page, context=ctx)
        local2fact[st["id"]] = f
        facts.append(f)
    new_total = brain.add_facts(facts)
    for st in steps:
        dep_ids = [local2fact[d].id for d in st["depends_on"] if d in local2fact]
        if dep_ids:
            brain.add_dependencies(local2fact[st["id"]].id, dep_ids)
    yield {"type": "chunk", "page": page, "chunk": 1, "total_chunks": 1,
           "facts": [st["text"] for st in steps]}
    return new_total


def ingest_collect(path, filename, brain, llm, extract_mode="auto") -> dict:
    """Drain the generator and return the final `done` event (for tests/non-stream use)."""
    last = None
    for ev in ingest_document(path, filename, brain, llm, extract_mode=extract_mode):
        last = ev
    return last
