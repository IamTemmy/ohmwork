"""Tests for D7's two independent verification checks."""

from ohmwork.derivation import all_assignments, evaluate
from ohmwork.expr import Var
from ohmwork.network import Series, Transistor, to_network
from ohmwork.parser import parse
from ohmwork.synth import synthesize
from ohmwork.verify import verify


def minterms_from_expr(var_order, expr_text):
    ast = parse(expr_text)
    rows = all_assignments(var_order)
    return {i for i, row in enumerate(rows) if evaluate(ast, row)}


def test_correctly_synthesized_gate_passes_both_checks():
    var_order = ["a", "b", "c"]
    minterms = minterms_from_expr(var_order, "(abc)'")
    result = synthesize(var_order, minterms)
    v = verify(result.pdn, result.pun, var_order, minterms)
    assert v.functional_pass is True
    assert v.structural_pass is True
    assert v.passed is True
    assert v.vector_count == 8
    assert v.mismatches == ()
    assert v.floating == ()
    assert v.shorted == ()


def test_a_clean_dual_pun_never_floats_or_shorts_across_many_functions():
    # The structural-validity invariant, checked (not assumed) across a
    # spread of functions rather than just the acceptance-test three.
    for expr_text, var_order in [
        ("ab+c'", ["a", "b", "c"]),
        ("(a+b)(c+d)", ["a", "b", "c", "d"]),
        ("a'b'c' + abc", ["a", "b", "c"]),
    ]:
        minterms = minterms_from_expr(var_order, expr_text)
        result = synthesize(var_order, minterms)
        v = verify(result.pdn, result.pun, var_order, minterms)
        assert v.structural_pass, expr_text


def test_dont_care_rows_are_reported_not_checked_against_a_fixed_expectation():
    var_order = ["a", "b"]
    result = synthesize(var_order, minterms={0}, dont_cares={1})
    v = verify(result.pdn, result.pun, var_order, minterms={0}, dont_cares={1})
    assert v.functional_pass is True
    assert 1 in v.dont_care_assignments
    assert 0 not in v.mismatches


# --- Genuine detection: a deliberately broken (non-dual) network ----------


def test_detects_a_float_when_pun_is_not_a_true_dual():
    # Build a PDN and a PUN that are NOT each other's dual (PUN gated by a
    # different literal entirely) — verify() must catch the resulting
    # floating output rather than trust the construction.
    pdn = to_network(parse("a"), "n")  # conducts when a=1
    broken_pun = to_network(parse("b"), "p")  # conducts when b=0
    v = verify(pdn, broken_pun, ["a", "b"], minterms={2, 3})  # a=1 rows
    # a=0,b=1 (row1): pdn off (a=0); pun off (b=1, PMOS wants b=0) -> floats.
    assert 1 in v.floating
    assert v.structural_pass is False


def test_detects_a_float_when_neither_network_conducts():
    # Both networks built as series (not a dual pair): PDN needs a=1,b=1 to
    # conduct; PUN (PMOS, on when gate=0) needs a=0,b=0. At a=1,b=0 neither
    # is satisfied — the output floats, and verify() must catch it.
    pdn = Series((Transistor(Var("a"), "n"), Transistor(Var("b"), "n")))
    pun = Series((Transistor(Var("a"), "p"), Transistor(Var("b"), "p")))
    v = verify(pdn, pun, ["a", "b"], minterms=set())
    assert 2 in v.floating  # row 2 = a=1,b=0
    assert v.structural_pass is False
