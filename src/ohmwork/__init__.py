"""Ohmwork — digital logic work at the speed of typing.

See docs/CHARTER.md for the mission and docs/decisions.md for the definitional
decisions (D1-D14) that this implementation follows.
"""

from ohmwork.errors import ParseError
from ohmwork.expr import And, Const, Expr, Not, Or, Var, Xor
from ohmwork.parser import parse

__all__ = [
    "ParseError",
    "Expr",
    "Var",
    "Not",
    "And",
    "Or",
    "Xor",
    "Const",
    "parse",
]
