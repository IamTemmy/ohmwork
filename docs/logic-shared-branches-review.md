# Shared signal branch layout review

Base: main `cf81bb1` (merged PR #25). Owner feedback: the four-term expression
`xy'+x'y+xy+x'y'` should be as readable as four hand-drawn product branches,
while preserving the seven-gate implementation with two shared inverters.

## Behavior

- The existing branch recognizer now permits shared primary-fed NOT/BUF gates.
  Each such gate appears once in a compact two-column bank above the branches.
- All product/sum branch gates align in one column, even when some inputs are
  direct and others inverted. Shared signals arrive through labeled appearances,
  e.g. `[g0] y'`, with the source bank defining `[g0] = y'`.
- `inputs` remains the unique input inventory. `signal_appearances` describes
  visual references to actual gate outputs, never cloned gates or new inputs.
  Every route still records the original driver, destination gate and terminal.
- Selecting the shared source highlights all its routed uses and labels. Numeric
  aliases and junction markers update from the same verified row. Downloaded
  SVG contains every source/alias and the selected input snapshot, without
  temporary selection highlighting.
- More complex shared subcircuits retain the existing wired layout. This does
  not change gate compilation, counts, Boolean semantics, optimization or D8.
- The example still has seven gates (2 NOT + 4 AND + 1 four-input OR), and F=1
  for all four input vectors. Its deliberately expanded implementation is not
  presented as a physically optimized circuit or as minimum transistor cost.

## Reproduction / tests

```sh
python -m pytest -q tests/test_logic_view.py tests/test_logic_gates.py tests/test_logic_interface.py
python -m pytest -q tests/test_logic_browser.py
```

Focused Python checks: 136 passed. Browser regression covers all four vectors,
seven unique gate symbols, shared signal values, aligned branches, keyboard
selection/Escape focus return, label highlighting, no text overlap/clipping,
390/1280 widths and both themes, and self-contained SVG export. Python geometry
checks include shared-only and mixed shared/inline inverters, POS branches,
exact route inventory, endpoints and no wire through a symbol. A separate case
ensures a shared product gate does not accidentally qualify for unary layout.

Inspect CI artifact `schematic-visual-review/logic/shared-export-*.png` for the
complete diagram. The browser keeps a local scroll viewport on narrow screens;
exports always contain the full diagram.

## Claude review focus

Confirm no shared source gets cloned, each labeled reference resolves to the
right driver, exactly one physical gate produces each shared signal, all numeric
copies update together, and tables/report counts remain seven for the owner case.
Compare the four aligned ANDs against the owner's drawing while checking source
bank/branch separation, light/dark visibility, mobile scrolling and exports.
