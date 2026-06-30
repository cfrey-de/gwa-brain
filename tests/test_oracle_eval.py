"""Direction #1 harness (gwa/oracle_eval.py): the document-as-oracle mutation test.

Guards two things: (a) the document-value oracle KILLS every realistic structural mutant on
the demo trees (100% — the empirical backbone of the thesis), and (b) the instrument is not a
rubber stamp — sub-tolerance resolution probes DO survive, so a survival can be observed.
"""
import json
import pathlib

from gwa.codegen import generate
from gwa.oracle_eval import _STRUCTURAL, evaluate

BRAIN = json.loads((pathlib.Path(__file__).parent.parent / "demo" / "brain.json").read_text())


def _target(substr):
    return next(f["id"] for f in BRAIN["facts"] if substr.lower() in f["text"].lower())


def test_oracle_kills_all_structural_mutants_and_probes_can_survive():
    for target in ("profit margin", "fill time in minutes"):
        code, _ = generate(BRAIN, _target(target))
        res = evaluate(code)
        structural = [o for k, _, o in res if k in _STRUCTURAL]
        assert structural and all(o == "killed" for o in structural)   # 100% kill, no coincidental pass
        probes = [o for k, _, o in res if k == "tolerance_probe"]
        assert "survived" in probes                                    # not a rubber stamp
