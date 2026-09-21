# Ohmwork — Decisions

This is the single source of truth for every definitional question in `docs/CHARTER.md` §7,
and every one that arises later. Code that contradicts this document is a bug in the code,
not in the document. See §9 of the charter for the working agreement that governs how
entries here are proposed and changed.

Each entry records the question, the choice, the reasoning, and the date it was settled.

---

## D1 — What does "minimum transistors" mean, and over what search space?

**Choice:** Minimize transistor count over the implementation classes Ohmwork currently
supports, and report whether optimality was proven within that space. The supported space
is declared explicitly here and grows as the engine does — it is never claimed to be "all
valid CMOS implementations." For v1 the space is: single-stage complex gates (AOI/OAI and
their generalizations) plus NAND/NOR decompositions, with inverters counted per D2. The
single-gate solution is reported as primary when one exists; multi-stage alternatives are
reported alongside it.

**Reasoning:** An unqualified "minimum" claim over all of CMOS is not something a v1 engine
can honestly make. Naming the search space precisely lets the tool make a true, checkable
claim now and widen the claim later without retracting anything it said before.

**Date:** 2026-09-13

**Update (2026-09-14):** M1b's actual first implementation (D16) covers only the
single-stage AOI/OAI half of the space named above — the "plus NAND/NOR decompositions"
(multi-stage) half described here is **not yet built**. This was flagged by ChatGPT's M1b
review as a documents-disagreeing-with-each-other risk (exactly what §9's working agreement
exists to catch): a reader could take D1's text alone to mean multi-stage decomposition
already ships. It doesn't. D16 is the authoritative statement of what v1 actually searches;
multi-stage NAND/NOR decomposition remains real future work, not yet scheduled to a
milestone.

---

## D2 — Are complemented inputs free (dual-rail), or must inverters be counted?

**Choice:** Counted. Each required inverter costs 2 transistors. A `--dual-rail` flag is
provided for the case where complements are given for free.

**Reasoning:** Courses grade against the cost of realizing a function from uncomplemented
inputs unless told otherwise; charging for inverters by default matches that convention and
avoids silently flattering the transistor count.

**Date:** 2026-09-13

---

## D3 — Is there a maximum series stack height?

**Choice:** Unconstrained (textbook mode) by default. The tool reproduces the answer a
course expects rather than refusing a topology on manufacturability grounds. When a stack
exceeds 4, an **advisory** is emitted noting that production designs typically cap there —
context, not a veto. `--max-stack N` enables the engineering constraint.

**Reasoning:** Coursework routinely uses stacks a fab engineer wouldn't ship. Ohmwork's job
is to check the course's answer, not to second-guess it, while still surfacing the
real-world caveat for anyone who wants it.

**Date:** 2026-09-13

---

## D4 — How are don't-cares treated?

**Choice:** Assigned freely to minimize transistor count, with the assignment reported.

**Reasoning:** This is the standard treatment and the one every textbook problem assumes;
reporting the assignment keeps the choice auditable rather than hidden.

**Date:** 2026-09-13

---

## D5 — What breaks ties between equal-cost solutions?

**Choice:** Serialize each candidate to a canonical form, then compare lexicographically.
Canonicalization is deliberately shallow and cost-preserving: flatten associative chains
into n-ary nodes, sort commutative operands by a defined key (D10 variable order, then
arity, then string). No identity rewrites — in particular no De Morgan — because those
change transistor cost and would canonicalize away the very difference being priced. Must
be fully deterministic.

**Reasoning:** Determinism (design principle §5.3) requires a defined tie-break, not an
incidental one from set/dict iteration order or solver internals. Keeping canonicalization
shallow ensures the tie-break never accidentally picks a cheaper-looking but
differently-costed rewrite.

**Date:** 2026-09-13

---

## D6 — What does the tool do when it cannot prove minimality?

**Choice:** Return the best found result, explicitly labelled as **not proven minimal**,
with the search bound stated. Never imply optimality it has not established.

**Reasoning:** Design principle §5.5 ("honest about limits"). A student relying on an
unearned "minimal" claim is worse off than one told the search was bounded.

**Date:** 2026-09-13

---

## D7 — What counts as verification passing?

**Choice:** Two independent checks, reported separately. (a) *Functional equivalence*: the
generated PDN/PUN network, simulated across all 2^n input vectors, matches the source truth
table exactly. (b) *Static CMOS structural validity*: no input combination leaves the
output floating or creates a VDD-to-ground short. The output reports vector count, floating
states, and conflicts individually — never one generic pass/fail.

**Reasoning:** This is the project's core differentiator (charter §4, claim 2). Collapsing
two structurally different failure modes into one boolean would hide which guarantee
actually failed.

**Date:** 2026-09-13

---

## D8 — What is the expression syntax?

**Choice:** Textbook notation: juxtaposition is AND (`xy`), `'` is complement, `+` is OR,
`^` is XOR, parens override. Variables are a single letter with an optional trailing digit
(`A`, `x`, `A0`, `B2`), so `ABC` unambiguously means `A·B·C`. Multi-character identifiers
are not supported in v1; if added later they will require an explicit `*` operator. No bare
overbars — ambiguous input is rejected with an error, never guessed. (Cf. `(ABC + D)'` vs
`(ABC)' + D`, which are different functions.)

**Reasoning:** Restricting variables to single-letter-plus-digit removes the
tokenization ambiguity that multi-character identifiers would otherwise create against bare
juxtaposition-as-AND, without needing a delimiter for the common case. Rejecting anything
outside the declared grammar (unbalanced parens, stray digits, dangling operators) up front
is cheaper and safer than guessing what the user meant.

**Date:** 2026-09-13

---

## D9 — Which intermediate columns appear in a derivation table?

**Choice:** Full breakout by default. Every distinct sub-expression in the parse tree, in
evaluation order, including complemented literals as their own columns — so `x'y + xy'`
yields columns for `x`, `y`, `x'`, `y'`, `x'y`, `xy'`. Deduplicated. `--terse` collapses to
product terms and output; `--cols` takes an explicit list.

**Reasoning:** Every term and section of a problem stays individually identifiable, which is
what makes the table usable for locating an error rather than just confirming one (charter
§5.2, "show the work").

**Date:** 2026-09-13

---

## D10 — Variable ordering in output?

**Choice:** Order of first appearance in the expression, not alphabetical — matches how the
user wrote it.

**Reasoning:** The table should read the way the student wrote the problem, not the way a
dictionary would sort it.

**Date:** 2026-09-13

---

## D11 — Does the tool explain *why* a K-map group reduces to a given term?

**Choice:** Yes — a differentiating feature, not a nicety. For each group, report which
variables change across the minterms (eliminated) and which hold constant (kept, in true or
complemented form), then the resulting product term. The narration must itself be verified
against the minterm set before printing: recompute the term from the minterms and confirm it
matches what the explanation claims.

**Reasoning:** A confidently wrong explanation is worse than none — it actively misleads a
student who trusts the tool's reasoning, not just its answer.

**Date:** 2026-09-13

---

## D12 — Is a complemented input generated once and shared?

**Choice:** Yes. One inverter per complemented literal per design, costed at 2 transistors
regardless of how many places it feeds — not one inverter per use site. Fanout effects are
out of scope per charter §6. The optimizer must additionally weigh restructuring to avoid
the inverter entirely against paying its 2 transistors.

**Reasoning:** Charging per use site would misprice every design with a complemented
literal used more than once, and would make the transistor count depend on how the
expression happened to be written rather than on the network actually built.

**Date:** 2026-09-13

---

## D13 — Implementation language?

**Choice:** Python.

**Reasoning:** The algorithms are faster to write and test, it matches the owner's existing
toolchain, and M1 is a local CLI. A browser version, if it happens, ports the core or wraps
it — not a reason to pay a TypeScript tax now.

**Date:** 2026-09-13

---

## D14 — How is the tool kept approachable for an intro digital-logic user?

**Choice:** Layered subcommands, not modes. `tt` (derivation table), `kmap` (groups and
explanations), `synth` (adds the transistor layer). Transistor content never appears
unasked. Help text and README lead with `tt`; synthesis is listed last. Jargon in output is
glossed inline on first appearance (e.g. naming what AOI31 means). No separate "beginner
mode" — explicit modes double the test surface and drift out of sync.

**Reasoning:** A first-time user should never be shown transistor-level output before they
ask for it, and a maintained single mode is cheaper than two modes that inevitably diverge.

**Date:** 2026-09-13

---

## D15 — The variable name `F` collides with the output column; how is it resolved?

**Choice:** The bare letter `F` is reserved and cannot be used as a variable name;
`ohmwork tt "F + y"` is rejected the same way any other invalid input is (D8), with an
error naming the conflict and suggesting a fix (e.g. `F0`, or a different letter). `F0`,
`F1`, and lowercase `f` are unaffected — they render distinctly from the output column and
don't collide.

**Reasoning:** D8 permits any single letter as a variable name, and D9/the M1a acceptance
test fix the output column's label as `F` — the two decisions weren't checked against each
other and a variable literally named `F` collides with it (`ohmwork tt "F + y"` printed two
columns both headed "F" and the confusing line `F = F + y`). Renaming the output column
instead was considered and rejected: the M1a acceptance test in charter §8 requires the
output column be `F` and the report read `F = x`, so the output side of this collision isn't
free to move. Disambiguating only when a collision actually occurs (e.g. relabeling just the
variable in that one case) was also considered and rejected as unwarranted cleverness for an
edge case that barely anyone hits — it adds a rendering special-case that has to be
maintained and tested for a name almost no one needs. Rejecting the name at parse time
follows the same pattern D8 already established for other sources of ambiguity (malformed
variable suffixes, unbalanced parens): fix it in the grammar, not in downstream display
logic.

**Date:** 2026-09-13

---

## D16 — M1b v1: what exactly is the declared search space, and how are PDN/PUN built?

**Choice:** D1 requires the search space to be "declared explicitly... and grows as the
engine does." For M1b's first pass, the declared space is: **two candidate PDN shapes per
function, both single-stage, both derived from flat two-level Quine-McCluskey SOPs** — not
general algebraic factoring (kernel/co-kernel extraction, à la Espresso/SIS). Concretely:

