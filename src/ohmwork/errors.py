"""Errors shared across the Ohmwork engine."""

from __future__ import annotations


class ParseError(ValueError):
    """Raised when an expression cannot be parsed unambiguously.

    Per D8 (docs/decisions.md): ambiguous or invalid input is rejected with a
    clear error, never guessed. ``position`` is the 0-based index into the
    original source string where the problem was detected, when known.
    """

    def __init__(self, message: str, *, position: int | None = None, source: str | None = None):
        self.position = position
        self.source = source
        if position is not None and source is not None:
            pointer = " " * position + "^"
            message = f"{message}\n  {source}\n  {pointer}"
        super().__init__(message)
