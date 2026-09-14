"""Tests for `synth`'s truth-table input parsing."""

import pytest

from ohmwork.truth_table import parse_index_list, parse_table_string, parse_var_list


# --- parse_var_list -----------------------------------------------------------


def test_parses_a_simple_var_list():
    assert parse_var_list("a,b,c") == ["a", "b", "c"]


def test_strips_whitespace_around_names():
    assert parse_var_list(" a , b ,c ") == ["a", "b", "c"]


def test_rejects_empty_list():
    with pytest.raises(ValueError, match="non-empty"):
        parse_var_list("")


def test_rejects_duplicate_names():
    with pytest.raises(ValueError, match="duplicate"):
        parse_var_list("a,b,a")


def test_rejects_invalid_variable_name():
    with pytest.raises(ValueError, match="invalid variable name"):
        parse_var_list("a,2x")


def test_rejects_multi_letter_entry():
    with pytest.raises(ValueError, match="not a single D8 variable"):
        parse_var_list("a,bc")


def test_reuses_d15_reservation_of_f():
    with pytest.raises(ValueError, match="invalid variable name"):
        parse_var_list("F,a")


def test_allows_digit_suffixed_names():
    assert parse_var_list("A0,A1,B2") == ["A0", "A1", "B2"]


# --- parse_index_list ----------------------------------------------------------


def test_parses_index_list():
    assert parse_index_list("1,3,5", n_vars=3, what="--ones") == {1, 3, 5}


def test_empty_index_list_is_empty_set():
    assert parse_index_list("", n_vars=3, what="--dc") == set()
    assert parse_index_list("   ", n_vars=3, what="--dc") == set()


def test_rejects_out_of_range_index():
    with pytest.raises(ValueError, match="out of range"):
        parse_index_list("8", n_vars=3, what="--ones")  # max valid is 7 for 3 vars


def test_rejects_non_integer_entry():
    with pytest.raises(ValueError, match="not a non-negative integer"):
        parse_index_list("1,x", n_vars=3, what="--ones")


def test_rejects_negative_index():
    with pytest.raises(ValueError, match="out of range"):
        parse_index_list("-1", n_vars=3, what="--ones")


# --- parse_table_string --------------------------------------------------------


def test_parses_table_string():
    minterms, dont_cares = parse_table_string("1010", n_vars=2)
    assert minterms == {0, 2}
    assert dont_cares == set()


def test_parses_dont_cares_in_table_string():
    minterms, dont_cares = parse_table_string("1x0-", n_vars=2)
    assert minterms == {0}
    assert dont_cares == {1, 3}


def test_rejects_wrong_length_table():
    with pytest.raises(ValueError, match="exactly 8 characters"):
        parse_table_string("101", n_vars=3)


def test_rejects_invalid_table_character():
    with pytest.raises(ValueError, match="invalid character"):
        parse_table_string("10-2", n_vars=2)  # correct length (4), '2' is invalid
