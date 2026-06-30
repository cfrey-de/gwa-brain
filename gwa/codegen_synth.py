"""Direction #1, step C — ORACLE-GUIDED formula synthesis.

Empirical finding that motivates this: the derivation extractor normalises facts to
result-only statements ("Gross profit is EUR 200,000") and keeps the dependency DAG, but
DROPS the operator. The controlled-phrasing parser in `gwa.codegen` therefore finds nothing.

But the operator is recoverable WITHOUT reading prose: given a derived node's dependency
VALUES and the value the document STATES for it, search the small space of
{+, -, *, /} x operand-order x {raw, percent-as-ratio} x {result, result/100} for the
combination(s) that reproduce the stated value. The document's own number disambiguates the
formula — the oracle doesn't just verify the code, it SYNTHESISES it. If exactly one formula
survives, we emit it deterministically (no LLM). If several survive (a genuine tie) or none,
that node is flagged for an LLM/text tie-breaker — the honest place the language model earns
its keep.

Run:  python -m gwa.codegen_synth research/hard_phrasing/brain.json margin total
"""
import itertools

from gwa.codegen import _result, _slug, _subject

_TOL = 1e-4


def _value(fact):
    """(number, is_percent) the document states for this fact."""
    v, u = _result(fact["text"])
    return v, (u == "percent")


def recover(dep_values, result):
    """dep_values: [(num, is_pct), ...] in DAG order; result: (num, is_pct).
    Return the distinct formulas (op, operand-order, per-operand scale, result/100?) that
    reproduce the stated result. Binary nodes only (the demo/hard cases)."""
    if len(dep_values) != 2:
        return []
    def interps(v):                       # a percent operand may mean its ratio (19% -> 0.19)
        yield (v[0], 1.0)
        if v[1]:
            yield (v[0] / 100.0, 0.01)
    r_targets = [(result[0], False)] + ([(result[0] / 100.0, True)] if result[1] else [])
    sols, seen = [], set()
    for order in set(itertools.permutations(range(2))):
        a_opts = list(interps(dep_values[order[0]]))
        b_opts = list(interps(dep_values[order[1]]))
        for (av, asc) in a_opts:
            for (bv, bsc) in b_opts:
                for sym, val in (("+", av + bv), ("-", av - bv), ("*", av * bv),
                                 ("/", av / bv if bv else None)):
                    if val is None:
                        continue
                    for (rt, rdiv) in r_targets:
                        if abs(val - rt) <= max(1e-9, abs(rt) * _TOL):
                            # +,* are commutative: a op b and b op a are ONE formula, not two
                            if sym in ("+", "*"):
                                key = (sym, tuple(sorted((asc, bsc))), rdiv)
                            else:
                                key = (sym, order, asc, bsc, rdiv)
                            if key not in seen:
                                seen.add(key)
                                sols.append(dict(op=sym, order=order, scale=(asc, bsc), rdiv=rdiv))
    return sols


def synthesize(brain, target_id):
    """Walk the target's DAG, recover each derived node's operator against the oracle, and
    emit grounded Python. Returns (source, rows) where rows records per-node recovery."""
    by_id = {f["id"]: f for f in brain["facts"]}
    deps = brain["deps"]
    order, seen = [], set()
    def visit(n):
        if n in seen or n not in by_id:
            return
        seen.add(n)
        for c in deps.get(n, []):
            visit(c)
        order.append(n)
    visit(target_id)

    name = {fid: _slug(_subject(by_id[fid]["text"])) for fid in order}
    inputs, funcs, checks, rows = [], [], [], []

    for fid in order:
        f = by_id[fid]
        val, pct = _value(f)
        ds = deps.get(fid, [])
        if not ds:
            inputs.append(f'{name[fid]} = {val!r}   # "{f["text"]}"')
            continue
        sols = recover([_value(by_id[d]) for d in ds], (val, pct))
        distinct_ops = {(s["op"], s["order"], s["scale"], s["rdiv"]) for s in sols}
        if len(distinct_ops) == 1:
            s = sols[0]
            status = "unique"
        elif len(distinct_ops) > 1:
            rows.append((name[fid], "AMBIGUOUS", f"{len(distinct_ops)} formulas fit -> LLM/text tie-breaker"))
            funcs.append(f'# ~ {name[fid]}: ambiguous ({len(distinct_ops)} formulas reproduce {val}) -> needs LLM')
            continue
        else:
            rows.append((name[fid], "NONE", f"no formula reproduces {val} -> extraction/value error"))
            funcs.append(f'# x {name[fid]}: no formula reproduces {val} -> flagged')
            continue

        ordered = [ds[i] for i in s["order"]]
        params = [name[d] for d in ordered]
        terms = [f"{p} / 100" if sc == 0.01 else p for p, sc in zip(params, s["scale"])]
        expr = f" {s['op']} ".join(terms)
        funcs.append(f'def {name[fid]}({", ".join(params)}):\n'
                     f'    """{f["text"]} — operator recovered against the stated value."""\n'
                     f'    return {expr}')
        args = ", ".join(("_" + name[d] if deps.get(d) else name[d]) for d in ordered)
        lhs = "_" + name[fid]
        assertion = (f"round({lhs} * 100, 2) == {val}" if s["rdiv"] else f"round({lhs}, 2) == {val}")
        checks.append(f'{lhs} = {name[fid]}({args})\nassert {assertion}, "{name[fid]}"')
        rows.append((name[fid], "unique",
                     f"{' '.join(terms).replace(name[fid], '')}= {'{}%'.format(val) if pct else val}".strip()))

    src = ['"""Oracle-synthesised business logic — operators recovered against document values."""', '']
    src += ["# inputs:", *inputs, "", "# derived (operator recovered by oracle-guided search):"]
    src += ["\n\n".join(funcs), "", 'if __name__ == "__main__":']
    src += ["    " + l for c in checks for l in c.split("\n")]
    src += [f'    print("\\u2713 {len(checks)} nodes: operators recovered AND verified against the document")']
    return "\n".join(src), rows


if __name__ == "__main__":
    import json
    import sys
    brain = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "research/hard_phrasing/brain.json"))
    targets = sys.argv[2:] or ["margin", "total"]
    uniq = amb = none = 0
    for target in targets:
        tid = next(f["id"] for f in brain["facts"] if target.lower() in f["text"].lower())
        code, rows = synthesize(brain, tid)
        print(f"\n==== target '{target}' — operator recovery ====")
        for n, st, detail in rows:
            print(f"   [{st:<9}] {n}: {detail}")
            uniq += st == "unique"; amb += st == "AMBIGUOUS"; none += st == "NONE"
        print("   --- generated code ---")
        print("\n".join("   " + l for l in code.splitlines()))
        try:
            exec(compile(code, "<s>", "exec"), {"__name__": "__main__"})
        except AssertionError as e:
            print(f"   xoracle REJECTED synthesised formula: {e}")
    print(f"\n==== recovery: {uniq} unique · {amb} ambiguous · {none} none ====")
