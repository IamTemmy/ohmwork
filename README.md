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

## Development

```bash
./.venv/bin/pytest
```
