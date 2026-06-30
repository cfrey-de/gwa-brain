"""Prototype: derivation tree -> grounded, executable business logic.

Idea (a next step beyond the rendered tree): the `depends_on` DAG that GWA Brain extracts
from a document is already a dataflow graph. This turns it into runnable Python — one pure
function per derived quantity — AND auto-generates a grounding check: every node must
reproduce the value the *document itself states*. The document is the test oracle.

So the chain is: documents -> facts + derivation DAG -> generated code, verified against the
document's own numbers. If the generated code does NOT reproduce a stated value, that node is
flagged (un-grounded) instead of silently trusted — the same "guarded, not trusted" stance,
one level up (cf. README "How GWA Brain differs": this is the *executable* end of provenance).

HONEST SCOPE: the formula parser below is a HEURISTIC over controlled phrasing
("X equals A divided by B, and equals R"). It is NOT a general NL-to-code engine. The
GROUNDING guarantee does not come from the parser — it comes from the assert-against-the-
document-value check. A wrong parse fails its assert and is rejected, not shipped.
"""
import re

_OPS = [("divided by", "/"), ("multiplied by", "*"), ("times", "*"),
        ("minus", "-"), ("plus", "+")]
_UNIT = r"percent|euros?|litres? per second|litres?|seconds?|minutes?|hours?|bar|kilograms?|metres?"


def _num(tok):
    """'500,000' / '9 600' / '1 200' / '16' -> float (comma & space thousands separators)."""
    return float(tok.replace(",", "").replace(" ", "").replace(" ", ""))


def _first_number(s):
    m = re.search(r"\d[\d,.  ]*\d|\d", s)
    return _num(m.group(0)) if m else None


def _strip_article(s):
    return re.sub(r"^(the|a|an)\s+", "", s.strip().lower())


def _slug(s):
    return re.sub(r"[^a-z0-9]+", "_", _strip_article(s)).strip("_")


def _subject(text):
    """The thing being defined: everything before the first 'equals/is/are'."""
    return re.split(r"\s+(?:equals|is|are)\s+", text, maxsplit=1)[0].strip()


def _result(text):
    """(value, unit) the document STATES for this fact. For a derived fact it is the part
    after ', and equals'; for a leaf it is the number in the sentence. Prefer the number that
    sits next to a unit, so 'Q3 Revenue is 500,000 euros' yields 500000, not 3 (from 'Q3')."""
    tail = re.split(r",\s+and\s+(?:equals|is)\s+", text, maxsplit=1)
    seg = tail[1] if len(tail) > 1 else text
    m = re.search(r"(\d[\d,. ]*\d|\d)\s*(" + _UNIT + r")", seg)
    if m:
        return _num(m.group(1)), m.group(2)
    return _first_number(seg), ""


def _parse_formula(text, dep_facts):
    """-> (op_symbol, [operandA_ref, operandB_ref]) or None if it can't be grounded.
    Each operand ref is ('fact', id) | ('literal', number). Operands are matched to the
    node's OWN deps by name (NOT by deps order — order is unreliable for '/' and '-')."""
    head = re.split(r",\s+and\s+(?:equals|is)\s+", text, maxsplit=1)[0]
    for phrase, sym in _OPS:
        if phrase in head:
            left, _, right = head.partition(phrase)
            a = re.split(r"\s+(?:equals|is|are)\s+", left, maxsplit=1)[-1]
            operands = []
            for raw in (a, right):
                p = _strip_article(raw.rstrip("."))
                if re.fullmatch(r"[\d,.  ]+", p):          # a literal constant (e.g. 60)
                    operands.append(("literal", _num(p)))
                    continue
                hit = next((df for df in dep_facts
                            if p in _strip_article(_subject(df["text"]))
                            or _strip_article(_subject(df["text"])) in p), None)
                if not hit:
                    return None                                 # operand not grounded in a dep
                operands.append(("fact", hit["id"]))
            return sym, operands
    return None


def generate(brain, target_id):
    """Return (python_source, n_nodes). `brain` is a loaded brain.json dict."""
    by_id = {f["id"]: f for f in brain["facts"]}
    deps = brain["deps"]

    order, seen = [], set()
    def visit(n):
        if n in seen or n not in by_id:
            return
        seen.add(n)
        for c in deps.get(n, []):
            visit(c)
        order.append(n)                                         # deps-before-dependents
    visit(target_id)

    name = {fid: _slug(_subject(by_id[fid]["text"])) for fid in order}
    src = ['"""Auto-generated from a GWA Brain derivation tree. Each function is grounded in a',
           'source clause; the checks at the bottom assert it reproduces the document\'s value."""', '']
    inputs, funcs, checks = [], [], []

    for fid in order:
        f = by_id[fid]
        src_lbl = f["source_doc"]
        val, unit = _result(f["text"])
        if not deps.get(fid):                                   # leaf -> an input constant
            inputs.append(f'{name[fid]} = {val!r}   # "{f["text"]}" [{src_lbl}]')
            continue
        parsed = _parse_formula(f["text"], [by_id[d] for d in deps[fid] if d in by_id])
        if not parsed:                                          # honest gap: cannot ground it
            funcs.append(f'# ⚠ could not ground "{f["text"]}" — left as a gap')
            continue
        sym, operands = parsed
        ref = lambda o: (str(o[1]) if o[0] == "literal" else name[o[1]])
        params = [name[o[1]] for o in operands if o[0] == "fact"]
        expr = f" {sym} ".join(ref(o) for o in operands)
        funcs.append(f'def {name[fid]}({", ".join(params)}):\n'
                     f'    """{f["text"]} [{src_lbl}]."""\n'
                     f'    return {expr}')
        # grounding check: feed the deps' computed/leaf values, assert the stated result
        args = ", ".join(("_" + name[o[1]] if deps.get(o[1]) else name[o[1]])
                         for o in operands if o[0] == "fact")   # literals are inlined, not params
        call = f"{name[fid]}({args})"
        if unit == "percent":
            checks.append(f'_{name[fid]} = {call}\n'
                          f'assert round(_{name[fid]} * 100, 2) == {val}, "{name[fid]} (percent)"')
        else:
            checks.append(f'_{name[fid]} = {call}\n'
                          f'assert round(_{name[fid]}, 2) == {val}, "{name[fid]} ({unit})"')

    src += ["# --- inputs (leaf facts, value stated in the source) ---", *inputs, ""]
    src += ["# --- derived business logic (one function per derived quantity) ---"]
    src += ["\n\n".join(funcs), ""]
    src += ['# --- grounding check: every node must reproduce the document-stated value ---',
            'if __name__ == "__main__":', *["    " + l for c in checks for l in c.split("\n")],
            f'    print("✓ all {len(checks)} derived nodes reproduce the document values")']
    return "\n".join(src), len(checks)


if __name__ == "__main__":
    import json
    import sys
    brain = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "demo/brain.json"))
    target = sys.argv[2] if len(sys.argv) > 2 else "profit margin"
    tid = next(f["id"] for f in brain["facts"] if target.lower() in f["text"].lower())
    code, n = generate(brain, tid)
    print(code)
