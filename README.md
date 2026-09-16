# Ohmwork

Digital logic work at the speed of typing, showing its work at every step.

See [docs/CHARTER.md](docs/CHARTER.md) for the mission and scope, and
[docs/decisions.md](docs/decisions.md) for the definitional decisions (D1–D16) that govern
the implementation.

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

## Usage

```bash
ohmwork tt "xy + xy'"
```

`tt` prints the derivation table — one column per intermediate sub-expression, in the
order the terms are evaluated — followed by the simplified result. See
[docs/decisions.md](docs/decisions.md) D8 for the expression syntax and D9 for what a
derivation table contains.

- `--md` / `--latex` — Markdown or LaTeX output instead of the terminal table.
- `--terse` — collapse the table to just the top-level product terms and the output.
- `--cols "x,y,xy"` — show exactly these columns (each a valid expression), plus the output.

`synth` synthesizes a verified static CMOS gate from a truth table (D1: single-stage
AOI/OAI and their generalizations, plus NAND/NOR — see
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

`ui` (M1.1) starts a small local web page for `tt`/`synth` — form fields instead of flags,
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
