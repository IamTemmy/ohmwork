# D18 Phase 3: K-map in the synthesis report

The synthesis UI now shows the same verified K-map renderer used in the standalone
tab, with aligned group cards and a shared explanation panel. It appears after
the schematic. Each instance has its own diagram, group selection and disclosure
IDs; building or clearing synthesis leaves an existing standalone map alone.

## Source and polarity

One synthesize_from_input call feeds the existing report, presenter, schematic,
and build_synthesis_kmap. The adapter already checks exact chosen AST reconstruction,
input provenance, and the circuit's chosen don't-care assignments. Integration
never invokes standalone cover selection. AOI groups original F zeros and presents
POS for F; OAI reconstructs the chosen SOP for F from its complemented expression.
The page and SVG explicitly show the complementation step to the actual PDN F'.
Original X cells remain X; their selected circuit assignments are reported.

The /api/synth response adds kmap (view, connection, pdn, assignments, output).
The original output string and all CLI golden output remain unchanged.
Copy solution includes the K-map explanation; Copy advanced report stays unchanged.
Download K-map SVG clones the live map, including selection and the PDN equation.
Copy K-map explanation uses server-formatted text, with a fallback and token-gated
feedback if clipboard access fails. No second fetch or frontend algebra is involved.

A new submission clears previous synthesis content. Input edits and New Problem
invalidate pending responses and remove map, cards, proof panel and copy fallback.
A failed map/provenance build returns an error without partial result fields.

## Independent review

Run the full suite, including the Chromium tests. Tests exercise:
- Exact server view against the verified adapter and one synthesis call, while
  K-map cover-selection entry points are monkeypatched to raise.
- AOI, OAI, shared inverters, dual rail, custom names, and the inverter-cost tie
  where chosen bcd differs from standalone a'cd; unchanged legacy report text.
- Atomic failure when the synthesis adapter rejects provenance.
- Actual SVG geometric bridge for NAND3, NOR4, AOI31, OAI22, shared-inverter AOI21
  and AND; worked steps, clipboard and byte-identical live-DOM download.
- Coexisting standalone/synthesis maps, independent proof panels and unique IDs,
  narrow viewports, input/New Problem cleanup, delayed responses after edits.

Browser artifacts include synthesis-*.png alongside existing K-map fixtures.
Use a port other than 5757 for manual review, leaving the user's live instance alone.

This PR implements Phase 3 under the owner's authorization. Independent Claude
review and merge remain separate from implementation.

## Review corrections

- Validate the displayed F-to-F' complement against the exact chosen PDN AST for
  both AOI and OAI before returning a synthesis map. Mutation tests deliberately
  break the complement operation and require rejection in each direction.
- Give all six synthesis browser fixtures unique semantic screenshot names.
- Keep the full PDN equation once in copied synthesis explanations; retain the
  zero-group explanation in standalone POS reports.
- Keep visible group instructions static. Dynamic hover/focus announcements remain
  in an accessible live region outside document flow, since changing their length
  above the cards can move the pointer target during a real click. Card alignment
  tests now assert unchanged page coordinates through every card hover and exit,
  at 1280/800/360px. No forced clicks, retries or relaxed geometry assertions.
