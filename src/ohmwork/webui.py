"""M1.1: a local web front end for `tt`/`synth`, for anyone who'd rather
fill in form fields than remember flags. Built entirely on the standard
library (``wsgiref`` + ``json``) — no new project dependency for what is,
functionally, two JSON endpoints and a static page.

Everything here is transport (HTTP <-> function call) and presentation
(the page); the actual behavior of ``tt``/``synth`` lives in
``ohmwork.api`` and below, which the CLI calls too — this module changes
nothing about what either command does or returns."""

from __future__ import annotations

import json
import sys
import webbrowser
from wsgiref.simple_server import WSGIRequestHandler, make_server

from ohmwork.api import render_tt, synthesize_from_input
from ohmwork.errors import ParseError
from ohmwork.presenter import build_synth_view, validate_output_name
from ohmwork.report import format_synth_report

_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Ohmwork</title>
<style>
  :root { color-scheme: light dark; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
    max-width: 880px; margin: 2rem auto; padding: 0 1rem; line-height: 1.4;
  }
  h1 { font-size: 1.4rem; margin-bottom: .25rem; }
  p.tagline { opacity: .7; margin-top: 0; font-size: .9rem; }
  .tabs { display: flex; gap: .25rem; margin: 1.25rem 0 0; border-bottom: 1px solid #8886; }
  .tab {
    padding: .5rem 1.1rem; cursor: pointer; border: none; background: none;
    font-size: 1rem; opacity: .55; font-family: inherit; border-bottom: 2px solid transparent;
  }
  .tab.active { opacity: 1; border-bottom-color: currentColor; font-weight: 600; }
  .panel { display: none; padding-top: 1rem; }
  .panel.active { display: block; }
  label { display: block; margin-top: .85rem; font-size: .9rem; }
  input[type=text], input[type=number] {
    width: 100%; box-sizing: border-box; padding: .45rem .5rem; font: inherit;
    margin-top: .2rem; border: 1px solid #8886; border-radius: 5px; background: transparent; color: inherit;
  }
  .row { display: flex; gap: 1.4rem; flex-wrap: wrap; margin-top: .6rem; align-items: center; }
  .row label { margin-top: 0; display: inline-flex; align-items: center; gap: .35rem; font-weight: normal; }
  button.submit {
    margin-top: 1.1rem; padding: .55rem 1.4rem; font-size: 1rem; cursor: pointer;
    border-radius: 6px; border: 1px solid #8886; background: #8882; color: inherit; font-family: inherit;
  }
  button.submit:hover { background: #8884; }
  pre#output {
    white-space: pre-wrap; background: #8881; padding: 1rem; border-radius: 6px;
    margin-top: 1.25rem; min-height: 1.5rem; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: .85rem; overflow-x: auto;
  }
  pre#output.error { color: #c0392b; }
  pre#output.empty { display: none; }
  .hint { font-size: .78rem; opacity: .6; margin-top: .2rem; }
</style>
</head>
<body>
<h1>Ohmwork</h1>
<p class="tagline">Digital logic work at the speed of typing — form fields instead of flags.</p>

<div class="tabs">
  <button type="button" class="tab active" data-tab="tt">Derivation table</button>
  <button type="button" class="tab" data-tab="synth">Synthesis</button>
</div>

<form class="panel active" id="panel-tt">
  <label>Expression (D8 notation: juxtaposition = AND, ' = complement, + = OR, ^ = XOR)
    <input type="text" id="tt-expr" placeholder="xy + xy'" autofocus>
  </label>

  <div class="row">
    <label><input type="radio" name="tt-format" value="terminal" checked> Terminal</label>
    <label><input type="radio" name="tt-format" value="md"> Markdown</label>
    <label><input type="radio" name="tt-format" value="latex"> LaTeX</label>
  </div>

  <div class="row">
    <label><input type="radio" name="tt-cols" value="full" checked> Full breakout</label>
    <label><input type="radio" name="tt-cols" value="terse"> Terse (product terms only)</label>
    <label><input type="radio" name="tt-cols" value="custom"> Custom columns</label>
  </div>
  <label id="tt-cols-label" style="display:none">Columns (comma-separated; F is always included)
    <input type="text" id="tt-cols-input" placeholder="x,y,xy">
  </label>

  <button type="submit" class="submit">Run</button>
</form>

<form class="panel" id="panel-synth">
  <div class="row">
    <label><input type="radio" name="synth-mode" value="expr" checked> From expression</label>
    <label><input type="radio" name="synth-mode" value="table"> From truth table</label>
  </div>

  <div id="synth-expr-fields">
    <label>Expression (its truth table is derived automatically)
      <input type="text" id="synth-expr" placeholder="(abc)'">
    </label>
  </div>

  <div id="synth-table-fields" style="display:none">
    <label>Variables (comma-separated, 1-4)
      <input type="text" id="synth-vars" placeholder="a,b,c,d">
    </label>
    <div class="row">
      <label><input type="radio" name="synth-table-mode" value="minterms" checked> Minterms &amp; don't-cares</label>
      <label><input type="radio" name="synth-table-mode" value="bits"> Bit string</label>
    </div>
    <div id="synth-minterm-fields">
      <label>Minterms where F=1 (comma-separated)
        <input type="text" id="synth-ones" placeholder="0,1,4">
      </label>
      <label>Don't-cares (comma-separated, optional — D4)
        <input type="text" id="synth-dc" placeholder="2,6">
      </label>
    </div>
    <div id="synth-bits-fields" style="display:none">
      <label>Truth table, row-ordered (0/1/x or -)
        <input type="text" id="synth-table" placeholder="1100011x">
      </label>
    </div>
  </div>

  <div class="row">
    <label><input type="checkbox" id="synth-dual-rail"> Dual-rail (complements free — D2)</label>
  </div>
  <label>Max stack height (optional — D3's opt-in engineering constraint)
    <input type="number" id="synth-max-stack" min="1">
  </label>

  <button type="submit" class="submit">Synthesize</button>
</form>

<pre id="output" class="empty"></pre>

<script>
function $(id) { return document.getElementById(id); }
function checkedValue(name) {
  const el = document.querySelector(`input[name=${name}]:checked`);
  return el ? el.value : null;
}

document.querySelectorAll(".tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
    tab.classList.add("active");
    $("panel-" + tab.dataset.tab).classList.add("active");
  });
});