1. **Construction.** The PDN must conduct exactly when the output should be 0, so it is
   built from `F'` (never `F` directly): AND becomes series, OR becomes parallel, each
   literal becomes one transistor (NMOS). The PUN is the topological dual of the PDN — same
   literals, series and parallel swapped, PMOS instead of NMOS. This is the standard
   complementary-CMOS construction, not a decision point in itself; what *is* decided here
   is which expression for `F'` gets fed into it.
2. **Every literal-minimal candidate in both directions, not just one of each.** Two SOP
   covers can tie on term count and literal count while needing a different number of
   complemented literals — which changes their *total* transistor cost once shared inverters
   (point 5) are counted. So every tied cover is built into a candidate, not only whichever
   one Quine-McCluskey's own (inverter-blind) tie-break happens to settle on first:
   - **AOI**: every literal-minimal SOP of `F'` (D4's don't-care handling applies here too)
     — each a parallel-of-series PDN.
   - **OAI**: every literal-minimal SOP of `F`, each structurally De Morgan-complemented
     (swap And/Or, complement each literal — a deliberate, visible synthesis step, distinct
     from D5's ban on identity rewrites in canonicalization/tie-breaking) — each a
     series-of-parallels PDN.
   Whichever candidate has the cheapest **complete** cost (PDN + PUN + shared inverters)
   wins; a genuine tie on that complete cost is broken exactly as D5 prescribes (canonical
   rendered form, compared lexicographically) — never before complete cost is compared.
3. **What this space does *not* find.** A function whose cheapest realization needs a
   literal shared across product terms in a way neither flat-SOP candidate captures will not
   be found — general multi-level factoring is future work, not v1. Per D6, a result is
   labeled "not proven minimal" unless the narrow certificate in point 4 applies.
4. **Minimality certificate.** If the chosen PDN uses exactly one literal per declared
   variable (every declared variable appears, and the literal count equals the variable
   count), Ohmwork proves a lower bound of exactly `2n` **PDN+PUN (core) transistors** — a
   function depending on n variables needs at least n literals in each of the dual
   networks, full stop. **This certificate is specific to complementary static CMOS; it
   makes no claim about pass-transistor logic, ratioed logic, dynamic logic, or any other
   circuit family.** Whether it also certifies the realization's *complete* transistor
   count (core + shared inverters, point 5) depends on whether the chosen design needs any
   inverters at all:
   - **Inverter cost is zero:** core cost equals complete cost, so the complete design is
     proven minimal within complementary static CMOS. This is the case for all three of
     M1b's acceptance-test gates (single-stage NAND/NOR/AOI/OAI, no complemented inputs).
   - **Inverter cost is nonzero:** only the core is proven minimal; complete
     transistor-count minimality remains unproven — Ohmwork has no certificate covering
     inverter cost, and says so rather than implying one.
   This is the only minimality claim v1 makes.

   **Historical note (superseded 2026-09-18):** point 4 originally read "...the result is
   provably minimal in *any* search space — a function depending on n variables needs at
   least n literals, full stop," with no complementary-static-CMOS scoping and no
   core/complete-cost distinction — that phrasing is **not current policy**; the paragraph
   above is. Two ChatGPT reviews of the same dogfooding round (CPE 635 Exam #1, then the
   AOI21 inverter case, `(a'b+c)'`: 6 core + 2 inverter = 8 total) caught both problems:
   "any search space" overclaimed across circuit families, and — more substantively — the
   certificate was being presented as covering a design's *complete* cost even when it
   needed inverter transistors the argument never bounded. `synth.py`'s
   `_prove_minimal_or_none` and `presenter.py`'s `_minimality_summary` implement the
   corrected rule above, in the Advanced Report, the student-facing summary, Copy Solution,
   and the JSON `reasoning` fields alike. No candidate generation, selection, transistor
   counting, or verification changed across either round — wording and presentation only.
5. **Inverters (D2/D12).** Costed at 2 transistors each, once per distinct complemented
   literal appearing in the *chosen* candidate's `F'` (shared across every product term that
   uses it, never per use site), unless `--dual-rail` is given.
6. **Gate naming (D14).** Read off the chosen PDN's shape: all-series -> NAND-n, all-parallel
   -> NOR-n, parallel-of-series -> AOI followed by each series branch's length (descending),
   series-of-parallels -> OAI likewise. Anything else is reported as an unnamed "custom
   complex gate" rather than guessed — though because Quine-McCluskey's output is always a
   flat two-level SOP, both candidates are always one of these four shapes today; the
   fallback exists for when factoring (point 3) is eventually added and can produce deeper
   nesting.
7. **Variable count.** Charter §8 scopes M1b's deliverable and acceptance test to 3-4
   variables and explicitly excludes 5+ from M1 entirely. `synth` enforces 1-4 (1-2 are
   strictly simpler than the tested ceiling, so nothing is gained by refusing them; only the
   upper bound is a real scope line) and rejects anything outside it rather than silently
   running an unscoped search.
8. **Verification is a precondition of returning a result, not a separate step a caller can
   skip.** Per charter §4 ("every emitted network is exhaustively simulated... before it is
   returned"), `synthesize()` runs D7's verification on the chosen design internally and
   raises rather than returning it if verification fails — a caller (the CLI included)
   cannot obtain a `SynthesisResult` that hasn't already passed. A failure here means a bug
   in this module, not bad input.

**Reasoning:** D1 explicitly names "AOI/OAI and their generalizations" as the v1 search
space alongside NAND/NOR decompositions — this is that space made concrete and
implementable, not an expansion of it. Building full multi-level factoring now would be a
substantially larger effort for a case the M1b acceptance test doesn't require (all three of
its gates are already optimal flat-SOP realizations); shipping the narrower, honestly-scoped
version first, with D6 correctly declining to overclaim on cases it can't solve, matches
design principle 5.1 ("correct before clever"). Per the working agreement (§9), a second
collaborator building an independent M1b implementation needs this written down to get the
*same* answers on anything beyond the three acceptance-test gates — without it, two correct
but differently-scoped synthesizers would disagree on cases like `((a+b)c)'`, which this
search space happens to solve optimally (by trying the OAI candidate) but a pure-AOI-only
implementation would not.

**Date:** 2026-09-13

**Update (2026-09-14):** ChatGPT's independent M1b review found that the first
implementation of this decision had a real bug relative to its own stated intent: selection
compared only PDN+PUN cost (excluding inverters) before picking a winner, and `minimize()`
committed to a single literal-minimal cover via its own lexicographic tie-break *before*
synthesis ever saw whether an equally-minimal alternative needed fewer inverters. Together
these could — and, in a constructed reproducer, did — pick an 18-transistor design over a
16-transistor one, and separately an 8-transistor design over a 6-transistor one, in both
cases because the cheaper option lost a tie-break that never should have run (the true costs
weren't equal). Point 2 above now states the corrected rule (complete cost, all tied covers
considered) that was always the *intent*; the review also confirmed the three
acceptance-test gates were unaffected (none of them hit this tie condition). Points 7 and 8
were added in the same pass: the 5+-variable exclusion from D1/charter §8 was never actually
enforced in code, and verification (D7) was checked by the CLI but didn't prevent a failed
design from being returned with exit code 0 — both are closed now, the latter by making
verification a precondition inside `synthesize()` itself rather than a separate step a
caller could skip or ignore.

**Update (2026-09-15):** Fixing the above (retaining every tied cover instead of just one)
introduced a determinism regression, also caught by ChatGPT's review: the new candidate
lists were built from Python `set`/`frozenset` internals in `simplify._minimal_extra_cover`,
whose iteration order depends on `PYTHONHASHSEED` (randomized per-process by default) —
across 80 seeds, the same input produced two byte-distinct outputs, differing only in which
of two equal-cost candidates was listed first. The chosen circuit itself was never affected,
only the "candidates considered" display — but design principle 5.3 ("identical input
yields byte-identical output") makes no exception for cosmetic ordering. Fixed at three
layers: `_minimal_extra_cover` now sorts its own output by each cover's bit patterns before
returning (fixing the root cause), `minimal_covers` independently sorts its result by
rendered form (so its own determinism doesn't depend on trusting that internal fix), and
`synth._build_candidates` sorts the combined candidate list the same way before it ever
reaches `SynthesisResult` — so no caller, not just the report, can observe hash-dependent
order. Verified against the reported reproducer across 10 different `PYTHONHASHSEED` values
(previously 2 distinct outputs, now 1) and added as a genuine cross-process regression test,
since hash randomization is fixed per-process and can't be exercised any other way.

---

## D17 — APPROVED. Phase A and Phase B implemented and shipped. What does a real transistor-level schematic show, and how is it built?

**Status:** approved for implementation (2026-09-18, after two review rounds — see the
revision history at the end of this entry). **Acceptance test 8's connectivity requirement was
amended 2026-09-19 to recognize named-net ports as a second valid connectivity convention for
gate-signal nets only — see the "Connectivity conventions" addition below and the revision
history's final entry.** **Phase A (the schematic layout model,
`src/ohmwork/schematic.py`) is implemented** as of commit `0dc480a` (2026-09-19), with four
corrective follow-up commits after independent review found real adversarial gaps in
`validate_layout_geometry`/`_canonical_layout_topology`. First round (`8623b13`): a wire routed
through another net's declared point without being caught, a self-loop device hanging the
topology-fidelity graph reduction, nothing cross-checking a device's `gate_net` against its own
structured gate identity or the primary/complement mapping table, and device geometry/`literal`
fields never being checked against the documented coordinate formulas. Second round: nothing
restricted which *kind* of net a core device's source/drain terminal could reference, so a
PDN/PUN diffusion terminal could reuse a primary gate net in place of its own internal junction
net — fully self-consistent wire geometry, invisible to electrical simulation and topology
fidelity alike; closed with an explicit PUN/PDN terminal-domain allowlist, junction-ownership
validation, and a full net-inventory closure check. Third round: `layout.vdd_net_id`/
`gnd_net_id`/`output_net_id` and the VDD/GND nets' own labels were never pinned to the literal
strings `"VDD"`/`"GND"`/`"OUT"` — every other check was purely relative to whatever those
fields said, so a globally-consistent rename (e.g. to `SUPPLY`/`RETURN`) or a plain VDD/GND
label swap passed every gate; closed with explicit literal-identity checks plus a
`build_schematic`-level check that the OUT net's label matches the requested `output_name`
(the one thing `validate_layout_geometry` alone can't verify, having no `output_name` to
compare against). Fourth round: gates 1-3 never cross-checked against the *particular*
`SynthesisResult` being rendered — the dual-rail build of a function needing a shared inverter
has an identical PDN/PUN core topology and computes the identical function (dual-rail's
external complement net is correct by construction), so it passed electrical behavior,
geometry integrity, and topology fidelity (which deliberately excludes inverters) when
substituted for the normal, inverter-bearing result it doesn't belong to. Closed with a fourth
gate, `_validate_source_fidelity`, checking device-role counts, D12 inverter-mode/accounting,
`var_order`, dimensions, and the output label directly against `result`/`output_name`; also
added a cross-process determinism regression (identical inputs produce identical
nets/devices/wires/junctions and stable ids across different `PYTHONHASHSEED` values), since
Phase B's model-to-SVG bridge depends on that stability. All four rounds fixed, with
regression tests, before Phase B began. **Phase B (SVG rendering, `presenter.py`/`webui.py`
wiring, "Download SVG", acceptance tests 8 and 10) is implemented and shipped** — see the
revision history's final entry for the full implementation/review history. This entry exists
specifically so the schematic
renderer described below was *not* built until this decision (and its acceptance tests) was
reviewed and approved — a diagram encodes electrical connectivity and can be technically wrong
even while looking attractive, which is a materially different risk than the wording-only
presentation work in D-adjacent UI commits. That review is now done; implementation may begin
against the acceptance tests below. The current CLI/Advanced Report ASCII schematic (a
VDD/PUN-expression/F/PDN-expression/GND text block) stays exactly as it is regardless of this
entry — this is an *additional* presentation, not a replacement.

**Trigger:** real coursework dogfooding of all three M1b acceptance-test gates through the
actual web UI (CPE 635 Exam #1, 2026-09-18) surfaced two independent, user-identified gaps in
the same session: the Derivation table's output not matching the Synthesis tab's table
polish (addressed separately, M1.3), and this one — the synthesis result's "schematic" being
a topology *summary*, not something a student could read against or reproduce on paper
(compare a hand-drawn 4-input NOR with individually labeled PMOS/NMOS transistors, gate
inputs, VDD/GND rails, and wires). Per the charter's explicit deferral of "SVG/graphical
transistor schematics" and this project's standing instruction that K-map/schematic work
gets a decision entry + acceptance tests before code (the same pattern this entry itself
follows), this is that entry.

**Proposed choice:**

1. **Source of truth.** The SVG is built deterministically and directly from
   `SynthesisResult.pdn`, `.pun`, and its shared-inverter data (`inverter_literals`/
   `inverter_transistors`, D12) — the same already-verified object graph `report.py` and
   `presenter.py` already read. It never parses the ASCII report text or a rendered Boolean-
   expression string; doing so would mean the diagram could silently drift from what was
   actually verified (D7), exactly the class of bug this project's presenter-layer design
   principle (facts read off the object graph, never reparsed) exists to prevent.
2. **What it shows.** A recognizable transistor-level complementary static CMOS schematic:
   VDD rail at top; PMOS pull-up network (PUN) above the output node; the output node in the
   middle, labeled with the chosen output name (not always literal "F" — M1.2's
   `output_name`); NMOS pull-down network (PDN) below it; GND rail at bottom. Standard,
   visually distinguishable PMOS and NMOS transistor symbols (gate, source, drain, with PMOS's
   conventional gate bubble); gate/input labels on every transistor; wires and junction dots
   at real electrical connections (or, for gate-signal nets only, named-net ports — see the
   "Connectivity conventions" amendment below); series and parallel sub-network topology laid
   out to match the actual `Network` tree (`network.py`'s `Series`/`Parallel`/`Transistor`
   nodes — already exactly the structure a layout algorithm needs, no new engine data
   required); PUN and PDN
   labeled as such.
3. **Complemented inputs (D12) are drawn at transistor level, never as a gate symbol.** In
   normal mode, each distinct complemented literal counted by `inverter_literals` is rendered
   as **exactly one PMOS device symbol plus one NMOS device symbol** — two transistor symbols,
   connected between the VDD and GND rails exactly like any other inverter stage, sharing one
   complemented-output net between them. A logic-gate triangle (or any other non-transistor
   glyph) is not an acceptable substitute — the whole point of this decision is a
   transistor-level diagram, and an inverter drawn as a gate would silently misrepresent that.
   Both of that inverter's two devices count toward the total symbol count (point 5). That
   shared complemented-output net is wired to every transistor gate that uses the literal
   (never one inverter per use site — the same sharing rule D12 already establishes for the
   transistor *count*, now also true of the *drawing*). Under `--dual-rail`: the complemented
   rail is still shown/labeled at each gate that needs it, but no inverter symbols are drawn
   and none are counted — matching D2's existing rule that dual-rail complements are free.
4. **The layout model has explicit, named electrical nets and device terminals — it is not
   just a picture.** Every device (transistor or inverter-half) has typed terminals (gate,
   source, drain) and every net (VDD, GND, the output, each internal node) has a stable name,
   in the model itself, before any SVG is produced. This is what makes the model
   independently checkable for correctness (point 7 below and the connectivity acceptance
   test) rather than only "looks right" — converting the already-verified `Network` tree into
   this model is itself a step that can introduce a bug, and an untyped, unnamed geometry-only
   model would have no way to catch one.
5. **Symbol count must agree with the report.** The number of transistor symbols in the
   complete diagram (PDN + PUN + inverters, each inverter counted as its two devices per point
   3) must equal `SynthesisResult.total_transistors` — checked structurally by the acceptance
   tests below, not eyeballed.
6. **Initial exclusions** (v1 scope, not permanent): transistor sizing (W/L ratios); body
   terminals and body effect; analog device parameters; physical layout or parasitics; SPICE
   simulation or netlist export; arbitrary non-series-parallel circuits (D16 point 3 already
   excludes these from what `synth` even finds, so the renderer only ever needs to lay out
   series/parallel trees); K-map rendering (a separate, also-deferred charter item, not part
   of this decision).
7. **Implementation direction** (for after this entry is approved, not before):
   - A testable schematic *layout model* — the named nets/typed devices of point 4, plus
     positions and wire segments for layout — computed from the `Network` tree and kept
     separate from the SVG string it produces, so the model's own correctness (acceptance
     tests 1-7 below) can be checked structurally without rendering anything.
   - That model rendered as responsive inline SVG with a stable `viewBox`, built via
     `document.createElementNS`/`textContent` (or an equivalently safe internal renderer) —
     never string-concatenated `innerHTML`, the same rule M1.3's HTML table follows. Every
     rendered transistor and net carries a stable identifier (e.g. a `data-device-id`/
     `data-net-id` attribute) tying it back to the layout model's own IDs — required for
     acceptance test 8's model-to-SVG bridge check, not optional polish.
   - No AI-generated or bitmap circuit images at any point — the whole reason for this
     decision is that the output must be deterministic and provably tied to the verified
     network, which a generated image cannot guarantee.
   - "Download SVG" always; "Copy image" if practical once the renderer exists (not a blocker
     for v1).

**Connectivity conventions (2026-09-19 amendment — see the revision history's final entry).**
Live Phase B dogfooding of the routing-fixed implementation (commit `5c6863e`) found that
requiring every connection to be one continuous drawn wire forces a visually inferior
gate-signal distribution bus — long wires looping around the whole circuit — that reads as an
auto-routed wiring diagram rather than a textbook schematic, even once the crossings-through-
the-core problem itself was fixed at the model level. This amendment does not relax D17's
correctness bar: it replaces "all connectivity must be one continuous drawn wire" with the
broader, still fully machine-verifiable rule that every connection must be represented by one
of two recognized, visible, structurally-checkable conventions.

- **Geometric conductor connection** (the original, still-mandatory convention for everything
  except gate-signal nets): endpoints visibly meet through continuous wire geometry and
  explicit junction dots where required.
- **Named-net connection**: electrically identical endpoints terminate in explicit, visible
  named-net ports carrying the same canonical net identity and displayed label, with no
  continuous wire drawn between them.

A matching `data-net-id` alone is never sufficient for either convention on its own — a
non-continuous connection is valid only when the SVG visibly renders the named-net-port
convention below, and it is checked structurally (acceptance test 8) exactly as rigorously as a
geometric connection already is.

Named-net ports are permitted **only** for gate-signal nets — `gate_primary`,
`gate_complement_internal`, `gate_complement_external` — and may never substitute for
source/drain diffusion wiring, internal series/parallel junctions, the output path, or a
PUN/PDN-to-VDD/GND connection, all of which must stay continuously, geometrically wired.
Within that permitted scope:

- Every transistor gate must visibly connect to either a continuous gate wire, or a short gate
  stub that terminates at a visible named-net port. The stub itself is still real, model-backed
  geometry — only the *long-distance bus between ports* is replaced by label-matching, never
  the local connection from a transistor to its own port.
- Every named-net port carries stable semantic attributes: a `data-port-id`, the `data-net-id`
  it belongs to, the canonical displayed net label, and its exact terminal/anchor point.
- The visible port label must match the model net's own label exactly; every port sharing a
  `data-net-id` displays that same label; no two distinct net IDs ever display the same label.
- Each visible gate stub must geometrically meet both its own transistor's modeled gate
  terminal and its named port's anchor point.
- A shared inverter's complemented output net must visibly originate at that inverter's own
  output and terminate at a named port (e.g. `a′`); every occurrence of that port must
  reference the same model net — a label that merely *looks* like the right complement,
  without tracing back to the inverter's own net, does not satisfy this.
- Under `--dual-rail` (D2), complemented inputs must be visibly identified as externally
  supplied, never shown as inverter-generated — matching this entry's existing dual-rail rule
  (point 3) for the transistor-level drawing itself.
- Unlabeled, disconnected stubs are forbidden; an invisible element, or `data-net-id` agreement
  without a visible, matching port label, never establishes drawn connectivity.

**Renderer policy:** prefer whichever representation reads most clearly as a textbook
schematic — short labeled gate stubs by default for gate-signal nets; a continuous gate wire
only where that is locally simpler and clearer; always-continuous wiring for source/drain
topology, the output path, and supplies; conventional VDD/GND symbols; a shared inverter
presented as its own distinctly labeled subcircuit (point 3).

**Acceptance tests** (to exist, reviewed, before implementation starts — same role the
charter's M1a/M1b acceptance tests played for those milestones):

1. **Q1 (3-input NAND):** 3 parallel PMOS from VDD to the output node; 3 series NMOS from the
   output to GND; exactly 6 transistor symbols total.
2. **Q2 (4-input NOR):** 4 series PMOS from VDD to the output; 4 parallel NMOS from the output
   to GND; exactly 8 transistor symbols total.
3. **Q3 (AOI31):** PDN has the `abc` series branch in parallel with `d`; PUN is its correct
   dual ((a+b+c) in series with d); exactly 8 transistor symbols total.
4. **Complemented-input case** (e.g. the AOI21 `(a'b+c)'` example from the minimality-wording
   review round): the complemented literal's inverter is exactly one PMOS symbol and one NMOS
   symbol (never a gate glyph, per point 3), sharing one complemented-output net; every
   transistor gate using that literal connects to that *same* net, not separate ones; total
   symbol count equals core + inverter's two devices (8, for that example).
5. **Dual-rail version of the same case:** the complemented rail is shown at the transistors
   that need it; zero inverter symbols are drawn; total symbol count equals core cost only (6).
6. **Output name:** setting a custom output name (M1.2) changes the schematic's output-node
   label to match, without changing the circuit itself.
7. **Layout-model connectivity is independently verified for every input vector** — not just
   asserted to look like the right shape. For each of the function's `2^n` input assignments,
   evaluating the layout model's own nets/devices (independently of the already-verified
   `Network` tree, so this specifically catches a bug introduced while *converting* that tree
   into the layout model) must show: the output net connects to exactly one of VDD or GND;
   it never floats (connects to neither); it never shorts (connects to both); and its
   resulting logic value matches the function `synth` actually verified (D7). This is D7's own
   discipline — exhaustive simulation before trusting a network — applied a second time, to
   the model that will actually be drawn.
8. **A semantic model-to-SVG bridge test**, so a correct layout model rendered incorrectly is
   still caught — and so "trustworthy-looking metadata" isn't mistaken for a rendering that's
   actually correct. For every model wire, device, junction, and (per the connectivity
   conventions above) named-net port: assert exact bidirectional correspondence with the
   rendered SVG — none missing, none duplicated, none extra — located by stable identifiers,
   with the correct device type (PMOS/NMOS) and gate label. The emitted geometry itself must be
   checked, not just those labels:
   - For every model device terminal and wire segment, the SVG element's own coordinates/
     endpoints must match the layout model's corresponding values.
   - For a geometrically-wired connection: two endpoints the model considers part of the same
     net must visibly meet in the SVG (the same point, or an explicit junction-dot element at
     that point) — a `data-net-id` match alone doesn't prove the drawn wires actually connect
     there.
   - For a named-net-port connection (gate-signal nets only, per the connectivity conventions
     above): every gate terminal reaches a visible, labeled port through a model-backed local
     stub; the port's `data-net-id` and displayed label match the model's; every port sharing a
     `data-net-id` displays the same canonical label, and no two distinct net IDs display the
     same label; a shared inverter's complement port is driven by that inverter's own output
     net, not merely labeled to look like it is; label-only connectivity is never accepted in
     place of continuous wiring for source/drain paths, internal series/parallel junctions, the
     output path, or VDD/GND.
   - No conductive wire exists in the SVG that isn't backed by a wire segment in the model, and
     no named-net port exists that isn't backed by a real device gate terminal or the
     shared inverter output explicitly required above — ruling out
     both an accidental extra connection the model never specified and a decorative port with
     nothing real behind it.
   - A PMOS device's SVG markup includes its gate-bubble element; an NMOS device's does not —
     checked structurally (the element's presence/absence and type), not by how it looks
     rendered.
   - "Download SVG" (point 7) must produce its file from this same checked representation —
     not a separately-serialized copy that could drift — and that downloaded SVG must pass
     these same semantic device/net/port/geometry assertions, not just the inline one.

   All of the above are structural DOM/attribute/coordinate assertions against the rendered
   SVG's own markup — this is **not** a pixel comparison and **not** an exact-SVG-string
   snapshot, both of which would be fragile to unrelated visual changes and wouldn't actually
   verify electrical correctness; stable semantic assertions (including comparing the actual
   coordinate values the model specifies) are the right tool here precisely because they
   survive a purely cosmetic layout tweak while still catching a real model-to-SVG bug —
   including the specific failure mode of correct-looking `data-*` labels sitting on
   incorrectly-connected or incorrectly-shaped geometry.
9. **Layout-model tests are structural, not pixel-based.** Tests 1-3, 5, and 6 above assert
   against the layout model's own data (transistor positions/types/gate-labels/connectivity,
   symbol counts), the same principle test 8 extends to the rendered SVG itself.
10. **Browser-level coverage** (Playwright, alongside the structural tests above): the SVG
    appears for a synthesis result and disappears when the result becomes stale or New Problem
    is pressed (same stale-result discipline M1.2/M1.3 already established); its displayed
    transistor-symbol count equals the model's (and thus the report's) count; it's responsive
    (scales with viewport, doesn't overflow); it has an accessible name/description; it
    renders legibly in both light and dark mode (`prefers-color-scheme`).

**Reasoning:** The charter already defers "SVG/graphical transistor schematics" explicitly —
this entry doesn't reopen that scope decision, it fulfills the condition the charter itself
sets for revisiting deferred polish ("until real coursework use shows what's actually worth
polishing," §10), which three real exam questions run through the actual UI now satisfies.
The decision-entry-first requirement is not bureaucratic overhead for its own sake: a wrong
transistor count, a mis-shared inverter, or PDN/PUN topology that doesn't match the verified
`Network` tree would be a *correctness* bug wearing a nicer coat of paint, and the acceptance
tests above are what makes "the diagram matches what D7 already verified" a checkable claim
rather than an eyeballed one — the same reason D16 wrote down the search space before D16's
own implementation, and D1 before the engine that had to honor it. Points 3-4 and acceptance
tests 4 and 7-9 exist because a first review round (2026-09-18) found the original draft's
"never parse rendered text/markup" principle, while correctly aimed at the ASCII report, had
left two real gaps on the SVG side itself: nothing pinned down *how* an inverter is drawn
(a gate-symbol substitute would misrepresent "transistor-level"), and nothing checked that the
model-to-layout conversion or the model-to-SVG rendering step each preserve the electrical
facts D7 already verified, as opposed to merely producing a plausible-looking picture.

**Date:** 2026-09-18 (proposed). **Revised:** 2026-09-18, incorporating a first review round's
three amendments (inverter rendered at transistor level, named nets/terminals with per-vector
connectivity verification, and a semantic — not pixel/snapshot — model-to-SVG bridge test).
**Revised again:** 2026-09-18, a second review round approved the substance of those three
amendments and required one further clarification to acceptance test 8: the semantic bridge
must check the SVG's actual emitted geometry (device-terminal and wire-segment coordinates,
same-net endpoints visibly meeting or sharing a junction, no unmodeled extra wire, PMOS gate
bubble present/NMOS absent) — not only `data-*` identifiers, which could sit on incorrectly-
connected or incorrectly-shaped geometry and still look "trustworthy." Also clarified that
"Download SVG" must be produced from, and pass, the same checked representation and semantic
assertions as the inline SVG. **Approved for implementation** as of this revision.

**Amended 2026-09-19** (after Phase A was signed off and Phase B had already been through two
implementation/review rounds — commits `3b97e18`, `1f09ad5`, `5c6863e`): live dogfooding of the
routing-fixed Phase B implementation found that acceptance test 8's original "every connection
must be one continuous drawn wire" requirement, applied literally, forces a visually inferior
gate-signal distribution bus for repeated inputs — long wires looping around the whole circuit —
even once `5c6863e` had already fixed the separate problem of those wires crossing *through* the
transistor core. Added a second recognized connectivity convention, **named-net ports**, for
gate-signal nets only (never for source/drain, internal junctions, the output path, or
PUN/PDN-to-VDD/GND connections, which stay continuously wired as before) — see the "Connectivity
conventions" addition above and acceptance test 8's revised wording. This is a documentation-only
amendment: no renderer, model, or test code was written or changed as part of it; implementation
against the new convention is a separate, subsequent round, to be reviewed on its own.

**Phase B shipped, 2026-09-19** (four PRs, implemented by Codex against the amendment above,
each independently reviewed by Claude before merge — methodology: isolated `git worktree` per
review, never touching the user's own checkout/server; full test suite rerun from a clean venv;
an independently-written verification script re-deriving each round's key correctness claim from
raw model data rather than trusting the PR's own helpers/tests; live-browser rendering of the
acceptance cases plus edge cases; and, from PR #2 onward, pulling the actual live "Download SVG"
output into a standalone render to confirm export fidelity):
- **[PR #1](https://github.com/IamTemmy/ohmwork/pull/1)** (`9039d7b`): the named-net gate-port
  renderer itself — conventional MOSFET symbols, named ports for repeated gate inputs, shared
  inverters drawn as their own subcircuit, Download SVG. 378 Python + 96 browser tests.
- **[PR #2](https://github.com/IamTemmy/ohmwork/pull/2)** (`843775e`): moved the output tap off
  the PUN/PDN's own bus and onto the exact midpoint of a real one-device-pitch gap between the
  two networks, with its own junction dot; extended ground-bus reconstruction to reach a shared
  inverter's now-relocated ground connection.
- **[PR #3](https://github.com/IamTemmy/ohmwork/pull/3)** (`d3bfdad`): fixed the midpoint
  calculation to center on the *visible* network silhouette (real bus wire, or a lone device's
  symbol shoulder) rather than the invisible raw device-terminal edge, and anchored PUN/PDN
  captions to each network's own top row instead of the (now visually-shifting) output boundary.
- **[PR #4](https://github.com/IamTemmy/ohmwork/pull/4)** (`6297610`+`a531706`): replaced the
  coordinate-transform approach with a genuine recursive layout algorithm walking the `Network`
  tree directly — series children centered horizontally, parallel children vertically, both
  root networks sharing a center axis, using integer half-pitch cells specifically to avoid
  rounding drift on odd width/height differences. Replaced plain text captions with dashed
  bracket annotations spanning each network's own transistors, clear of gate labels. Device/net
  identity from the wired layout is preserved and checked at every recursion step.
- Merged at `main` `b2b8922`. Final state: 489 Python + browser tests green, plus a
  from-scratch 25-shape battery (covering shapes beyond the four acceptance cases: wider
  NAND/NOR, OAI variants, hand-built deep-nested/asymmetric trees, multi-inverter and dual-rail
  combinations, non-default output names, multi-character variable names) checked structurally
  and visually with zero problems found, independently cross-checked by a second reviewer
  (ChatGPT, working from the same repository) with matching results.

---

## D18 — Implemented and shipped. What does a K-map view show, and how is it built?

**Current status (2026-09-21):** all three phases shipped: verified grouping/model,
standalone CLI/UI rendering and worked explanations, and synthesis integration
(PR #11, with selection explanations in PR #12). The staged independent reviews
are complete. The original specification and review clarifications below are
retained as design history.

**Trigger:** the charter's own original, never-built vision (§ intro: "the K-map with groupings
drawn" is listed alongside the schematic as part of what `synth` produces given a truth table);
D11's already-approved requirement that the tool narrate *why* each group reduces to its term,
verified against the minterms before printing; D14's already-planned `kmap` subcommand,
mirroring `tt`. All three have existed since M1a (2026-09-13) and were deliberately deferred
("K-map rendering" — charter's M1 exclusion list) until real coursework use justified the work,
the same bar D16 and D17 both cleared. Real use has now cleared it here too: the user wants a
standalone K-map section (mirroring the Derivation tab) and the K-map worked into `synth`'s own
"full solution" report, explaining the specific expression the engine already chose.

**Scope: two consumers, one shared model.**
1. **Standalone K-map view** — new web UI tab (mirroring "Derivation table") and a `kmap` CLI
   subcommand (D14), for learning/simplifying a function on its own: the user supplies a
   function (expression or truth table, the same input surface `tt`/`synth` already accept) and
   sees its K-map, every selected group, and the narrated explanation of each (D11).
2. **Synthesis-integrated K-map** — embedded in `synth`'s existing report, explaining the
   *specific* expression `SynthesisResult.chosen` already realized — never a freshly and
   independently computed "the" simplification of F that might legitimately differ from what
   was actually built (see point 5).

Both consumers share the same grouping/model logic; only which minterm set gets visualized
differs (a user-supplied function for the standalone view, vs. `chosen`'s own target minterm
set for the synth view).

**1. What already exists and must not be broken.** `simplify.py`'s Quine-McCluskey +
Petrick's-method implementation (`_prime_implicants`, `_essential_cover`,
`_minimal_extra_cover`, `minimal_covers`, `minimize`) is the actual, already-signed-off (M1a,
dogfooded, golden-CLI-pinned via `tests/test_golden_cli_output.py`) algorithm that finds minimal
covers — this is exactly a K-map's own prime-implicant step, and it must be **reused, not
reimplemented**. It currently works on bit-pattern strings (`'0'`/`'1'`/`'-'`) and returns only
the final algebraic `Expr` for the winning cover(s), discarding the specific covered-minterm-set
each term corresponds to — the one thing a visual K-map needs to draw a group's exact shape.
None of `simplify.py`'s existing public functions may change behavior, signature, or return
type; new structured data is exposed *alongside* them (a new function or an additive field),
never in place of them. `synth.py`'s `_build_candidates` already makes the exact choice this
decision needs to render faithfully — AOI candidates group the *zeros* of F (`zeros = full -
minterms - dont_cares`) to build F′ directly; OAI candidates group the *ones* of F, then
structurally De Morgan-complement the result (see point 5) — and `SynthesisResult.chosen`/
`other_candidates` are read from, never independently re-derived. Separately,
`derivation.all_assignments` and every minterm-index convention in this codebase is a fixed
binary count (MSB = first-declared variable), **not** Gray code — a K-map's row/column axes
need Gray-code ordering for adjacency to hold, and that mapping is new work (point 3).
`SynthesisResult` does not currently carry the `minterms`/`dont_cares` it was built from (only
the winning `Candidate`/`Network`/counts) — rendering a K-map for `chosen` needs the actual cell
values, so this is new data to *add*, without changing any existing field's meaning or the
golden CLI output.

**2. Supported variable counts; SOP vs. POS.** Same ceiling as everywhere else in the engine
(D16, `synth.MIN_VARS`/`MAX_VARS`): 1-4 variables — a K-map beyond 4 variables (needing 3D or
overlaid layout) is out of scope, matching the charter's own "5+ variables" exclusion. Both
directions are real, distinct pictures, not the same grouping relabeled:
- **SOP**: group the 1-cells (minterms); each group is a product term; OR them together. This
  is what the standalone view defaults to, and what `synth`'s OAI candidates are built from.
- **POS**: group the 0-cells; each group is a *sum* term (the group's own De Morgan dual —
  variables that are 1 across the group become complemented literals OR'd together, and vice
  versa); AND the group-terms together. This is what `synth`'s AOI candidates are actually built
  from — `_build_candidates` groups F's zero-cells directly to get F′, which read pedagogically
  is "circle the 0s of F to get F′."

The standalone view should let the user choose SOP or POS (or show both) — both are legitimate
coursework asks. The synth-integration view has **no free choice**: it must show whichever one
actually matches `chosen.label` (point 5).

**3. Grid layout: Gray-code ordering, cell-to-minterm mapping.** Proposed convention (needs
review, but pinned to something concrete rather than left to be improvised mid-build): split
`var_order` into a row-variable group (the first `floor(n/2)` variables, in D10/`var_order`
order) and a column-variable group (the remaining `ceil(n/2)`) — 4 variables: 2×2 (4×4 grid);
3 variables: 1×2 (2×4 grid); 2 variables: 1×1 (2×2 grid); 1 variable: 0×1 (a 1×2 grid, degenerate
but must still render legibly, never crash or get special-cased away). Each axis is labeled in
standard reflected Gray-code order (2 values: `0,1`; 4 values: `00,01,11,10`) — never plain
binary, which would break the adjacency property groups depend on. A cell's row-Gray-code and
column-Gray-code concatenate (row bits then column bits, matching `var_order`'s own bit-position
convention already used everywhere else) to give its minterm index in the same convention
`all_assignments`/`simplify.py` already use, invertible in both directions (checked
independently — acceptance test 1). Edge/corner wraparound (a group spanning the grid's
left/right edges, top/bottom edges, or all four corners) is a direct, expected consequence of
Gray-code adjacency wrapping per axis — the *model* represents such a group as one group over
its true (possibly visually split) cell set; drawing it legibly (e.g. split bracket pieces at
the wrap) is a rendering concern, not a reason to model it as multiple groups.

**4. Structured group data and verified explanations (D11).** A new structured type (not just
an `Expr`) records, per selected group: which cells (minterm indices) it covers, which covered
cells are don't-cares actually being used by this cover, the dash-pattern/term string, whether
it's essential, and the resulting literal/term. Both the renderer (draw the bracket over exactly
those cells) and the narration (D11: which variables are eliminated, which are kept, in true or
complemented form) consume this. Per D11's own already-approved requirement, each group's
narration must be *recomputed from its own covered-minterm set and checked against the stated
term* before being shown, never merely asserted — the direct K-map analog of D17's
`_validate_named_ports`/`_validate_source_fidelity` gates.

**5. F vs. F′: the synth-integration view must explain the actual chosen expression.** The
single most important correctness rule for that consumer: render the grouping that actually
produced `SynthesisResult.chosen`, never a freshly-computed simplification of F that a
standalone call to `minimize()`/`minimal_covers()` might return instead — `_build_candidates`
explores *every* tied minimal cover in each direction and may pick one that differs from
`minimize()`'s own separate D5 tie-break. Concretely:
- `chosen.label == "AOI"`: render F's K-map (1s = `minterms`, dashes = `dont_cares`), with
  groups covering the **0-cells** that reconstruct `chosen.f_prime`'s own product terms exactly
  (POS reading) — state explicitly that grouping the 0s gives F′ directly.
- `chosen.label == "OAI"`: render F's K-map, with groups covering the **1-cells** that
  reconstruct the *pre-De-Morgan* SOP of F (the OAI candidate's own intermediate step, before
  complementation) — narrate the subsequent structural complementation as its own explicit step
  producing the PDN's actual series-of-parallels shape, never silently skip straight to
  `f_prime`.
- Either way, the group set shown is reconstructed from `chosen.f_prime` (or an
  additively-exposed intermediate the chosen candidate already carries) — **never** recomputed
  independently, so a coincidental re-simplification landing on a different, equally-valid cover
  can never silently mismatch the PDN the schematic tab shows for the same result.
- `F` and `F′` must be visibly, unambiguously labeled wherever both appear near each other (the
  map's own title/legend, not inferred from context) — matching D15's existing concern about the
  name `F` colliding with other things, and the schematic tab's own complemented-literal
  labeling conventions (D12).

**6. Acceptance tests** (to exist, reviewed, before implementation starts — same role D16's and
D17's own lists played):
1. **Cell-to-minterm/Gray-code correctness**: for every variable count (1-4) and every cell, the
   row/column Gray-code position maps to the documented minterm index and back, exactly — an
   independent, from-scratch bit-manipulation check, not a round-trip through the code being
   tested.
2. **Singleton groups**: an essential prime implicant covering exactly one minterm (no adjacent
   1s to merge with) renders as a single-cell group.
3. **Ordinary (non-wrapping) groups**: standard pairs/quads/octets each render as one contiguous
   rectangular bracket over exactly its covered cells.
4. **Overlapping groups**: a cell covered by more than one selected group renders with every one
   of its groups genuinely distinguishable over that shared cell — not merged, not one hidden
   behind another, unambiguous from the rendering (not color alone — point 7).
5. **Edge/corner wraparound**: groups spanning left-right edges, top-bottom edges, and (4-var)
   all four corners at once each render as one group with the correct wrapped cell set, legible
   despite the visual split.
6. **Don't-cares**: a don't-care cell actually used by a selected group renders distinguishably
   from one that isn't, and from a genuine 0 or 1 (D4: "assignment reported"); the legend
   distinguishes all three cell states unambiguously.
7. **Constant functions** (all-0, all-1, including via don't-cares covering every remaining
   cell): the degenerate "no groups"/"one all-covering group" cases render without crashing and
   without a misleading empty-looking map.
8. **Multiple equally-minimal covers**: a function whose `minimal_covers()` returns more than
   one tied cover — the standalone view states which one it's showing (D5's tie-break, or
   whatever `minimize()` picks, named as such) and the synth-integration view shows the one
   `SynthesisResult.chosen` actually used, even when the two differ for the same function.
9. **F vs. F′ distinction in the synth view**: for both an AOI-chosen and an OAI-chosen example
   result, the rendered map/groups match point 5's rule exactly — checked structurally, not
   eyeballed.
10. **Independent model-to-visual bridge check** (D17 acceptance-test-8's own pattern, applied
    here): every drawn group in the SVG corresponds to exactly one declared group in the model,
    covering exactly its declared cells — none missing, none extra, none wrong — located by
    stable identifiers, the same discipline the schematic renderer already follows.
11. **Browser-level coverage** (Playwright): group-to-term highlighting (selecting/hovering a
    term highlights its own group and vice versa, per the visual-design goal below), keyboard
    accessibility, responsive layout at narrow widths, "Download SVG"/export parity via the same
    live-DOM-clone technique D17 already proved out (never a re-serialized copy), and the same
    stale-result-clears discipline every other tab already follows (M1.2/M1.3, D17 test 10).

**7. Visual design** (owned by Codex; constraints only). Per the stated goal: each selected
group gets a visually distinct color with a matching label for its simplified term, so a student
sees at a glance which cells produce which term. Codex owns the concrete execution — including
how overlapping and wraparound groups are drawn — within these constraints, carried over
directly from D17's "no AI-generated/bitmap images, deterministic inline SVG" rule and this
project's existing accessibility bar:
- Group identity must be legible without relying on color alone (pattern, label placement, or
  an equivalent non-color cue) — colorblind-accessible by construction, not an afterthought.
- Cell values (0/1/dash) must stay legible where a colored group bracket overlaps or sits
  adjacent to them.
- Same "Download SVG" fidelity bar D17 established: the exported file is the same checked DOM,
  never a separately-serialized copy.

**8. Phasing** (per direction: design both consumers together in this one entry, implement in
reviewed stages):
1. **Shared model + grouping + verified explanations** — the K-map data model (grid layout,
   Gray-code mapping, structured groups, D11 narration) built on `simplify.py`'s existing
   algorithm, with its own structural test suite (acceptance tests 1-9). No rendering yet.
   Reviewed and approved before phase 2 starts.
2. **Standalone K-map view** — the web UI tab + `kmap` CLI subcommand, rendering phase 1's model
   per the visual-design goals. Reviewed (including acceptance tests 10-11) before phase 3
   starts.
3. **Synthesis integration** — the same model/renderer embedded in `synth`'s report, wired to
   `SynthesisResult.chosen` per point 5, with its own targeted review of the F/F′ correctness
   rule specifically.

Each phase is its own PR(s), independently reviewed by Claude in an isolated environment before
merge — the same adversarial-review discipline as D17's four rounds.

**Date:** 2026-09-19 (proposed); reviewed/amended 2026-09-20 under the owner's explicit
implementation authorization. Phase 1 only proceeds now; independent review precedes Phase 2.


### D18 review clarifications — 2026-09-20 (before implementation)

These clarify/supersede ambiguous wording above:

- **Polarity:** zero-groups yield an SOP for F′, or, after complementing each product
  into a sum and ANDing, a POS for F. Those are different expressions, never the same
  formula with a different output label. The model records both the grouped-target SOP
  and the resulting expression for F. AOI reads chosen.f_prime directly as that target SOP;
  OAI structurally complements chosen.f_prime to recover its original SOP for F. Unsupported
  shapes are rejected rather than expanded, reoptimized, or guessed. Existing AOI/OAI ASTs
  (including bare literals/products) are reconstructible. The synthesis adapter must check
  exact AST round-trip back to the chosen expression, not equivalence alone.
- **Grid choice:** first floor(n/2) variables on rows, remainder on columns: 1×2, 2×2,
  2×4, 4×4. This is an explicit product convention, not a claim that transposed maps are
  mathematically wrong. Zero-bit row labels are the empty bit string. Variable order is
  the supplied order, never alphabetical sorting. Minterm numbering remains binary.
- **Scope:** K-map Phase 1 supports 1–4 variables; this does not assert every existing
  derivation/minimization endpoint has the synthesis variable cap.
- **Reuse:** the existing Expr-returning minimizer already retains sufficient cube structure
  to recover exact group membership without parsing text. No optimization refactor is needed.
  A small additive prime-pattern query may expose the existing QM output for essentiality;
  production code must not introduce a second minimizer. Synthesis reconstruction never calls
  minimal_covers/minimize again; examining all primes for essentiality is not cover selection.
- **Constants:** SOP with no required ones is F=0/no groups; POS with no required zeros is
  F=1/no groups. If at least one required target cell exists and every other cell is a
  don't-care, one whole-map group yields F=1 (SOP) or F=0 (POS). Thus an entirely unspecified
  map deterministically chooses 0 in SOP and 1 in POS; both are valid and explicitly reported.
  A standalone map may be constant even though CMOS synthesis currently rejects constant
  networks; this phase does not change that existing synthesis behavior.
- **Don't-cares:** keep the original X value, group-membership/used status, and selected F
  assignment separately. An uncovered X is assigned 0 for SOP or 1 for POS. A used X takes
  the grouping value. Integration checks assignments against the chosen candidate including
  the engine's verification.dont_care_assignments; it never erases input provenance.
- **Essentiality:** essential means a prime implicant uniquely covers a required target cell
  among ALL legal prime implicants, not merely among selected groups. Store witness minterms.
  Do not add a group containing only don't-cares. Record term count/literal count and all
  tied standalone expressions, but do not claim to minimize transistor count.
- **Verification:** separately enumerate legal Boolean cubes in the checker (at most 3^4)
  to verify prime/essential status and optimal standalone cover cost without relying on QM
  or Petrick. Recompute fixed/varying variable facts from group members, prove complete cube
  membership (a power-of-two count alone is insufficient), exact legal cell membership,
  required coverage, term polarity, deterministic IDs, expression equivalence on all care
  rows, and don't-care assignments. Verify row/column mappings and visible rectangle pieces
  against their actual cell sets; wrapped pieces remain one group with one ID.
- **Additional acceptance tests:** invalid inputs, variable permutations/letter-digit names,
  all-X maps in both forms, checker mutation tests (wrong membership, diagonal/non-cube group,
  wrong polarity/explanation/essentiality, missing or duplicate coverage, wrong grid/pieces,
  source substitution), determinism across hash seeds, exhaustive fully specified 1–3-variable
  functions and 1–2-variable ternary tables, representative 4-variable tables. Test the
  synthesis tie case where inverter cost chooses a different cover from standalone D5.
- **Phase boundary:** Phase 1 exposes immutable Python model objects and builders, including
  a synthesis adapter and input provenance on SynthesisResult. It changes no CLI output,
  existing API JSON, schematic, or web interface. Browser overlap/geometry/export assertions
  (including actual path coverage, not merely data-* labels) land with Phase 2. Phase 3 wires
  the adapter into synthesis UI without rerunning synthesis or selecting a new candidate.

### D18 worked-group explanations — 2026-09-20

Owner-requested addition following Phase 2 coursework testing: show group IDs,
canonical minterm sums (SOP) or maxterm products (POS), literal expansions, and
an expandable expression/law/reason table. Preserve existing group highlighting.
Use pairwise distributive, complement, and identity steps from each actual cube;
verify every intermediate expression against the group's cell set over every
input vector before presenting it. Mark original X members and their selected
assignment explicitly. This is explanatory work, not a change to cover selection.
Include the worked steps in Copy explanation / CLI, expand the SVG legend with
cell notation and literal expansion, and provide a collapsible Boolean-law
reference. Full step tables remain in the UI/text report to keep SVG diagrams
manageable. Owner authorized implementation directly in the conversation.

## D19 — Implemented and shipped. What does a SPICE netlist export show, and how is it built?

**Current status (2026-09-21):** both phases shipped and independently reviewed:
Phase 1 exporter/model and ngspice verification in PR #13; Phase 2 CLI/UI
integration in PR #14. PRs #15–#16 added the accessible SPICE help disclosure and
card presentation. Model assumptions and compatibility limits remain unchanged.
The following specification and review history are retained for traceability.

**Review history:** drafted by Claude (2026-09-21); revised after Codex's first review (`715a210`) and
second review (`13e5459`). **This is the third revision.** Codex's third pass confirmed the
architecture and the supply/port fixes from round 2 are sound, and found **one more blocking
naming bug** (device names, point 1 below) plus four targeted precision/consistency corrections
(points 2-5) — no redesign, same architecture throughout all three rounds. The device-naming bug
was independently reproduced against the actual code before being accepted, same discipline as
every prior bug in this entry. At that revision, final review and owner authorization were
still pending; they have since been completed as recorded above.

**Trigger:** the charter's own original v1 scope (§6: "SPICE netlist export") — deferred since
M1b alongside K-map rendering and the schematic, both of which have since shipped (D17, D18).

**Scope: one new consumer, no new modeling.** Unlike D17/D18, this needs no new topology
computation — `schematic.py`'s already-built, already-verified `Layout` (D17 Phase A) has every
electrical fact a netlist needs: `Device.kind`/`.gate_net`/`.source_net`/`.drain_net`/`.role`,
`Layout.vdd_net_id`/`gnd_net_id`/`output_net_id`/`var_order`/`primary_nets`/`complement_nets`/
`inverter_driven_vars`, and `Net.label` (a net's human-facing display name, distinct from its
fixed internal id — e.g. the output net's `id` is always literally `"OUT"`, D17 point 3, while
its `label` carries whatever `output_name` was actually requested). This entry is a
**presentation/export layer over that existing model**, never a second circuit-construction path
— must build from `Layout` only, never re-derive connectivity independently.

**1. Every SPICE identifier — nets, ports, subcircuit/model/device names — is synthetic and
safe; nothing is exempt, including VDD and ground.** Two separate bugs in the first revision,
both closed here:
   - **(Codex, round 2) SPICE subcircuit scoping doesn't work the way the first revision
     assumed.** A non-global node not listed as a formal `.SUBCKT` port is *local to that
     subcircuit instance* — a net literally named `VDD` inside a `.SUBCKT` that doesn't declare a
     `VDD` port is **not** the same node as an outer-scope net of the same name; each instantiation
     gets its own fresh local `VDD` node, disconnected from the real supply. The first revision's
     "`VDD` is referenced directly inside the subcircuit body, not a formal pin" claim was simply
     wrong about how SPICE scoping works (the one exception, `.GLOBAL` directives, was never
     specified and isn't used here). **Fix: both `VDD` and ground are explicit, formal `.SUBCKT`
     ports** — no net is special-cased as implicitly visible.
   - **(Round 1 already established, restated for consistency) Case-insensitive collisions.**
     `Layout`'s raw net ids (`net_a` vs `net_A`) collide under SPICE's case-insensitive node
     matching — reproduced independently on `(aA)'` before round 1 was written; still fixed the
     same way.
   - **(Codex, round 2) Identifier safety isn't only a net-naming problem.** `.SUBCKT` names,
     `.model` names, and device names all need the same safe-character discipline, and none of
     them should ever embed `Device.literal` (explicitly documented in `schematic.py` as
     "display-only rendering... never read for correctness") — e.g. a complemented literal like
     `b'` contains a character (`'`) that has no business inside a SPICE token.
   - **(Codex, round 3) Reusing `Device.id` verbatim — round 2's own fix — is itself a blocking
     bug, and case-insensitive collisions aren't limited to nets.** Reproduced independently
     before accepting this: `synthesize_from_input(expr='aA')` (plain `aA`, not `(aA)'` — this
     specific shape needs internally-generated inverters for both variables) produces
     `Layout.devices` with ids `INV_A_N`, `INV_A_P`, `INV_a_N`, `INV_a_P`, alongside `M0`-`M3`.
     Lower-cased, `INV_A_N`/`INV_a_N` collide, as do `INV_A_P`/`INV_a_P` — the exact same class of
     case-insensitive collision round 1 already fixed for nets, just missed for devices. Worse:
     these ids start with `I`, but a SPICE element line's *leading character* determines its type
     (`M` = MOSFET, `I` = independent current source) — emitting `INV_a_P drain gate source bulk
     model` would either fail to parse as a MOSFET or be silently misread as declaring a current
     source, not a transistor. Round 2's "device names reuse `Device.id` directly, already safe"
     claim was wrong on both counts.
   - **Resolution, replacing round 2's point 1 in full:** every SPICE-syntax identifier is drawn
     from one of three small, fixed, deterministic synthetic schemes, never from `Layout`/`Device`
     data verbatim:
     - **Nets/ports**: `n0`, `n1`, `n2`, ... — first assigned, in order, to every entry in
       `Layout.nets` (its own deterministic order; VDD and ground get `n<i>` like everything else,
       no exemptions); **then**, continuing the same sequence, one more `n<i>` for each
       **unconnected declared-input port** (point 2), allocated in `var_order` order — so these
       never collide with a real electrical net's synthetic name, and their allocation order is
       itself deterministic.
     - **Devices**: `m0`, `m1`, `m2`, ... assigned once, in `Layout.devices`' own deterministic
       order — never `Device.id`. Lower-case `m` (SPICE element-type detection is case-insensitive,
       so this is exactly as valid as `M0` while staying consistent with the file's general
       lowercase convention).
     - **Models/subcircuit**: fixed literal constants, the same for every export —
       `ohmwork_gate` (subcircuit name), `nmos_model`, `pmos_model`. Sufficient for v1, which
       exports exactly one gate per file (multi-output/multi-gate netlists are excluded, point 6)
       — no per-gate derivation or stripping logic needed, and therefore no separate safety
       analysis for a derived name.
     Collision-free by construction within each scheme (pure lowercase-ASCII-and-digit tokens,
     never user-influenced casing or characters), and the three schemes can never collide with
     each other since they use disjoint prefixes (`n`/`m`/fixed words) and SPICE keeps node names
     and element-instance names in separate namespaces regardless.
   - **`Device.id` (`M0`, `INV_a_P`, ...) is preserved only in mapping comments**, never as a
     SPICE token — same rule point 1 already established for net ids.
   - **Traceability preserved in comments, three-way for nets, one-way for devices**: for every
     net, one comment line records **(a)** the synthetic name, **(b)** the `Layout` net id when
     the net corresponds to one (some don't — point 2), and **(c)** the net's `Net.label` and a
     plain-English **role** (primary input / external complement input / unconnected declared
     input / output / supply / ground / internal junction). This is what makes a custom output
     name like `Y` traceable end to end even though its `Layout` id stays the fixed `OUT` —
     confirmed by construction: `Net.label` for the output net already carries the requested
     `output_name` (verified directly: `build_textbook_schematic(synthesize_from_input(expr='a'),
     'Y')`'s output net has `id='OUT'`, `label='Y'`). For every device, one comment line records
     its synthetic name (`m<i>`) and its original `Device.id` (`M0`, `INV_a_P`, ...).
   - **Regression tests** (added to point 8): the `(aA)'` net-collision case; **`aA` (undecorated
     — the shape that actually needs internally-generated inverters), asserting device names are
     case-insensitively unique and every one begins with `m`** — Codex's instruction that a bare
     safe-character regex is insufficient is followed exactly: this is a dedicated assertion, not
     folded into the general identifier-safety sweep; the custom-output-name traceability case
     (`Y`) asserting the comment for the output net shows all three of synthetic name / `OUT` /
     `Y`.

**2. Port list: fixed pin order and count driven by `var_order`, not by which nets happen to
exist — Codex's "port-list contradiction" reproduced and closed.** Codex gave two concrete cases;
both reproduced independently against the actual code before accepting this point:
   - `variables=a,b`, `ones=2,3`: `var_order=['a','b']`, but `b` never appears anywhere in the
     synthesized circuit at all — `Layout.primary_nets=(('a','net_a'),)`,
     `complement_nets=(('a','net_a_n'),)`, and `b` is absent from `Layout.nets` entirely. A port
     scheme built by iterating `primary_nets` (the first revision's approach) would simply have no
     port for `b` — an interface that silently varies in size/shape depending on what the
     minimizer happened to need, not on what the user declared.
   - `expr=a`, `dual_rail=True`: `var_order=['a']`, but `Layout.primary_nets=()` (empty) while
     `complement_nets=(('a','net_a_n'),)` — the chosen circuit uses only `a`'s external complement,
     never `a` itself. The first revision's rule ("one pin per `primary_nets` entry, plus a
     complement pin for dual-rail-external ones") would emit a complement pin for `a` with **no
     corresponding primary pin at all** — an inconsistent, self-contradictory interface.
   - **Resolution, replacing the first revision's pin-order rule in point 2:** the port list is
     built by **traversing `var_order` directly**, never by iterating `primary_nets`/
     `complement_nets` and hoping every declared variable shows up:
     1. For every variable in `var_order`, in order: **always emit exactly one primary port.**
        If the variable has a `Layout.primary_nets` entry, that port connects to the mapped
        synthetic name for that net. If it doesn't (the `b` case above), the port is still formally
        declared — a real, connected-to-nothing `.SUBCKT` pin — and tagged in the trailing comment
        as an **unconnected declared input** (a legitimate, documented case, not a bug).
     2. Then, for every variable in `var_order`, in order, whose complement is an *external*
        dual-rail input (`var` has a `Layout.complement_nets` entry **and**
        `var not in Layout.inverter_driven_vars`): emit one additional complement port, connected
        to the mapped synthetic name for that net. This correctly covers the `a`/dual-rail case:
        `a` gets both its (unconnected) primary port and its (connected) complement port, a
        consistent pair rather than an orphaned complement.
     Full fixed pin order: `.SUBCKT ohmwork_gate <output> <VDD> <ground> <primary ports,
     var_order order> <external complement ports, var_order order>`.
   - **Net inventory closure test, adjusted per Codex's instruction**: partitioned into two
     checks rather than one blanket rule — every **connected** port/net name must map to a real
     `Layout` net (as before); every **unconnected declared input** must be a formal port that is
     *not* wired to any device terminal anywhere in the emitted body — checked structurally, not
     just by trusting its comment label.
   - **Regression tests** (added to point 8): both reproduced cases above, each asserting the
     exact resulting port list/order/connectedness.

**3. Two generated artifacts, connectivity fully separated from analog assumptions.** Unchanged
core structure (a non-runnable `.SUBCKT` connectivity template plus a separate, clearly-labeled
educational simulation example, both from the same device records). **Round 2's own explanation of
*why* a bare `LEVEL=1` card is insufficient was itself imprecise and is corrected here (Codex,
round 3):** it is not that `VTO=0` "causes conduction at zero gate-source bias" — that overstates
a specific electrical failure mode this document isn't positioned to assert precisely. The actual
problem, stated exactly as Codex specified: **bare `LEVEL=1` relies on simulator defaults rather
than an explicitly documented educational model. The example therefore specifies its model
parameters, including signed NMOS/PMOS threshold voltages** (NMOS `VTO` positive, PMOS `VTO`
negative, per SPICE's own sign convention — round 2 never specified sign; round 1's "no numeric
parameters" framing is what this corrects).
   - **`.SUBCKT` template**: unchanged — no `.model` cards defined at all, `M` lines reference
     undefined model names, every `W=`/`L=` is the non-numeric token `TBD`. Deliberately cannot be
     simulated as-is.
   - **Educational example**: full numeric `.model nmos_model NMOS(LEVEL=1 ...)` /
     `.model pmos_model PMOS(LEVEL=1 ...)` cards (lowercase fixed model names, point 1) specifying
     **explicit numerical educational parameters** — a deliberate term, not "fabrication-validated"
     ones; this project makes no claim these values are validated against a real fabrication
     process. **Not every parameter needs a nonzero value** — a deliberately, explicitly chosen
     zero (e.g. `LAMBDA=0` to disable channel-length modulation as a stated simplification) is
     legitimate; what's required is that every value present is a deliberate, documented choice,
     never an unstated simulator default. Threshold voltages specifically must be explicit and
     correctly signed (above). Supply: `VDD = 5V DC` (a plain, widely-recognized illustrative test point,
     not a fabricated physical parameter — safe to pin directly). Sizing: one uniform `W=10u L=1u`
     for every transistor, clearly labeled illustrative/arbitrary. Output thresholds for the
     point-4 harness: output ≤ 20% of `VDD` reads as logic-0, ≥ 80% reads as logic-1, anything in
     between is an **ambiguous level that fails the test**.
   - **Parameter sourcing may be completed during Phase 1 implementation, not in this document**
     (Codex, round 3, explicitly accepting deferral) — **on the condition that Phase 1's own
     review requires, as part of that PR, the complete numeric `.model` cards, their exact
     citation, a stated list of assumptions (which effects are modeled vs. deliberately zeroed),
     and successful simulation results demonstrating the example actually produces correct logic
     levels across the acceptance battery.** This is a required Phase 1 review-gate item, not an
     optional nice-to-have — see point 9.

**4. ngspice verification: exhaustive input+complement sweep, required in CI, optional only
locally.**
   - The harness enumerates **every one of the 2^n logical input vectors** over `var_order` (not
     just the connected primary ports). For each vector, it drives every exposed **primary** port
     to that vector's value where connected, and — per Codex's instruction — drives every exposed
     **external complement** port to the logical NOT of its corresponding variable's value for
     that vector, **including for a complement-only variable** (point 2's dual-rail `a` case: `a`'s
     primary port is unconnected internally, but its complement port is real and must still
     receive the correct, vector-dependent driven value; formally unconnected does not mean
     undriven — every instantiated `.SUBCKT` port needs a source on it regardless of whether the
     subcircuit body itself uses it).
   - Pinned supply/model/sizing/thresholds from point 3's educational example, applied
     consistently across the whole sweep.
   - **Complete failure handling, every category explicit** (Codex, round 3 — tightened from
     round 2's non-convergence/ambiguous-level pair): the harness **rejects** — fails the test, in
     every case, for that input vector — a **missing output value** (ngspice reports nothing for
     the output node), a **non-finite output value** (`NaN`/`Inf`, e.g. from a solver edge case or
     an output-parsing failure), **non-convergence**, and an **ambiguous output level** (point 3's
     20%/80% band). None of these are ever silently skipped, defaulted, or rounded to a guess.
     **Don't-care rows are checked against `result.verification.dont_care_assignments[minterm]`**
     specifically (the chosen circuit's own actual reported value), never against "any" logically
     acceptable one.
   - **CI requirement, tightened per Codex's instruction**: the dedicated CI job installs
     `ngspice` explicitly and **must fail if that installation doesn't succeed or the binary isn't
     found** — a missing tool in CI is a job failure, never a silent skip, since a silently-skipping
     required check defeats the point of requiring it. **Local runs are the only place a
     missing-`ngspice` skip is allowed** — `pip install -e ".[dev]"` and ordinary local test runs
     never need `ngspice` present, matching how the Chromium suite already self-skips locally.

**5. Compatibility claims, qualified to what's tested — and to the right artifact.** The netlist
targets portable SPICE3-style syntax intended to be readable by common simulators (ngspice,
LTspice, HSPICE), but **only ngspice compatibility is actually verified**, and — Codex's
correction — that claim applies **only to the educational example**, the one artifact that's
actually simulated (point 4). The `.SUBCKT` template is deliberately non-runnable (point 3's `TBD`
tokens, undefined model references) and no compatibility claim of any kind applies to it.
Documentation/file comments must say exactly this: "the educational example is tested with
ngspice; it and the connectivity template are written in portable SPICE3-style syntax intended to
work with other simulators, which are untested."

**6. What stays excluded** (unchanged from D17 point 6): real transistor sizing as a *design
output* (point 3's illustrative example is explicitly not that), body-effect modeling beyond
whatever the cited educational parameters happen to imply, analog parasitics, physical
layout/DRC, arbitrary non-series-parallel circuits, multi-output netlists.

**7. CLI/UI surface.** Mirrors D17/D18's established pattern: a `--netlist` flag/output mode on
`synth` (CLI), and "Download SPICE netlist" button(s) beside "Download SVG" in the web UI's
synthesis report (server-side generation from `Layout`, no client-side reconstruction). Deferred
to Phase 2 — see point 9. Exact flag names/UI copy left to implementation.

**8. Acceptance tests** (supersedes the first revision's list in full):
1. **Structural round-trip**: the point-2 port-list algorithm, applied to `Layout`, produces
   exactly the documented ports in the documented order; every `Layout.device` appears exactly
   once with its own synthetic drain/gate/source/bulk nets in the documented column order —
   checked by parsing emitted text back into structured records and comparing against `Layout`,
   never eyeballed.
2. **Net inventory closure (partitioned)**: every connected port/net maps to a real `Layout` net;
   every unconnected declared input is a formal port wired to no device terminal anywhere in the
   body; the comment-mapping is exactly bijective with the nets it documents.
3. **Case-insensitive net-naming collisions**: `(aA)'` and a 3-variable case-differing set
   (`a`/`A`/`a0`) — lower-cased emitted net/port names contain zero duplicates.
4. **Device naming, checked separately and explicitly — a safe-character regex alone is
   insufficient** (Codex, round 3): `aA` (undecorated — the shape that actually needs
   internally-generated inverters, producing `Layout` device ids `INV_A_N`/`INV_A_P`/`INV_a_N`/
   `INV_a_P` alongside `M0`-`M3`) — assert (a) every emitted device name is unique even when
   lower-cased, and (b) every emitted device name begins with `m`, the required MOSFET-instance
   leading character. Both assertions are structural/positional, not just a regex match.
5. **Synthetic-name allocation completeness**: since no identifier is ever derived from a
   variable name or `Device.id` (point 1), this is no longer a "safety" concern but a coverage
   one — across the full D8 variable-name alphabet (letters plus optional trailing digit,
   including large net/device inventories within the supported 1–4 variable inputs), the
   `n<i>`/`m<i>` allocation stays deterministic, complete
   (every `Layout` net/device and every unconnected declared input gets exactly one name), and
   collision-free; no `Device.literal` content ever appears as a token, only in comments.
6. **The two port-list-contradiction regressions**, reproduced exactly: `variables=a,b ones=2,3`
   (unconnected `b` primary port present, correctly tagged) and `expr=a dual_rail=True` (`a`'s
   primary port present-but-unconnected, its complement port present-and-connected).
7. **Custom output name traceability**: `output_name='Y'` — the output net's comment shows its
   synthetic name, `Layout` id `OUT`, and label `Y` together.
8. **Device count matches the report**: exactly `SynthesisResult.total_transistors`, across
   NAND3/NOR4/AOI31/AOI21 (shared inverter)/AND (dual-simultaneous-shared-inverter)/dual-rail/wide
   (40T) cases.
9. **Device/model polarity**: every `kind=="p"` device references `pmos_model`, every `"n"`
   device references `nmos_model`, in both artifacts.
10. **Bulk convention**: every PMOS device's bulk is the mapped `VDD` port/net, every NMOS
    device's bulk is the mapped ground port/net — no exceptions, and (per point 1) never the
    literal strings `VDD`/`GND`/`0` inside the `.SUBCKT` body.
11. **Shared inverters**: one shared inverter feeding multiple gates emits exactly one inverter's
    worth of devices, wired to every consumer.
12. **Wired vs. textbook `Layout.style` equivalence**: exporting the same `SynthesisResult` from
    both schematic layouts yields electrically equivalent netlists (same roles/kinds, same
    net-equivalence classes under the point-1 mapping) even if geometry/internal ids differ.
13. **Determinism**: identical `Layout` input produces byte-identical netlist text across runs and
    `PYTHONHASHSEED` values.
14. **Mutation tests**: wrong bulk assignment, swapped drain/source, a missing device, two
    distinct `Layout` nets or devices mapped to the same synthetic name, a shuffled port order, an
    unconnected port incorrectly wired to a device, a complement port driven to the *same* value
    as its variable instead of its logical NOT (point 4) — each independently caught by the tests
    above.
15. **(CI-only, dedicated job)**: the exhaustive ngspice sweep itself (point 4) — every input
    vector, correct complement-driving including complement-only variables, don't-care check
    against `dont_care_assignments`, and all four failure modes (missing output, non-finite
    output, non-convergence, ambiguous level); the job fails outright if `ngspice` isn't available
    rather than skipping.

**9. Phasing — adopts Codex's recommendation directly** (the first revision left this
undecided; round 2 gave a concrete split, taken as-is; unchanged in round 3):
   - **Phase 1**: export records, naming/ports (points 1-2), the `.SUBCKT` template, structural
     and mutation tests (point 8, tests 1-14), the educational example (point 3, **including the
     Phase-1 review-gate requirement**: complete model cards, citation, stated assumptions, and
     successful simulation results across the acceptance battery), and the required dedicated
     ngspice CI job (point 4/8 test 15) — the fully self-verifying exporter, reviewed and merged
     with no UI attached yet.
   - **Phase 2**: CLI/UI integration (point 7) — downloads, filenames, export parity with the
     existing schematic/K-map download pattern, stale-result clearing, explanatory text.
   - Each phase its own PR, independently reviewed before the next starts — same discipline as
     D18's three phases.

**Claude's read on Codex's round-3 review, for the owner:** no technical disagreement with any of
the five points. The device-naming bug (point 1) was independently reproduced against the actual
code before being accepted — `aA` really does produce case-colliding, wrongly-`I`-prefixed device
ids under round 2's own "reuse `Device.id`" rule, which I should have tested at the same time I
tested the net-naming collision rather than assuming device ids were safe by analogy. Points 2-5
are consistency/precision corrections I agree with outright, including Codex's correction of my
own imprecise `VTO=0` explanation (replaced verbatim with the wording Codex specified) and the
explicit acceptance that parameter sourcing defers to Phase 1's own review gate rather than
needing to be pinned in this document. Across all three rounds, the pattern has held: every
concrete, checkable claim — mine or Codex's — gets independently reproduced against the real code
before being written into or accepted into this entry, not taken on trust either direction.

**Date:** 2026-09-21. Phase 1 authorized following final review of `8d227a8`, shipped and
independently reviewed clean as PR #13 (`4efad85`); Phase 2 (CLI/UI integration) authorized the
same day. Phase 1 implementation details, exact model citation, assumptions, and reproduction
instructions: [SPICE Phase 1](spice.md).


### v1 closeout reconciliation — 2026-09-21

The owner authorized implementing the charter's remaining CSV export and reconciling
shipping status after the final product sweep. CSV uses the existing DerivationTable:
one header row followed by binary 0/1 rows in the existing variable/column order.
CLI `tt --csv` is mutually exclusive with Markdown/LaTeX and respects `--terse`/`--cols`.
The web Download CSV button exports the displayed derivation, generated server-side
with the same formatter. Files use UTF-8, comma delimiters, standard CSV quoting,
and LF record endings, without a BOM, prose footer, or extra blank record.

This fulfills an existing scope item, without changing minimization or synthesis.
D16's bounded search space, the 1–4-variable K-map/synthesis limits, and the explicit
multi-stage decomposition deferral remain in force. The CSV/documentation
PR is the final implementation closeout item. Independent review and release approval
are tracked on that PR, rather than asserted here before review takes place.
