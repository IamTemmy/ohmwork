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


# --- D9: --terse and --cols --------------------------------------------------


def header_labels(out):
    """Exact column headers from a terminal-table ``tt`` output, parsed from
    the header row rather than substring-matched (labels like "y'" and
    "xy'" would otherwise falsely match each other)."""
    header_line = out.splitlines()[1]
    return [p.strip() for p in header_line.split("|") if p.strip() != ""]


def test_tt_terse_shows_only_product_terms_and_output():
    code, out, err = run(["tt", "xy + xy'", "--terse"])
    assert code == 0
    assert header_labels(out) == ["xy", "xy'", "F"]
    assert "F = x" in out


def test_tt_cols_shows_exactly_the_requested_columns():
    code, out, err = run(["tt", "x'y + xy'", "--cols", "x,x',xy'"])
    assert code == 0
    assert header_labels(out) == ["x", "x'", "xy'", "F"]


def test_tt_cols_rejects_unknown_column():
    code, out, err = run(["tt", "xy", "--cols", "z"])
    assert code != 0
    assert out == ""
    assert "error" in err.lower()


def test_tt_cols_rejects_empty_list():
    code, out, err = run(["tt", "xy", "--cols", ""])
    assert code != 0
    assert "error" in err.lower()


# --- D15: "F" as a variable name is rejected, not silently collided --------


def test_tt_rejects_bare_f_as_a_variable():
    code, out, err = run(["tt", "F + y"])
    assert code != 0
    assert out == ""
    assert "reserved" in err.lower()


def test_tt_allows_f_with_trailing_digit():
    code, out, err = run(["tt", "F0 + y"])
    assert code == 0
    assert header_labels(out) == ["F0", "y", "F"]


def test_tt_terse_and_cols_are_mutually_exclusive_at_the_cli():
    import contextlib
    import io

    import pytest

    err = io.StringIO()
    with contextlib.redirect_stderr(err), pytest.raises(SystemExit) as exc_info:
        main(["tt", "xy", "--terse", "--cols", "x"])
    assert exc_info.value.code == 2
    assert "not allowed" in err.getvalue().lower()


# --- `ui` subcommand (M1.1) ---------------------------------------------------
#
# run_server() itself blocks forever serving the page, so these only check
# that `ui` is wired up correctly and passes its flags through — the server
# and its HTTP behavior are covered end to end in tests/test_webui.py.


def test_ui_command_is_registered():
    import contextlib
    import io

    import pytest

    out = io.StringIO()
    with contextlib.redirect_stdout(out), pytest.raises(SystemExit) as exc_info:
        main(["ui", "--help"])
    assert exc_info.value.code == 0
    assert "--port" in out.getvalue()
    assert "--no-browser" in out.getvalue()


def test_ui_command_calls_run_server_with_parsed_flags(monkeypatch):
    import ohmwork.cli as cli_module

    calls = []
    monkeypatch.setattr(
        cli_module,
        "run_ui",
        lambda args, *, stdout, stderr: calls.append((args.port, args.no_browser)) or 0,
    )
    code, out, err = run(["ui", "--port", "9999", "--no-browser"])
    assert code == 0
    assert calls == [(9999, True)]


def test_ui_defaults_to_port_5757_and_opening_a_browser(monkeypatch):
    import ohmwork.webui as webui_module

    captured = {}

    def fake_run_server(*, host="127.0.0.1", port=5757, open_browser=True, stdout=None):
        captured["port"] = port
        captured["open_browser"] = open_browser

    monkeypatch.setattr(webui_module, "run_server", fake_run_server)
    code, out, err = run(["ui"])
    assert code == 0
    assert captured == {"port": 5757, "open_browser": True}
