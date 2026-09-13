"""Tests for the Quine-McCluskey minimizer used to report the simplified
result alongside the derivation table."""

from ohmwork.derivation import build_table, variables_in_order
from ohmwork.expr import render
from ohmwork.parser import parse
from ohmwork.simplify import simplify


def simplified_str(expr_text: str) -> str:
    ast = parse(expr_text)
    var_order = variables_in_order(ast)
    table = build_table(ast)
    return render(simplify(var_order, table.output.values))


def test_acceptance_xy_plus_xy_prime_simplifies_to_x():
    assert simplified_str("xy + xy'") == "x"


def test_xor_pattern_does_not_simplify():
    assert simplified_str("x'y + xy'") == "x'y + xy'"


def test_tautology_simplifies_to_constant_one():
    assert simplified_str("x + x'") == "1"


def test_contradiction_simplifies_to_constant_zero():
    assert simplified_str("xx'") == "0"


def test_redundant_term_is_absorbed():
    # x + xy == x
    assert simplified_str("x + xy") == "x"


def test_already_minimal_two_variable_or_is_unchanged():
    assert simplified_str("x+y") == "x + y"


def test_three_variable_consensus():
    # xy + x'z + yz  ==  xy + x'z  (yz is the consensus term, redundant)
    result = simplified_str("xy + x'z + yz")
    assert result in ("xy + x'z", "x'z + xy")
