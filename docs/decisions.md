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

## D17 — APPROVED. Phase A implemented; Phase B pending. What does a real transistor-level schematic show, and how is it built?

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
wiring, "Download SVG", acceptance tests 8 and 10) is not yet started.** This entry exists
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
     no named-net port exists that isn't backed by a real device gate terminal — ruling out
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
