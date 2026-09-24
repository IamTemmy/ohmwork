# D21 Phase 1: logic-gate foundation

Owner authorized incremental implementation on 2026-09-24. This phase is a
reviewable Python library foundation; there is no new UI tab or CLI command yet.
Review this before Phase 2 wires the model into interactive diagrams. Existing
CMOS/K-map/derivation behavior and their public limits remain unchanged.

## Commit sequence

1. `d5284fd`: D21 contract, bounds, primitive semantics and review phases.
2. `30fb2ee`: immutable circuit model, compiler, evaluator and exhaustive verifier.
3. Subsequent test/handoff commit: acceptance battery and these reproduction notes.

## Review targets

`src/ohmwork/logic_gates.py`:

- Input IDs i0... and gate IDs g0... are canonical, independent of display names.
  Driver references preserve input-terminal order and multiplicity. Output is an
  explicit driver ID, including the direct-wire case.
- All eight primitives; NOT/BUF unary and others 2-8 inputs. XOR/XNOR mean
  odd/even parity. No minimizer or CMOS algorithm is called.
- Compiler preserves parsed structure with direct NAND/NOR/XNOR recognition and
  identical-AST sharing. It is not a minimum-gate or minimum-transistor optimizer.
- Topology validation rejects missing/forward drivers, cycles, invalid arities,
  unknown types, wrong IDs/output and unreachable gates. Tuple collections
  preserve the immutable model contract.
- The graph evaluator uses gate types and driver values; the verifier separately
  evaluates the source AST. All input rows must agree before builders return.
  Returned rows contain inputs, every gate output and the final output in fixed
  order. These will power future UI toggles without browser-side Boolean algebra.
- Eight-input/128-gate/4096-character/64-nesting bounds are enforced before
  exhaustive evaluation. Existing D8 input names and first-appearance order apply.
- Count is the number of actual gates; depth is longest gate path. These are
  ideal Boolean values/stages, not timing, area or transistor-cost estimates.

## Run

```bash
python3 -m venv .venv
./.venv/bin/pip install -e '.[dev]'
./.venv/bin/pytest tests/test_logic_gates.py -q
./.venv/bin/pytest -q
./.venv/bin/python - <<'PY'
from ohmwork.logic_gates import build_basic_gate, build_expression_circuit
for source in ['ab+c', "(abc+de)'", 'a^b^c^d^e^f^g^h']:
    r = build_expression_circuit(source)
    print(source, r.gate_count, r.depth, len(r.rows))
r = build_basic_gate('XNOR', ('a', 'b', 'c'))
for row in r.rows:
    print(row.inputs, row.output)
PY
```

Expected summaries: `ab+c` = 2 gates/depth 2/8 rows; professor case =
3 gates/depth 2/32 rows; eight-input XOR = 1 gate/depth 1/256 rows.
The professor case's separate CMOS implementation remains 10 transistors; the
three generic symbols here are not asserted to have that transistor count.

## Acceptance and evidence

87 focused tests passed locally. They cover every supported primitive/arity,
all Boolean vectors, nested complements, shared/repeated operands, direct wires,
case-sensitive names/order, all input guards and the real 128-gate bound,
structural mutations, structurally legal function-changing mutations, strict
assignments, source identity and cross-process/hash-seed determinism.

The PR description records the exact head and CI run. No browser behavior is
changed in Phase 1; the existing browser and SPICE CI jobs remain regression
gates. Phase 2 needs dedicated geometric, interaction, keyboard, export and
1280/390px visual checks; it is not covered merely by this phase passing.

## Claude handoff

Check the D21 semantics against the actual compiler, especially n-ary parity,
complemented-gate recognition, duplicate terminals and identical-subexpression
sharing. Challenge the independent validator with incorrect but topologically
valid graphs. Confirm bound checks precede exhaustive work and counts/depth do
not imply optimization or transistor cost. Flag any model changes needed before
standard-symbol layout and public API/CLI/UI integration begin.
