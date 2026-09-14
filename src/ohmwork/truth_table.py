"""Parsing for `ohmwork synth`'s truth-table input: an explicit variable
list plus either minterm/don't-care index lists or a row-ordered bit
string. Not a D-level decision (it doesn't change what any answer *means*,
just the CLI's input surface — see docs/decisions.md's own distinction
between definitional questions and implementation details), but validated
the same way D8 expression input is: rejected clearly rather than guessed.
"""

from __future__ import annotations

from ohmwork.errors import ParseError
from ohmwork.expr import Var
from ohmwork.parser import parse


def parse_var_list(spec: str) -> list[str]:
    """Parse a comma-separated variable list (e.g. ``"a,b,c"``), reusing the
    D8 parser to validate each name (so D15's reservation of "F" and D8's
    single-letter-plus-optional-digit rule apply here too, automatically)."""
    names = [s.strip() for s in spec.split(",")]
    if not spec.strip() or any(not n for n in names):
        raise ValueError("--vars must be a non-empty, comma-separated list of variable names")
    for name in names:
        try:
            ast = parse(name)
        except ParseError as e:
            raise ValueError(f"invalid variable name {name!r}: {e}") from e
        if not isinstance(ast, Var) or ast.name != name:
            raise ValueError(f"{name!r} is not a single D8 variable name")
    if len(set(names)) != len(names):
        raise ValueError("--vars contains duplicate variable names")
    return names


def parse_index_list(spec: str, n_vars: int, what: str) -> set[int]:
    """Parse a comma-separated list of minterm indices (e.g. ``"1,3,5"``),
    validating each is an integer in range for ``n_vars`` variables."""
    spec = spec.strip()
    if not spec:
        return set()
    full = 2**n_vars
    result: set[int] = set()
    for piece in spec.split(","):
        piece = piece.strip()
        if not piece.lstrip("-").isdigit():
            raise ValueError(f"{what} entry {piece!r} is not a non-negative integer")
        idx = int(piece)
        if not (0 <= idx < full):
            raise ValueError(
                f"{what} entry {idx} is out of range: must be in [0, {full}) for {n_vars} variables"
            )
        result.add(idx)
    return result


def parse_table_string(table: str, n_vars: int) -> tuple[set[int], set[int]]:
    """Parse a row-ordered bit string (``'0'``/``'1'``/``'x'`` or ``'-'`` for
    don't-care) of length ``2**n_vars`` into (minterms, dont_cares)."""
    expected_len = 2**n_vars
    if len(table) != expected_len:
        raise ValueError(
            f"--table must have exactly {expected_len} characters (2^{n_vars} rows "
            f"for {n_vars} variables), got {len(table)}"
        )
    minterms: set[int] = set()
    dont_cares: set[int] = set()
    for i, ch in enumerate(table):
        if ch == "1":
            minterms.add(i)
        elif ch == "0":
            pass
        elif ch in ("x", "X", "-"):
            dont_cares.add(i)
        else:
            raise ValueError(
                f"--table has invalid character {ch!r} at position {i}; use 0, 1, or x/- for don't-care"
            )
    return minterms, dont_cares
