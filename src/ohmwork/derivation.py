"""Build a derivation table from a parsed expression: D9 (full column
breakout, deduplicated, in evaluation order) and D10 (variables ordered by
first appearance)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import reduce
from operator import xor as _bool_xor

from ohmwork.expr import And, Const, Expr, Not, Or, Var, Xor, render


def variables_in_order(node: Expr) -> list[str]:
    """Distinct variable names in order of first appearance (D10)."""
    seen: dict[str, None] = {}

    def walk(n: Expr) -> None:
        if isinstance(n, Var):
            seen.setdefault(n.name, None)
        elif isinstance(n, Not):
            walk(n.operand)
        elif isinstance(n, (And, Or, Xor)):
            for o in n.operands:
                walk(o)
        elif isinstance(n, Const):
            pass
        else:  # pragma: no cover
            raise TypeError(f"unknown expression node: {n!r}")

    walk(node)
    return list(seen.keys())


def subexpressions_in_order(node: Expr) -> list[Expr]:
    """Every distinct sub-expression in the parse tree, deduplicated by
    rendered form, ordered the way a derivation table is filled in by hand
    (D9): the plain variables (D10 order), then the single-variable
    complemented literals that appear (``x'``, ``y'``, ...), then every
    compound sub-expression (products, sums, complements of those) in
    evaluation order. The root lands last regardless of which of those
    buckets it falls into — the caller relabels it "F"."""
    var_order = variables_in_order(node)
    complemented: dict[str, Expr] = {}
    compounds: dict[str, Expr] = {}

    def walk(n: Expr) -> None:
        if isinstance(n, Var):
            return
        if isinstance(n, Const):
            return
        if isinstance(n, Not):
            if isinstance(n.operand, Var):
                complemented.setdefault(n.operand.name, n)
                return
            walk(n.operand)
            compounds.setdefault(render(n), n)
            return
        if isinstance(n, (And, Or, Xor)):
            for o in n.operands:
                walk(o)
            compounds.setdefault(render(n), n)
            return
        raise TypeError(f"unknown expression node: {n!r}")  # pragma: no cover

    walk(node)

    ordered: list[Expr] = [Var(name) for name in var_order]
    ordered.extend(complemented.values())
    ordered.extend(compounds.values())
    return ordered


def evaluate(node: Expr, assignment: dict[str, bool]) -> bool:
    """Evaluate ``node`` under a variable assignment."""
    if isinstance(node, Var):
        return assignment[node.name]
    if isinstance(node, Const):
        return node.value
    if isinstance(node, Not):
        return not evaluate(node.operand, assignment)
    if isinstance(node, And):
        return all(evaluate(o, assignment) for o in node.operands)
    if isinstance(node, Or):
        return any(evaluate(o, assignment) for o in node.operands)
    if isinstance(node, Xor):
        return reduce(_bool_xor, (evaluate(o, assignment) for o in node.operands))
    raise TypeError(f"unknown expression node: {node!r}")  # pragma: no cover


def all_assignments(variables: list[str]) -> list[dict[str, bool]]:
    """Every assignment of the given variables, 2^n rows, counted in binary
    with the first-listed variable as the most significant bit — a
    conventional, fully deterministic row order (design principle: correct
    before clever, deterministic)."""
    n = len(variables)
    rows = []
    for i in range(2**n):
        bits = [(i >> (n - 1 - k)) & 1 for k in range(n)]
        rows.append({var: bool(bit) for var, bit in zip(variables, bits)})
    return rows


@dataclass(frozen=True)
class Column:
    label: str
    node: Expr
    values: list[bool]


@dataclass(frozen=True)
class DerivationTable:
    variables: list[str]
    rows: list[dict[str, bool]]
    columns: list[Column]

    @property
    def output(self) -> Column:
        return self.columns[-1]


def build_table(node: Expr) -> DerivationTable:
    """Build the full D9/D10 derivation table for a parsed expression."""
    variables = variables_in_order(node)
    rows = all_assignments(variables)
    subexprs = subexpressions_in_order(node)

    columns: list[Column] = []
    for i, sub in enumerate(subexprs):
        is_root = i == len(subexprs) - 1
        label = "F" if is_root else render(sub)
        values = [evaluate(sub, row) for row in rows]
        columns.append(Column(label=label, node=sub, values=values))

    return DerivationTable(variables=variables, rows=rows, columns=columns)
