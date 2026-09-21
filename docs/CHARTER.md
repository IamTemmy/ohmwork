# Ohmwork — Project Charter

**Status (2026-09-21):** the v1 feature set is implemented, including CSV export.
Final release approval is recorded through independent PR review; this status does
not itself create a release or version tag.
D17 schematics, D18 K-maps (including synthesis integration), and D19 SPICE export
have shipped. Decisions D1–D19 remain authoritative. Earlier M1 exclusions below
record the historical milestone scope, not the current shipping status.
**Owner:** Temiloluwa Adesola (@IamTemmy)
**Collaborators:** Claude (via Claude Code), ChatGPT
**Name:** Ohmwork

---

## 1. Mission

Ohmwork does digital logic work at the speed of typing, and shows its work at every step.

Given a Boolean expression, it produces a full derivation table — a column for every intermediate term, not just the final output — so a hand-worked solution can be checked line by line rather than trusted wholesale. Given a truth table, it produces the minimized form, the K-map with groupings drawn, a transistor-level static CMOS schematic, the transistor count, the gate's name, and a SPICE netlist.

Both directions share one engine. Every synthesized result is checked by simulating the generated transistor network back against the original specification before it is returned.

The tool exists to compress hours of mechanical work into minutes without hiding the reasoning. It is a verification instrument first and a shortcut second.

## 2. Vision

The tool a digital logic or VLSI student reaches for the way a calculus student reaches for Wolfram Alpha — not to skip the work, but to check it, and to see the reasoning laid out when they are stuck.

Longer term, Ohmwork grows from a single-gate synthesizer into a teaching-grade circuit workbench: multi-output functions, alternative logic families, delay and sizing estimates, and eventually topics from advanced circuit theory beyond digital logic. The name is deliberately not tied to K-maps or CMOS so that growth does not require a rebrand.

## 3. Origin and audience

The project comes out of two courses: undergraduate Digital Logic and graduate CPE 635 Advanced Circuit Theory. The immediate user is the author, solving and checking his own coursework. The natural next users are classmates, then anyone taking the same courses anywhere.

Adoption is the goal; monetization is not. There is no revenue model and none is planned.

## 4. Why build rather than adopt

This section exists to be falsified. If any of it stops being true, the project's justification weakens and that should be said out loud.

The landscape as of drafting:

- **Boolean minimizers and K-map solvers are abundant.** Dozens of truth-table generators on GitHub, plus mature web K-map tools. This half of the problem is solved and Ohmwork should not pretend otherwise — it should use the standard algorithms (Quine-McCluskey, Espresso) rather than reinvent them.
- **Circuit simulators are abundant.** Falstad, Digital, LTspice. They simulate circuits you draw; they do not synthesize them.
- **The gap is the last mile.** No maintained tool found that goes from truth table to a *minimum-transistor static CMOS schematic* with a transistor count and a gate name. Logic Friday came closest at the gate level and is dead and Windows-only.

Ohmwork's differentiator is therefore **synthesis plus verification**, not minimization. Two claims define it:

1. It answers the question courses actually ask — "minimum transistors, how many, what is it called" — end to end.
2. It never returns an unverified design. Every emitted network is exhaustively simulated against the source truth table first.

Claim 2 is the harder one to copy and the reason a student would trust it over a hand-rolled script.

## 5. Design principles

1. **Correct before clever.** A wrong answer delivered fast is worse than useless for coursework. Verification is a gate, not a feature.
2. **Show the work.** Every output includes the reasoning path: groupings, factored form, network derivation. A result with no derivation is a failure of the product even if the number is right.
3. **Deterministic.** Identical input yields byte-identical output. Tie-breaks are defined, not incidental. This is load-bearing for a multi-contributor project (see §8).
4. **Core is a library.** The engine is importable and UI-free. CLI, web, and anything else are thin shells over it.
5. **Honest about limits.** When the tool cannot prove a result is minimal, it says so rather than implying it.

## 6. Scope

