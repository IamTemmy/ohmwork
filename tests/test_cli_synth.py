"""CLI-level tests for `ohmwork synth` (docs/CHARTER.md §8 M1b acceptance
test: reproduce the three CPE 635 Fall 2026 Exam #1 answers)."""

import contextlib
import io

from ohmwork.cli import main


def run(args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(args)
    return code, out.getvalue(), err.getvalue()


# --- M1b acceptance test ------------------------------------------------------


def test_acceptance_3_input_nand_via_expr():
    code, out, err = run(["synth", "--expr", "(abc)'"])
    assert code == 0
    assert err == ""
    assert "Gate: 3-input NAND" in out
    assert "Total:       6" in out
    assert "functional equivalence: PASS" in out
    assert "structural validity: PASS" in out


def test_acceptance_4_input_nor_via_truth_table():
    code, out, err = run(["synth", "--vars", "a,b,c,d", "--ones", "0"])
    assert code == 0
    assert "Gate: 4-input NOR" in out
    assert "Total:       8" in out


def test_acceptance_aoi31_via_table_string():
    # (abc+d)' truth table, row order a,b,c,d (a=MSB): F=1 wherever d=0 and
    # not all of a,b,c are 1 (i.e. every even index except 14 = 1,1,1,0).
    table = "1010101010101000"
    code, out, err = run(["synth", "--vars", "a,b,c,d", "--table", table])
    assert code == 0
    assert "Gate: AOI31" in out
    assert "Total:       8" in out


# --- Input modes and validation ----------------------------------------------


def test_dont_care_flag_reduces_transistor_count():
    code, out, err = run(["synth", "--vars", "a,b", "--ones", "0", "--dc", "1"])
    assert code == 0
    assert "Total:       2" in out
    assert "don't-cares assigned (D4)" in out


def test_dual_rail_flag_removes_inverter_cost():
    code, out, err = run(["synth", "--expr", "(a'b+c)'"])
    assert code == 0
    assert "Inverters:   2" in out
    code2, out2, err2 = run(["synth", "--expr", "(a'b+c)'", "--dual-rail"])
    assert code2 == 0
    assert "Inverters:   0" in out2


def test_max_stack_rejects_when_no_candidate_fits():
    code, out, err = run(["synth", "--expr", "(abc)'", "--max-stack", "1"])
    assert code != 0
    assert out == ""
    assert "max-stack" in err.lower()


def test_rejects_expr_combined_with_vars():
    code, out, err = run(["synth", "--expr", "ab", "--vars", "a,b"])
    assert code != 0
    assert "error" in err.lower()


def test_rejects_vars_without_ones_or_table():
    code, out, err = run(["synth", "--vars", "a,b"])
    assert code != 0
    assert "error" in err.lower()


def test_rejects_table_combined_with_ones():
    code, out, err = run(["synth", "--vars", "a,b", "--table", "1000", "--ones", "0"])
    assert code != 0
    assert "error" in err.lower()


def test_rejects_index_in_both_ones_and_dc():
    code, out, err = run(["synth", "--vars", "a,b", "--ones", "0,1", "--dc", "1"])
    assert code != 0
    assert "error" in err.lower()


def test_rejects_invalid_expr():
    code, out, err = run(["synth", "--expr", "a+"])
    assert code != 0
    assert "error" in err.lower()


def test_rejects_no_input_given():
    code, out, err = run(["synth"])
    assert code != 0
    assert "error" in err.lower()


def test_rejects_reserved_f_in_vars():
    code, out, err = run(["synth", "--vars", "F,a", "--ones", "0"])
    assert code != 0
    assert "error" in err.lower()


def test_rejects_five_or_more_variables():
    code, out, err = run(["synth", "--vars", "a,b,c,d,e", "--ones", "0"])
    assert code != 0
    assert "1-4 variables" in err


def test_verification_failure_exits_nonzero_not_success(monkeypatch):
    # Confirms the CLI actually surfaces a failed-verification error rather
    # than printing exit code 0 -- the exact defect ChatGPT's review found
    # (it injected a failing VerificationResult and got exit 0 back). A real
    # failure can no longer occur through normal input (synthesize() itself
    # now gates on it), so this forces the failure at the boundary the CLI
    # actually depends on.
    import ohmwork.cli as cli_module

    def fake_synthesize(*args, **kwargs):
        raise RuntimeError("failed its own D7 verification (forced for this test)")

    monkeypatch.setattr(cli_module, "synthesize", fake_synthesize)
    code, out, err = run(["synth", "--expr", "(abc)'"])
    assert code != 0
    assert out == ""
    assert "error" in err.lower()
