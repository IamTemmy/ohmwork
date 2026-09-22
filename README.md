# Ohmwork

Digital logic work at the speed of typing, showing its work at every step.

See [docs/CHARTER.md](docs/CHARTER.md) for the mission and scope, and
[docs/decisions.md](docs/decisions.md) for the definitional decisions (D1–D20) that govern
the implementation.

## v1.1 scope and limits

The v1 feature set includes derivation tables, standalone and synthesis-integrated
K-maps, verified transistor schematics, SPICE exports, and CSV derivation-table
export. Implementation is complete within the limits below; release approval and
version tagging are separate from feature availability.

K-maps and synthesis support 1–5 declared variables (D20). Derivation/minimization supports five
variables; the web derivation table permits up to eight, with potentially higher
computation time. Synthesis searches the D16 single-stage AOI/OAI candidate space,
not every possible CMOS circuit. Multi-stage NAND/NOR decomposition, analog design
sizing, and six-variable K-map/synthesis support remain future work. Constant
functions are supported by standalone K-maps but rejected by CMOS synthesis.

Five-variable K-maps use two 4×4 Gray-code planes. The first declared variable
selects the plane; matching positions across planes are adjacent. Planes appear
side by side on wide screens and stack on narrow screens, with local scrolling.
The API, CLI, editable grids, schematic, and SPICE exports use the same verified
result. For example:

```bash
ohmwork synth --expr "(abc+de)'"
ohmwork kmap --expr "(abc+de)'" --form pos
```

Five-variable exact search can stop at a resource limit rather than return an
unverified or partially minimized answer. Each production direction and the
standalone independent cover checker has its own 2,000,000-work-unit /
20,000-storage-item allowance. Synthesis uses two production searches; standalone
K-maps use a production search plus an independent check. Both must finish.
These are algorithm counters, not a wall-clock latency promise. CLI exhaustion
prints `search limit:` and exits 2; the HTTP API returns `error_kind: search_limit`.
v1.1 closeout still requires independent review and owner dogfooding.

## Setup

Ohmwork uses a project-specific virtual environment — not a conda environment. Run these
from inside this project folder (`cd` here first if you're not already in it):

```bash
python3 -m venv .venv
./.venv/bin/pip install -e ".[dev]"
```

Every command below (`ohmwork ...`, `pytest`) needs the virtual environment active in your
shell first:

```bash
source .venv/bin/activate
```

You'll see `(.venv)` in your prompt once it's active; `deactivate` turns it back off. If you
don't want to activate it, prefix every command with `./.venv/bin/` instead (`./.venv/bin/ohmwork ui`,
`./.venv/bin/pytest`) — same effect, no activation needed.

## Karnaugh maps

The **K-map** tab in `ohmwork ui` accepts an expression, a clickable truth-table
input grid, minterm/don't-care lists, or a binary-order bit string (1–5 variables).
Choose SOP to group ones or POS to group zeros. Select a colored group or its
explanation to isolate it; group IDs and stroke patterns distinguish overlaps
and wraparound pieces without relying on color alone. Original X cells remain
visible, with the chosen assignments listed separately.

Download SVG preserves the displayed map, group legend, result, and X assignments.
Copy explanation gives a plain-text derivation. The command-line equivalent is:

```sh
ohmwork kmap --expr "ab + a'c"
ohmwork kmap --vars "a,b,c,d" --ones "0,2,8,10"
ohmwork kmap --vars "a,b" --table "1X00" --form pos --output-name Y
```

The synthesis report embeds the same verified K-map view, explaining the chosen
circuit and why its AOI/OAI construction was selected.

## SPICE export

In the synthesis report, use **Download SPICE template** for a connectivity
file requiring models and sizes, or **Download SPICE example** for a runnable
educational DC example. Both describe the displayed schematic exactly.

```sh
ohmwork synth --expr "(abc+d)'" --netlist template --output-name Y > gate.sp
ohmwork synth --expr "(abc+d)'" --netlist example --output-name Y > gate.cir
ngspice -n -b gate.cir
```

Bare `--netlist` selects the template. The example sets logical inputs to zero
and external complements to one, using illustrative 5 V / W=10u / L=1u values.
It is not a fabrication design. See [docs/spice.md](docs/spice.md) for model
sources, assumptions, Python usage, and verification.

## Usage

```bash
ohmwork tt "xy + xy'"
```

`tt` prints the derivation table — one column per intermediate sub-expression, in the
order the terms are evaluated — followed by the simplified result. See
[docs/decisions.md](docs/decisions.md) D8 for the expression syntax and D9 for what a
derivation table contains.

- `--md` / `--latex` — Markdown or LaTeX output instead of the terminal table.
- `--csv` — data-only CSV: headers followed by 0/1 rows, with no explanation footer.
  Works with `--terse` or `--cols`. For example: `ohmwork tt "xy + xy'" --csv > table.csv`.
  The Derivation tab also offers **Download CSV** for the displayed table.
- `--terse` — collapse the table to just the top-level product terms and the output.
- `--cols "x,y,xy"` — show exactly these columns (each a valid expression), plus the output.

`synth` synthesizes a verified static CMOS gate from a truth table (D1: single-stage
AOI/OAI constructions, including single-stage NAND/NOR gates — see
[docs/decisions.md](docs/decisions.md) D16 for exactly what that means and D1–D7 for the
transistor-cost, inverter, and verification rules it follows). Give it a truth table either
as an expression to derive one from, or explicitly:

```bash
ohmwork synth --expr "(abc)'"                       # derives the truth table from a D8 expression
ohmwork synth --vars "a,b,c,d" --ones "0,1,4" --dc "2"   # explicit minterms + don't-cares (D4)
ohmwork synth --vars "a,b" --table "1x01"            # row-ordered bit string (0/1/x or -)
```

Reports every candidate considered, the chosen gate's name and transistor count (PDN, PUN,
and any shared inverters — D12), an ASCII schematic, and independent functional-equivalence
and structural-validity verification (D7). `--dual-rail` assumes complemented inputs are
free (D2); `--max-stack N` enforces D3's engineering stack-height constraint instead of the
default advisory-only textbook mode.

`ui` (M1.1) starts a small local web page for derivation tables, K-maps, and synthesis — form fields instead of flags,
for routine use:

```bash
ohmwork ui
```

Opens `http://127.0.0.1:5757/` in your browser (`--port N` to use a different port,
`--no-browser` to just print the URL). It's a thin wrapper over the same `ohmwork.api`
functions the CLI itself calls — nothing about `tt`/`synth`'s behavior changes, and the CLI
keeps working exactly as before. Stop the server with Ctrl+C.

**No terminal typing, every time:** double-click [`launch-ui.command`](launch-ui.command)
from Finder to start the server and open the browser in one click. It's still the same
local server underneath (nothing hosted, nothing new to trust); this just skips retyping the
setup dance each time. Closing its Terminal window stops the server, same as Ctrl+C would.

**A real app icon, pinnable to the Dock (macOS):** run
[`packaging/macos/build_app.sh`](packaging/macos/build_app.sh) to build `Ohmwork.app` (put
next to this project folder by default) — a proper double-clickable app with its own icon
that you can drag straight onto the Dock or into Applications, like any other app. It's a
thin wrapper: launching it just opens Terminal running `launch-ui.command` above, so the
actual behavior is identical either way. The `.app` itself isn't checked into git (it's a
generated, machine-specific build artifact — rebuild it any time, e.g. if you move this
folder); the build script is.

## Development

```bash
./.venv/bin/pytest
```
