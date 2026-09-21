# SPICE export — D19

The export layer consumes the verified schematic `Layout`; synthesis, naming,
model parameters, and transistor accounting are unchanged by CLI/UI integration.

## CLI and browser downloads (Phase 2)

`ohmwork synth --expr "(abc+d)'" --netlist template > gate.sp` prints only the
connectivity template. Bare `--netlist` does the same. Select `--netlist example`
for the runnable educational deck. Existing truth-table inputs, don't-cares,
`--dual-rail`, and `--max-stack` apply identically to ordinary synthesis.
`--output-name Y` sets the export label; on `synth` it requires `--netlist`.
Ordinary synthesis output remains unchanged. Errors go to stderr with a nonzero
exit code and no partial file on stdout.

The synthesis UI offers **Download SPICE template** and **Download SPICE example**
beside Download SVG. Visible descriptions explain the distinction, example
assumptions, and default stimulus. Filenames are `ohmwork-Y-template.sp` and
`ohmwork-Y-educational.cir` for output Y. The server generates both from the exact
Layout used for the displayed schematic; JavaScript downloads the returned text
without reconstructing circuit connectivity. CLI/API/download bytes match.

Input edits, mode changes, New problem, and a fresh submission clear stored
export text and disable downloads. A superseded response cannot restore old
exports. Export validation failure returns no partial successful result.

## Reproduce an export

```python
from pathlib import Path
from ohmwork.api import synthesize_from_input
from ohmwork.schematic import build_textbook_schematic
from ohmwork.spice import render_spice_template, render_spice_example

result = synthesize_from_input(expr="(abc+d)'")
layout = build_textbook_schematic(result, "Y")
Path("gate-template.sp").write_text(render_spice_template(layout))
Path("gate-example.cir").write_text(render_spice_example(
    layout, {"a": 1, "b": 1, "c": 1, "d": 0}
))
```

`render_spice_example(layout)` defaults to **all logical inputs zero**. An explicit
assignment must contain exactly the declared variables and boolean/integer 0/1
values. Every external complement input is driven automatically to the opposite
value. No source assignment is inferred from expression display text.

Run the example with `ngspice -n -b gate-example.cir`. Its `.op` analysis reports
the output voltage in the node table; the mapping comment identifies the output.

The **template is deliberately not runnable**: each MOS instance has `W=TBD L=TBD`,
and its referenced model names have no definitions. A caller must replace those
placeholders and provide models before using it. The **educational example is
runnable**, with the same connectivity and separate, explicit analog assumptions.
It is not a fabrication design or a transistor-sizing recommendation.

The educational example is tested with ngspice; it and the connectivity template
are written in portable SPICE3-style syntax intended to work with other simulators,
which are untested. The template itself has no simulator compatibility claim.

## Electrical identity and interface

`build_spice_model(layout)` returns immutable node, port, and device records.
It checks Layout structural validity; callers use the existing `build_schematic`
or `build_textbook_schematic` builders for source-fidelity and electrical
verification against a synthesis result. Geometry never determines connectivity.

- Each real Layout net gets `n0`, `n1`, … in Layout order, including both rails.
- Additional unconnected declared inputs get subsequent names in variable order.
- Each device gets `m0`, `m1`, … in Layout order, preserving drain/gate/source roles.
- MOS terminal order is drain, gate, source, bulk, model. PMOS bulk connects to the
  supply formal; NMOS bulk connects to the ground formal.
- The subcircuit is `ohmwork_gate`; models are `nmos_model` and `pmos_model`.
- Pin order is output, supply, ground, all declared primary inputs, then external
  complement inputs. Both input lists follow `var_order`.
- Internal complements never become external ports. An unused primary input still
  has a formal pin, including when only its external complement is used.
- The example's `x0` connects the ground formal to top-level node `0`. There is no
  hardcoded global ground or supply inside the subcircuit.

Mapping comments contain JSON-escaped original net IDs, labels, roles, and original
device IDs. They retain custom output labels and case-sensitive user identity
without using user text as a SPICE identifier or permitting newline injection.
`validate_spice_export` parses our emitted subcircuit dialect directly against
Layout, including comments, pin order, terminal order, polarity, sizing, and count.
It is a structural checker, not a general SPICE parser or an analog verifier.
The example's top-level stimulus is independently checked in the simulation tests.

## Educational model source and assumptions

