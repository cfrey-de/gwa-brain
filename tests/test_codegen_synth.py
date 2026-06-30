"""Direction #1, step C — oracle-guided formula synthesis (gwa/codegen_synth.py).

The derivation extractor drops the operator (facts become result-only: "Gross profit is EUR
200,000"); these tests show the operator is recovered purely from the dependency values + the
document-stated result, that genuine ties are flagged (where an LLM/text tie-breaker is
needed), and that an impossible node yields no formula.
"""
import json
import pathlib

from gwa.codegen_synth import recover, synthesize

BRAIN = json.loads((pathlib.Path(__file__).parent.parent / "research" / "hard_phrasing" / "brain.json").read_text())


def _target(substr):
    return next(f["id"] for f in BRAIN["facts"] if substr.lower() in f["text"].lower())


def test_operators_recovered_on_operator_free_facts():
    for target in ("margin", "total"):
        code, rows = synthesize(BRAIN, _target(target))
        assert rows and all(st == "unique" for _, st, _ in rows)          # every operator recovered
        exec(compile(code, "<s>", "exec"), {"__name__": "__main__"})      # and the code passes its oracle


def test_percent_operand_and_scaling_recovered():
    # net=400, rate=19% -> 76 requires * with the rate read as a ratio (19/100)
    ops = {s["op"] for s in recover([(400.0, False), (19.0, True)], (76.0, False))}
    assert ops == {"*"}


def test_genuine_tie_is_flagged_for_a_tie_breaker():
    # 2 and 2 giving 4: '+' and '*' both fit -> the oracle alone cannot decide (needs LLM/text)
    ops = {s["op"] for s in recover([(2.0, False), (2.0, False)], (4.0, False))}
    assert {"+", "*"} <= ops


def test_no_formula_when_result_is_unreachable():
    assert recover([(3.0, False), (7.0, False)], (999.0, False)) == []
