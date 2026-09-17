"""Integration tests for the M1.1 web UI: a real WSGI server on an
ephemeral port, hit over real HTTP — not just the WSGI callable invoked
in-process, so this also exercises request parsing end to end."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest
from wsgiref.simple_server import make_server

from ohmwork.webui import _QuietWSGIRequestHandler, app


@pytest.fixture
def server_url():
    httpd = make_server("127.0.0.1", 0, app, handler_class=_QuietWSGIRequestHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read().decode("utf-8"))


def test_index_page_serves_html(server_url):
    with urllib.request.urlopen(server_url + "/", timeout=5) as resp:
        assert resp.status == 200
        assert resp.headers["Content-Type"].startswith("text/html")
        body = resp.read().decode("utf-8")
    assert "<title>Ohmwork</title>" in body
    assert "Derivation table" in body
    assert "Synthesis" in body


def test_index_page_script_is_valid_javascript(server_url):
    # Regression: _PAGE is embedded as a Python string literal (webui.py);
    # a non-raw string interprets "\n" etc. inside the JS source as Python
    # escapes at import time, silently corrupting the served script (found
    # by hand during M1.2's manual browser testing -- every button broke
    # with a JS SyntaxError, since a literal newline landed inside a JS
    # string literal). If Node is available, actually parse the served
    # script; the raw-string requirement itself is covered unconditionally
    # by the string-check test below.
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available to check JS syntax")

    with urllib.request.urlopen(server_url + "/", timeout=5) as resp:
        body = resp.read().decode("utf-8")
    script = body.split("<script>", 1)[1].split("</script>", 1)[0]
    result = subprocess.run([node, "--check", "-"], input=script, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_page_source_uses_a_raw_string_literal():
    # The actual root-cause guard for the bug above: _PAGE must be declared
    # with `r"""` (raw), not `"""`, so no future edit can reintroduce a
    # Python-escape-vs-JS-escape collision.
    import ohmwork.webui as webui_module
    import inspect

    src = inspect.getsource(webui_module)
    assert 'r"""<!doctype html>' in src, "_PAGE must stay a raw string (r\"\"\") -- see the docstring on this test"


def test_index_page_has_synth_ui_elements(server_url):
    # M1.2: the restructured synthesis panel's key elements should exist,
    # as a lightweight structural regression check (this repo has no
    # headless-browser test framework -- see M1.2's plan review for why).
    with urllib.request.urlopen(server_url + "/", timeout=5) as resp:
        body = resp.read().decode("utf-8")
    for expected_id in [
        "synth-output-name", "synth-grid-wrap", "synth-manual-details",
        "res-gate-line", "res-function-line", "res-pdn-expr", "res-pun-expr",
        "res-selection-note", "res-alternatives", "res-advanced",
        "copy-solution", "copy-advanced",
    ]:
        assert f'id="{expected_id}"' in body, expected_id


def test_unknown_path_is_404(server_url):
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(server_url + "/nope", timeout=5)
    assert exc_info.value.code == 404


# --- /api/tt --------------------------------------------------------------------


def test_api_tt_acceptance_case(server_url):
    result = post_json(server_url + "/api/tt", {"expression": "xy + xy'"})
    assert result["ok"] is True
    assert "F = x" in result["output"]
    for header in ["x", "y", "y'", "xy", "xy'"]:
        assert header in result["output"]


def test_api_tt_rejects_ambiguous_input_as_a_clean_error_not_a_500(server_url):
    result = post_json(server_url + "/api/tt", {"expression": "A12"})
    assert result["ok"] is False
    assert "output" not in result
    assert isinstance(result["error"], str) and result["error"]


def test_api_tt_terse_and_format_options(server_url):
    result = post_json(server_url + "/api/tt", {"expression": "xy + xy'", "terse": True, "md": True})
    assert result["ok"] is True
    assert result["output"].startswith("|")  # markdown table
    assert "xy" in result["output"]


def test_api_tt_custom_cols(server_url):
    result = post_json(server_url + "/api/tt", {"expression": "x'y + xy'", "cols": "x, x'"})
    assert result["ok"] is True
    assert "x'" in result["output"]


# --- /api/synth -------------------------------------------------------------------


def test_api_synth_acceptance_case_from_expr(server_url):
    result = post_json(server_url + "/api/synth", {"expr": "(abc)'"})
    assert result["ok"] is True
    assert "Gate: 3-input NAND" in result["output"]
    assert "Total:       6" in result["output"]


def test_api_synth_from_explicit_truth_table(server_url):
    result = post_json(server_url + "/api/synth", {"variables": "a,b", "ones": "0", "dc": "1"})
    assert result["ok"] is True
    assert "Total:       2" in result["output"]


def test_api_synth_from_bit_string(server_url):
    result = post_json(server_url + "/api/synth", {"variables": "a,b", "table": "1x01"})
    assert result["ok"] is True


def test_api_synth_rejects_five_variables_as_a_clean_error(server_url):
    result = post_json(server_url + "/api/synth", {"variables": "a,b,c,d,e", "ones": "0"})
    assert result["ok"] is False
    assert "1-4 variables" in result["error"]


