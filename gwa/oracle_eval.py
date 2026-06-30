"""Research harness (direction #1): how strong is the document's OWN stated value as a test
oracle for LLM-compiled derivation code?

Method — mutation testing over `gwa.codegen` output. We take a correct generated program
(functions + the auto-generated "assert each node reproduces the document-stated value" check)
and apply single, realistic compilation-error mutations to the generated code:

    op_swap       an operator is wrong           (a / b  ->  a * b)
    operand_swap  operands flipped (non-commut.) (a - b  ->  b - a)
    rewire        a wrong-but-in-scope input      (a / b  ->  a / c)
    scale         a unit/scale slip               (x      ->  x * 60)

Each mutant is run against the grounding check. Outcome:
    killed    the oracle raised AssertionError — a wrong VALUE was caught  (good)
    survived  the check passed anyway — a COINCIDENTAL pass                (dangerous)
    crashed   a runtime error — caught by execution, not by the oracle

Headline metrics: kill rate (killed / value-mutants) and, more importantly, the survival
rate — wrong code the document oracle failed to catch. Low survival => the document is a
strong oracle; the surviving mutants characterise exactly where it is blind (e.g. commutative
ops, or perturbations inside the rounding tolerance).

This is the empirical core of the "document as its own test oracle" thesis, and it doubles as
the first real measurement the PoC has produced. Run:  python -m gwa.oracle_eval
"""
import ast
import contextlib
import copy
import io

_ARITH = {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/"}
_NONCOMMUTATIVE = (ast.Sub, ast.Div)


def _funcs(tree):
    return [n for n in tree.body if isinstance(n, ast.FunctionDef)]


def _return_of(tree, fi):
    fn = _funcs(tree)[fi]
    return next(s for s in fn.body if isinstance(s, ast.Return))


def _leaf_names(tree):
    return [t.id for n in tree.body if isinstance(n, ast.Assign)
            for t in n.targets if isinstance(t, ast.Name)]


def mutants(source):
    """Yield (kind, description, mutated_source) — one single-point mutation each."""
    tree = ast.parse(source)
    leaves = _leaf_names(tree)
    for fi, fn in enumerate(_funcs(tree)):
        ret = next((s for s in fn.body if isinstance(s, ast.Return)), None)
        if not ret or not isinstance(ret.value, ast.BinOp):
            continue
        b = ret.value
        op_t = type(b.op)
        scope = [a.arg for a in fn.args.args] + leaves

        # 1) operator swap
        for newop in (ast.Add, ast.Sub, ast.Mult, ast.Div):
            if newop is not op_t:
                m = copy.deepcopy(tree)
                _return_of(m, fi).value.op = newop()
                yield ("op_swap", f"{fn.name}: {_ARITH[op_t]} -> {_ARITH[newop]}", ast.unparse(m))

        # 2) operand swap (only a real error for non-commutative ops)
        if isinstance(b.op, _NONCOMMUTATIVE):
            m = copy.deepcopy(tree)
            mb = _return_of(m, fi).value
            mb.left, mb.right = mb.right, mb.left
            yield ("operand_swap", f"{fn.name}: swap operands of '{_ARITH[op_t]}'", ast.unparse(m))

        # 3) wrong-input rewire — replace a Name operand with a different in-scope variable
        for side in ("left", "right"):
            node = getattr(b, side)
            if isinstance(node, ast.Name):
                for alt in scope:
                    if alt != node.id:
                        m = copy.deepcopy(tree)
                        setattr(_return_of(m, fi).value, side, ast.Name(id=alt, ctx=ast.Load()))
                        yield ("rewire", f"{fn.name}: {side} {node.id} -> {alt}", ast.unparse(m))

        # 4) unit / scale slip
        for factor in (10, 60):
            m = copy.deepcopy(tree)
            r = _return_of(m, fi)
            r.value = ast.BinOp(left=r.value, op=ast.Mult(), right=ast.Constant(value=factor))
            yield ("scale", f"{fn.name}: * {factor}", ast.unparse(m))

        # 5) resolution probe (NOT a realistic error — it maps the oracle's blind band):
        # an error smaller than the check's round(,2) tolerance is invisible. The surviving
        # eps localises the blind band, which is unit-dependent (percent-to-2dp is 100x tighter
        # than euros-to-2dp), so the same absolute slip is caught for one node, missed for another.
        for eps in (0.00004, 0.004, 0.02):
            m = copy.deepcopy(tree)
            r = _return_of(m, fi)
            r.value = ast.BinOp(left=r.value, op=ast.Add(), right=ast.Constant(value=eps))
            yield ("tolerance_probe", f"{fn.name}: + {eps}", ast.unparse(m))


def _run(source):
    try:
        with contextlib.redirect_stdout(io.StringIO()):   # swallow the generated code's own print
            exec(compile(source, "<mut>", "exec"), {"__name__": "__main__"})
        return "survived"
    except AssertionError:
        return "killed"
    except Exception:            # noqa: BLE001 — any runtime error = crashed (not the oracle)
        return "crashed"


def evaluate(source):
    """-> list of (kind, description, outcome) for every mutant of `source`."""
    return [(k, d, _run(s)) for k, d, s in mutants(source)]


_STRUCTURAL = ("op_swap", "operand_swap", "rewire", "scale")


def _report(title, results):
    from collections import Counter
    struct = [(k, d, o) for k, d, o in results if k in _STRUCTURAL]
    probes = [(k, d, o) for k, d, o in results if k == "tolerance_probe"]
    by = Counter(o for _, _, o in struct)
    vm = by["killed"] + by["survived"]              # value-changing (non-crash) mutants
    print(f"\n== {title} ==")
    print(f"   realistic structural mutants: {len(struct)}   "
          f"killed={by['killed']} survived={by['survived']} crashed={by['crashed']}   "
          f"-> kill rate {by['killed'] / vm:.0%} of {vm} value-mutants")
    for k in sorted({k for k, _, _ in struct}):
        c = Counter(o for kk, _, o in struct if kk == k)
        print(f"     {k:<13} killed={c['killed']:<3} survived={c['survived']:<3} crashed={c['crashed']}")
    for k, d in [(k, d) for k, d, o in struct if o == "survived"]:
        print(f"   ! STRUCTURAL SURVIVOR (dangerous coincidental pass): [{k}] {d}")
    surv_p = [d for _, d, o in probes if o == "survived"]
    print(f"   resolution probes: {len(probes)}  survived={len(surv_p)}"
          f"  (sub-tolerance errors invisible to the round-2 oracle)")
    for d in surv_p:
        print(f"     - {d}")
    return by


if __name__ == "__main__":
    import json
    import sys
    from collections import Counter

    from gwa.codegen import generate

    brain = json.load(open(sys.argv[1] if len(sys.argv) > 1 else "demo/brain.json"))
    targets = sys.argv[2:] or ["profit margin", "fill time in minutes"]
    total = Counter()
    for target in targets:
        tid = next(f["id"] for f in brain["facts"] if target.lower() in f["text"].lower())
        code, _ = generate(brain, tid)
        total += _report(target, evaluate(code))
    vm = total["killed"] + total["survived"]
    print(f"\n== OVERALL == killed={total['killed']} survived={total['survived']} "
          f"crashed={total['crashed']}  |  kill rate {total['killed'] / vm:.0%} of {vm} value-mutants")
