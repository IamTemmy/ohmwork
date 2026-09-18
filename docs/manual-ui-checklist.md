# Manual UI checklist (web UI)

The data layer (presenter.py, `/api/synth` JSON schema, dedup logic,
output-name validation, the grid's required bit-string format) is covered by
pytest in `tests/test_presenter.py` and `tests/test_webui.py`. A headless
Chromium smoke test (`tests/test_webui_browser.py`, needs the `browser`
extra — `pip install -e ".[dev,browser]" && playwright install chromium`)
covers the highest-value subset of actual clicking/rendering/clipboard
behavior: tab/result isolation, Q1's single combined AOI/OAI row, grid
cycling and submission, collapse behavior, error-state cleanup, and full
Copy Solution/Copy Advanced Report content. Items below marked **(automated)**
are covered there — re-checking them by hand is optional, not required.

This checklist covers the rest: what neither structural pytest nor the one
Chromium smoke test reaches (Q2/Q3-specific cases, light/dark mode,
cross-browser and real-OS clipboard behavior, visual polish). Re-run it
whenever `webui.py`'s `_PAGE` (the frontend) changes materially.

## Setup

```bash
./.venv/bin/ohmwork ui --no-browser
```

Open the printed URL yourself, or drive it with a real browser tool.

## Derivation table tab

- [ ] `xy + xy'` renders the full breakout table and `F = x`.
- [ ] Switching format (Terminal/Markdown/LaTeX) changes the output.
- [ ] Switching to "Custom columns" reveals the columns field; switching away hides it.

## Synthesis tab — grid input

- [ ] Typing `A,B,C` in Variables builds an 8-row grid, rows in order
      `000, 001, 010, ..., 111` (variable 0 = leftmost = MSB).
- [ ] Clicking an output cell cycles `0 → 1 → X → 0`. **(automated)**
- [ ] Changing the Variables field rebuilds the grid (old clicks don't survive
      a variable-count change). **(automated)**
- [ ] Entering 0 variables shows the "enter 1-4 variables" hint, not an empty/broken grid.
- [ ] Entering 5+ variables shows the "grid supports up to 4" hint.
- [ ] Setting Q1's exact pattern (A,B,C; all rows `1` except `111` → `0`) and
      submitting gives **3-input NAND, 6 transistors**. **(automated)**

## Synthesis tab — manual entry (advanced)

- [ ] "Enter the truth table manually instead" is collapsed by default. **(automated)**
- [ ] Opening it and filling in minterms/don't-cares, or the bit-string field,
      overrides the grid (confirm by checking the result matches the manual
      input, not whatever was in the grid).

## Synthesis tab — results (student view)

For each of Q1 (`(ABC)'`), Q2 (`A,B,C,D` / `1000000000000000`), Q3 (`(ABC+D)'`):

- [ ] Answer summary shows gate name, `F = ...`, transistor count, and
      "Verified for all N input combinations."
- [ ] Q1 specifically: only **one** alternative line in Reasoning (AOI and OAI
      coincide) — not two identical `F' = ABC` entries. **(automated)**
- [ ] Q3 specifically: **two** distinct alternatives shown, with the correct
      "strictly lower... 8 vs 12" reasoning sentence.
- [ ] Reasoning's minimality line matches what's in Advanced Details' full text.
- [ ] "Advanced details" is collapsed by default; expanding it shows the
      exact legacy CLI report (candidates, schematic, D7 verification block). **(automated)**

## Output name

- [ ] Leaving it blank behaves as "F".
- [ ] Setting it to `Y` or `M`: Answer Summary's function line uses it;
      Advanced Details' report text still says `F`/`F'` (unaffected).
- [ ] Setting it to something invalid (e.g. `Out`, two digits, punctuation)
      shows a clear inline error, no partial/stale result left visible. **(automated)**
- [ ] Setting it to one of the function's own input variable names is rejected.

## Copy buttons

- [ ] "Copy solution" shows "Copied!" feedback and the copied text uses the
      chosen output name, and includes the full student-facing solution
      (CMOS implementation, reasoning, alternatives — not just the four
      summary lines). **(automated: output name + content coverage, not the
      "Copied!" visual feedback)**
- [ ] "Copy advanced report" shows "Copied!" and copies the exact legacy
      report text (always "F"/"F'", regardless of output name). **(automated:
      content coverage, not the "Copied!" visual feedback)**
- [ ] If the Clipboard API is unavailable in the test environment, confirm
      the fallback still leaves the user with usable text (execCommand,
      then a prompt, then visible selected text) rather than a silent
      failure or an uncaught console error.

## Cross-cutting

- [ ] Light and dark mode (OS/browser preference) both render legibly —
      check the answer-summary card, the truth-table grid, and Advanced
      Details' `<pre>` block specifically.
- [ ] Tab switching (Derivation table / Synthesis) preserves each panel's
      own state independently, and a result from one tab never shows while
      the other tab is active. **(automated)**
- [ ] No uncaught console errors at any point in the above. **(automated for
      every scenario the Chromium smoke test exercises — the `page` fixture
      itself fails a test on any uncaught JS exception; light/dark mode and
      anything manual-only above is still uncovered)**
