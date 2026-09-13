"""CLI-level acceptance tests (docs/CHARTER.md §8 M1a acceptance test)."""

from ohmwork.cli import main


def run(args):
    """Run the CLI in-process, returning (exit_code, stdout, stderr)."""
    import io
    import contextlib

    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(args)
    return code, out.getvalue(), err.getvalue()


def test_acceptance_tt_xy_plus_xy_prime():
    code, out, err = run(["tt", "xy + xy'"])
    assert code == 0
    assert err == ""
    for header in ["x", "y", "y'", "xy", "xy'", "F"]:
        assert header in out
    assert "F = x" in out


def test_acceptance_tt_columns_appear_in_order():
    code, out, err = run(["tt", "xy + xy'"])
    header_line = out.splitlines()[1]  # first row of the ASCII table is the rule; second is headers
    # Headers must appear left-to-right in D9/D10 order.
    positions = [header_line.index(h) for h in ["x", "y", "y'", "xy", "xy'", "F"]]
    assert positions == sorted(positions)


def test_acceptance_rejects_ambiguous_input():
    code, out, err = run(["tt", "A12"])
    assert code != 0
    assert out == ""
    assert "error" in err.lower()
    assert "F =" not in out  # sanity: no guessed result was printed


def test_rejects_unbalanced_parens():
    code, out, err = run(["tt", "(x+y"])
    assert code != 0
    assert "error" in err.lower()


def test_tt_markdown_output():
    code, out, err = run(["tt", "xy + xy'", "--md"])
    assert code == 0
    assert out.startswith("|")
    assert "F = x" in out


def test_tt_latex_output():
    code, out, err = run(["tt", "xy + xy'", "--latex"])
    assert code == 0
    assert r"\begin{array}" in out
    assert "F = x" in out


# --- Three further expressions of increasing depth (charter §8 M1a
# acceptance: "including one with nested parens and one XOR") --------------


def test_deeper_expression_1_simple_or():
    code, out, err = run(["tt", "a+b"])
    assert code == 0
    assert "F = a + b" in out


def test_deeper_expression_2_nested_parens():
    code, out, err = run(["tt", "(x+y)z"])
    assert code == 0
    for header in ["x", "y", "z", "x + y", "F"]:
        assert header in out
    assert "F = xz + yz" in out


def test_deeper_expression_3_xor():
    code, out, err = run(["tt", "a^b^c"])
    assert code == 0
    assert "F =" in out
