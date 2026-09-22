# D20 Phase 2 review handoff

Phase 1 at `cfab4fa` was independently reviewed by Claude, with conditional approval
to proceed. This branch resolves those conditions and enables five-variable
synthesis/K-maps across Python, CLI and the web UI together. Independent Phase 2
review and the owner's live `(abc+de)'` dogfood remain required before closeout.

## Review findings addressed

1. **Budget meaning:** retained separate per-invocation budgets and documented
   their composition. Synthesis has two production directions; standalone K-map
   has production plus an independent oracle. Each successful logical operation
   has at most 4,000,000 counted units across those two invocations, not 2,000,000
   total. The 20,000-item threshold is per invocation, not bytes or process RSS.
   Finite cube enumeration, input work, circuit verification and rendering are
   outside these counters. There is no public wall-clock guarantee.
2. **Validation headroom:** production success is insufficient to return a
   standalone map: the independent oracle must finish too. Its exhaustion causes
   an explicit failed build with no partial result. This is tested directly.
3. Added duplicate-cell and incorrect-eliminated-variable mutations.
4. Assert the full 153-candidate synthesis inventory: four AOI candidates at 36T,
   149 OAI candidates at 44T, unique/stably sorted, with exact D5 winner selection.
5. Document `plane=0` as a plane **index**, including the single-plane default;
   `KMap.plane_variable` determines whether a selector exists. Retained compatible
   defaults instead of introducing a second nullable representation.
6. `SearchLimitExceeded` is an expected resource outcome: CLI exits 2 with
   `search limit:`, and both HTTP endpoints return `error_kind: search_limit`
   without a result. The API docstring now distinguishes this from internal bugs.

## Presentation and behavior

Two 4×4 planes use the first declared variable as selector, rows 2–3, columns 4–5,
Gray order 00/01/11/10, and unchanged binary minterm indices. The response includes
explicit plane labels, piece planes, global group IDs and `crosses_planes`.
Server-side display coordinates are laid out side by side. The browser moves
only display positions when the containing region is narrow: axes, cells,
labels and group pieces all move using the same plane index. No Boolean grouping
or cell inventory is reconstructed in JavaScript. ResizeObserver updates the
layout on window/container changes and is disconnected when a result clears.

The page allows a wider content region while a five-variable map is visible.
At 1280px the planes fit side by side; at 390px they stack, retaining readable
120px cells inside local horizontal scrolling. SVG export retains its transforms
and explicit dimensions, so both planes survive without app JavaScript. New
five-variable exports restore all groups to full visibility; v1 selected-export
behavior is retained for existing 1–4-variable maps.

Group hover, keyboard focus, and pinned selection apply to every piece in both
planes. Group legends and proofs explain cross-plane membership. The shared
proof panel keeps the existing card arrangement, Close/Escape/focus return.
Insets are bounded, and three-character group badges fit 16-group parity maps.
CLI/copy reports label both planes and explain corresponding-position adjacency.
Both editable truth-table grids accept 32 rows; six-variable input rejects before
truth enumeration. Derivation limits and all electrical/export logic are unchanged.

## Reproduce

```bash
python3 -m venv .venv
./.venv/bin/pip install -e '.[dev,browser]'
./.venv/bin/playwright install chromium
./.venv/bin/pytest tests/test_five_variable_core.py tests/test_five_variable_interface.py -q
./.venv/bin/pytest tests/test_five_variable_browser.py -q
./.venv/bin/python tools/benchmark_five_variables.py
OHMWORK_REQUIRE_NGSPICE=1 ./.venv/bin/pytest tests/test_spice_ngspice.py -q
./.venv/bin/ohmwork synth --expr "(abc+de)'"
./.venv/bin/ohmwork kmap --expr "(abc+de)'" --form pos
./.venv/bin/ohmwork ui --port 5761
```

The system ngspice binary is mandatory in CI and optional locally. Do not start a
second instance on the owner's live port 5757. Editable installs need a pull and
server restart to load updates, not a reinstall.

## Validation trail

The local Chromium download failed (invalid/truncated archive), so no local live
browser pass is claimed. The required CI browser job runs dedicated five-variable
checks before the full existing browser regression suite. It saves full-page PNGs,
actual downloaded SVGs, and re-rendered standalone SVG screenshots under
`test-artifacts/kmaps/five-*`, uploaded as `schematic-visual-review`.

Checks cover 1280/390px in both themes for standalone and synthesis maps, exact
geometric cell coverage against the server model, clipping/page overflow,
selection in both planes, proof keyboard/focus behavior, actual SVG downloads
and standalone rendering, parity/repeated colors, cross-plane wrapping, Xs and
32-row grids. Non-browser tests cover all 243 cubes in both SOP and POS, public
input modes, CLI/SPICE output, explicit exhaustion errors and the review fixes.
The existing 70-fixture performance and 776-operating-point ngspice gates remain.

### Measured results and visual review

Initial implementation commit `62a4698` passed all seven jobs in
[run 35795438429](https://github.com/IamTemmy/ohmwork/actions/runs/35795438429):

- Python 3.10/3.11/3.12/3.13: all green; Python 3.12 reports 921 passed,
  51 skipped (optional browser/ngspice paths are exercised by their own jobs).
- Chromium: 11 new five-variable tests passed in 13.56 seconds; all 141 existing
  browser tests passed in 133.86 seconds.
- SPICE: required ngspice job green; local rerun also passed all 67 tests,
  including all 776 operating points across the existing and five-variable cases.
- Performance: 70 fixtures; slowest measured fixture 0.117747 seconds,
  peak RSS 18,904 KiB; maximum per-invocation observed work 18,349,
  peak counted items 2,699. These are measurements, not universal bounds.
- Local non-browser/non-SPICE suite: 902 passed in 47.70 seconds.

Downloaded and inspected the actual CI PNGs and exported SVG renders: wide
light-theme synthesis, narrow dark-theme standalone export, wide standalone
page, and narrow synthesis page. The exports retain both planes, labels,
cross-plane grouping and all visible memberships without app JavaScript.

Visual review identified unused card columns after the page widens. A follow-up
sets five-variable card columns from the actual group count (at most three on
desktop, two at intermediate widths, one on mobile). The existing 1–4-variable
card layout remains unchanged. Browser assertions now require the professor's
two cards to fill their row at equal widths on desktop and stack on mobile.
The PR checks are rerun on this correction; the PR description records the
final reviewed commit and run so reviewers can reproduce that exact state.
