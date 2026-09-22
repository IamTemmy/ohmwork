"""Tests for ohmwork.api — the UI-agnostic layer both the CLI and the web
UI (M1.1) call, so this is also where "the two front ends never drift
apart" is actually proven, not just asserted."""

import contextlib
import io

import pytest

from ohmwork.api import derive_from_input, format_tt_report, render_synth, render_tt, resolve_truth_table
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


# --- derive_from_input / format_tt_report (M1.3) --------------------------------
#
# derive_from_input is the structured counterpart to render_tt, mirroring
# synthesize_from_input's role for synth: the raw DerivationResult both
# render_tt (CLI text) and presenter.build_tt_view (the web UI's
# structured table) build on, computed exactly once.


def test_derive_from_input_matches_the_acceptance_test():
    result = derive_from_input("xy + xy'")
    assert [c.label for c in result.table.columns] == ["x", "y", "y'", "xy", "xy'", "F"]
    assert result.table.variables == ["x", "y"]
    from ohmwork.expr import render as render_expr

    assert render_expr(result.simplified) == "x"


def test_derive_from_input_rejects_ambiguous_input():
    with pytest.raises(ParseError):
        derive_from_input("A12")


def test_derive_from_input_terse_and_cols_are_mutually_exclusive():
    with pytest.raises(ValueError):
        derive_from_input("xy", terse=True, cols=["x"])


def test_derive_from_input_terse_columns():
    result = derive_from_input("ab+c", terse=True)
    assert [c.label for c in result.table.columns] == ["ab", "c", "F"]


def test_derive_from_input_custom_columns():
    result = derive_from_input("x'y + xy'", cols=["x", "x'"])
    assert [c.label for c in result.table.columns] == ["x", "x'", "F"]


def test_derive_from_input_xor_intermediate_column():
    result = derive_from_input("x^y")
    assert [c.label for c in result.table.columns] == ["x", "y", "F"]  # x^y IS F, no separate intermediate


def test_derive_from_input_xor_as_a_sub_expression_gets_its_own_column():
    result = derive_from_input("(x^y)z")
    labels = [c.label for c in result.table.columns]
    assert "x ^ y" in labels
    assert labels[-1] == "F"


def test_format_tt_report_matches_render_tt():
    # format_tt_report is render_tt's own formatting logic, extracted so
    # webui.py can call it on an already-computed DerivationResult without
    # re-deriving -- must produce byte-identical text to the original
    # single-call render_tt for the same inputs, in every format.
    for kwargs in [{}, {"md": True}, {"latex": True}, {"terse": True}]:
        result = derive_from_input("xy + xy'", terse=kwargs.get("terse", False))
        assert format_tt_report(result, md=kwargs.get("md", False), latex=kwargs.get("latex", False)) == render_tt(
            "xy + xy'", **kwargs
        )


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


def test_render_synth_rejects_six_or_more_variables():
    with pytest.raises(ValueError, match="1-5 variables"):
        render_synth(variables="a,b,c,d,e,g", ones="0")