def test_api_synth_dual_rail_and_max_stack_options(server_url):
    result = post_json(
        server_url + "/api/synth",
        {"expr": "(a'b+c)'", "dual_rail": True, "max_stack": "4"},
    )
    assert result["ok"] is True
    assert "Inverters:   0" in result["output"]


def test_api_synth_invalid_max_stack_is_a_clean_error(server_url):
    result = post_json(server_url + "/api/synth", {"expr": "(abc)'", "max_stack": "not-a-number"})
    assert result["ok"] is False
    assert "whole number" in result["error"]


def test_api_endpoints_never_return_a_server_error_for_bad_input(server_url):
    # Empty body / missing fields should come back as a clean {ok: false},
    # not a 500 — the WSGI app's own last-resort guard is what this checks.
    result = post_json(server_url + "/api/tt", {})
    assert result["ok"] is False
    result2 = post_json(server_url + "/api/synth", {})
    assert result2["ok"] is False


# --- M1.2: structured `result` field ------------------------------------------


def test_api_synth_result_field_matches_the_three_exam_questions(server_url):
    cases = [
        ({"expr": "(ABC)'"}, "3-input NAND", 6),
        ({"variables": "A,B,C,D", "table": "1000000000000000"}, "4-input NOR", 8),
        ({"expr": "(ABC+D)'"}, "AOI31", 8),
    ]
    for payload, gate_name, total in cases:
        result = post_json(server_url + "/api/synth", payload)
        assert result["ok"] is True
        assert "output" in result  # legacy field still present, additive change
        assert result["result"]["gate_name"] == gate_name
        assert result["result"]["total_transistors"] == total


def test_api_synth_q1_alternatives_are_deduplicated_via_the_api(server_url):
    result = post_json(server_url + "/api/synth", {"expr": "(ABC)'"})
    alts = result["result"]["reasoning"]["alternatives"]
    assert len(alts) == 1
    assert set(alts[0]["labels"]) == {"AOI", "OAI"}


@pytest.mark.parametrize("name", ["F", "Y", "M"])
def test_api_synth_custom_output_name(server_url, name):
    result = post_json(server_url + "/api/synth", {"expr": "(ABC)'", "output_name": name})
    assert result["ok"] is True
    assert result["result"]["function"] == f"{name} = (ABC)'"


def test_api_synth_rejects_invalid_output_name(server_url):
    result = post_json(server_url + "/api/synth", {"expr": "(ABC)'", "output_name": "Out"})
    assert result["ok"] is False
    assert "not a valid output name" in result["error"]
    assert "output" not in result
    assert "result" not in result


def test_api_synth_rejects_output_name_colliding_with_input_variable(server_url):
    result = post_json(server_url + "/api/synth", {"expr": "(ABC)'", "output_name": "A"})
    assert result["ok"] is False
    assert "duplicates an input variable" in result["error"]


def test_api_synth_exactly_once_per_request(server_url, monkeypatch):
    import ohmwork.api as api_module

    calls = []
    original = api_module.synthesize

    def counting_synthesize(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(api_module, "synthesize", counting_synthesize)
    result = post_json(server_url + "/api/synth", {"expr": "(ABC)'"})
    assert result["ok"] is True
    assert len(calls) == 1


def test_api_synth_forced_verification_failure_returns_no_output_or_result(server_url, monkeypatch):
    # Mirrors the pre-M1.2 CLI-level check (a real bug ChatGPT's M1.1
    # review found: a failed verification once still returned exit 0).
    # Here: neither the legacy `output` text nor the new `result` dict may
    # ever be present in a failure response.
    import ohmwork.api as api_module

    def failing_synthesize(*args, **kwargs):
        raise RuntimeError("failed its own D7 verification (forced for this test)")

    monkeypatch.setattr(api_module, "synthesize", failing_synthesize)
    result = post_json(server_url + "/api/synth", {"expr": "(ABC)'"})
    assert result["ok"] is False
    assert "output" not in result
    assert "result" not in result


# --- Truth-table grid -> exact engine bit string ----------------------------
#
# The grid itself is client-side JS with no Python equivalent to unit-test
# directly, but the contract it must uphold is: whatever bit string the
# grid builds gets sent through the exact same `table` field the manual
# input already exercises. These confirm the manual path (which the grid
# is required to funnel into) behaves identically regardless of which UI
# affordance produced it, and pin the exact row-ordering convention the
# grid's own JS must replicate (variable 0 = MSB, row i = format(i, '0nb')).


def test_grid_equivalent_bit_string_produces_the_acceptance_result(server_url):
    # This is exactly the string a correctly-built grid must produce for
    # Q1 (A,B,C; F=0 only when A=B=C=1): row 7 ('111') is the only zero.
    grid_bit_string = "11111110"
    result = post_json(server_url + "/api/synth", {"variables": "A,B,C", "table": grid_bit_string})
    assert result["ok"] is True
    assert result["result"]["gate_name"] == "3-input NAND"
    assert result["result"]["total_transistors"] == 6
