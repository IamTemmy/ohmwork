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
from ohmwork.derivation import variables_in_order
from ohmwork.errors import ParseError
from ohmwork.parser import parse
from ohmwork.presenter import build_synth_view, validate_output_name
from ohmwork.report import format_synth_report

# The server binds to loopback only (D-adjacent: see run_server's default
# host), but loopback binding alone doesn't stop a hostile page the user
# has open in another tab from POSTing here -- browsers still send "simple"
# cross-origin requests (no preflight) even though CORS then blocks the
# attacker page from reading the *response*. That's enough to let a
# malicious page burn CPU/memory on this local server while ``ohmwork ui``
# is running. Three independent layers close that off for POST routes:
# requiring a JSON content type (forces the browser into a CORS preflight
# for any cross-origin POST, which fails closed since we don't answer
# OPTIONS), rejecting a foreign Origin outright as defense in depth, and
# capping the request body size. ``tt`` additionally has no engine-level
# variable cap (unlike synth's D-scoped 3-4), so the web endpoint caps it
# separately -- the CLI's behavior (tested byte-for-byte) is untouched.
#
# The Origin check must not trust the request's own ``Host`` header as
# "what this server's origin is" -- that header is client-supplied, so a
# DNS-rebinding attacker (a hostname that resolves to their server, then
# to 127.0.0.1) can make the browser send both a ``Host`` and an
# ``Origin`` that match each other while neither is actually this server.
# ``environ["SERVER_PORT"]`` is the one thing here the WSGI server itself
# sets from the real listening socket, not from any client header, so
# "self" is defined against loopback hostnames + that port, not the
# request's own Host.
_MAX_BODY_BYTES = 65_536
_MAX_TT_VARIABLES = 8  # 9 vars ~11s, 10 vars ~108s on this machine (measured) --
# wsgiref's server is single-threaded, so that blocks the whole UI, not just the request.
_LOOPBACK_HOSTNAMES = ("127.0.0.1", "localhost", "[::1]", "::1")

