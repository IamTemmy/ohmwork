"""The Boolean expression AST and its D8 textbook-notation rendering.

``And``, ``Or``, and ``Xor`` are n-ary and store their operands as a tuple —
associative chains are flattened at parse time (e.g. ``a+b+c`` is one
``Or`` node with three operands, not two nested ones). This is the shallow,
cost-preserving flattening D5 (docs/decisions.md) calls for; nothing here
performs identity rewrites (no De Morgan, no absorption).
"""

from __future__ import annotations

from dataclasses import dataclass


class Expr:
    """Base class for every node in a parsed Boolean expression."""

    __slots__ = ()

    def __str__(self) -> str:  # pragma: no cover - overridden by subclasses
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class Var(Expr):
    """A single-letter-plus-optional-digit variable, per D8."""

    name: str

    def __str__(self) -> str:
        return self.name


@dataclass(frozen=True, slots=True)
class Const(Expr):
    """A Boolean constant. Not produced by the D8 parser directly; used
    internally when simplification collapses an expression to 0 or 1."""

    value: bool

    def __str__(self) -> str:
        return "1" if self.value else "0"


@dataclass(frozen=True, slots=True)
class Not(Expr):
    """Complement of a single operand (``'``)."""

    operand: Expr

    def __str__(self) -> str:
        return render(self)


@dataclass(frozen=True, slots=True)
class And(Expr):
    """Juxtaposition (``xy``). N-ary; must have at least one operand."""

    operands: tuple[Expr, ...]

    def __str__(self) -> str:
        return render(self)


@dataclass(frozen=True, slots=True)
class Or(Expr):
    """``+``. N-ary; must have at least one operand."""

    operands: tuple[Expr, ...]

    def __str__(self) -> str:
        return render(self)


@dataclass(frozen=True, slots=True)
class Xor(Expr):
    """``^``. N-ary; must have at least one operand."""

    operands: tuple[Expr, ...]

    def __str__(self) -> str:
        return render(self)


def mk_and(operands: list[Expr] | tuple[Expr, ...]) -> Expr:
    """Build an ``And``, collapsing a single operand to itself."""
    operands = tuple(operands)
    if len(operands) == 1:
        return operands[0]
    return And(operands)


def mk_or(operands: list[Expr] | tuple[Expr, ...]) -> Expr:
    """Build an ``Or``, collapsing a single operand to itself."""
    operands = tuple(operands)
    if len(operands) == 1:
        return operands[0]
    return Or(operands)


def mk_xor(operands: list[Expr] | tuple[Expr, ...]) -> Expr:
    """Build a ``Xor``, collapsing a single operand to itself."""
    operands = tuple(operands)
    if len(operands) == 1:
        return operands[0]
    return Xor(operands)


# --- D8 textbook-notation rendering -----------------------------------------
#
# Precedence, tightest to loosest: complement (') > AND (juxtaposition)
# > XOR (^) > OR (+). A child is parenthesized only when its own precedence
# is looser than what its parent position requires.


def _render_not_target(node: Expr) -> str:
    """Render the operand a ``'`` attaches to: bare if it's a Var/Const/Not
    (postfix complements chain without parens, e.g. ``x''``), parenthesized
    otherwise."""
    if isinstance(node, (Var, Const, Not)):
        return render(node)
    return f"({render(node)})"


def _render_and_factor(node: Expr) -> str:
    """Render one juxtaposed factor of an And: OR/XOR bind looser than AND
    and need parens; everything else doesn't."""
    if isinstance(node, (Or, Xor)):
        return f"({render(node)})"
    return render(node)


def _render_xor_operand(node: Expr) -> str:
    """Render one operand of a Xor: OR binds looser than XOR and needs
    parens; AND/NOT/Var/Const don't."""
    if isinstance(node, Or):
        return f"({render(node)})"
    return render(node)


def render(node: Expr) -> str:
    """Render ``node`` back to D8 textbook notation."""
    if isinstance(node, Var):
        return node.name
    if isinstance(node, Const):
        return "1" if node.value else "0"
    if isinstance(node, Not):
        count = 0
        inner: Expr = node
        while isinstance(inner, Not):
            count += 1
            inner = inner.operand
        return _render_not_target(inner) + ("'" * count)
    if isinstance(node, And):
        return "".join(_render_and_factor(o) for o in node.operands)
    if isinstance(node, Xor):
        return " ^ ".join(_render_xor_operand(o) for o in node.operands)
    if isinstance(node, Or):
        return " + ".join(render(o) for o in node.operands)
    raise TypeError(f"unknown expression node: {node!r}")  # pragma: no cover
