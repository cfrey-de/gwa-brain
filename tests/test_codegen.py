"""Prototype: derivation tree -> grounded, executable code (gwa/codegen.py).

Verifies that (a) the generated code reproduces the values the demo documents state, and
(b) the embedded grounding check actually BITES when the logic is wrong — i.e. the document
value is a real oracle, not decoration.
"""
import json
import pathlib

import pytest

from gwa.codegen import generate

BRAIN = json.loads((pathlib.Path(__file__).parent.parent / "demo" / "brain.json").read_text())


def _target(substr):
    return next(f["id"] for f in BRAIN["facts"] if substr.lower() in f["text"].lower())


def _run(code):
    exec(compile(code, "<gen>", "exec"), {"__name__": "__main__"})


def test_generated_code_reproduces_document_values():
    for target in ("profit margin", "fill time in minutes"):
        code, n = generate(BRAIN, _target(target))
        assert n == 3
        _run(code)   # the embedded asserts raise if any node misses its document-stated value


def test_grounding_guard_catches_wrong_logic():
    # corrupt the top function; the document-value assert must fail (guarded, not trusted)
    code, _ = generate(BRAIN, _target("profit margin"))
    broken = code.replace("return operating_profit / q3_revenue",
                          "return operating_profit / q3_revenue * 2")
    assert broken != code
    with pytest.raises(AssertionError):
        _run(broken)