_PAGE = r"""<!doctype html>
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
  input.output-name-input { width: 5rem; }
  .row { display: flex; gap: 1.4rem; flex-wrap: wrap; margin-top: .6rem; align-items: center; }
  .row label { margin-top: 0; display: inline-flex; align-items: center; gap: .35rem; font-weight: normal; }
  button.submit {
    padding: .55rem 1.4rem; font-size: 1rem; cursor: pointer;
    border-radius: 6px; border: 1px solid #8886; background: #8882; color: inherit; font-family: inherit;
  }
  button.submit:hover { background: #8884; }
  .action-row { margin-top: 1.1rem; }
  button.btn-secondary {
    padding: .55rem 1.2rem; font-size: .95rem; cursor: pointer; opacity: .7;
    border-radius: 6px; border: 1px solid #8884; background: transparent; color: inherit; font-family: inherit;
  }
  button.btn-secondary:hover { opacity: 1; background: #8882; }
  pre#tt-output {
    white-space: pre-wrap; background: #8881; padding: 1rem; border-radius: 6px;
    margin-top: 1.25rem; min-height: 1.5rem; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: .85rem; overflow-x: auto;
  }
  pre#tt-output.error { color: #c0392b; }
  pre#tt-output.empty { display: none; }
  .hint { font-size: .78rem; opacity: .6; margin-top: .2rem; }

  /* Truth-table grid */
  table.truth-grid { border-collapse: collapse; margin-top: .75rem; font-size: .9rem; }
  table.truth-grid th, table.truth-grid td {
    border: 1px solid #8886; padding: .35rem .6rem; text-align: center;
  }
  table.truth-grid th { font-weight: 600; background: #8881; }
  button.cell-btn {
    width: 2.2rem; height: 2rem; font: inherit; font-weight: 600; cursor: pointer;
    border: 1px solid #8886; border-radius: 4px; background: transparent; color: inherit;
  }
  button.cell-btn:hover { background: #8884; }
  button.cell-btn:focus-visible { outline: 2px solid #5a82ff; outline-offset: 1px; }
  button.cell-btn[data-val="X"] { opacity: .65; }

  details.manual-entry { margin-top: .85rem; }
  details.manual-entry summary { cursor: pointer; font-size: .85rem; opacity: .8; }
  details.manual-entry .row, details.manual-entry label { margin-top: .6rem; }

  /* Synth result */
  #synth-error {
    white-space: pre-wrap; background: #8881; color: #c0392b; padding: 1rem;
    border-radius: 6px; margin-top: 1.25rem; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: .85rem;
  }
  #synth-error.empty { display: none; }
  #synth-result.empty { display: none; }
  #synth-result { margin-top: 1.25rem; }

  .answer-summary {
    background: #5a82ff14; border: 1px solid #5a82ff40; border-radius: 8px; padding: 1rem 1.2rem;
  }
  .answer-summary .gate-line { font-size: 1.15rem; font-weight: 700; }
  .answer-summary .function-line {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 1.05rem; margin-top: .4rem;
  }
  .answer-summary .topology-line, .answer-summary .verified-line { font-size: .88rem; opacity: .8; margin-top: .3rem; }
  .answer-summary .verified-line { color: #2e8b57; }
  .answer-summary .dont-care-note { font-size: .8rem; opacity: .7; margin-top: .3rem; font-style: italic; }

  .section { margin-top: 1.4rem; }
  .section h3 { font-size: .95rem; margin: 0 0 .5rem; opacity: .85; }
  table.kv { border-collapse: collapse; font-size: .88rem; }
  table.kv td { padding: .3rem .8rem .3rem 0; vertical-align: top; }
  table.kv td:first-child { opacity: .65; white-space: nowrap; }
  table.kv td.mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }

  .reasoning p { font-size: .9rem; margin: .3rem 0; }
  ul.alt-list { font-size: .85rem; padding-left: 1.2rem; margin: .5rem 0 0; }
  ul.alt-list li { margin: .2rem 0; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  ul.alt-list li.chosen { font-weight: 600; font-family: inherit; }

  details.section summary { cursor: pointer; font-size: .95rem; opacity: .85; }
  pre#res-advanced {
    white-space: pre-wrap; background: #8881; padding: 1rem; border-radius: 6px;
    margin-top: .75rem; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: .85rem; overflow-x: auto;
  }

  .copy-row { margin-top: 1.2rem; }
  button.copy-btn {
    padding: .4rem 1rem; font-size: .85rem; cursor: pointer; border-radius: 6px;
    border: 1px solid #8886; background: transparent; color: inherit; font-family: inherit;
  }
  button.copy-btn:hover { background: #8884; }
  button.copy-btn.copied { background: #2e8b5730; border-color: #2e8b57; }
  pre.copy-fallback {
    white-space: pre-wrap; background: #8881; padding: .75rem; border-radius: 6px;
    margin-top: .5rem; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: .8rem; overflow-x: auto; border: 1px dashed #8886;
  }
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

  <div class="row action-row">
    <button type="submit" class="submit">Run</button>
    <button type="button" class="btn-secondary" id="tt-new-problem">New problem</button>
  </div>

  <pre id="tt-output" class="empty"></pre>
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

    <div id="synth-grid-wrap"></div>

    <details class="manual-entry" id="synth-manual-details">
      <summary>Enter the truth table manually instead (minterms or a bit string)</summary>
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
    </details>
  </div>

  <label>Output name (optional — defaults to F)
    <input type="text" id="synth-output-name" class="output-name-input" placeholder="F" maxlength="2">
  </label>

  <div class="row">
    <label><input type="checkbox" id="synth-dual-rail"> Dual-rail (complements free — D2)</label>
  </div>
  <label>Max stack height (optional — D3's opt-in engineering constraint)
    <input type="number" id="synth-max-stack" min="1">
  </label>

  <div class="row action-row">
    <button type="submit" class="submit">Synthesize</button>
    <button type="button" class="btn-secondary" id="synth-new-problem">New problem</button>
  </div>

  <pre id="synth-error" class="empty"></pre>

  <div id="synth-result" class="empty">
    <div class="answer-summary">
      <div class="gate-line" id="res-gate-line"></div>
      <div class="function-line" id="res-function-line"></div>
      <div class="topology-line" id="res-topology-line"></div>
      <div class="verified-line" id="res-verified-line"></div>
      <div class="dont-care-note" id="res-dont-care-note"></div>
    </div>

    <div class="section">
      <h3>CMOS implementation</h3>
      <table class="kv">
        <tr><td>PDN (NMOS)</td><td class="mono" id="res-pdn-expr"></td></tr>
        <tr><td>PUN (PMOS)</td><td class="mono" id="res-pun-expr"></td></tr>
        <tr><td>NMOS count</td><td id="res-nmos"></td></tr>
        <tr><td>PMOS count</td><td id="res-pmos"></td></tr>
        <tr><td>Inverters</td><td id="res-inverters"></td></tr>
        <tr><td>Stack heights</td><td id="res-stacks"></td></tr>
      </table>
    </div>

    <div class="section reasoning">
      <h3>Reasoning</h3>
      <p id="res-selection-note"></p>
      <p id="res-minimality"></p>
      <ul class="alt-list" id="res-alternatives"></ul>
    </div>

    <details class="section">
      <summary>Advanced details</summary>
      <pre id="res-advanced"></pre>
    </details>

    <div class="row copy-row">
      <button type="button" class="copy-btn" id="copy-solution">Copy solution</button>
      <button type="button" class="copy-btn" id="copy-advanced">Copy advanced report</button>
    </div>
  </div>
</form>

<script>
function $(id) { return document.getElementById(id); }
function checkedValue(name) {
  const el = document.querySelector(`input[name=${name}]:checked`);
  return el ? el.value : null;
}
function clearChildren(el) {
  while (el.firstChild) el.removeChild(el.firstChild);
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

// --- Truth-table grid --------------------------------------------------------
//
// Primary way to build a truth table: shows every row for the declared
// variables, with a clickable output cell cycling 0 -> 1 -> X -> 0. Feeds
// the exact same row-ordered bit-string format (variable 0 = MSB) that
// the manual "Bit string" field and --table already accept -- nothing
// about how the engine interprets a truth table changes.
let gridState = [];

function parseVarList(raw) {
  return raw.split(",").map(s => s.trim()).filter(s => s.length > 0);
}

function buildGrid() {
  const vars = parseVarList($("synth-vars").value);
  const wrap = $("synth-grid-wrap");
  clearChildren(wrap);
  gridState = [];

  if (vars.length === 0) {
    const msg = document.createElement("p");
    msg.className = "hint";
    msg.textContent = "Enter 1-4 variables above to build the truth table grid.";
    wrap.appendChild(msg);
    return;
  }
  if (vars.length > 4) {
    const msg = document.createElement("p");
    msg.className = "hint";
    msg.textContent = "The grid supports up to 4 variables (M1 scope); use fewer, or enter the truth table manually below.";
    wrap.appendChild(msg);
    return;
  }

  const n = vars.length;
  const rows = 1 << n;
  gridState = new Array(rows).fill("0");

  const table = document.createElement("table");
  table.className = "truth-grid";

  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  vars.forEach(v => {
    const th = document.createElement("th");
    th.textContent = v;
    headRow.appendChild(th);
  });
  const outTh = document.createElement("th");
  outTh.textContent = "Output";
  headRow.appendChild(outTh);
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  for (let i = 0; i < rows; i++) {
    const tr = document.createElement("tr");
    const bits = i.toString(2).padStart(n, "0");
    for (const b of bits) {
      const td = document.createElement("td");
      td.textContent = b;
      tr.appendChild(td);
    }
    const outTd = document.createElement("td");
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "cell-btn";
    btn.textContent = "0";
    btn.dataset.val = "0";
    btn.setAttribute("aria-label", vars.join("") + "=" + bits + " output, currently 0. Press to cycle 0, 1, X.");
    btn.addEventListener("click", () => cycleCell(i, btn));
    outTd.appendChild(btn);
    tr.appendChild(outTd);
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  wrap.appendChild(table);
}

function cycleCell(i, btn) {
  const next = { "0": "1", "1": "X", "X": "0" };
  gridState[i] = next[gridState[i]];
  btn.textContent = gridState[i];
  btn.dataset.val = gridState[i];
  btn.setAttribute("aria-label", "output, currently " + gridState[i] + ". Press to cycle 0, 1, X.");
  clearSynthResultDisplay();
}

function gridToBitString() {
  return gridState.join("");
}

$("synth-vars").addEventListener("input", () => { buildGrid(); clearSynthResultDisplay(); });

// --- Requests ------------------------------------------------------------------

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
  const result = await postJSON("/api/tt", payload);
  const out = $("tt-output");
  out.classList.remove("empty");
  out.classList.toggle("error", !result.ok);
  out.textContent = result.ok ? result.output : "error: " + result.error;
});

function resetTtForm() {
  // Clears this tab's own problem data only -- the format/columns radios
  // are a workflow preference (like synth-mode below), not per-problem
  // data, so they're deliberately left alone.
  $("tt-expr").value = "";
  $("tt-cols-input").value = "";
  const out = $("tt-output");
  out.classList.add("empty");
  out.classList.remove("error");
  out.textContent = "";
  $("tt-expr").focus();
}
$("tt-new-problem").addEventListener("click", resetTtForm);

// --- Synth result rendering ------------------------------------------------------

let lastSolutionText = "";
let lastAdvancedText = "";

function renderSynthResult(view, rawOutput) {
  $("res-gate-line").textContent = `${view.gate_name} — ${view.total_transistors} transistors`;
  $("res-function-line").textContent = view.function;
  $("res-topology-line").textContent = view.topology_note || "";
  $("res-topology-line").style.display = view.topology_note ? "block" : "none";
  $("res-verified-line").textContent = view.verified_summary;

  const dcNote = $("res-dont-care-note");
  if (view.function_uses_dont_cares) {
    dcNote.textContent = "This is the function Ohmwork implemented after freely assigning the don't-care rows (see Advanced details).";
    dcNote.style.display = "block";
  } else {
    dcNote.textContent = "";
    dcNote.style.display = "none";
  }

  $("res-pdn-expr").textContent = view.pdn.expression;
  $("res-pun-expr").textContent = view.pun.expression;
  $("res-nmos").textContent = view.pdn.transistors;
  $("res-pmos").textContent = view.pun.transistors;
  const invertersText = view.inverters.count === 0
    ? "0"
    : `${view.inverters.count} (shared: ${view.inverters.literals.map(l => l + "'").join(", ")})`;
  $("res-inverters").textContent = invertersText;
  const stacksText = `PDN ${view.pdn.stack_height}, PUN ${view.pun.stack_height}` + (view.stack_advisory ? ` — ${view.stack_advisory}` : "");
  $("res-stacks").textContent = stacksText;

  $("res-selection-note").textContent = view.reasoning.selection_note;
  $("res-minimality").textContent = view.reasoning.minimality_summary;

  function formatAlternative(alt) {
    const label = alt.labels.join("/");
    return `${label}: F' = ${alt.expression} (${alt.total_cost} transistors)` + (alt.is_chosen ? " — chosen" : "");
  }

  const altList = $("res-alternatives");
  clearChildren(altList);
  view.reasoning.alternatives.forEach(alt => {
    const li = document.createElement("li");
    if (alt.is_chosen) li.classList.add("chosen");
    li.textContent = formatAlternative(alt);
    altList.appendChild(li);
  });

  $("res-advanced").textContent = rawOutput;

  const summaryLines = [
    `${view.gate_name} — ${view.total_transistors} transistors`,
    view.function,
    view.topology_note || "",
    view.verified_summary,
    view.function_uses_dont_cares
      ? "This is the function Ohmwork implemented after freely assigning the don't-care rows (see Advanced details)."
      : "",
  ].filter(Boolean);

  const cmosLines = [
    "CMOS implementation:",
    `  PDN (NMOS): ${view.pdn.expression}`,
    `  PUN (PMOS): ${view.pun.expression}`,
    `  NMOS count: ${view.pdn.transistors}`,
    `  PMOS count: ${view.pun.transistors}`,
    `  Inverters: ${invertersText}`,
    `  Stack heights: ${stacksText}`,
  ];

  const reasoningLines = [
    "Reasoning:",
    `  ${view.reasoning.selection_note}`,
    `  ${view.reasoning.minimality_summary}`,
    ...view.reasoning.alternatives.map(alt => `  ${formatAlternative(alt)}`),
  ];

  lastSolutionText = [summaryLines, cmosLines, reasoningLines].map(section => section.join("\n")).join("\n\n");
  lastAdvancedText = rawOutput;
}

$("panel-synth").addEventListener("submit", async (e) => {
  e.preventDefault();
  const payload = {
    dual_rail: $("synth-dual-rail").checked,
    max_stack: $("synth-max-stack").value || null,
    output_name: $("synth-output-name").value || null,
  };
  if (checkedValue("synth-mode") === "expr") {
    payload.expr = $("synth-expr").value;
  } else {
    payload.variables = $("synth-vars").value;
    const manualOpen = $("synth-manual-details").open;
    if (manualOpen && checkedValue("synth-table-mode") === "bits") {
      payload.table = $("synth-table").value;
    } else if (manualOpen) {
      payload.ones = $("synth-ones").value;
      payload.dc = $("synth-dc").value || null;
    } else if (gridState.length > 0) {
      payload.table = gridToBitString();
    } else {
      $("synth-error").classList.remove("empty");
      $("synth-error").textContent = "error: enter 1-4 variables to build the truth table grid (or use manual entry below).";
      $("synth-result").classList.add("empty");
      return;
    }
  }

  const result = await postJSON("/api/synth", payload);
  const errEl = $("synth-error");
  const resEl = $("synth-result");
  if (!result.ok) {
    errEl.classList.remove("empty");
    errEl.textContent = "error: " + result.error;
    resEl.classList.add("empty");
    return;
  }
  errEl.classList.add("empty");
  errEl.textContent = "";
  resEl.classList.remove("empty");
  renderSynthResult(result.result, result.output);
});

// --- Stale-result prevention / New problem ----------------------------------------
//
// Once a result (or error) is on screen, editing any input that feeds the
// synthesis call must hide it immediately -- otherwise the old answer
// keeps showing as though it belongs to whatever's now in the form. This
// never re-synthesizes on its own; it only clears the display. The user
// still has to press Synthesize for a new answer.

const _RESULT_TEXT_FIELD_IDS = [
  "res-gate-line", "res-function-line", "res-topology-line", "res-verified-line", "res-dont-care-note",
  "res-pdn-expr", "res-pun-expr", "res-nmos", "res-pmos", "res-inverters", "res-stacks",
  "res-selection-note", "res-minimality", "res-advanced",
];

function clearSynthResultDisplay() {
  const errEl = $("synth-error");
  const resEl = $("synth-result");
  errEl.classList.add("empty");
  errEl.textContent = "";
  resEl.classList.add("empty");

  // Actually clear the stale content, not just hide it -- "empty" is a
  // display toggle, and leaving old text underneath it would still be a
  // stale answer sitting in the DOM (and briefly visible if something
  // ever removed the .empty class without re-rendering first).
  _RESULT_TEXT_FIELD_IDS.forEach(id => { $(id).textContent = ""; });
  clearChildren($("res-alternatives"));

  const advancedDetails = document.querySelector("#synth-result details.section");
  if (advancedDetails) advancedDetails.open = false;

  document.querySelectorAll("#synth-result .copy-fallback").forEach(el => el.remove());
  $("copy-solution").classList.remove("copied");
  $("copy-solution").textContent = "Copy solution";
  $("copy-advanced").classList.remove("copied");
  $("copy-advanced").textContent = "Copy advanced report";

  lastSolutionText = "";
  lastAdvancedText = "";
}

[
  "synth-expr", "synth-ones", "synth-dc", "synth-table", "synth-output-name", "synth-max-stack",
].forEach(id => $(id).addEventListener("input", clearSynthResultDisplay));
$("synth-dual-rail").addEventListener("change", clearSynthResultDisplay);
document.querySelectorAll("input[name=synth-mode]").forEach(r => r.addEventListener("change", clearSynthResultDisplay));
document.querySelectorAll("input[name=synth-table-mode]").forEach(r => r.addEventListener("change", clearSynthResultDisplay));

function resetSynthForm() {
  // The chosen synth-mode (From expression / From truth table) is a
  // workflow choice, not per-problem data -- a student working through
  // several questions of the same type shouldn't have to reselect it
  // every time. Everything else here is problem-specific and gets cleared.
  const mode = checkedValue("synth-mode");

  $("synth-expr").value = "";
  $("synth-vars").value = "";
  $("synth-ones").value = "";
  $("synth-dc").value = "";
  $("synth-table").value = "";
  $("synth-output-name").value = "";
  $("synth-dual-rail").checked = false;
  $("synth-max-stack").value = "";

  $("synth-manual-details").open = false;
  document.querySelector('input[name="synth-table-mode"][value="minterms"]').checked = true;
  updateSynthTableModeVisibility();

  buildGrid(); // synth-vars is now empty -> clears the grid and gridState
  clearSynthResultDisplay();

  (mode === "table" ? $("synth-vars") : $("synth-expr")).focus();
}
$("synth-new-problem").addEventListener("click", resetSynthForm);

// --- Copy buttons ----------------------------------------------------------------

function showCopyFallback(btn, text) {
  // Last resort: neither the Clipboard API nor execCommand nor prompt()
  // worked in this environment (seen for real in one embedded/automated
  // browser context during testing) -- show the text inline, selected,
  // so the user can copy it by hand. Never throws.
  const existing = btn.parentElement.querySelector(".copy-fallback");
  if (existing) existing.remove();
  const box = document.createElement("pre");
  box.className = "copy-fallback";
  box.textContent = text;
  btn.insertAdjacentElement("afterend", box);
  try {
    const range = document.createRange();
    range.selectNodeContents(box);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);
  } catch (e) {
    // Selecting it for them is a nicety, not required -- the text is
    // visible either way.
  }
}

async function copyText(text, btn) {
  let copied = false;

  if (navigator.clipboard && navigator.clipboard.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      copied = true;
    } catch (e) {
      // Permissions, insecure context, etc. -- try the next strategy.
    }
  }

  if (!copied) {
    try {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      copied = document.execCommand("copy");
      document.body.removeChild(ta);
    } catch (e) {
      // execCommand unavailable or disabled -- try the next strategy.
    }
  }

  if (!copied) {
    try {
      window.prompt("Copy failed automatically; copy this manually:", text);
      copied = true; // the user had a chance to copy, even if we can't confirm it
    } catch (e) {
      // prompt() itself can be unsupported in some embedded/automated
      // browser contexts -- fall through to the visible-text fallback
      // rather than leaving an uncaught exception.
    }
  }

  if (!copied) {
    showCopyFallback(btn, text);
    return;
  }

  const original = btn.textContent;
  btn.textContent = "Copied!";
  btn.classList.add("copied");
  setTimeout(() => { btn.textContent = original; btn.classList.remove("copied"); }, 1500);
}

$("copy-solution").addEventListener("click", () => copyText(lastSolutionText, $("copy-solution")));
$("copy-advanced").addEventListener("click", () => copyText(lastAdvancedText, $("copy-advanced")));
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
    expression = body.get("expression") or ""
    cols_raw = body.get("cols") or None
    cols = [c.strip() for c in cols_raw.split(",")] if cols_raw else None
    try:
        n_vars = len(variables_in_order(parse(expression)))
    except ParseError as e:
        return _json_response(start_response, "200 OK", {"ok": False, "error": str(e)})
    if n_vars > _MAX_TT_VARIABLES:
        return _json_response(
            start_response,
            "200 OK",
            {
                "ok": False,
                "error": (
                    f"this expression has {n_vars} variables; the web UI caps derivation "
                    f"tables at {_MAX_TT_VARIABLES} variables to keep requests fast — use "
                    "the CLI (`ohmwork tt`) for larger tables"
                ),
            },
        )
    try:
        output = render_tt(
            expression,
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


def _plain_text_error(start_response, status: str, message: str):
    body = message.encode("utf-8")
    start_response(status, [("Content-Type", "text/plain; charset=utf-8"), ("Content-Length", str(len(body)))])
    return [body]


def _expected_hosts(environ) -> tuple[str, ...]:
    """The ``Host``/``Origin`` values a legitimate request to *this* server
    can carry: a loopback hostname plus the port the WSGI server actually
    bound (``SERVER_PORT``, set by the server itself from the real socket
    — never from a client-supplied header, unlike ``HTTP_HOST``)."""
    port = environ.get("SERVER_PORT", "")
    return tuple(f"{host}:{port}" for host in _LOOPBACK_HOSTNAMES)


def _host_is_allowed(environ) -> bool:
    """Rejects a spoofed ``Host`` header outright (e.g. DNS rebinding: a
    hostname that resolves to an attacker's server for the initial page
    load, then to 127.0.0.1 for the actual request, while the browser
    still sends the original hostname as ``Host``). Comparing ``Origin``
    against ``HTTP_HOST`` alone can't catch this, since both would carry
    the same spoofed name -- ``Host`` itself must be a loopback address
    first."""
    return environ.get("HTTP_HOST", "") in _expected_hosts(environ)


def _origin_is_allowed(environ) -> bool:
    """No ``Origin`` header (a same-origin form submit, a direct API call,
    curl) is allowed; a present one must match a loopback origin at this
    server's actual port — anything else is a page from elsewhere asking
    this loopback server to do work."""
    origin = environ.get("HTTP_ORIGIN")
    if not origin:
        return True
    expected = _expected_hosts(environ)
    return any(origin in (f"http://{host}", f"https://{host}") for host in expected)


def _reject_hostile_post(environ, start_response):
    """Guards applied to every POST before it reaches a handler. Returns a
    WSGI response iterable to short-circuit the request, or ``None`` to let
    it proceed. See the module-level comment above ``_MAX_BODY_BYTES`` for
    why these checks exist together."""
    if not _host_is_allowed(environ):
        return _plain_text_error(start_response, "403 Forbidden", "unrecognized Host header")

    if not _origin_is_allowed(environ):
        return _plain_text_error(start_response, "403 Forbidden", "cross-origin requests are not allowed")

    content_type = environ.get("CONTENT_TYPE", "").split(";")[0].strip().lower()
    if content_type != "application/json":
        return _plain_text_error(start_response, "415 Unsupported Media Type", "request body must be application/json")

    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    if length > _MAX_BODY_BYTES:
        return _plain_text_error(start_response, "413 Payload Too Large", f"request body exceeds {_MAX_BODY_BYTES} bytes")

    return None


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
    if method == "POST":
        rejection = _reject_hostile_post(environ, start_response)
        if rejection is not None:
            return rejection
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
