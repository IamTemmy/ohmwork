# Manual UI checklist (web UI)

The data layer (presenter.py, `/api/synth` JSON schema, dedup logic,
output-name validation, the grid's required bit-string format) is covered by
pytest in `tests/test_presenter.py` and `tests/test_webui.py`. A headless
Chromium smoke test (`tests/test_webui_browser.py`, needs the `browser`
extra — `pip install -e ".[dev,browser]" && playwright install chromium`)
covers the highest-value subset of actual clicking/rendering/clipboard
behavior: tab/result isolation, Q1's single combined AOI/OAI row, grid
cycling and submission, collapse behavior, error-state cleanup, full Copy
Solution/Copy Advanced Report content, the Derivation table's structured
HTML table (M1.3) across all three column modes, and its Copy formatted
output. Items below marked **(automated)** are covered there — re-checking
them by hand is optional, not required.

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

- [ ] `xy + xy'` renders as a clean HTML table (headers x, y, y', xy, xy', F) with the
      output column (F) visually distinguished, and `F = x` above it. **(automated)**
- [ ] Switching to "Custom columns" reveals the columns field; switching away hides it.
- [ ] Full breakout / Terse / Custom columns each produce the expected header set.
      **(automated)**
- [ ] A wide derivation (many columns) scrolls horizontally rather than breaking the page
      layout. **(automated: wrapper CSS, not a visual check of an actual wide table)**
- [ ] Terminal/Markdown/LaTeX (under "Export", inside the result) are copy-only formats now
      — switching them does **not** change or clear the visible table. **(automated)**
- [ ] "Copy formatted output" copies the selected format's text (verify each of the three)
      and shows "Copied!" feedback; the collapsed "Formatted output preview" reflects the
      same text after copying. **(automated: content and feedback, not the click-triggered
      "Copying…" transition itself)**

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

## New problem / stale results

- [ ] "New problem" in the Synthesis tab clears the expression, variables,
      grid, manual entry field *values*, output name, dual-rail, max
      stack, and the result/error — but keeps you on "From expression" or
      "From truth table," and preserves whether manual entry was open and
      its Minterms/Bit string selection, all as workflow choices rather
      than per-problem data. **(automated)**
- [ ] After "New problem," focus lands on the first relevant field for
      the preserved mode (`Expression` or `Variables`). **(automated)**
- [ ] "New problem" in the Derivation table tab clears the expression and
      output, and focuses `Expression`. **(automated)**
- [ ] "New problem" in one tab never touches the other tab's inputs or
      result. **(automated)**
- [ ] After a result is showing, editing the expression, variables, a
      grid cell, a manual-entry field, output name, dual-rail, or max
      stack immediately hides the old result — without re-synthesizing
      on its own. **(automated: expression and one grid cell; the rest of
      the field list shares the same code path)**
- [ ] Opening or closing "Enter the truth table manually instead" after a
      result is showing clears that result too — it changes which fields
      the next Synthesize actually reads, so it's a material input-mode
      change like From expression/From truth table. **(automated, both
      directions)**
- [ ] Editing the Derivation table's expression, or changing its columns
      mode (Full/Terse/Custom), after a result is showing clears that
      result too. Changing the Export format (Terminal/Markdown/LaTeX)
      does **not** — it no longer affects the visible table (M1.3).
      **(automated)**
- [ ] If you submit, then edit the form (or click New problem) before the
      response comes back, the eventual response must never repopulate
      the old or a stale answer — the display should reflect only your
      latest edit or the cleared state. Same for submitting twice in a
      row where the responses arrive out of order: the second submission
      always wins, regardless of network timing. Same guarantee for
      "Copy formatted output"'s own fetch — editing the form or clicking
      New problem while a copy is in flight must not write stale text to
      the clipboard. **(automated via a controllable mocked fetch, for
      Synthesis, Derivation table, and Derivation table's copy button)**

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
