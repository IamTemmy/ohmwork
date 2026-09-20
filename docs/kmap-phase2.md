# D18 Phase 2 review guide

The standalone K-map tab and `ohmwork kmap` CLI now consume Phase 1's verified
model. Phase 1 was independently accepted and merged in PR #5 (`68874a1`).
Phase 2 is a separate review; synthesis integration remains Phase 3.

## Implementation

- `api.kmap_from_input`: expression or existing truth input conventions;
  cap 1–4 variables before evaluating the truth table, then build once.
- `kmap_view.py`: JSON view, explicit display rectangle coordinates, CLI/copy
  report. No selection or Boolean minimization in the presenter or JavaScript.
- `kmap_ui.py`: isolated CSS/HTML/JS embedded by webui. No asset service or new
  runtime dependency. The shared `renderKmap` function accepts a view and DOM
  containers, ready for later synthesis use without duplicating rendering.
- `/api/kmap`: existing Host/Origin/content-type/body-size protections; failures
  return no partial result. Existing API response schemas remain untouched.
- CLI adds `kmap --expr ...` / `--vars ... --ones ... --dc ...` / `--table ...`,
  `--form sop|pos`, and `--output-name`. Existing golden output is unchanged.

## Visual and interaction contract

Groups have distinct colors, stroke patterns, and G-number IDs. Original 0/1/X
values remain foreground text. Each cell lists all its group memberships;
wrapped pieces share one identity, with the wrapped edges named in the legend.
Inset outlines separate coincident group boundaries. Light fills can overlap,
but group identity is conveyed by boundaries, IDs and selection, not mixed color.

Hover, focus, or select an outline/term card to emphasize the corresponding
cells and explanation. Click pins/unpins; Escape or Show all groups resets.
SVG group controls support Space/Enter; HTML cards and truth-grid cells use
native buttons. Fixed readable SVG dimensions scroll inside the container on
narrow screens rather than shrinking cell values.

Input modes: expression, clickable binary truth grid, minterm/DC lists, bit
string. SOP/POS and output labels are explicit. Original X values, chosen X
assignments, used/unused status, constant results, and tied covers are visible.
Input edits/form changes/New Problem invalidate pending responses and empty
result DOM; New Problem preserves input mode and SOP/POS and affects no other tab.

Download SVG clones the same live SVG, including its embedded scoped styles,
legend, equation and X assignments. Current selection is preserved. Copy
explanation uses the server-formatted report; clipboard failure produces a
selectable fallback. Stale copy fallback/feedback is suppressed after editing.

## Tests and reproduction

```sh
python3 -m venv /tmp/ohmwork-kmap-ui-review
/tmp/ohmwork-kmap-ui-review/bin/pip install -e '.[dev,browser]'
/tmp/ohmwork-kmap-ui-review/bin/playwright install chromium
/tmp/ohmwork-kmap-ui-review/bin/pytest -q
/tmp/ohmwork-kmap-ui-review/bin/ohmwork ui --port 5758 --no-browser
```

Use an isolated checkout; do not interrupt the owner's live port 5757 instance.

- 22 API/CLI/presenter tests: one computation, no partial output on failure,
  input modes, cap-before-enumeration, transport guards, CLI parity and exact
  rectangle enclosure for every fully specified 3-variable function.
- 21 new Playwright tests: direct actual-SVG-rectangle enclosure of exactly each
  group's source minterms (not just data-* matches), complete group/value/member
  inventory, viewBox text containment, standalone export identity, keyboard/grid
  cycling, tab isolation, resets, stale failure and out-of-order success, errors,
  clipboard fallback, light/dark mode, and 360px scroll behavior.
- 13 visual/export fixtures: corners, both edge wraps, ordinary overlap, six
  overlapping groups at one cell, POS, one variable, constants, all-X, used/unused
  Xs, long labels, and tied covers. PNG/SVG artifacts are uploaded by browser CI.
- Existing Python and 100 browser regressions remain in the CI suite.

Please independently inspect both dense all-group and isolated-group views,
wrap semantics, group/polarity explanations, cell-to-minterm mapping, standalone
export styling, and input/result races. No phase-3 synthesis UI change is claimed.