### In scope for v1
- Boolean expression input in textbook notation
- **Derivation tables**: a column per intermediate sub-expression, in evaluation order, not just the final output column
- Output in terminal, Markdown, LaTeX, and CSV
- Truth table input (including don't-cares)
- Exact minimization for up to 5 variables
- Minimum-transistor **static CMOS** synthesis, single-output, within the D16
  single-stage AOI/OAI search space (1–4 variables)
- Transistor count, gate name, K-map render (1–4 variables), factored form
- SPICE netlist export
- Exhaustive verification of every emitted design

CSV exports contain table headers and binary data rows only; narrative explanations
remain in the other report formats. The original D1 aspiration of multi-stage
NAND/NOR decomposition remains explicitly deferred by D1's 2026-09-14 update and
D16. Five-variable exact minimization does not promise five-variable synthesis or
a five-variable K-map.

### Explicit non-goals for v1
- Pass-transistor, transmission-gate, dynamic/domino, or ratioed logic
- Multi-output / shared-logic optimization
- Transistor sizing, delay, power, or area estimation
- Physical layout, stick diagrams, or DRC
- Sequential logic (latches, flip-flops, state machines)
- Accounts, hosting, or any backend

Non-goals are not "never." They are "not until v1 ships and gets used."

## 7. Decisions requiring agreement before implementation

**These must be settled in `docs/decisions.md` before either collaborator writes the optimizer.** They are definitional, not stylistic — two correct implementations that disagree on these will produce different answers to the same problem and cost a day to reconcile.

Recommended defaults are given; the owner decides.

| # | Question | Recommended default |
|---|---|---|
| D1 | What does "minimum transistors" mean, and over what search space? | Minimize transistor count **over the implementation classes Ohmwork currently supports**, and report whether optimality was proven within that space. The supported space is declared explicitly in `decisions.md` and grows as the engine does — it is never claimed to be "all valid CMOS implementations." For v1 the space is: single-stage complex gates (AOI/OAI and their generalizations) plus NAND/NOR decompositions, with inverters counted per D2. Report the single-gate solution as primary when one exists; report multi-stage alternatives alongside. |
| D2 | Are complemented inputs free (dual-rail), or must inverters be counted? | **Counted.** Each required inverter costs 2 transistors. Provide a `--dual-rail` flag for the case where complements are given. |
| D3 | Is there a maximum series stack height? | **Unconstrained (textbook mode) by default.** The tool reproduces the answer a course expects rather than refusing a topology on manufacturability grounds. When a stack exceeds 4, emit an **advisory** noting that production designs typically cap there — context, not a veto. `--max-stack N` enables the engineering constraint. |
| D4 | How are don't-cares treated? | Assigned freely to minimize transistor count, with the assignment reported. |
| D5 | What breaks ties between equal-cost solutions? | Serialize each candidate to a **canonical form**, then compare lexicographically. Canonicalization is deliberately **shallow and cost-preserving**: flatten associative chains into n-ary nodes, sort commutative operands by a defined key (D10 variable order, then arity, then string). **No identity rewrites** — in particular no De Morgan — because those change transistor cost and would canonicalize away the very difference being priced. Must be fully deterministic. |
| D6 | What does the tool do when it cannot prove minimality? | Return the best found result, explicitly labelled as **not proven minimal**, with the search bound stated. Never imply optimality it has not established. |
| D7 | What counts as verification passing? | **Two independent checks, reported separately.** (a) *Functional equivalence*: the generated PDN/PUN network, simulated across all 2^n input vectors, matches the source truth table exactly. (b) *Static CMOS structural validity*: no input combination leaves the output floating or creates a VDD-to-ground short. Output reports vector count, floating states, and conflicts individually — never one generic pass. |
| D8 | What is the expression syntax? | Textbook notation: juxtaposition is AND (`xy`), `'` is complement, `+` is OR, `^` is XOR, parens override. **Variables are a single letter with an optional trailing digit** (`A`, `x`, `A0`, `B2`) so `ABC` unambiguously means A·B·C. Multi-character identifiers are not supported in v1; if added later they will require an explicit `*` operator. No bare overbars — ambiguous input is **rejected with an error, never guessed**. (Cf. `(ABC + D)'` vs `(ABC)' + D`, which are different functions.) |
| D9 | Which intermediate columns appear in a derivation table? | **Full breakout by default.** Every distinct sub-expression in the parse tree, in evaluation order, including complemented literals as their own columns — so `x'y + xy'` yields columns for `x`, `y`, `x'`, `y'`, `x'y`, `xy'`, `F`. Rationale: every term and section of a problem stays individually identifiable, which is what makes the table usable for locating an error rather than just confirming one. Deduplicated. `--terse` collapses to product terms and output; `--cols` takes an explicit list. |
| D10 | Variable ordering in output? | Order of first appearance in the expression, not alphabetical — matches how the user wrote it. |
| D11 | Does the tool explain *why* a K-map group reduces to a given term? | **Yes — this is a differentiating feature, not a nicety.** For each group, report which variables change across the minterms (eliminated) and which hold constant (kept, in true or complemented form), then the resulting product term. **The narration must itself be verified** against the minterm set before printing: recompute the term from the minterms and confirm it matches what the explanation claims. A confidently wrong explanation is worse than none. |
| D12 | Is a complemented input generated once and shared? | **Yes.** One inverter per complemented literal per design, costed at 2 transistors regardless of how many places it feeds — not one inverter per use site. Fanout effects are out of scope per §6. The optimizer must additionally weigh **restructuring to avoid the inverter entirely** against paying its 2 transistors; that trade is sometimes the whole difference between two candidates. |
| D13 | Implementation language? | **Python.** The algorithms are faster to write and test, it matches the owner's existing toolchain, and M1 is a local CLI. A browser version, if it happens, ports the core or wraps it — not a reason to pay a TypeScript tax now. |
| D14 | How is the tool kept approachable for an intro digital-logic user? | **Layered subcommands, not modes.** `tt` (derivation table), `kmap` (groups and explanations), `synth` (adds the transistor layer). Transistor content never appears unasked. Help text and README lead with `tt`; synthesis is listed last. Jargon in output is glossed inline on first appearance (e.g. naming what AOI31 means). **No separate "beginner mode"** — explicit modes double the test surface and drift out of sync. |

## 8. Milestone 1

M1 ships in two halves. **M1a is useful on its own and lands first** — the tool should be earning its keep on coursework before the synthesis engine exists.

### M1a — Derivation engine — **shipped 2026-09-13**

**Goal:** expression in → full derivation table out, fast enough to be worth opening.

**Deliverable:** parser for the D8 syntax, evaluation over all 2^n rows, a column per intermediate sub-expression, clean terminal rendering, plus `--latex` and `--md` output. Reports the simplified result alongside the table.

**Acceptance test:** `ohmwork tt "xy + xy'"` produces columns for `x`, `y`, `y'`, `xy`, `xy'`, and `F`, and reports `F = x`. Three further expressions of increasing depth, including one with nested parens and one XOR, render correctly. Ambiguous input is rejected rather than guessed.

### M1b — Synthesis engine — **shipped 2026-09-14**

**Goal:** truth table in → verified minimum-transistor static CMOS design out.

**Deliverable:** minimization, factoring, PDN/PUN construction, transistor count, gate name, ASCII schematic, and pass/fail verification, for 3–4 variables.

**Acceptance test:** Ohmwork independently reproduces all three answers from the CPE 635 Fall 2026 Exam #1 — 6 transistors / 3-input NAND, 8 transistors / 4-input NOR, 8 transistors / AOI31 — with correct derivations and passing verification.

**Deliberately excluded from M1 entirely:** K-map rendering, SPICE export, web UI, 5+ variables.

**Note (added 2026-09-15):** "web UI" above meant a hosted/browser-deployed product — the
thing D13 calls paying "a TypeScript tax" prematurely. M1.1 (below) is a different thing: a
strictly local, same-machine form front end for the existing CLI, in plain Python
(`wsgiref`) with no new dependency and no separate frontend toolchain — it doesn't port or
duplicate the core, it just gives the same engine a second, friendlier way to be typed into.
Recorded here rather than left to read as a contradiction.

### M1.1 — Local web UI — **shipped 2026-09-15**

Not part of the original M1 scope above; added afterward because remembering CLI flags was
real friction once M1 was actually being used. `ohmwork ui` starts a local server (stdlib
only) hosting form fields for `tt`/`synth`, wrapping the same `ohmwork.api` functions the
CLI itself calls — proven byte-identical to CLI output by test, not just asserted. No engine
or decision changed. Deliberately deferred: visual design/polish, until real coursework use
(§10) shows what's actually worth polishing.

Those acceptance tests are the milestones. Not "the code runs."

## 9. Working agreement

Claude and ChatGPT both contribute to the same repository, sequentially rather than concurrently: Claude builds Milestone 1, then ChatGPT reviews and extends.

Rules:

- `docs/decisions.md` is the single source of truth for every question in §7 and every one that arises later. Code that contradicts it is a bug in the code, not in the document.
- A collaborator who disagrees with a decision proposes a change to `decisions.md` and waits for the owner's call. They do not implement around it.
- Every decision entry records: the question, the choice, the reasoning, and the date.
- The second collaborator's first task on any milestone is to run the acceptance test independently before reading the implementation.

The purpose of the second perspective is to catch what the first one assumed. That only works if the assumptions are written down where both can see them.

## 10. Kill criteria

The project should be reconsidered, not quietly continued, if any of these hold:

- The author stops using it on his own coursework within a month of M1 shipping.
- A maintained tool is found that already does verified truth-table-to-transistor synthesis well.
- Reaching a trustworthy result takes longer than solving the problem by hand.
- It begins displacing higher-priority portfolio work rather than fitting around it.

---

*§7's decisions are settled (D1–D19, see `docs/decisions.md`) and M1 has shipped — this
charter is no longer a draft awaiting sign-off, though §9's process still applies to
anything that arises later. Scope and mission (§1–§6, §10) remain the standing reference.*