The numeric model parameters below reproduce ngspice's own
[`examples/TransmissionLines/ltra1_1_line.sp`, lines 13–16](https://github.com/ngspice/ngspice/blob/032b1c32c4dbad45ff132bcfac1dbecadbd8abb0/examples/TransmissionLines/ltra1_1_line.sp#L13-L16),
pinned at commit `032b1c32c4dbad45ff132bcfac1dbecadbd8abb0`.
The original example is a MOS driver for a transmission line, **not a process
qualification source**. We reuse its model numbers for a reproducible educational
DC check. The unusually large `TOX=18000N` is retained exactly, not corrected or
represented as a modern process value.

Original names `mn0p9`/`mp1p0` are renamed. `LEVEL=1` is made explicit. We also pin
`TNOM`, diode leakage, series resistance, otherwise-zero capacitance parameters,
and noise defaults rather than relying on their implicit values. These additions
come from the Level-1 parameter/default definitions in the
[ngspice manual, MOSFET section](https://ngspice.sourceforge.io/docs/ngspice-manual.pdf)
(version 47, §7.6.2.5, Level-1 parameter table); they are documented defaults, not
newly inferred process measurements. The complete cards emitted are:

```spice
.model nmos_model NMOS (LEVEL=1 VTO=0.8 KP=48U GAMMA=0.30 PHI=0.55
+ LAMBDA=0.00 CGSO=0 CGDO=0 CJ=0 CJSW=0 TOX=18000N LD=0.0U
+ TNOM=27 IS=1e-14 JS=0 RD=0 RS=0 RSH=0 KF=0 AF=1
+ CBD=0 CBS=0 CGBO=0 PB=0.8 MJ=0.5 MJSW=0.5 FC=0.5)
.model pmos_model PMOS (LEVEL=1 VTO=-0.8 KP=21U GAMMA=0.45 PHI=0.61
+ LAMBDA=0.00 CGSO=0 CGDO=0 CJ=0 CJSW=0 TOX=18000N LD=0.0U
+ TNOM=27 IS=1e-14 JS=0 RD=0 RS=0 RSH=0 KF=0 AF=1
+ CBD=0 CBS=0 CGBO=0 PB=0.8 MJ=0.5 MJSW=0.5 FC=0.5)
```

| Choice | Meaning and limits |
| --- | --- |
| Level 1; explicit VTO, KP, GAMMA, PHI | Square-law educational MOS model; process-derived fallback calculations for these quantities are not used. |
| Nonzero GAMMA | Body effect is retained. Bulk-to-supply wiring does **not** remove it from stacked devices. |
| LAMBDA=0 | No channel-length modulation. |
| IS=1e-14, JS=0 | Explicit bulk-junction saturation current; no area-scaled junction current. |
| RD=RS=RSH=0, LD=0 | No series resistance or lateral diffusion correction. |
| CGSO=CGDO=CGBO=CJ=CJSW=CBD=CBS=0 | No explicit overlap/junction capacitance; no physical parasitic extraction. Level-1 intrinsic capacitance may still exist, but no transient analysis is performed. |
| PB/MJ/MJSW/FC defaults | Explicit junction-capacitance defaults; their capacitances are zero here. |
| KF=0, AF=1 | Explicit flicker-noise defaults; no noise analysis. |
| TEMP=TNOM=27 °C | Fixed temperature; no temperature sweep. |
| Supply 5 V; every device W=10u, L=1u | D19's illustrative choices, not sizes copied from the source or optimized for performance. |
| Unloaded output; DC operating point only | Checks stable logic, not delay, fanout, power, noise margin curves, or silicon behavior. |
| GMIN=1e-12, RELTOL=1e-3, ABSTOL=1e-12, VNTOL=1e-6 | Explicit numerical solver settings. |

No junction areas/perimeters are inferred from the schematic (instance defaults
are zero). Sheet-resistance multipliers have no effect with `RSH=0`. Doping,
mobility, and work-function fallbacks are not used to derive the explicitly supplied
Level-1 DC parameters. Remaining simulator bookkeeping defaults are not physical
measurements or additional Ohmwork design outputs.

## Verification and review

```sh
pip install -e ".[dev]"
pytest tests/test_spice.py -q
# Install ngspice with your operating system package manager, then:
OHMWORK_REQUIRE_NGSPICE=1 pytest tests/test_spice.py tests/test_spice_ngspice.py -q
```

The dedicated `spice-test` CI job installs the **system binary** and makes its
absence a failure. Ordinary local runs skip simulation cases when ngspice is
missing; the structural and harness-failure tests still run. Ordinary Python CI
matrix jobs need no simulator; the dedicated job is the mandatory electrical gate.
Repository branch-protection settings are not changed by this PR.

The battery covers NAND3, NOR4, AOI31, shared-inverter AOI21, AND, buffer, inverter,
OAI22, asymmetric and deeply nested trees, the 40T case, case-sensitive names,
unused declared inputs, and don't-cares — each with and without dual rail.
Every logical input vector is simulated. Care rows match the original minterms;
don't-care rows match the chosen circuit's reported assignments, not an arbitrary
acceptable assignment. Output ≤1 V is low, ≥4 V is high; an intermediate,
missing, invalid, or non-finite output fails. Solver errors, non-convergence,
nonzero exit codes, and timeouts fail independently of any printed voltage.

Structural mutation tests corrupt bulk connections, D/S order, model polarity,
device count, node/device identity, mapping comments, port order, and unused-input
wiring. A separate stimulus mutation verifies that a complement cannot silently
be driven in phase with its primary. All valid D8 variable names are exercised
within the existing supported variable count (`F` remains reserved by D15).
Wired and textbook layouts must produce identical electrical artifacts.

CI uploads every vector's actual `.cir` deck, simulator `.log`, and per-case
`results.json` in the `spice-electrical-review` artifact. These let Claude inspect
both connectivity and measured voltages, rather than trusting a pass count alone.

Initial Phase 1 verification used ngspice 42: all 328 operating points across 34
circuit/mode combinations passed, including six don't-care rows. Measured outputs
ranged from approximately 6.2e-10 V to 5.000001 V. The non-browser regression suite
passed 640 tests; the subsequently added model-card/documentation consistency test
also passed (641 non-browser tests in total). CI rechecks the committed tree.
