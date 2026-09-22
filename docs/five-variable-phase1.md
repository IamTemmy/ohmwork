# D20 Phase 1 review handoff

Status: implemented for independent review, not public five-variable enablement.
Based on the D20 proposal in PR #20 (`96a233b`), with its review clarifications
recorded in decisions.md. The owner authorized starting the build.

## What changed

- Private five-variable synthesis core behind the existing public four-variable
  wrapper. Same candidate ranking, shared-inverter accounting, stack filtering,
  and electrical verification.
- Private standalone and synthesis K-map builders accept five variables. Cells
  and rectangle pieces carry plane numbers; the container names its plane
  variable/labels. Global group identities and memberships are retained.
- Independent validator checks all 32 positions, plane-aware rectangle coverage,
  maximal components, prime cube membership, assignments, and full tied-cover
  inventories. Worked proofs still independently evaluate every step.
- Public synthesis rejects unsupported expressions before truth enumeration.
  Public API/CLI/UI remain at four variables until Phase 2. Existing K-map
  presentation functions reject internal two-plane models rather than flattening
  them incorrectly. No UI/CSS implementation is included.
- Exact-search safety: deterministic work/storage budgets raise on exhaustion;
  never return an incomplete cover list or claim a partial answer is minimum.
- Required performance CI job plus expanded existing required ngspice suite.

## Performance finding and correction

The first direct Petrick implementation exceeded a 2,000,000-operation budget
on this reproducible case:

- ones: 3,5,6,7,8,9,12,13,18,19,21,22,25,26,29,30
- don't-cares: 1,4,10,11,14,16,23,27,31

The implementation now deduplicates/reorders clauses, tests absorption against
surviving shorter subsets, and prunes partial products larger than a *witnessed
complete cover*. This last bound is exact: a minimum cover cannot have more
terms than an already constructed valid cover, and multiplying clauses cannot
remove terms from a partial product. The greedy witness is not a selected answer;
all minimum ties still survive. This fixture now produces all **149 SOP and 4
POS ties**, agreeing with the independent recursive cover oracle. Its combined
synthesis candidate inventory has 153 entries in each rail mode.

Measured locally on Linux x86_64, Python 3.12: 70/70 benchmark fixtures completed.
The slowest was that fixture at 0.10548 seconds, maximum observed process RSS
14,720 KiB, maximum per-search work 18,349 and storage counter 2,699 items.
Wall time includes both standalone maps and both rail-mode syntheses with their
integrated models, but excludes rendering and child-process startup. RSS includes
the interpreter. CI captures the complete input fixtures and measurements as an
artifact. These results are not exhaustive over all five-variable truth tables.

Production per-search limits: 2,000,000 work units and 20,000 frontier/cache
items. The separate benchmark gate requires each child process to finish within
10 seconds and 128 MiB RSS. Limits fail explicitly, without partial answers.
Derivation has no newly introduced budget. Optimizations preserve its exact
results as checked by the existing tests.

## Validation and reproduction

```bash
python3 -m venv .venv
./.venv/bin/pip install -e '.[dev]'
./.venv/bin/pytest -q --ignore=tests/test_webui_browser.py --ignore=tests/test_kmap_browser.py --ignore=tests/test_spice_ngspice.py
OHMWORK_REQUIRE_NGSPICE=1 ./.venv/bin/pytest tests/test_spice_ngspice.py -q
./.venv/bin/python tools/benchmark_five_variables.py
```

ngspice is a system dependency, required in its CI job and optional locally.
The expanded analog battery checks **776 operating points**: the prior 328 plus
448 five-variable points (seven fixtures, two rail modes, all 32 vectors).
Fixtures include the professor's AOI32, NAND5, NOR5, OAI, shared inverters,
case-sensitive/unused inputs with complement-only dual-rail ports, and asymmetric
cross-plane don't-cares. Every deck drives external complements and checks the
chosen circuit's actual don't-care assignments. All 67 ngspice tests passed locally.

The new model tests cover all 243 cubes and worked proofs, both polarities,
constants/all-X, asymmetric X usage, malformed plane/cell/piece mutations,
non-cube mutation, arbitrary variable names, stacks, parity, both rail modes,
wire/textbook SPICE equality, seeded tied covers, hash determinism, and exhaustion.
No new browser behavior is claimed by this phase; the existing browser job remains
required for public four-variable regression coverage.

## Review focus

Please independently inspect the safe cardinality pruning and tied-cover
preservation, both budget failure paths, plane metadata/geometry, and the
phase boundary. Confirm the numeric gates and public error behavior before
Phase 2 starts. Phase 2 still needs two-plane SVG/CLI/UI, accessible shared
selection/proofs, downloads, and browser verification at desktop/mobile sizes.
