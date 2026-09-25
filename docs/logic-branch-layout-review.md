# Logic layout and signal-label follow-up (PR #25)

Base: merged D21 Phase 2, main `b91d493`. Presentation only; no parser,
netlist compilation, Boolean evaluation, synthesis, or optimization changes.

## Owner request

For `xy'+x'y`, follow the clearer hand-drawn arrangement: two independently
readable product branches, small inline inverters, and repeated x/y labels.
Explain g0/g1/... in the truth table and avoid repeating F as another column.

## Implementation

- `logic_view.py` recognizes a final multi-input gate fed by independent
  multi-input branches whose terminals are primary inputs or unary NOT/BUF
  gates on primary inputs. All internal gates must have exactly one consumer.
- Each gate is still drawn once with the same canonical ID, kind, terminal
  order and driver identity. Shared internal signals use the original wired
  layout; no gate is cloned to obtain a cleaner picture.
- `input_appearances` contains repeated visual labels for primary nets.
  `inputs` remains the unique ordered input inventory used by toggles/rows;
  its coordinates refer to the first visible appearance. Every route retains
  its driver/gate/terminal identity. The SVG explicitly explains matching labels.
- Unary symbols in branch mode are 40 units tall and half the normal width.
  First-stage routes are straight; branch outputs route to the centered final gate.
- Gate expressions are derived from the verified circuit. Expanded expressions
  exceeding 80 characters fall back to a local equation referencing preceding
  gate IDs, preventing exponential shared-expression expansion.
- Table headings show ID plus expression. `table_gates` excludes the output
  driver; F remains the sole final-output column. Full canonical signal rows
  are retained for live updates and SVG snapshots. Copied reports omit the
  duplicate output column too. Singular “1 gate” wording is corrected.

## Verification

Local focused tests: 129 passed. Local non-browser/non-ngspice suite: 1,031
passed. Chromium installation locally returns a truncated archive; actual
browser execution and screenshot review therefore use the GitHub browser job.

Run:

```sh
python -m pytest -q tests/test_logic_gates.py tests/test_logic_view.py tests/test_logic_interface.py
python -m pytest -q tests/test_logic_browser.py
```

New checks cover the exact route/model inventory and endpoints (including
repeated input appearances), no wire-through-symbol geometry, SOP/POS branch
shapes, all four XOR vectors, unchanged five-gate identities, shared-inverter
fallback, descriptive table headers, single-gate column deduplication, exported
SVG appearances, and 1280/390px in light/dark themes. Existing multilevel
all-256-vector browser checks now compare the deliberately shortened table while
continuing to verify every gate's numeric signal independently.

CI screenshots: `schematic-visual-review` artifact, `logic/branches-*.png`.
Also inspect the existing professor-case snapshots since its independent
branches now use the same layout policy.

## Claude review focus

1. Repeated labels always refer to the same input; every occurrence updates.
2. Shared internal gates remain single physical symbols in the wired fallback.
3. Small inverter terminal endpoints match the transformed symbol.
4. Table and copied-report columns match the verified rows after omitting the
   final gate column; diagram gate IDs remain unchanged.
5. Open/download the expanded XOR in both themes at 1280 and 390; check text
   overlap, local scrolling, keyboard inspection and signal updates.

Leave this draft until independent review; no Phase 3 work is included.
