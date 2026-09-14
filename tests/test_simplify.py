"""Tests for the Quine-McCluskey minimizer used to report the simplified
result alongside the derivation table."""

from ohmwork.derivation import build_table, variables_in_order
from ohmwork.expr import render
from ohmwork.parser import parse
from ohmwork.simplify import minimize, simplify


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


def _literal_count(expr_str: str) -> int:
    return sum(1 for ch in expr_str if ch.isalpha())


def test_tie_break_prefers_fewest_literals_not_just_lexicographic_order():
    # Regression: among covers tied on term count, the D5 canonical-string
    # tie-break must only decide between covers that are ALSO tied on total
    # literal count — it must never prefer a lexicographically-smaller
    # string that has strictly more literals. This 4-variable function has
    # two term-count-4 covers, one with 12 literals and one with 13.
    var_order = ["a", "b", "c", "d"]
    minterms = {1, 2, 3, 4, 6, 8, 9, 10, 11, 13}
    result = render(minimize(var_order, minterms))
    assert _literal_count(result) == 12


def test_dont_care_used_to_reduce_literal_count():
    # 2 vars (a,b): minterms {0}, don't-care {1}. Without the don't-care,
    # minterm 0 alone needs both literals (a'b'). Assigning the don't-care
    # (minterm 1 = a'b) to 1 as well lets it combine with minterm 0 into a
    # single-literal term: a'.
    result = minimize(["a", "b"], minterms={0}, dont_cares={1})
    assert render(result) == "a'"


def test_dont_care_not_required_to_be_covered():
    # The don't-care itself need not evaluate to 1 in the chosen minimal
    # form; it's optional, not mandatory, per D4.
    result = minimize(["a", "b"], minterms={0}, dont_cares=set())
    assert render(result) == "a'b'"


def test_no_dont_cares_is_unaffected_default():
    assert render(minimize(["x", "y"], {0, 3})) == render(
        minimize(["x", "y"], {0, 3}, dont_cares=set())
    )


def test_all_dont_care_and_no_minterms_is_constant_false():
    # Nothing is required to be 1, so the cheapest valid assignment is 0
    # everywhere, even though every position is "free".
    result = minimize(["a", "b"], minterms=set(), dont_cares={0, 1, 2, 3})
    assert render(result) == "0"


def test_minterms_plus_dont_cares_covering_everything_is_constant_true():
    result = minimize(["a", "b"], minterms={0, 1}, dont_cares={2, 3})
    assert render(result) == "1"


def test_tie_break_prefers_fewest_literals_more_cases():
    # A few more concrete counterexamples from the same bug class (found by
    # randomized search against the pre-fix code, where each used to come
    # out one literal heavier than necessary).
    var_order = ["a", "b", "c", "d"]
    cases = [
        ({0, 1, 3, 5, 6, 8, 9, 12, 13, 14}, 12),
        ({0, 4, 5, 7, 9, 10, 12, 13, 14}, 14),
        ({0, 3, 4, 6, 7, 10, 11, 12, 13, 14}, 14),
    ]
    for minterms, expected_literals in cases:
        result = render(minimize(var_order, minterms))
        assert _literal_count(result) == expected_literals, (minterms, result)