function updateTtColsVisibility() {
  $("tt-cols-label").style.display = checkedValue("tt-cols") === "custom" ? "block" : "none";
}
document.querySelectorAll("input[name=tt-cols]").forEach(r => r.addEventListener("change", updateTtColsVisibility));

function updateSynthModeVisibility() {
  const mode = checkedValue("synth-mode");
  $("synth-expr-fields").style.display = mode === "expr" ? "block" : "none";
  $("synth-table-fields").style.display = mode === "table" ? "block" : "none";
}
document.querySelectorAll("input[name=synth-mode]").forEach(r => r.addEventListener("change", updateSynthModeVisibility));

function updateSynthTableModeVisibility() {
  const mode = checkedValue("synth-table-mode");
  $("synth-minterm-fields").style.display = mode === "minterms" ? "block" : "none";
  $("synth-bits-fields").style.display = mode === "bits" ? "block" : "none";
}
document.querySelectorAll("input[name=synth-table-mode]").forEach(r => r.addEventListener("change", updateSynthTableModeVisibility));

async function postJSON(url, payload) {
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    return await res.json();
  } catch (e) {
    return { ok: false, error: "could not reach the ohmwork server: " + e };
  }
}

function showResult(result) {
  const out = $("output");
  out.classList.remove("empty");
  out.classList.toggle("error", !result.ok);
  out.textContent = result.ok ? result.output : "error: " + result.error;
}

$("panel-tt").addEventListener("submit", async (e) => {
  e.preventDefault();
  const colsMode = checkedValue("tt-cols");
  const payload = {
    expression: $("tt-expr").value,
    md: checkedValue("tt-format") === "md",
    latex: checkedValue("tt-format") === "latex",
    terse: colsMode === "terse",
    cols: colsMode === "custom" ? $("tt-cols-input").value : null,
  };
  showResult(await postJSON("/api/tt", payload));
});

