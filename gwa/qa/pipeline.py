"""The Q&A pipeline: Decompose -> Retrieve -> Guard -> Gap -> Formulate -> Accumulate.

`run(...)` does the work synchronously and calls `emit(event)` for each pipeline event
(so the SSE endpoint can forward them live); it returns the full QAResult. `ask(...)`
is the no-stream convenience wrapper used by tests.

Only kept facts reach the formulate step (enforced), and the formulate prompt instructs
the model to cite them and add nothing else — so every shipped sentence is *meant* to be
source-bound (Stufe 2; best-effort, not code-validated). Uncovered sub-requirements are
detected and raised as gaps (enforced); the prompt asks the model to declare them.
"""
from gwa.llm import extract_json
from gwa.models import QAResult
from gwa.qa.guard import guard
from gwa.qa.prompts import (DECOMPOSE_SYSTEM, FORMULATE_SYSTEM,
                            build_formulate_user)
from gwa.qa.retriever import retrieve


def decompose(question, llm):
    try:
        raw = llm.complete("decompose", DECOMPOSE_SYSTEM, question, temperature=0.0)
        subs = extract_json(raw).get("sub_requirements", [])
    except Exception as e:  # noqa: BLE001
        print(f"[pipeline] decompose failed, using whole question: {e}")
        subs = []
    clean = [s.strip() for s in subs if isinstance(s, str) and s.strip()]
    return clean or [question.strip()]


def gap_check(sub_requirements, kept):
    covered = set()
    for c in kept:
        covered |= set(c.covers)
    return [sub_requirements[i] for i in range(len(sub_requirements)) if i not in covered]


def formulate(question, kept, gaps, llm):
    facts = [(c.fact.text, c.fact.source_label) for c in kept]
    user = build_formulate_user(question, facts, gaps)
    try:
        return llm.complete("formulate", FORMULATE_SYSTEM, user, temperature=0.2).strip()
    except Exception as e:  # noqa: BLE001
        print(f"[pipeline] formulate failed: {e}")
        if not kept:
            return "No supported facts are available to answer this question."
        return " ".join(f"{t} [{s}]" for t, s in facts)


def _node(c, status):
    return {"id": c.fact.id, "type": "fact",
            "label": c.fact.text[:48] + ("…" if len(c.fact.text) > 48 else ""),
            "text": c.fact.text, "source": c.fact.source_label, "status": status,
            "reason": c.reason, "weight": round(c.fact.weight, 3), "uses": c.fact.uses}


def build_tree(answer, kept, struck, gaps, brain):
    ANS = "__answer__"
    nodes = [{"id": ANS, "type": "answer", "label": "Answer", "text": answer[:160],
              "source": "", "status": "answer", "reason": "", "weight": 1.0}]
    seen = {ANS}
    links = []

    def add_node(n):
        if n["id"] not in seen:
            seen.add(n["id"])
            nodes.append(n)

    for c in kept:
        add_node(_node(c, "kept"))
        links.append({"source": c.fact.id, "target": ANS, "kind": "support"})

    # derivation chain FIRST: each kept fact's prerequisite closure -> a deep tree.
    # (Added before struck so a prerequisite that was also a retrieved-but-struck
    # candidate is shown as part of the chain, not as a rejected candidate.)
    dep = brain.dependency_subtree([c.fact.id for c in kept])
    for n in dep["nodes"]:
        add_node(n)
    links.extend(dep["links"])

    for c in struck:
        if c.fact.id in seen:        # already shown as kept or as a derivation prerequisite
            continue
        add_node(_node(c, "struck"))
        links.append({"source": c.fact.id, "target": ANS, "kind": "struck"})
    for i, g in enumerate(gaps):
        gid = f"__gap_{i}__"
        add_node({"id": gid, "type": "gap", "label": g, "text": g,
                  "source": "", "status": "gap", "reason": "uncovered", "weight": 1.0})
        links.append({"source": gid, "target": ANS, "kind": "gap"})

    # co-usage edges among kept facts (accumulation made visible)
    for e in brain.co_usage_subgraph([c.fact.id for c in kept])["links"]:
        links.append({"source": e["source"], "target": e["target"],
                      "weight": e["weight"], "kind": "co_usage"})
    return {"nodes": nodes, "links": links}


def run(question, brain, llm, settings, guard_cross=None, emit=None):
    emit = emit or (lambda e: None)
    question = (question or "").strip()

    subs = decompose(question, llm)
    emit({"type": "decompose", "sub_requirements": subs})

    candidates = retrieve(brain, subs, settings)
    emit({"type": "retrieve", "candidates": len(candidates)})

    kept, struck = guard(candidates, subs, llm, guard_cross)
    for c in kept:
        emit({"type": "guard_keep", "id": c.fact.id, "fact": c.fact.text,
              "source": c.fact.source_label})
    for c in struck:
        emit({"type": "guard_strike", "id": c.fact.id, "fact": c.fact.text,
              "source": c.fact.source_label, "reason": c.reason})

    gaps = gap_check(subs, kept)
    for g in gaps:
        emit({"type": "gap", "missing": g})

    answer = formulate(question, kept, gaps, llm)

    # ACCUMULATE: cited facts gain weight + co-usage edges -> re-rank future retrieval
    brain.record_usage([c.fact for c in kept], question)
    brain.save()

    tree = build_tree(answer, kept, struck, gaps, brain)
    result = QAResult(
        question=question, answer=answer, sub_requirements=subs,
        used_facts=[c.to_dict() for c in kept],
        struck_facts=[c.to_dict() for c in struck],
        gaps=gaps,
        sources=sorted({c.fact.source_label for c in kept}),
        dependency_tree=tree,
    )
    emit({"type": "answer", "text": answer, "result": result.to_dict()})
    return result


def ask(question, brain, llm, settings, guard_cross=None) -> QAResult:
    return run(question, brain, llm, settings, guard_cross=guard_cross)
