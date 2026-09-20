# K-map explanation readability follow-up

Owner dogfooding found that an expanded proof in a three-column group-card grid
squeezed the reason column into broken word fragments. An open group now spans
the full grid width; the Boolean reference also has its own full row. Desktop
tables use a fixed 58/42 expression/reason split and ordinary word wrapping.
At 600px and below each row stacks its expression above its explanation while
retaining the underlying table headings. Closing the proof restores the cards.

The worked-expression formatter parenthesizes AND operands within OR, as well
as the already-required OR operands within AND. Each minterm in an SOP expansion
is visibly enclosed, consistently in the table, preview, copy/CLI and SVG legend.
The Boolean AST, group membership, reduction steps and verification are unchanged.

New browser regressions use the actual three-group, four-variable coursework
case at 1280px and 360px. They check open-card width, readable reason-column width
and height, ordinary wrapping, stacked mobile order, no document overflow,
parenthesized expansion, closing behavior, and preserved highlighting. CI images
are readable-steps-1280.png and readable-steps-360.png under kmaps/. The exact
four-variable m0+m2 expansion is additionally pinned in a unit test.

This is a presentation correction to PR #7, not Phase 3 synthesis integration.
