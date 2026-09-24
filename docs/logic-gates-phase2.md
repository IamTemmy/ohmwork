# D21 Phase 2 — interactive logic circuits

PR #24 is stacked on the reviewed, unmerged Phase 1 PR #23 (`fcd58bc`).
No CMOS synthesis, K-map grouping, or SPICE export algorithm changes.

## Review map and commits

- `abdfd83`: deterministic symbols/routes, SVG snapshots, geometric bridge tests;
  input-name errors use product wording instead of `--vars`.
- `cacac98`: shared API, `logic` CLI, standalone Logic gates tab, input switches,
  verified internal signals, matching truth-table row, gate explanations, downloads.
- `5d2443c`: Chromium acceptance battery and CI artifact collection; scope SVG CSS
  to this diagram and add same-net branching dots.
- Follow-up documentation/validation commits are listed in the PR history.

The repeated core validation calls are intentional and now commented: expression
bounds must precede compiler recursion/hashing, and preset validation precedes
construction of its source AST. Final independent verification remains mandatory.

## Run locally

```sh
git fetch origin
git switch codex/logic-gates-ui
python3 -m venv .venv
./.venv/bin/pip install -e '.[dev,browser]'
./.venv/bin/playwright install chromium
./.venv/bin/pytest -q tests/test_logic_gates.py tests/test_logic_view.py tests/test_logic_interface.py
./.venv/bin/pytest -q tests/test_logic_browser.py
./.venv/bin/ohmwork ui --port 5761 --no-browser
```

Use a separate checkout if another branch has local edits. Port 5757 is the owner's
live instance; these commands deliberately use a separate port.

CLI examples:

```sh
./.venv/bin/ohmwork logic --gate XOR --vars a,b,c
./.venv/bin/ohmwork logic --expr "(abc+de)'"
./.venv/bin/ohmwork logic --expr "(abc+de)'" --svg > logic.svg
```

`logic_from_input(expr=...)` or `logic_from_input(kind='AND', variables='a,b')`
returns the Phase 1 verified model. The POST `/api/logic` route builds the same
model and returns geometry, all verified signal rows, SVG, and a text report.
It uses the existing Host/Origin/content-type/body-size guards.

## Rendering and interaction contract

- Unshared first-stage input wires align with their terminal heights.
- Gates occupy depth columns. Column gutters expand with terminal count so every
  destination terminal has its own lane. Edges that skip stages route above the
  gate field, with distinct source exit lanes. Wires never traverse gate bodies.
- Geometry retains ordered `(driver, gate, terminal)` identities and exact pin
  coordinates. Repeated drivers produce separate terminal routes. SVG data
  attributes preserve that inventory; junction dots mark actual same-net branches.
  Crossings without dots are not connections.
- Traditional distinctive gate shapes, inversion bubbles, and the extra XOR
  input curve are rendered as SVG paths. Labels identify gate kind and stable ID.
- Browser switches select a server-verified row by binary index. They never
  implement gate logic. All gate values, wire values and the highlighted row
  come from that row. Color is supplemented by numeric values.
- Native input and inspection buttons support keyboard activation. Diagram gates
  support Enter/Space. Closing an explanation or pressing Escape returns focus
  to its opener. SVG/table scrolling regions are keyboard reachable.
- Wide diagrams retain readable text through local scrolling; they are not
  squeezed to fit a phone. The page's four tabs wrap on narrow screens. Truth-table cells have explicit
  borders/padding, sticky headings, and an emphasized output column.
- Download SVG captures the current input vector, all gates/routes/values, and a
  descriptive input/output snapshot. Temporary selection and interactive roles
  are removed. It works standalone without JavaScript. CLI SVG starts at all 0s.
- The plain text report contains the complete truth table and internal columns.
- Input edits, mode/preset changes, New problem, and fresh submissions clear prior
  results and disable exports. A generation token rejects obsolete responses.

## Evidence and independent review focus

Local non-browser/non-SPICE suite: **1,024 passed**. This includes 87 core tests,
19 renderer/geometry tests, and 16 integration tests. All 15 new Chromium cases
passed in CI, including both screen sizes/themes. The existing browser suite
also runs in that job. Consult the PR for the exact final head and CI result.

The initial browser run exposed two test-harness errors: `inner_text()` was used
on SVG text (changed to `text_content()`), and full-page capture stalled on raw
SVG documents (changed to viewport capture, as in existing SVG tests). Keyboard,
clipping, and export assertions passed before those capture failures. A separate
implementation correction preserves canonical gate order after depth-based
coordinate placement, now tested across every internal signal and all 256 vectors
of `(ab+cd)(ef+gh)` in both Python and Chromium.

A deterministic 40-case nested-expression geometry sweep also found no collinear
overlap between wires driven by different signals. This supplements, rather than
replaces, the checked-in exact terminal/endpoint and no-gate-body-crossing tests.

`test_logic_browser.py` covers all eight primitives, every vector for 3-input
primitives, all 256 vectors for 8-input XNOR and a seven-gate, multilevel expression, shared/repeated connections, a direct
wire, invalid inputs, stale response rejection, keyboard/focus behavior, and
1280/390px in light/dark themes. It saves live and standalone SVG screenshots
under `test-artifacts/logic`, in the CI visual-review artifact.

Please independently review visible connectivity as well as the metadata bridge,
especially long edges, fan-out, repeated terminals, and OR-family input curves.
Confirm downloads are standalone snapshots and no styles leak into existing tabs.
Check that the professor case reads **3 ideal gates, depth 2, 32 vectors**, without
suggesting that this generic gate decomposition is the **10-transistor** CMOS
implementation shown separately by Synthesis.

Phase 3 (truth-table-to-gate synthesis) remains a separate review/implementation
step. No minimum-gate mapping, six-variable CMOS/K-map support, or multi-output
circuit synthesis is introduced here.

Screenshot review found unstyled table cells and unnecessarily close input-wire
runs in the professor example. The final presentation pass adds readable table
tracks, consistent compact buttons, centered diagrams, and aligned unshared
first-stage inputs. Browser checks assert minimum cell width and local diagram/
table scrolling at 390px. The focused 122-test core/view/interface set passed
again after this visual correction.
