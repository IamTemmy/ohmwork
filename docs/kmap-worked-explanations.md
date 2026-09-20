# Worked K-map explanations review

Follow-up to Phase 2, requested and approved during coursework testing. Phase 3
synthesis integration is not part of this change.

`kmap_steps.py` expands the actual group into minterms for SOP or maxterms for
POS, then eliminates changing variables from last to first. Each pair uses
explicit distributive, complement and identity steps. Intermediate ASTs are
checked on every input against group cell membership (its complement for POS),
and the final function must match the existing chosen group term. No minimizer
or group selection change. Explicit multiplication avoids ambiguity with digit
suffixed variable names. Included X cells are marked as selected assignments.

`kmap_view.py` exposes the verified steps. SVG legends now include Group N (GN),
cell notation, expanded Boolean terms, simplified term, and wrap/DC notes, with
height calculated from wrapped lines. `kmap_ui.py` adds expandable per-group
expression/law tables and a Boolean reference; controls remain outside buttons.
SVG download includes the expanded legend; full tables are in the UI and copy /
CLI report. Existing hover/select behavior stays intact. New Problem empties all
new sections as well as the original diagram.

Review both SOP and POS, singleton/full-map cases, don't-cares and long variable
names. Unit coverage enumerates all 1–4 variable cubes in both forms and rejects
mutated terms/incomplete cubes. Existing visual/export fixtures check changed
legend bounds. Two browser regressions inspect actual step rows, law reference,
highlighting, copied explanations, expanded SVG text and reset cleanup. Their
full-page images are saved as worked-SOP.png / worked-POS.png in CI artifacts.

Use an isolated checkout and port 5758, leaving the user's 5757 server alone.
