# D18 Phase 1 review guide

Phase 1 supplies the verified data model. There is no new web tab, CLI command,
SVG, or synthesis response field yet. Claude reviews this phase before merge
and before Phase 2 (standalone interface) begins. Phase 3 integrates the same
model/renderer into synthesis.

## Entry points

```python
from ohmwork.kmap import build_kmap, build_synthesis_kmap, validate_kmap

model = build_kmap(['a', 'b', 'c', 'd'], {0, 2, 8, 10}, form='SOP')
# One group, four corner pieces, pattern '-0-0', term b'd'.
```

- `build_kmap`: uses existing minimal_covers/minimize; SOP groups ones, POS
  groups zeros. Standalone objective is term count, literal count, then D5.
- `build_synthesis_kmap`: reads the verified SynthesisResult and reconstructs
  the selected candidate directly. It never runs cover selection again.
- `validate_kmap`: independent cube enumeration, essentiality, exact-cover
  oracle for standalone minimality/tied covers, algebra and cell geometry.
  Raises on failure; both builders gate their result through it and check
  source identity separately before return.

SynthesisResult adds immutable minterms/dont_cares snapshots. Optional None
values preserve legacy construction and cause the adapter to reject missing
provenance rather than guess. Existing public minimizer functions, candidate
selection, report text, CLI, API schema, and schematic renderer are unchanged.
The additive `prime_implicant_patterns` helper exposes existing QM output.

## Model contract

- Immutable dataclasses: KMap, Cell, Group, VariableFact, Rectangle.
- First floor(n/2) variables on rows, remainder on columns. Shapes 1x2, 2x2,
  2x4, 4x4; reflected Gray axes; binary minterm IDs. Preserve supplied order.
- KMap's minterms/dont_cares always refer to original F. Cell.value is 0/1/X;
  assigned_value is the selected F value; group_ids include every overlapping
  group. Output names change only the display name, not cells or group IDs.
- grouped_expression is the SOP of the grouped target: F for SOP, F' for POS.
  expression is the resulting SOP/POS for F. For synthesis, synthesis_f_prime
  is the exact chosen AST and origin pins AOI/POS or OAI/SOP explicitly.
- Each group has a stable G1… ID in selected term order, a bit pattern,
  all member minterms, used don't-cares, a term of F, per-variable fixed/varying
  facts, checked explanatory text, and essential witness minterms.
- Essentiality is defined against all relevant primes, not selected groups.
- Pieces are maximal visible rectangles in row/column cell units; a wrapped
  group retains one ID. They do not prescribe pixel offsets, colors, or SVG
  paths. The later visual bridge must check actual geometric cell coverage.
- Standalone alternatives are all tied F expressions, in existing target-SOP
  D5 order; selected_alternative is 0. POS ordering therefore follows F' SOP,
  not a new lexicographic ranking of complemented F expressions. Synthesis
  exposes no independently selected alternatives.
- All-X chooses F=0 in SOP, F=1 in POS. Both have no groups; no group may consist
  solely of Xs. Whole-map target groups are supported when a required target
  exists. Original X labels are retained with their chosen F assignments.

## Verification and reproduction

```sh
python3 -m venv /tmp/ohmwork-kmap-review
/tmp/ohmwork-kmap-review/bin/pip install -e '.[dev]'
/tmp/ohmwork-kmap-review/bin/pytest tests/test_kmap.py -q
/tmp/ohmwork-kmap-review/bin/pytest -q --ignore=tests/test_webui_browser.py
```

75 new tests include:

- Exact 1–4-variable axes, ordinary groups, singletons, both edge wraps,
  four corners, overlaps, used/unused Xs, all constants, variable ordering,
  output renaming, input rejection, and hash-seed determinism.
- All 276 fully specified 1–3-variable functions in both forms (552 maps),
  all 90 ternary 1–2-variable tables in both forms (180 maps), and 160 seeded
  four-variable ternary tables in both forms (320 maps), plus their eligible
  synthesis adapters in both dual-rail modes.
- Mutation rejection for cell mapping/values, false cubes, wrong term polarity,
  fabricated narration/facts/essentiality, wrong group pieces/links/IDs,
  missing/duplicate groups, false alternatives, source substitution, unverified
  source results, and inconsistent circuit don't-care assignments.
- A concrete inverter-aware tie: F zeros {7}, X={3,4,8,12,13,14,15}. Standalone
  F' SOP is a'cd; synth chooses bcd. Adapter is tested with minimizer calls
  forbidden, preserving bcd and the circuit's X assignments.

The verifier does not trust a power-of-two cell count: it enumerates all 3^n
cubes independently, filters forbidden/opposite cells and X-only cubes, then
checks exact membership. A separate memoized set-cover search checks minimum
cost and the complete standalone tie inventory. This oracle is a verification
path only, never the production cover selector.

Review especially polarity/AST fidelity, constant cases, essentiality, complete
cube membership, and whether the structured contract is sufficient for clear
wraparound/overlap rendering. Browser assertions and visual acceptance are
still Phase 2 obligations, not claims made by this phase.
