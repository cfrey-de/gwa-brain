"""Reality check for the G2 gap: does GWA's extraction + oracle-guided consistency audit catch
a numeric inconsistency planted in a MESSY, realistic document (not the curated demo)?

For each doc: ingest with the real LLM (derivation mode) -> a derivation DAG over the STATED
numbers; then audit every derived node — does ANY arithmetic over its dependency values
reproduce the value the document states for it? If none does, the node is FLAGGED as a
self-inconsistency. Compare to ground truth (one planted wrong result + several correct ones +
noise numbers that must NOT be flagged).

This measures the ONLY axis where G2 has a moat (recovery on arbitrary messy documents). It is
a research harness, not a shipped feature. Run:  python research/reality_check.py
"""
import json
import pathlib

from gwa.codegen_synth import _value, recover
from gwa.config import Settings
from gwa.deps import build_embedder, build_limiter, build_llm, build_qdrant
from gwa.graph.brain import KnowledgeBrain
from gwa.ingestion.ingest import ingest_collect

HERE = pathlib.Path(__file__).parent / "reality_check"

# ground truth: the planted (wrong) node, its stated value, and the correct nodes that must stay OK
GT = {
    "doc_a_report.txt": {"planted": "margin", "planted_val": 18,
                         "correct": ["gross profit", "operating profit"]},
    "doc_b_budget.txt": {"planted": "project budget", "planted_val": 460000,
                         "correct": ["direct costs", "overhead"]},
}


def _consistent(dep_values, result):
    """Does some arithmetic over the deps reproduce the stated result? Binary -> recover();
    n-ary -> try sum-of-all and product-of-all (percent operand as ratio)."""
    if len(dep_values) == 2:
        return bool(recover(dep_values, result))
    targets = [result[0]] + ([result[0] / 100.0] if result[1] else [])
    s = sum(v[0] for v in dep_values)
    p = 1.0
    for v in dep_values:
        p *= (v[0] / 100.0 if v[1] else v[0])
    return any(abs(s - t) <= max(1e-9, abs(t) * 1e-4) or abs(p - t) <= max(1e-9, abs(t) * 1e-4)
              for t in targets)


def audit(brain):
    by_id = {f["id"]: f for f in brain["facts"]}
    rows = []
    for fid, f in by_id.items():
        ds = brain["deps"].get(fid, [])
        if not ds:
            continue                                    # leaf / noise number -> not a derived claim
        if any(d not in by_id for d in ds):
            rows.append((f["text"], None, [], "dep-missing"))
            continue
        vals = [_value(by_id[d]) for d in ds]
        res = _value(f)
        ok = _consistent(vals, res)
        rows.append((f["text"], res[0], [v[0] for v in vals], "OK" if ok else "FLAGGED"))
    return rows


def run():
    import tempfile
    for name, gt in GT.items():
        ddir = tempfile.mkdtemp(prefix="rc_")             # isolate each doc (no cross-doc leak)
        s = Settings()
        brain = KnowledgeBrain(build_qdrant(s), build_embedder(s, build_limiter(s)),
                               data_dir=ddir, collection=s.collection)
        llm = build_llm(s, build_limiter(s))
        ingest_collect(str(HERE / name), name, brain, llm, extract_mode="derivation")
        brain.save()
        d = json.loads((pathlib.Path(ddir) / "brain.json").read_text())
        rows = audit(d)

        print(f"\n{'=' * 78}\n{name}  ({len(d['facts'])} facts, {len(rows)} derived nodes audited)")
        planted_row = None
        for text, stated, vals, status in rows:
            mark = "  " if status == "OK" else "->"
            print(f"  {mark} [{status:<11}] stated={stated} from deps={vals}  ::  {text[:70]}")
            if gt["planted"].lower() in text.lower():
                planted_row = (text, status)

        # scoring
        flagged_correct = [t for t, stated, vals, st in rows if st == "FLAGGED"
                           and any(c in t.lower() for c in gt["correct"])]
        if planted_row is None:
            print(f"  RESULT: MISS (extraction) — the planted node ('{gt['planted']}') was not extracted as a derived node")
        elif planted_row[1] == "FLAGGED":
            print(f"  RESULT: CAUGHT — planted inconsistency flagged ✓")
        else:
            print(f"  RESULT: MISS — planted node present but not flagged ({planted_row[1]})")
        print(f"  false positives on correct derivations: {len(flagged_correct)}"
              + (f"  {flagged_correct}" if flagged_correct else ""))


if __name__ == "__main__":
    run()
