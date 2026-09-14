# Ohmwork

Digital logic work at the speed of typing, showing its work at every step.

See [docs/CHARTER.md](docs/CHARTER.md) for the mission and scope, and
[docs/decisions.md](docs/decisions.md) for the definitional decisions (D1–D14) that govern
the implementation.

## Setup

Ohmwork uses a project-specific virtual environment — not a conda environment.

```bash
python3 -m venv .venv
./.venv/bin/pip install -e ".[dev]"
```

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

## Development

```bash
./.venv/bin/pytest
```
