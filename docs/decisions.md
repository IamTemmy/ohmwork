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
