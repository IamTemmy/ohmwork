"""CLI-level tests for `ohmwork synth` (docs/CHARTER.md §8 M1b acceptance
test: reproduce the three CPE 635 Fall 2026 Exam #1 answers)."""

import contextlib
import io
import os
import subprocess
import sys

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


# The exact wording below is pinned deliberately (not just "error" in
# err.lower()): ChatGPT's M1.1 review caught these seven messages drifting
# to UI-neutral prose when synth's input-resolution logic was extracted
# into ohmwork.api for the web UI to share — the CLI's own long-standing,
# already-signed-off stderr text must not change as a side effect of an
# internal refactor. Regression coverage for the exact legacy strings.


def test_rejects_expr_combined_with_vars():
    code, out, err = run(["synth", "--expr", "ab", "--vars", "a,b"])
    assert code != 0
    assert err == "error: --expr cannot be combined with --vars/--ones/--dc/--table\n"


def test_rejects_vars_without_ones_or_table():
    code, out, err = run(["synth", "--vars", "a,b"])
    assert code != 0
    assert err == "error: give --ones (or --table) alongside --vars\n"


def test_rejects_table_combined_with_ones():
    code, out, err = run(["synth", "--vars", "a,b", "--table", "1000", "--ones", "0"])
    assert code != 0
    assert err == "error: --table cannot be combined with --ones/--dc\n"


def test_rejects_index_in_both_ones_and_dc():
    code, out, err = run(["synth", "--vars", "a,b", "--ones", "0,1", "--dc", "1"])
    assert code != 0
    assert err == "error: index/indices [1] listed in both --ones and --dc\n"


def test_rejects_dc_without_ones_or_table():
    code, out, err = run(["synth", "--vars", "a,b", "--dc", "0"])
    assert code != 0
    assert err == "error: give --ones (or --table) alongside --vars\n"


def test_rejects_out_of_range_ones_index():
    code, out, err = run(["synth", "--vars", "a,b", "--ones", "8"])
    assert code != 0
    assert err == "error: --ones entry 8 is out of range: must be in [0, 4) for 2 variables\n"


def test_rejects_invalid_expr():
    code, out, err = run(["synth", "--expr", "a+"])
    assert code != 0
    assert "error" in err.lower()


def test_rejects_no_input_given():
    code, out, err = run(["synth"])
    assert code != 0
    assert err == "error: give --expr, or --vars together with --ones (or --table)\n"


def test_rejects_reserved_f_in_vars():
    code, out, err = run(["synth", "--vars", "F,a", "--ones", "0"])
    assert code != 0
    assert "error" in err.lower()


def test_rejects_six_or_more_variables():
    code, out, err = run(["synth", "--vars", "a,b,c,d,e,g", "--ones", "0"])
    assert code != 0
    assert "1-5 variables" in err


def test_output_is_byte_identical_across_hash_seeds():
    # Regression (ChatGPT's M1b review): this exact input has two tied OAI
    # candidates whose display order used to depend on PYTHONHASHSEED —
    # Python's hash randomization is fixed per-process at startup, so this
    # can only be tested faithfully across real subprocesses, not by
    # varying anything within this test process.
    args = [
        sys.executable,
        "-m",
        "ohmwork.cli",
        "synth",
        "--vars",
        "a,b,c,d",
        "--ones",
        "5,8,10",
        "--dc",
        "0,1,3,4,7,9,11,13,14",
    ]
    outputs = set()
    for seed in ("1", "2", "3", "4"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        result = subprocess.run(args, capture_output=True, text=True, env=env)
        assert result.returncode == 0, result.stderr
        outputs.add(result.stdout)
    assert len(outputs) == 1, f"output differed across hash seeds: {outputs}"


def test_verification_failure_exits_nonzero_not_success(monkeypatch):
    # Confirms the CLI actually surfaces a failed-verification error rather
    # than printing exit code 0 -- the exact defect ChatGPT's review found
    # (it injected a failing VerificationResult and got exit 0 back). A real
    # failure can no longer occur through normal input (synthesize() itself
    # now gates on it), so this forces the failure at the boundary the CLI
    # actually depends on.
    import ohmwork.cli as cli_module

    def fake_render_synth(*args, **kwargs):
        raise RuntimeError("failed its own D7 verification (forced for this test)")

    monkeypatch.setattr(cli_module, "render_synth", fake_render_synth)
    code, out, err = run(["synth", "--expr", "(abc)'"])
    assert code != 0
    assert out == ""
    assert "error" in err.lower()
