"""Tests for the D9 (full column breakout) / D10 (first-appearance variable
order) derivation table."""

import pytest

from ohmwork.derivation import build_table, variables_in_order
from ohmwork.parser import parse
from ohmwork.simplify import simplify


def col_labels(table):
    return [c.label for c in table.columns]


def col(table, label):
    return next(c for c in table.columns if c.label == label)


# --- M1a acceptance test (docs/CHARTER.md §8) -------------------------------
#
#   ohmwork tt "xy + xy'" produces columns for x, y, y', xy, xy', and F,
#   and reports F = x.


def test_acceptance_xy_plus_xy_prime_columns():
    table = build_table(parse("xy + xy'"))
    assert col_labels(table) == ["x", "y", "y'", "xy", "xy'", "F"]


def test_acceptance_xy_plus_xy_prime_values():
    table = build_table(parse("xy + xy'"))
    # Row order: x is the first-appearing variable (D10), so it's the MSB.
    # rows: (x=0,y=0) (x=0,y=1) (x=1,y=0) (x=1,y=1)
    assert col(table, "x").values == [False, False, True, True]
    assert col(table, "y").values == [False, True, False, True]
    assert col(table, "y'").values == [True, False, True, False]
    assert col(table, "xy").values == [False, False, False, True]
    assert col(table, "xy'").values == [False, False, True, False]
    assert col(table, "F").values == [False, False, True, True]


def test_acceptance_xy_plus_xy_prime_simplifies_to_x():
    table = build_table(parse("xy + xy'"))
    var_order = variables_in_order(parse("xy + xy'"))
    simplified = simplify(var_order, table.output.values)
    assert str(simplified) == "x"


# --- D9's own worked example -------------------------------------------------
#
#   x'y + xy' yields columns for x, y, x', y', x'y, xy'.


def test_d9_example_columns():
    table = build_table(parse("x'y + xy'"))
    assert col_labels(table) == ["x", "y", "x'", "y'", "x'y", "xy'", "F"]


def test_d9_example_does_not_simplify_further():
    table = build_table(parse("x'y + xy'"))
    var_order = variables_in_order(parse("x'y + xy'"))
    simplified = simplify(var_order, table.output.values)
    # x'y + xy' is XOR: no smaller SOP exists.
    assert str(simplified) == "x'y + xy'"


# --- D10: variable order is first appearance, not alphabetical -------------


def test_variable_order_follows_first_appearance_not_alphabetical():
    assert variables_in_order(parse("y + x")) == ["y", "x"]
    assert variables_in_order(parse("b'a")) == ["b", "a"]


# --- D9: deduplication -------------------------------------------------------


def test_repeated_subexpression_is_a_single_column():
    table = build_table(parse("xy + xy"))
    assert col_labels(table) == ["x", "y", "xy", "F"]


def test_repeated_variable_across_terms_is_a_single_column():
    table = build_table(parse("xy + xz"))
    assert col_labels(table) == ["x", "y", "z", "xy", "xz", "F"]


# --- Increasing-depth expressions (charter: "three further expressions of
# increasing depth, including one with nested parens and one XOR") ----------


def test_nested_parens_expression():
    table = build_table(parse("(x+y)z"))
    # (x+y)z is the whole expression (the root), so it's relabeled "F"
    # rather than appearing as its own extra column.
    assert col_labels(table) == ["x", "y", "z", "x + y", "F"]
    # z=1,x=0,y=0 -> 0; check a couple of rows for sanity.
    row_for = dict(zip(["x", "y", "z"], [False, False, True]))
    idx = table.rows.index(row_for)
    assert col(table, "F").values[idx] is False
    row_for = dict(zip(["x", "y", "z"], [True, False, True]))
    idx = table.rows.index(row_for)
    assert col(table, "F").values[idx] is True


def test_xor_expression():
    table = build_table(parse("x^y"))
    assert col_labels(table) == ["x", "y", "F"]
    assert col(table, "F").values == [False, True, True, False]


def test_deeper_expression_with_xor_and_and():
    table = build_table(parse("(a+b)^cd"))
    labels = col_labels(table)
    assert labels == ["a", "b", "c", "d", "a + b", "cd", "F"]
    var_order = variables_in_order(parse("(a+b)^cd"))
    assert var_order == ["a", "b", "c", "d"]


def test_root_that_is_a_bare_variable_has_only_one_column():
    table = build_table(parse("x"))
    assert col_labels(table) == ["F"]
    assert col(table, "F").values == [False, True]


def test_root_that_is_a_bare_complement():
    table = build_table(parse("x'"))
    assert col_labels(table) == ["x", "F"]
    assert col(table, "F").values == [True, False]


# --- D9: --terse (collapse to product terms and output) --------------------


def test_terse_collapses_to_product_terms_and_output():
    table = build_table(parse("xy + xy'"), terse=True)
    assert col_labels(table) == ["xy", "xy'", "F"]
    assert col(table, "xy").values == [False, False, False, True]
    assert col(table, "xy'").values == [False, False, True, False]
    assert col(table, "F").values == [False, False, True, True]


def test_terse_with_no_top_level_sum_shows_only_output():
    # No top-level Or means there's nothing to break into product terms.
    table = build_table(parse("(x+y)z"), terse=True)
    assert col_labels(table) == ["F"]


def test_terse_root_column_matches_full_breakout_output():
    full = build_table(parse("x'y + xy'"))
    terse = build_table(parse("x'y + xy'"), terse=True)
    assert col_labels(terse) == ["x'y", "xy'", "F"]
    assert terse.output.values == full.output.values


# --- D9: --cols (explicit column list) --------------------------------------


def test_cols_shows_exactly_the_requested_columns_plus_output():
    table = build_table(parse("x'y + xy'"), cols=["x", "x'", "xy'"])
    assert col_labels(table) == ["x", "x'", "xy'", "F"]


def test_cols_output_is_always_appended_even_if_not_requested():
    table = build_table(parse("xy + xy'"), cols=["xy"])
    assert col_labels(table) == ["xy", "F"]


def test_cols_deduplicates_repeated_requests():
    table = build_table(parse("xy + xy'"), cols=["x", "x", "xy"])
    assert col_labels(table) == ["x", "xy", "F"]


def test_cols_root_expression_requested_explicitly_still_ends_up_last():
    table = build_table(parse("xy + xy'"), cols=["xy + xy'", "x"])
    assert col_labels(table) == ["x", "F"]


def test_cols_rejects_a_column_that_is_not_a_subexpression():
    with pytest.raises(ValueError, match="not a sub-expression"):
        build_table(parse("xy"), cols=["z"])


def test_cols_rejects_an_unparseable_column_spec():
    with pytest.raises(ValueError, match="invalid column"):
        build_table(parse("xy"), cols=["x+"])


def test_terse_and_cols_are_mutually_exclusive():
    with pytest.raises(ValueError, match="mutually exclusive"):
        build_table(parse("xy"), terse=True, cols=["x"])
