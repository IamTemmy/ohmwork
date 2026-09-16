"""Tests for ohmwork.api — the UI-agnostic layer both the CLI and the web
UI (M1.1) call, so this is also where "the two front ends never drift
apart" is actually proven, not just asserted."""

import contextlib
import io

import pytest

from ohmwork.api import render_synth, render_tt, resolve_truth_table
from ohmwork.cli import main
from ohmwork.errors import ParseError


def run_cli(args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(args)
    return code, out.getvalue(), err.getvalue()


# --- render_tt ----------------------------------------------------------------


def test_render_tt_matches_the_acceptance_test():
    output = render_tt("xy + xy'")
    assert "F = x" in output
    for header in ["x", "y", "y'", "xy", "xy'", "F"]:
        assert header in output


def test_render_tt_rejects_ambiguous_input():
    with pytest.raises(ParseError):
        render_tt("A12")


def test_render_tt_terse_and_cols_are_mutually_exclusive_via_value_error():
    with pytest.raises(ValueError):
        render_tt("xy", terse=True, cols=["x"])


def test_render_tt_output_is_byte_identical_to_the_cli(tmp_path):
    # The CLI is a thin wrapper: for the same flags, its printed output
    # (module a trailing newline from print()) must exactly match what
    # render_tt() itself returns.
    direct = render_tt("x'y + xy'", md=True)
    code, out, err = run_cli(["tt", "x'y + xy'", "--md"])
    assert code == 0
    assert err == ""
    assert out == direct + "\n"


# --- resolve_truth_table --------------------------------------------------------


def test_resolve_truth_table_from_expr():
    var_order, minterms, dont_cares = resolve_truth_table(expr="(abc)'")
    assert var_order == ["a", "b", "c"]
    assert minterms == {0, 1, 2, 3, 4, 5, 6}
    assert dont_cares == set()


def test_resolve_truth_table_from_explicit_minterms():
    var_order, minterms, dont_cares = resolve_truth_table(variables="a,b", ones="0", dc="1")
    assert var_order == ["a", "b"]
    assert minterms == {0}
    assert dont_cares == {1}


def test_resolve_truth_table_rejects_expr_with_variables():
    # Exact wording matters here, not just "some error happened": this is
    # the CLI's own pre-M1.1 stderr text (D8-flag-oriented), and this
    # function is now also the web UI's path to the same check — a past
    # regression (caught in review) reworded it to UI-neutral prose here,
    # which silently changed the CLI's output. See api.resolve_truth_table's
    # own docstring for why the CLI-flavored wording is kept deliberately.
    with pytest.raises(ValueError, match=r"^--expr cannot be combined with --vars/--ones/--dc/--table$"):
        resolve_truth_table(expr="ab", variables="a,b")


def test_resolve_truth_table_rejects_nothing_given():
    with pytest.raises(ValueError):
        resolve_truth_table()


# --- render_synth ---------------------------------------------------------------


def test_render_synth_matches_the_acceptance_test():
    output = render_synth(expr="(abc)'")
    assert "Gate: 3-input NAND" in output
    assert "Total:       6" in output


def test_render_synth_output_is_byte_identical_to_the_cli():
    direct = render_synth(expr="(a+b+c+d)'")
    code, out, err = run_cli(["synth", "--expr", "(a+b+c+d)'"])
    assert code == 0
    assert err == ""
    assert out == direct + "\n"


def test_render_synth_rejects_five_or_more_variables():
    with pytest.raises(ValueError, match="1-4 variables"):
        render_synth(variables="a,b,c,d,e", ones="0")