$("panel-synth").addEventListener("submit", async (e) => {
  e.preventDefault();
  const payload = {
    dual_rail: $("synth-dual-rail").checked,
    max_stack: $("synth-max-stack").value || null,
  };
  if (checkedValue("synth-mode") === "expr") {
    payload.expr = $("synth-expr").value;
  } else {
    payload.variables = $("synth-vars").value;
    if (checkedValue("synth-table-mode") === "bits") {
      payload.table = $("synth-table").value;
    } else {
      payload.ones = $("synth-ones").value;
      payload.dc = $("synth-dc").value || null;
    }
  }
  showResult(await postJSON("/api/synth", payload));
});
</script>
</body>
</html>
"""


def _json_response(start_response, status: str, payload: dict):
    body = json.dumps(payload).encode("utf-8")
    start_response(status, [("Content-Type", "application/json"), ("Content-Length", str(len(body)))])
    return [body]


def _read_json_body(environ) -> dict:
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    raw = environ["wsgi.input"].read(length) if length else b""
    if not raw:
        return {}
    return json.loads(raw.decode("utf-8"))


def _handle_index(environ, start_response):
    body = _PAGE.encode("utf-8")
    start_response("200 OK", [("Content-Type", "text/html; charset=utf-8"), ("Content-Length", str(len(body)))])
    return [body]


def _handle_tt(environ, start_response):
    body = _read_json_body(environ)
    cols_raw = body.get("cols") or None
    cols = [c.strip() for c in cols_raw.split(",")] if cols_raw else None
    try:
        output = render_tt(
            body.get("expression") or "",
            md=bool(body.get("md")),
            latex=bool(body.get("latex")),
            terse=bool(body.get("terse")),
            cols=cols,
        )
    except (ParseError, ValueError) as e:
        return _json_response(start_response, "200 OK", {"ok": False, "error": str(e)})
    return _json_response(start_response, "200 OK", {"ok": True, "output": output})


def _handle_synth(environ, start_response):
    body = _read_json_body(environ)
    max_stack_raw = body.get("max_stack")
    try:
        max_stack = int(max_stack_raw) if max_stack_raw not in (None, "") else None
    except (TypeError, ValueError):
        return _json_response(start_response, "200 OK", {"ok": False, "error": "max stack height must be a whole number"})

    try:
        # Exactly one synthesis per request (M1.2): the legacy text report
        # (`output`, unchanged) and the new structured student view
        # (`result`) are both derived from this same verified
        # SynthesisResult -- never recomputed independently, and never
        # returned partially if anything below raises.
        result = synthesize_from_input(
            expr=body.get("expr") or None,
            variables=body.get("variables") or None,
            ones=body.get("ones") or None,
            dc=body.get("dc") or None,
            table=body.get("table") or None,
            dual_rail=bool(body.get("dual_rail")),
            max_stack=max_stack,
        )
        output_name = validate_output_name(body.get("output_name"), result.var_order)
    except (ParseError, ValueError, RuntimeError) as e:
        return _json_response(start_response, "200 OK", {"ok": False, "error": str(e)})

    output = format_synth_report(result, result.verification)
    view = build_synth_view(result, output_name=output_name, max_stack_applied=max_stack is not None)
    return _json_response(start_response, "200 OK", {"ok": True, "output": output, "result": view})


def _not_found(environ, start_response):
    body = b"not found"
    start_response("404 Not Found", [("Content-Type", "text/plain"), ("Content-Length", str(len(body)))])
    return [body]


_ROUTES = {
    ("GET", "/"): _handle_index,
    ("POST", "/api/tt"): _handle_tt,
    ("POST", "/api/synth"): _handle_synth,
}


def app(environ, start_response):
    """The WSGI application. A last-resort ``except`` guards against any
    unexpected exception crashing the whole server over one bad request —
    it's surfaced to the page as an error, not silently swallowed."""
    method = environ.get("REQUEST_METHOD", "GET")
    path = environ.get("PATH_INFO", "/")
    handler = _ROUTES.get((method, path))
    if handler is None:
        return _not_found(environ, start_response)
    try:
        return handler(environ, start_response)
    except Exception as e:  # noqa: BLE001 - deliberate last-resort guard, see docstring
        return _json_response(start_response, "200 OK", {"ok": False, "error": f"internal error: {e}"})


class _QuietWSGIRequestHandler(WSGIRequestHandler):
    def log_message(self, format, *args):  # noqa: A002 - matches BaseHTTPRequestHandler's signature
        pass  # keep the terminal quiet; failures still surface in the page's own error display


def run_server(*, host: str = "127.0.0.1", port: int = 5757, open_browser: bool = True, stdout=None) -> None:
    """Serve the UI until interrupted (Ctrl+C). Blocking — this is what
    ``ohmwork ui`` runs in the foreground."""
    stdout = stdout or sys.stdout
    httpd = make_server(host, port, app, handler_class=_QuietWSGIRequestHandler)
    url = f"http://{host}:{port}/"
    print(f"Ohmwork UI running at {url} (Ctrl+C to stop)", file=stdout)
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.", file=stdout)
    finally:
        httpd.server_close()
