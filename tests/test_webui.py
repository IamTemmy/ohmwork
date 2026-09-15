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
