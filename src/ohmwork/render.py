"""Rendering a DerivationTable for terminal, Markdown, and LaTeX output
(part of the M1a deliverable in docs/CHARTER.md §8)."""

from __future__ import annotations

from ohmwork.derivation import DerivationTable


def _cell(value: bool) -> str:
    return "1" if value else "0"


def _row_values(table: DerivationTable, row_index: int) -> list[str]:
    return [_cell(col.values[row_index]) for col in table.columns]


def format_terminal(table: DerivationTable) -> str:
    """Plain ASCII table, safe for any terminal."""
    headers = [c.label for c in table.columns]
    rows = [_row_values(table, i) for i in range(len(table.rows))]
    widths = [max(len(headers[j]), *(len(r[j]) for r in rows)) for j in range(len(headers))]

    def rule() -> str:
        return "+" + "+".join("-" * (w + 2) for w in widths) + "+"

    def fmt_row(cells: list[str]) -> str:
        return "|" + "|".join(f" {c:<{w}} " for c, w in zip(cells, widths)) + "|"

    lines = [rule(), fmt_row(headers), rule()]
    for r in rows:
        lines.append(fmt_row(r))
    lines.append(rule())
    return "\n".join(lines)


def format_markdown(table: DerivationTable) -> str:
    """GitHub-flavored Markdown table."""
    headers = [c.label for c in table.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(["---"] * len(headers)) + "|",
    ]
    for i in range(len(table.rows)):
        lines.append("| " + " | ".join(_row_values(table, i)) + " |")
    return "\n".join(lines)


def _latex_escape(label: str) -> str:
    return label.replace("'", "^{\\prime}")


def format_latex(table: DerivationTable) -> str:
    """A LaTeX ``array`` fit for dropping into a math environment."""
    headers = [c.label for c in table.columns]
    col_spec = "c" * len(headers)
    lines = [
        r"\begin{array}{" + col_spec + "}",
        " & ".join(_latex_escape(h) for h in headers) + r" \\",
        r"\hline",
    ]
    for i in range(len(table.rows)):
        lines.append(" & ".join(_row_values(table, i)) + r" \\")
    lines.append(r"\end{array}")
    return "\n".join(lines)
