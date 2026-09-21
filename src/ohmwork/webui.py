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

from ohmwork.api import derive_from_input, format_tt_report, synthesize_from_input, kmap_from_input
from ohmwork.kmap import build_synthesis_kmap
from ohmwork.expr import render
from ohmwork.kmap_view import build_kmap_view, format_kmap_report
from ohmwork.kmap_ui import CSS as KMAP_CSS, HTML as KMAP_HTML, JS as KMAP_JS
from ohmwork.derivation import variables_in_order
from ohmwork.errors import ParseError
from ohmwork.parser import parse
from ohmwork.presenter import build_schematic_view, build_synth_view, build_tt_view, validate_output_name
from ohmwork.report import format_synth_report
from ohmwork.schematic import build_textbook_schematic
from ohmwork.spice_exports import build_spice_exports

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
  #spice-export-help {
    position: relative; box-sizing: border-box;
    border: 1px solid #8886; border-radius: 8px; background: #8881;
    padding: 3.5rem 1rem 1rem;
  }
  #spice-export-help p:first-of-type { margin-top: 0; }
  #spice-export-help p:last-child { margin-bottom: 0; }
  #spice-help-close {
    position: absolute; top: .4rem; right: .4rem;
    width: 44px; height: 44px; padding: 0;
    display: grid; place-items: center;
    border: 0; border-radius: 6px; background: transparent; color: inherit;
    font: inherit; font-size: 1.5rem; line-height: 1; cursor: pointer;
  }
  #spice-help-close:hover { background: #8882; }
  #spice-help-close:focus-visible { outline: 2px solid currentColor; outline-offset: 2px; }
  /* Derivation result (M1.3) */
  #tt-error {
    white-space: pre-wrap; background: #8881; color: #c0392b; padding: 1rem;
    border-radius: 6px; margin-top: 1.25rem; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: .85rem;
  }
  #tt-error.empty { display: none; }
  #tt-result.empty { display: none; }
  #tt-result { margin-top: 1.25rem; }
  .tt-function-line {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 1.05rem; font-weight: 600;
  }
  .tt-table-wrap { overflow-x: auto; margin-top: .9rem; }
  table.tt-grid { border-collapse: collapse; font-size: .88rem; }
  table.tt-grid th, table.tt-grid td {
    border: 1px solid #8886; padding: .35rem .7rem; text-align: center; white-space: nowrap;
  }
  table.tt-grid th { font-weight: 600; background: #8881; }
  table.tt-grid th.tt-output-col, table.tt-grid td.tt-output-col {
    background: #5a82ff14; font-weight: 700;
  }
  #tt-formatted-preview {
    white-space: pre-wrap; background: #8881; padding: 1rem; border-radius: 6px;
    margin-top: .75rem; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    font-size: .85rem; overflow-x: auto;
  }
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

  /* Per-element schematic styling (.ow-*) is NOT here -- it lives in an
     embedded <style> the JS injects as the first child of #schematic-svg
     itself (see SCHEMATIC_SVG_STYLE_CSS below), so the exact same rules
     apply whether the SVG is inline on this page or opened standalone
     after Download SVG (a page-level stylesheet wouldn't reach a
     downloaded file, and a second, separately-maintained copy of the
     rules could drift from this one). Only layout/sizing, which is
     legitimately page-specific, stays here. */
  .schematic-wrap { overflow-x: auto; max-width: 100%; border: 1px solid #8886; border-radius: 8px; padding: .75rem; background: #8880; }
  #schematic-svg { display: block; height: auto; color: inherit; }

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
  button.copy-btn-primary {
    padding: .55rem 1.3rem; font-size: .95rem; font-weight: 600;
    background: #5a82ff22; border-color: #5a82ff60;
  }
  button.copy-btn-primary:hover { background: #5a82ff38; }
  .tt-export-actions {
    display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: .5rem; width: 18.5rem; max-width: 100%; align-items: stretch;
  }
  .tt-export-actions > button.copy-btn {
    box-sizing: border-box; width: 100%; min-height: 44px;
    padding: .4rem .75rem; font-size: .85rem; line-height: 1.4; font-weight: 600;
  }
  @media (max-width: 360px) {
    .tt-export-actions { grid-template-columns: minmax(0, 1fr); grid-auto-rows: 1fr; }
  }
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

  <pre id="tt-error" class="empty"></pre>

  <div id="tt-result" class="empty">
    <div class="tt-function-line" id="tt-function-line"></div>

    <div class="tt-table-wrap">
      <table class="tt-grid" id="tt-table" aria-label="Derivation table">
        <thead><tr id="tt-table-head"></tr></thead>
        <tbody id="tt-table-body"></tbody>
      </table>
    </div>

    <div class="row copy-row tt-export-actions">
      <button type="button" class="copy-btn copy-btn-primary" id="tt-copy-rich" title="Copy formatted table for Word or Google Docs" aria-label="Copy table for Word or Google Docs">Copy table</button>
      <button type="button" class="copy-btn" id="tt-download-csv" disabled>Download CSV</button>
    </div>

    <details class="section" id="tt-advanced-exports">
      <summary>Advanced exports</summary>
      <p class="hint">Copy formats for the table above — for Word or Google Docs, use "Copy
        table" instead; the table itself is always the current result.</p>
      <div class="row">
        <label><input type="radio" name="tt-format" value="terminal" checked> Plain text / Terminal</label>
        <label><input type="radio" name="tt-format" value="md"> Markdown source</label>
        <label><input type="radio" name="tt-format" value="latex"> LaTeX fragment</label>
      </div>
      <div class="row copy-row">
        <button type="button" class="copy-btn" id="tt-copy-formatted">Copy formatted output</button>
      </div>
      <details class="section" id="tt-preview-details">
        <summary>Formatted output preview</summary>
        <pre id="tt-formatted-preview"></pre>
      </details>
    </details>
  </div>
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

    <div class="section schematic-section">
      <h3>Schematic</h3>
      <div class="schematic-wrap">
        <svg id="schematic-svg" xmlns="http://www.w3.org/2000/svg" role="img"></svg>
      </div>
      <div class="row">
        <button type="button" class="btn-secondary" id="download-svg-btn">Download SVG</button>
        <button type="button" class="btn-secondary" id="download-spice-template" disabled aria-describedby="spice-template-note">Download SPICE template</button>
        <button type="button" class="btn-secondary" id="download-spice-example" disabled aria-describedby="spice-example-note">Download SPICE example</button>
      </div>
    </div>

    <button type="button" class="km-proof-toggle" id="spice-help-toggle"
      aria-expanded="false" aria-controls="spice-export-help" hidden>About SPICE downloads</button>
    <section class="section km-work" id="spice-export-help" aria-labelledby="spice-help-toggle" hidden>
      <button type="button" id="spice-help-close" aria-label="Close"><span aria-hidden="true">×</span></button>
      <p id="spice-template-note"><strong>Connectivity template:</strong> not runnable as-is. Supply transistor models and replace W=TBD / L=TBD before simulation. Both power rails are subcircuit pins.</p>
      <p id="spice-example-note"><strong>Educational example:</strong> runnable with ngspice, using an illustrative 5 V supply, uniform W=10u / L=1u, and cited example models. All logical inputs start at 0; external complements are driven to 1. This is one DC operating point, not a truth-table sweep or a fabrication-ready design.</p>
      <p>Both files describe this exact circuit. Model sources, assumptions, pin order, and node mappings are included in the files. Other simulators are untested.</p>
    </section>

    <section class="section" aria-label="K-map for the chosen circuit">
      <h3>K-map for this circuit</h3>
      <p id="synth-km-selection-reason"></p>
      <p id="synth-km-connection"></p>
      <p class="mono" id="synth-km-equation"></p>
      <p id="synth-km-pdn"></p>
      <div class="km-stage" id="synth-km-stage" tabindex="0" aria-label="Scrollable synthesis K-map"></div>
      <div class="km-actions">
        <button type="button" class="btn-secondary" id="synth-km-show-all">Show all groups</button>
        <button type="button" class="btn-secondary" id="synth-km-download">Download K-map SVG</button>
        <button type="button" class="btn-secondary" id="synth-km-copy">Copy K-map explanation</button>
      </div>
      <p>Select a group or term to isolate it. Select again, or press Escape, to show all.</p>
      <p id="synth-km-selection" class="km-selection-status" aria-live="polite"></p>
      <div class="km-group-list" id="synth-km-groups"></div>
      <p id="synth-km-assignments"></p>
    </section>

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

// A monotonically increasing token per form. Submitting captures the
// current value; any result-affecting edit, New Problem, or later
// submission bumps it. A response is only rendered if its captured token
// still equals the live one -- otherwise it's an in-flight request that's
// been superseded (by an edit, a New Problem, or a newer submission) and
// must be discarded rather than repopulating stale text into the DOM.
// ttCopyRequestToken is the same idea, but for "Copy formatted output"'s
// own fetch specifically -- kept separate from ttRequestToken so a Run
// and a Copy in flight at the same time don't cancel each other out
// (they update different things: the table vs. the clipboard/preview).
let ttRequestToken = 0;
let ttCopyRequestToken = 0;
let lastTtFormattedOutput = "";
// The structured view from the last successfully rendered result --
// "Copy table for Word/Docs" builds its clipboard content from this (the
// already-computed derivation result) plus the already-rendered #tt-table
// DOM, never by re-deriving or hitting /api/tt again.
let lastTtView = null;
let lastTtCsv = null;

function buildTtPayload() {
  const colsMode = checkedValue("tt-cols");
  return {
    expression: $("tt-expr").value,
    md: checkedValue("tt-format") === "md",
    latex: checkedValue("tt-format") === "latex",
    terse: colsMode === "terse",
    cols: colsMode === "custom" ? $("tt-cols-input").value : null,
  };
}

function removeCopyFallbackFor(btn) {
  // A copy-fallback box is always inserted as a sibling of its own
  // button (showCopyFallback below), so scoping removal to that button's
  // parent -- never a page- or #tt-result-wide selector -- is what keeps
  // one button's fallback from being able to touch another's. A prior
  // version of resetTtExportState used "#tt-result .copy-fallback",
  // which matched *both* #tt-copy-formatted's and #tt-copy-rich's
  // fallback boxes since both buttons live inside #tt-result -- a
  // ChatGPT review caught that changing the Advanced export format was
  // silently deleting a visible "Copy table for Word/Docs" fallback the
  // user hadn't touched at all.
  const existing = btn.parentElement.querySelector(".copy-fallback");
  if (existing) existing.remove();
}

function resetTtExportState() {
  // The Advanced-export side only: the cached preview text, the
  // #tt-copy-formatted button's state, any in-flight "Copy formatted
  // output" fetch, and *only that button's* copy fallback box -- never
  // #tt-copy-rich's, which belongs to the independent "Copy table for
  // Word/Docs" button and must survive an Advanced-export format change
  // untouched. Kept separate from the table-clearing below so a
  // tt-format change can invalidate a pending or already-shown copy
  // *without* touching #tt-result, which is still a perfectly valid,
  // unrelated table -- a ChatGPT review caught that changing the format
  // radio didn't bump ttCopyRequestToken, so a Terminal copy fetch still
  // in flight could land after switching to Markdown and silently
  // overwrite the clipboard/preview with the wrong format's text; and
  // even with no fetch in flight, the preview kept showing the
  // previously-copied format after switching, which is just as
  // misleading.
  ttCopyRequestToken++;
  const copyBtn = $("tt-copy-formatted");
  removeCopyFallbackFor(copyBtn);
  copyBtn.classList.remove("copied");
  copyBtn.textContent = "Copy formatted output";
  $("tt-formatted-preview").textContent = "";
  const previewDetails = $("tt-preview-details");
  if (previewDetails) previewDetails.open = false;
  lastTtFormattedOutput = "";
}
document.querySelectorAll("input[name=tt-format]").forEach(r => r.addEventListener("change", resetTtExportState));

function clearTtOutputDisplay() {
  ttRequestToken++;
  resetTtExportState();
  $("tt-error").classList.add("empty");
  $("tt-error").textContent = "";
  $("tt-result").classList.add("empty");
  $("tt-function-line").textContent = "";
  clearChildren($("tt-table-head"));
  clearChildren($("tt-table-body"));
  lastTtView = null;
  lastTtCsv = null;
  $("tt-download-csv").disabled = true;
  // The complete result is going stale here (edit, New Problem, or a
  // newer submission) -- unlike resetTtExportState above, both copy
  // buttons' fallbacks are cleared, since both are now equally stale.
  const richBtn = $("tt-copy-rich");
  removeCopyFallbackFor(richBtn);
  richBtn.classList.remove("copied");
  richBtn.textContent = "Copy table";
}
$("tt-expr").addEventListener("input", clearTtOutputDisplay);
$("tt-cols-input").addEventListener("input", clearTtOutputDisplay);
document.querySelectorAll("input[name=tt-cols]").forEach(r => r.addEventListener("change", clearTtOutputDisplay));
// tt-format (Terminal/Markdown/LaTeX) is a copy/export preference now, not
// something the visible table depends on -- see the M1.3 comment on
// renderTtResult below -- so changing it deliberately does NOT clear or
// hide the table the way editing the expression or columns does. It only
// resets the export state above.

function renderTtResult(view, rawOutput, csv) {
  lastTtCsv = csv;
  $("tt-download-csv").disabled = !csv;
  $("tt-function-line").textContent = view.simplified_function;

  const headRow = $("tt-table-head");
  clearChildren(headRow);
  view.headers.forEach((label, i) => {
    const th = document.createElement("th");
    th.scope = "col";
    th.textContent = label;
    if (i === view.output_column_index) th.classList.add("tt-output-col");
    headRow.appendChild(th);
  });

  const tbody = $("tt-table-body");
  clearChildren(tbody);
  view.rows.forEach(rowValues => {
    const tr = document.createElement("tr");
    rowValues.forEach((cellValue, i) => {
      const td = document.createElement("td");
      td.textContent = cellValue ? "1" : "0";
      if (i === view.output_column_index) td.classList.add("tt-output-col");
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });

  lastTtFormattedOutput = rawOutput;
  $("tt-formatted-preview").textContent = rawOutput;
  lastTtView = view;
}

$("tt-download-csv").addEventListener("click", () => {
  if (!lastTtCsv) return;
  const url = URL.createObjectURL(new Blob([lastTtCsv], {type:"text/csv;charset=utf-8"}));
  const link = document.createElement("a");
  link.href = url; link.download = "ohmwork-derivation.csv";
  document.body.appendChild(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});

$("panel-tt").addEventListener("submit", async (e) => {
  e.preventDefault();
  clearTtOutputDisplay();
  const myToken = ttRequestToken;
  const result = await postJSON("/api/tt", buildTtPayload());
  if (myToken !== ttRequestToken) return; // superseded while this request was in flight
  const errEl = $("tt-error");
  const resEl = $("tt-result");
  if (!result.ok) {
    errEl.classList.remove("empty");
    errEl.textContent = "error: " + result.error;
    resEl.classList.add("empty");
    return;
  }
  errEl.classList.add("empty");
  errEl.textContent = "";
  resEl.classList.remove("empty");
  renderTtResult(result.result, result.output, result.csv);
});

// --- "Copy formatted output" ------------------------------------------------------
//
// The visible table is always the current result (M1.3); Terminal/
// Markdown/LaTeX only pick what this button fetches and copies. It always
// asks the server fresh -- the client never reimplements render.py's
// formatting -- guarded by its own token so an edit, New Problem, or a
// second click supersedes an in-flight copy rather than letting a stale
// fetch overwrite the clipboard or the preview after the user's moved on.

$("tt-copy-formatted").addEventListener("click", async () => {
  const btn = $("tt-copy-formatted");
  const original = "Copy formatted output";
  const myToken = ++ttCopyRequestToken;
  btn.textContent = "Copying…";
  const result = await postJSON("/api/tt", buildTtPayload());
  if (myToken !== ttCopyRequestToken) return; // superseded; clearTtOutputDisplay already reset the button
  btn.textContent = original;
  if (!result.ok) return; // the visible error state, if any, already reflects why
  lastTtFormattedOutput = result.output;
  $("tt-formatted-preview").textContent = result.output;
  copyText(result.output, btn);
});

// --- "Copy table for Word/Docs" ---------------------------------------------------
//
// Word/Docs users pasting the Terminal/Markdown/LaTeX text above get raw
// pipes, dashes, or LaTeX commands, not a table -- because writeText()
// only ever offers a text/plain clipboard representation. This button
// writes a real text/html table alongside a tab-separated text/plain
// fallback, in one clipboard operation, entirely from data already on the
// page (lastTtView, set by renderTtResult, and the already-rendered
// #tt-table DOM) -- no new /api/tt request, no re-deriving, no second
// table-building implementation.

function buildTtInlineStyledTableClone() {
  // Clones the already-rendered #tt-table (built via safe DOM
  // construction in renderTtResult, textContent only) rather than
  // building a second one, then layers inline styles onto the *clone* --
  // Word and Google Docs both strip a pasted page's own <style> rules, so
  // the borders/padding/header shading have to travel as inline style
  // attributes to survive the paste.
  const clone = $("tt-table").cloneNode(true);
  clone.style.borderCollapse = "collapse";
  clone.setAttribute("border", "1"); // legacy attribute both Word and Docs also honor
  clone.querySelectorAll("th, td").forEach(cell => {
    cell.style.border = "1px solid #888888";
    cell.style.padding = "4px 10px";
    cell.style.textAlign = "center";
  });
  clone.querySelectorAll("th").forEach(cell => {
    cell.style.background = "#eeeeee";
    cell.style.fontWeight = "bold";
  });
  clone.querySelectorAll("td.tt-output-col, th.tt-output-col").forEach(cell => {
    cell.style.background = "#dbe6ff";
    cell.style.fontWeight = "bold";
  });
  // The live table's id/aria-label are meaningless (and, for id, invalid
  // as a duplicate) once this is pasted somewhere else -- strip them from
  // the clone and every descendant rather than carrying them along.
  clone.removeAttribute("id");
  clone.removeAttribute("aria-label");
  clone.querySelectorAll("[id]").forEach(el => el.removeAttribute("id"));
  return clone;
}

function buildTtRichHtml(view) {
  // Built entirely with createElement/textContent (the styled clone
  // above is itself a clone of a safely-built node); reading .innerHTML
  // back off a node assembled this way is serialization, not an unsafe
  // injection -- nothing here is ever assigned into innerHTML from a string.
  const wrapper = document.createElement("div");
  wrapper.appendChild(buildTtInlineStyledTableClone());
  const fnLine = document.createElement("p");
  fnLine.textContent = view.simplified_function;
  wrapper.appendChild(fnLine);
  return wrapper.innerHTML;
}

function buildTtRichPlainText(view) {
  const lines = [view.headers.join("\t")];
  view.rows.forEach(row => lines.push(row.map(cell => (cell ? "1" : "0")).join("\t")));
  lines.push("");
  lines.push(view.simplified_function);
  return lines.join("\n");
}

$("tt-copy-rich").addEventListener("click", async () => {
  const btn = $("tt-copy-rich");
  if (!lastTtView) return; // no result to copy -- shouldn't be reachable, #tt-result is hidden
  const view = lastTtView;
  const plainText = buildTtRichPlainText(view);

  let copiedRich = false;
  if (window.ClipboardItem && navigator.clipboard && navigator.clipboard.write) {
    try {
      const html = buildTtRichHtml(view);
      const item = new ClipboardItem({
        "text/html": new Blob([html], { type: "text/html" }),
        "text/plain": new Blob([plainText], { type: "text/plain" }),
      });
      await navigator.clipboard.write([item]);
      copiedRich = true;
    } catch (e) {
      // ClipboardItem/write unsupported, permission denied, insecure
      // context, etc. -- fall through to the plain-text-only defensive
      // chain below rather than leaving an uncaught rejection.
    }
  }

  if (copiedRich) {
    showCopiedFeedback(btn);
  } else {
    await copyText(plainText, btn); // same writeText -> execCommand -> prompt -> visible-fallback chain as every other copy button
  }
});

function resetTtForm() {
  // Clears this tab's own problem data only -- the format/columns radios
  // are a workflow preference (like synth-mode below), not per-problem
  // data, so they're deliberately left alone.
  $("tt-expr").value = "";
  $("tt-cols-input").value = "";
  clearTtOutputDisplay();
  $("tt-expr").focus();
}
$("tt-new-problem").addEventListener("click", resetTtForm);

// --- Schematic rendering (D17 Phase B) ---------------------------------------------
//
// Every model-declared electrical anchor (a device's own gate/source/drain
// points) and every WireSegment/Junction point is copied verbatim from the
// `schematic` view the server sends (presenter.build_schematic_view) -- same
// integer grid units as `schematic.CELL`, no transform, no re-derivation.
// The one thing NOT copied 1:1 is a transistor's own glyph geometry: the
// model gives three anchor points per device (gate/source/drain), not
// pixel-level symbol art, so the channel/gate-electrode/gate-bubble strokes
// that make a device *look* like a MOSFET are a fixed, deterministic
// template positioned from those three anchors -- tested directly (the gate
// path never touches the channel, PMOS-only bubble, label text), not just
// asserted from the code. The SVG viewBox margin is the only other invented
// number, and it's pure display padding that never touches a drawn
// coordinate.
//
// Built entirely via createElementNS/textContent/setAttribute, never
// innerHTML (D17 point 7) -- the same rule M1.3's HTML table follows. All
// presentational (stroke/fill) rules live in one embedded <style>
// (SCHEMATIC_SVG_STYLE_CSS), injected as part of the SVG subtree itself, so
// the exact same representation renders whether the SVG is inline on this
// page or opened standalone from a downloaded file -- there is no second,
// separately-maintained export renderer or stylesheet.

const SVG_NS = "http://www.w3.org/2000/svg";

const SCHEMATIC_SVG_STYLE_CSS = `
  .ow-wire { stroke: currentColor; stroke-width: 2.5; fill: none; }
  .ow-wire.ow-rail { stroke-width: 4; }
  .ow-channel { stroke: currentColor; stroke-width: 4; fill: none; stroke-linecap: round; }
  .ow-gate-electrode { stroke: currentColor; stroke-width: 3; fill: none; }
  .ow-gate-connector { stroke: currentColor; stroke-width: 2.5; fill: none; }
  .ow-gate-bubble { fill: Canvas; stroke: currentColor; stroke-width: 2; }
  .ow-junction-dot { fill: currentColor; stroke: none; }
  .ow-terminal-anchor { fill: transparent; stroke: none; }
  .ow-device-lead, .ow-supply-symbol { stroke: currentColor; stroke-width: 2.5; fill: none; }
  .ow-text { fill: currentColor; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
  .ow-port-label { font-size: 26px; }
  .ow-section-label { opacity: .6; }
  .ow-network-bracket { stroke: currentColor; stroke-width: 1.5; stroke-dasharray: 5 4; opacity: .45; fill: none; }
  .ow-net-label { font-weight: 700; }
`;

function svgEl(tag, attrs) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const k in attrs) el.setAttribute(k, attrs[k]);
  return el;
}

// Picks a deterministic anchor point (from the net's own already-modeled
// wire endpoints and device terminals -- never an invented coordinate) to
// place that net's label text near. `pick` only chooses which extremal
// among those real points to use ("min-y" for a rail drawn at the top,
// "max-y" for one drawn at the bottom); it never changes what the label
// says (always `net.label`, straight off the model).
function schematicNetAnchor(view, netId, pick) {
  const points = [];
  view.wires.forEach(w => { if (w.net_id === netId) { points.push(w.p1); points.push(w.p2); } });
  view.devices.forEach(d => {
    if (d.gate_net === netId) points.push(d.gate_point);
    if (d.source_net === netId) points.push(d.source_point);
    if (d.drain_net === netId) points.push(d.drain_point);
  });
  if (points.length === 0) return null;
  // Extremal y (top for a top rail, bottom for a bottom rail); ties broken
  // toward the rightmost point, which keeps the label clear of the
  // PUN/PDN section labels and gate-rail labels living in the left margin
  // and core columns -- still just picking among real modeled points.
  const sign = pick === "max-y" ? -1 : 1;
  return points.reduce((best, p) => (sign * (best.y - p.y) > 0 || (best.y === p.y && best.x < p.x)) ? p : best);
}

// Fixed MOSFET-symbol template constants (display geometry, not model
// data). GATE_GAP is the horizontal distance from the channel to the gate
// electrode -- the thing that must be > 0 for the gate to read as
// insulated, never touching the channel it controls.
const GATE_GAP = 16;
const GATE_PLATE_HALF_H = 18;
const GATE_BUBBLE_R = 6;

// One device's fixed-template MOSFET symbol, anchored purely by that
// device's own already-validated gate/source/drain points. A standard
// three-part glyph -- source-drain channel, a separate gate electrode, and
// a connector from that electrode out to the model's own gate_point -- with
// a PMOS-only inversion bubble (D17 point 3), never a logic-gate shape.
// The electrode is offset GATE_GAP away from the channel's own x, so the
// gate path (electrode + connector) never shares a point with the channel:
// an insulated gate, not a gate/channel short.
function schematicDeviceSymbol(d, textbook = false) {
  const g = svgEl("g", {
    class: "ow-device", "data-role": "device",
    "data-device-id": d.id,
    "data-kind": d.kind,
    "data-device-role": d.role,
    "data-gate-var": d.gate_var,
    "data-gate-complemented": String(d.gate_complemented),
  });

  // The model guarantees source_point.x === drain_point.x for every device
  // (Phase A's _expected_device_points) -- read directly, not re-derived.
  const channelX = d.source_point.x - (textbook ? 16 : 0);
  const gateY = d.gate_point.y; // === the channel's own vertical midpoint, by the same guarantee
  const plateX = channelX + (textbook ? -GATE_GAP : GATE_GAP);
  const topY = textbook ? gateY - 28 : d.source_point.y;
  const bottomY = textbook ? gateY + 28 : d.drain_point.y;

  g.appendChild(svgEl("line", {
    class: "ow-channel", "data-role": "channel",
    x1: channelX, y1: topY, x2: channelX, y2: bottomY,
  }));
  if (textbook) {
    ["source", "drain"].forEach(term => {
      const p = d[term + "_point"];
      const shoulderY = p.y < gateY ? topY : bottomY;
      g.appendChild(svgEl("polyline", {
        class: "ow-device-lead", "data-role": term + "-lead",
        points: `${p.x},${p.y} ${p.x},${shoulderY} ${channelX},${shoulderY}`,
      }));
    });
  }
  g.appendChild(svgEl("line", {
    class: "ow-gate-electrode", "data-role": "gate-electrode",
    x1: plateX, y1: gateY - GATE_PLATE_HALF_H, x2: plateX, y2: gateY + GATE_PLATE_HALF_H,
  }));
  g.appendChild(svgEl("line", {
    class: "ow-gate-connector", "data-role": "gate-connector",
    x1: plateX, y1: gateY, x2: d.gate_point.x, y2: d.gate_point.y,
  }));

  if (d.kind === "p") {
    g.appendChild(svgEl("circle", {
      class: "ow-gate-bubble", "data-role": "gate-bubble",
      cx: plateX + (textbook ? -1 : 1) * (GATE_BUBBLE_R + 2), cy: gateY, r: GATE_BUBBLE_R,
    }));
  }

  ["gate", "source", "drain"].forEach(term => {
    const p = d[term + "_point"];
    g.appendChild(svgEl("circle", {
      class: "ow-terminal-anchor", "data-role": "terminal", "data-terminal": term,
      "data-device-id": d.id, "data-net-id": d[term + "_net"],
      cx: p.x, cy: p.y, r: 3,
    }));
  });

  const label = svgEl("text", {
    class: "ow-device-label ow-text", "data-role": "device-label",
    x: d.gate_point.x + 6, y: d.gate_point.y - 6, "font-size": 26,
  });
  if (!textbook) { label.textContent = d.literal; g.appendChild(label); }

  return g;
}

// A hidden (display:none) but fully queryable per-net inventory: one
// <g data-role="net"> per net the model declares, straight off `view.nets`.
// Net *presence* isn't reliably recoverable from scattered data-net-id
// attributes on wires/terminals alone -- a net touched by exactly one
// device and no bus wire (e.g. a single-PMOS VDD with nothing to bus)
// never appears on any wire element -- so this is the one stable place
// "every model net appears, exactly once" is checkable directly.
function schematicNetInventory(view) {
  const inventory = svgEl("g", { "data-role": "net-inventory", style: "display:none" });
  view.nets.forEach(n => {
    inventory.appendChild(svgEl("g", {
      "data-role": "net", "data-net-id": n.id, "data-net-kind": n.kind, "data-net-label": n.label,
    }));
  });
  return inventory;
}

// Below this width (model content + margins, in model/viewBox units), a
// circuit renders at MIN_DISPLAY_WIDTH regardless -- otherwise a 1-2
// transistor circuit would render illegibly tiny. Above it, the SVG is
// rendered at a fixed PIXELS_PER_UNIT scale (not shrunk to fit the
// viewport), so a transistor symbol's on-screen size -- and label legibility
// -- stays constant no matter how wide the circuit is; .schematic-wrap
// scrolls horizontally instead of the labels shrinking to fit.
const PIXELS_PER_UNIT = 0.55;
const MIN_DISPLAY_WIDTH = 320;

let lastSchematicView = null;

function renderTextbookSchematic(svg, view) {
  const w = view.width * view.cell;
  const h = view.height * view.cell;
  const annotationWidth = 280;
  svg.setAttribute("viewBox", `${-annotationWidth} 0 ${w + annotationWidth} ${h}`);
  svg.setAttribute("aria-label", `Transistor-level schematic: ${view.total_transistors} transistors. Matching gate labels denote the same electrical net.`);
  const displayWidth = Math.max(MIN_DISPLAY_WIDTH, Math.round((w + annotationWidth) * PIXELS_PER_UNIT));
  svg.style.width = `${displayWidth}px`;
  // A standalone SVG without an explicit height can inherit the browser
  // viewport's height and shrink its contents to fit. Carry both dimensions
  // into Download SVG so device/label scale is identical inside and outside
  // the app, including diagrams taller than the viewport.
  svg.style.height = `${displayWidth * h / (w + annotationWidth)}px`;
  const netById = Object.fromEntries(view.nets.map(n => [n.id, n]));
  function label(text, x, y, attrs = {}) {
    const el = svgEl("text", {class: "ow-text", x, y, "font-size": 26, ...attrs});
    el.textContent = text;
    svg.appendChild(el);
    return el;
  }
  view.wires.forEach(w => svg.appendChild(svgEl("line", {
    class: "ow-wire" + (["VDD", "GND"].includes(w.net_id) ? " ow-rail" : ""),
    "data-role": "wire", "data-wire-id": w.id, "data-net-id": w.net_id,
    x1: w.p1.x, y1: w.p1.y, x2: w.p2.x, y2: w.p2.y,
  })));
  view.devices.forEach(d => svg.appendChild(schematicDeviceSymbol(d, true)));
  view.junctions.forEach(j => svg.appendChild(svgEl("circle", {
    class: "ow-junction-dot", "data-role": "junction", "data-junction-id": j.id,
    "data-net-id": j.net_id, cx: j.point.x, cy: j.point.y, r: 5,
  })));
  view.ports.forEach(p => {
    const g = svgEl("g", {"data-role": "port", "data-port-id": p.id, "data-net-id": p.net_id,
      "data-device-id": p.device_id, "data-terminal": p.terminal, "data-label": p.label,
      "data-x": p.point.x, "data-y": p.point.y});
    const t = svgEl("text", {class: "ow-text ow-port-label", "data-role": "port-label",
      x: p.point.x + (p.terminal === "gate" ? -9 : 9), y: p.point.y + 8,
      "text-anchor": p.terminal === "gate" ? "end" : "start"});
    t.textContent = p.label;
    g.appendChild(t);
    svg.appendChild(g);
  });
  view.boundaries.forEach(b => {
    const {x, y} = b.point;
    const g = svgEl("g", {"data-role": "boundary", "data-boundary-id": b.id, "data-net-id": b.net_id});
    if (b.net_id !== "OUT") {
      const bars = b.net_id === "VDD" ? [[-22, 22, 0]] : [[-24,24,0],[-16,16,9],[-7,7,18]];
      bars.forEach(([a,c,dy]) => g.appendChild(svgEl("line", {class: "ow-supply-symbol",
        "data-role": "supply-symbol", x1:x+a,y1:y+dy,x2:x+c,y2:y+dy})));
    } else {
      g.appendChild(svgEl("circle", {class:"ow-junction-dot","data-role":"output-endpoint",cx:x,cy:y,r:4}));
    }
    svg.appendChild(g);
    label(netById[b.net_id].label, x + (b.net_id === "OUT" ? 14 : 0),
      y + (b.net_id === "VDD" ? -18 : b.net_id === "GND" ? 52 : 8),
      {"data-role":"net-label","data-net-id":b.net_id,"font-weight":700,
       "text-anchor": b.net_id === "OUT" ? "start" : "middle"});
  });
  const core = view.devices.filter(d => d.role !== "inverter");
  const top = Math.min(...core.map(d => Math.min(d.source_point.y,d.drain_point.y)));
  // Annotations sit beside their own network, clear of its gate labels.
  // Their extents follow all device symbols belonging to the network role.
  for (const [role, type, description] of [["pun", "PMOS", "pull-up network"], ["pdn", "NMOS", "pull-down network"]]) {
    const members = core.filter(d => d.role === role);
    const first = Math.min(...members.map(d => d.gate_point.y - 28));
    const last = Math.max(...members.map(d => d.gate_point.y + 28));
    const middle = (first + last) / 2;
    const ids = new Set(members.map(d=>d.id));
    const bracketX = Math.min(...view.ports.filter(p=>p.terminal === "gate" && ids.has(p.device_id))
      .map(p=>p.point.x)) - 90;
    const group = svgEl("g", {"data-role":"network-annotation","data-network":role,
      "data-device-ids":members.map(d=>d.id).join(" ")});
    group.appendChild(svgEl("polyline", {class:"ow-network-bracket", "data-role":"network-bracket",
      points:`${bracketX+15},${first} ${bracketX},${first} ${bracketX},${last} ${bracketX+15},${last}`}));
    for (const [text, y] of [[type, middle - 8], [description, middle + 18]]) {
      const caption = svgEl("text", {class:"ow-text", "data-role":"network-caption",
        x:bracketX-25, y, "font-size":20, "text-anchor":"end", opacity:.7});
      caption.textContent = text;
      group.appendChild(caption);
    }
    svg.appendChild(group);
  }
  const inverters = view.devices.filter(d => d.role === "inverter" && d.kind === "p");
  inverters.forEach(d => label(`Shared ${d.gate_var} → ${d.gate_var}'`, d.source_point.x - 95, top - 75, {"font-size":22}));
  const external = view.nets.filter(n => n.kind === "gate_complement_external");
  if (external.length) {
    label(`External complements: ${external.map(n=>n.label).join(", ")}`,
      35, h - 24, {"font-size":20,"opacity":.7});
  } else {
    label("Matching gate labels", 35, h - 46, {"font-size":20,"opacity":.7});
    label("denote the same net.", 35, h - 24, {"font-size":20,"opacity":.7});
  }
}

function renderSchematic(view) {
  const svg = $("schematic-svg");
  clearChildren(svg);
  lastSchematicView = view;
  if (!view) return;

  const styleEl = svgEl("style", {});
  styleEl.textContent = SCHEMATIC_SVG_STYLE_CSS;
  svg.appendChild(styleEl);
  svg.appendChild(schematicNetInventory(view));
  if (view.style === "textbook") { renderTextbookSchematic(svg, view); return; }
  svg.style.height = "auto";

  // Top/bottom margins are taller than left/right -- purely to give the
  // PUN/PDN section title and the VDD/GND rail label two clearly separate
  // vertical bands (title further out, rail label hugging the rail),
  // rather than relying on horizontal spacing that a narrow circuit's own
  // geometry can't guarantee. This is display padding only -- it doesn't
  // touch any drawn coordinate, which all still come straight from `view`.
  const sideMargin = view.cell / 2;
  const vMargin = view.cell * 1.3;
  const contentW = view.width * view.cell;
  const contentH = view.height * view.cell;
  const w = contentW + sideMargin * 2;
  const h = contentH + vMargin * 2;
  svg.setAttribute("viewBox", `${-sideMargin} ${-vMargin} ${w} ${h}`);
  svg.setAttribute("aria-label", `Transistor-level schematic: ${view.total_transistors} transistors`);
  svg.style.width = `${Math.max(MIN_DISPLAY_WIDTH, Math.round(w * PIXELS_PER_UNIT))}px`;

  const netById = {};
  view.nets.forEach(n => { netById[n.id] = n; });

  view.wires.forEach(wire => {
    const net = netById[wire.net_id];
    const isRail = net && (net.kind === "rail_vdd" || net.kind === "rail_gnd");
    svg.appendChild(svgEl("line", {
      class: "ow-wire" + (isRail ? " ow-rail" : ""),
      "data-role": "wire", "data-wire-id": wire.id, "data-net-id": wire.net_id,
      x1: wire.p1.x, y1: wire.p1.y, x2: wire.p2.x, y2: wire.p2.y,
    }));
  });

  view.devices.forEach(d => svg.appendChild(schematicDeviceSymbol(d)));

  view.junctions.forEach(j => {
    svg.appendChild(svgEl("circle", {
      class: "ow-junction-dot", "data-role": "junction", "data-junction-id": j.id, "data-net-id": j.net_id,
      cx: j.point.x, cy: j.point.y, r: 5,
    }));
  });

  // VDD/GND labels sit close to their own rail (a narrow band right above/
  // below it), ending at the rail's own rightmost touch point (text-anchor
  // "end") so they never run past the right edge of the viewBox. OUT sits
  // right at the PUN/PDN seam, so its label is offset sideways from that
  // point instead of vertically, to stay clear of the device row right
  // above/below it.
  [
    [view.vdd_net_id, "min-y", 0, -14, "end"],
    [view.gnd_net_id, "max-y", 0, 26, "end"],
    [view.output_net_id, "min-y", 12, 8, "start"],
  ].forEach(([netId, pick, dx, dy, anchorMode]) => {
    const net = netById[netId];
    const anchor = net && schematicNetAnchor(view, netId, pick);
    if (!net || !anchor) return;
    const t = svgEl("text", {
      class: "ow-net-label ow-text", "data-role": "net-label", "data-net-id": netId,
      x: anchor.x + dx, y: anchor.y + dy, "font-size": 28, "text-anchor": anchorMode,
    });
    t.textContent = net.label;
    svg.appendChild(t);
  });

  // PUN/PDN section titles sit further out, near the outer edge of the
  // top/bottom margin band -- clearly separated vertically from the
  // VDD/GND rail labels above regardless of how narrow the circuit is.
  const punLabel = svgEl("text", { class: "ow-section-label ow-text", x: 0, y: -vMargin + 22, "font-size": 20 });
  punLabel.textContent = "PUN (PMOS pull-up)";
  svg.appendChild(punLabel);
  const pdnLabel = svgEl("text", {
    class: "ow-section-label ow-text", x: 0, y: contentH + vMargin - 8, "font-size": 20,
  });
  pdnLabel.textContent = "PDN (NMOS pull-down)";
  svg.appendChild(pdnLabel);
}

// The clone carries its own embedded <style> (appended in renderSchematic
// above) as part of its subtree, so this produces a fully self-contained,
// correctly-styled standalone file -- the exact same representation that's
// on screen, not a separately-serialized copy that could drift.
function serializeSchematicSvg() {
  const svg = $("schematic-svg");
  const clone = svg.cloneNode(true);
  clone.setAttribute("xmlns", SVG_NS);
  return new XMLSerializer().serializeToString(clone);
}

$("download-svg-btn").addEventListener("click", () => {
  if (!lastSchematicView) return;
  const outputName = (lastSchematicView.nets.find(n => n.id === lastSchematicView.output_net_id) || {}).label || "F";
  const blob = new Blob([serializeSchematicSvg()], { type: "image/svg+xml" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `ohmwork-schematic-${outputName}.svg`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
});

let lastSpiceExports = null;
for (const kind of ["template", "example"]) {
  $("download-spice-" + kind).addEventListener("click", () => {
    const artifact = lastSpiceExports?.[kind];
    if (!artifact) return;
    const url = URL.createObjectURL(new Blob([artifact.text], {type: "text/plain;charset=utf-8"}));
    const a = document.createElement("a");
    a.href = url;
    a.download = artifact.filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
}

function closeSpiceHelp(returnFocus = false) {
  $("spice-export-help").hidden = true;
  $("spice-help-toggle").setAttribute("aria-expanded", "false");
  if (returnFocus) $("spice-help-toggle").focus();
}
$("spice-help-toggle").addEventListener("click", () => {
  if (!$("spice-export-help").hidden) { closeSpiceHelp(true); return; }
  $("spice-export-help").hidden = false;
  $("spice-help-toggle").setAttribute("aria-expanded", "true");
});
$("spice-help-close").addEventListener("click", () => closeSpiceHelp(true));
for (const id of ["spice-help-toggle", "spice-export-help"]) {
  $(id).addEventListener("keydown", e => {
    if (e.key === "Escape") { e.preventDefault(); closeSpiceHelp(true); }
  });
}

// --- Synth result rendering ------------------------------------------------------

let lastSolutionText = "";
let lastAdvancedText = "";

let synthKmapDiagram = null;
let synthKmapReport = "";
function renderSynthResult(view, rawOutput, schematic, kmap, spice) {
  lastSpiceExports = spice;
  $("download-spice-template").disabled = !spice?.template;
  $("download-spice-example").disabled = !spice?.example;
  closeSpiceHelp();
  $("spice-help-toggle").hidden = !spice;
  clearChildren($("synth-km-stage"));
  clearChildren($("synth-km-groups"));
  synthKmapReport = kmap.output;
  $("synth-km-selection-reason").textContent = kmap.selection_reason;
  $("synth-km-connection").textContent = kmap.connection;
  $("synth-km-equation").textContent = kmap.view.output_name + " = " + kmap.view.expression;
  $("synth-km-pdn").textContent = kmap.pdn;
  $("synth-km-assignments").textContent = kmap.assignments;
  synthKmapDiagram = renderKmap(kmap.view, $("synth-km-stage"), $("synth-km-groups"),
    text => $("synth-km-selection").textContent = text);
  renderSchematic(schematic);
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
  lastSolutionText += "\n\nK-map for this circuit:\n" + synthKmapReport;
  lastAdvancedText = rawOutput;
}

// Same request-token pattern as tt's above -- see the comment there.
let synthRequestToken = 0;

$("panel-synth").addEventListener("submit", async (e) => {
  e.preventDefault();
  clearSynthResultDisplay();
  const myToken = ++synthRequestToken;
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
  if (myToken !== synthRequestToken) return; // superseded while this request was in flight
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
  renderSynthResult(result.result, result.output, result.schematic, result.kmap, result.spice);
});

$("synth-km-show-all").addEventListener("click",()=>synthKmapDiagram?.reset());
$("synth-km-download").addEventListener("click",()=>{
  if(!synthKmapDiagram) return;
  const clone=synthKmapDiagram.svg.cloneNode(true);
  const url=URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(clone)],{type:"image/svg+xml;charset=utf-8"}));
  const a=document.createElement("a");a.href=url;a.download="ohmwork-synthesis-kmap.svg";a.click();
  setTimeout(()=>URL.revokeObjectURL(url),1000);
});
$("synth-km-copy").addEventListener("click",async()=>{
  const text=synthKmapReport, token=synthRequestToken;
  if(!text) return;
  try {
    if(!navigator.clipboard?.writeText) throw new Error("clipboard unavailable");
    await navigator.clipboard.writeText(text);
    if(token===synthRequestToken) $("synth-km-copy").textContent="Copied!";
  } catch (_) {
    if(token===synthRequestToken) showCopyFallback($("synth-km-copy"),text);
  }
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
  synthRequestToken++; // invalidate any in-flight /api/synth request
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

  const staleSvg = $("schematic-svg");
  clearChildren(staleSvg); // same discipline -- clear, don't just hide, the stale SVG
  staleSvg.removeAttribute("style"); // drop the previous render's content-driven width too
  staleSvg.removeAttribute("viewBox");
  staleSvg.removeAttribute("aria-label");
  lastSchematicView = null;
  lastSpiceExports = null;
  $("download-spice-template").disabled = true;
  $("download-spice-example").disabled = true;
  closeSpiceHelp();
  $("spice-help-toggle").hidden = true;
  synthKmapDiagram = null;
  synthKmapReport = "";
  ["synth-km-stage","synth-km-groups","synth-km-selection-reason","synth-km-connection","synth-km-equation",
   "synth-km-pdn","synth-km-selection","synth-km-assignments"].forEach(id=>clearChildren($(id)));
  $("synth-km-copy").textContent = "Copy K-map explanation";

  lastSolutionText = "";
  lastAdvancedText = "";
}

[
  "synth-expr", "synth-ones", "synth-dc", "synth-table", "synth-output-name", "synth-max-stack",
].forEach(id => $(id).addEventListener("input", clearSynthResultDisplay));
$("synth-dual-rail").addEventListener("change", clearSynthResultDisplay);
document.querySelectorAll("input[name=synth-mode]").forEach(r => r.addEventListener("change", clearSynthResultDisplay));
document.querySelectorAll("input[name=synth-table-mode]").forEach(r => r.addEventListener("change", clearSynthResultDisplay));
// Opening/closing manual entry changes which fields the next submit will
// actually read (see the `manualOpen` branch above) -- that's a material
// input-mode change exactly like synth-mode/synth-table-mode, so it must
// invalidate a shown result the same way.
$("synth-manual-details").addEventListener("toggle", clearSynthResultDisplay);

function resetSynthForm() {
  // The chosen synth-mode (From expression / From truth table), whether
  // manual entry is open, and its Minterms/Bit string selection are all
  // workflow choices, not per-problem data -- a student working through
  // several questions of the same type shouldn't have to reselect any of
  // them every time. Everything else here is problem-specific and gets
  // cleared, including the manual-entry fields' actual values.
  const mode = checkedValue("synth-mode");

  $("synth-expr").value = "";
  $("synth-vars").value = "";
  $("synth-ones").value = "";
  $("synth-dc").value = "";
  $("synth-table").value = "";
  $("synth-output-name").value = "";
  $("synth-dual-rail").checked = false;
  $("synth-max-stack").value = "";

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
  removeCopyFallbackFor(btn); // this button's own stale fallback, if any -- never another button's
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

function showCopiedFeedback(btn) {
  const original = btn.textContent;
  btn.textContent = "Copied!";
  btn.classList.add("copied");
  setTimeout(() => { btn.textContent = original; btn.classList.remove("copied"); }, 1500);
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

  showCopiedFeedback(btn);
}

$("copy-solution").addEventListener("click", () => copyText(lastSolutionText, $("copy-solution")));
$("copy-advanced").addEventListener("click", () => copyText(lastAdvancedText, $("copy-advanced")));
</script>
</body>
</html>
"""


# Embed the isolated K-map assets into the same page/script scope. No new
# transport or asset route; the existing tab handler sees the new tab.
_PAGE = (_PAGE.replace('</style>', KMAP_CSS + '</style>', 1)
         .replace('<button type="button" class="tab" data-tab="synth">',
                  '<button type="button" class="tab" data-tab="kmap">K-map</button>\n'
                  '<button type="button" class="tab" data-tab="synth">', 1)
         .replace('<script>', KMAP_HTML + '\n<script>', 1)
         .replace('</script>', KMAP_JS + '\n</script>', 1))


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
        # M1.3: derived exactly once here -- both the legacy text
        # (`output`, unchanged) and the new structured table view
        # (`result`) are built from this same DerivationResult, never two
        # independent derivations that could theoretically disagree (the
        # same guarantee M1.2 already gives synth -- see _handle_synth).
        derivation = derive_from_input(expression, terse=bool(body.get("terse")), cols=cols)
    except (ParseError, ValueError) as e:
        return _json_response(start_response, "200 OK", {"ok": False, "error": str(e)})
    output = format_tt_report(derivation, md=bool(body.get("md")), latex=bool(body.get("latex")))
    view = build_tt_view(derivation)
    csv_output = format_tt_report(derivation, csv=True)
    return _json_response(start_response, "200 OK", {"ok": True, "output": output, "result": view, "csv": csv_output})


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

    try:
        output = format_synth_report(result, result.verification)
        view = build_synth_view(result, output_name=output_name, max_stack_applied=max_stack is not None)
        # Same already-verified `result` feeds the schematic layout model too
        # (D17 Phase B) -- build_textbook_schematic() runs all four correctness
        # gates before returning, so `layout` here is exactly the model the
        # frontend must render faithfully, never re-derived from `view`.
        layout = build_textbook_schematic(result, output_name)
        schematic = build_schematic_view(layout)
        spice = build_spice_exports(layout)
        model = build_synthesis_kmap(result, output_name)
        kmap_view = build_kmap_view(model)
        connection = (
            f"Group the 0s of {output_name}. Their products give {output_name}'; "
            f"complementing gives the POS for {output_name}."
            if model.form == "POS" else
            f"Group the 1s of {output_name} to obtain its SOP. Complementing this SOP "
            f"with De Morgan's law gives {output_name}' for the PDN."
        )
        connection += " These are the groups chosen for this circuit, not a new minimization."
        pdn = (f"PDN: {output_name}' = ({render(model.expression)})' = {render(result.chosen.f_prime)}. "
               f"The NMOS network conducts when {output_name}' is 1.")
        xs = [f"m{c.minterm} → {c.assigned_value}" for c in sorted(model.cells, key=lambda c:c.minterm) if c.value == "X"]
        assignments = "Original X cells retained; circuit assignments: " + "; ".join(xs) if xs else ""
        selection_reason = view["reasoning"]["kmap_selection_note"]
        kmap = {"selection_reason": selection_reason, "view": kmap_view, "connection": connection, "pdn": pdn, "assignments": assignments,
                "output": selection_reason + "\n" + connection + "\n" + pdn + "\n" + format_kmap_report(model)}
    except (ParseError, ValueError, RuntimeError) as e:
        return _json_response(start_response, "200 OK", {"ok": False, "error": str(e)})
    return _json_response(
        start_response, "200 OK", {"ok": True, "output": output, "result": view, "schematic": schematic, "kmap": kmap, "spice": spice}
    )


def _handle_kmap(environ, start_response):
    body = _read_json_body(environ)
    try:
        if not isinstance(body, dict):
            raise ValueError('request body must be a JSON object')
        keys = ('expr', 'variables', 'ones', 'dc', 'table', 'form', 'output_name')
        if any(key in body and not isinstance(body[key], str) for key in keys):
            raise ValueError('K-map input fields must be strings')
        result = kmap_from_input(**{key:body[key] for key in keys if key in body})
        view = build_kmap_view(result)
        output = format_kmap_report(result)
    except (ParseError, ValueError, RuntimeError) as exc:
        return _json_response(start_response, '200 OK', {'ok':False, 'error':str(exc)})
    return _json_response(start_response, '200 OK', {'ok':True, 'result':view, 'output':output})


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
    ("POST", "/api/kmap"): _handle_kmap,
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
