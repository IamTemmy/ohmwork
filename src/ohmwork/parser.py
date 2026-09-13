"""Tokenizer and recursive-descent parser for the D8 expression syntax.

Grammar (tightest binding first):

    expr     := or_expr END
    or_expr  := xor_expr ( '+' xor_expr )*
    xor_expr := and_expr ( '^' and_expr )*
    and_expr := factor+                      # juxtaposition == AND
    factor   := primary ( "'" )*              # postfix complement, chainable
    primary  := VAR | '(' or_expr ')'

A variable token is a single letter with an optional single trailing digit
(D8): ``A``, ``x``, ``A0``, ``B2``. Anything the grammar doesn't recognize —
an unknown character, a stray digit, unbalanced parens, a dangling operator,
an empty expression — is rejected with a ``ParseError`` rather than guessed,
per D8's "ambiguous input is rejected, never guessed."
"""

from __future__ import annotations

from dataclasses import dataclass

from ohmwork.errors import ParseError
from ohmwork.expr import Expr, Not, Var, mk_and, mk_or, mk_xor

_LETTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
_DIGITS = "0123456789"


@dataclass(frozen=True)
class Token:
    kind: str  # "VAR" | "NOT" | "OR" | "XOR" | "LPAREN" | "RPAREN" | "END"
    value: str
    pos: int


def tokenize(source: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    n = len(source)
    while i < n:
        ch = source[i]
        if ch.isspace():
            i += 1
            continue
        if ch in _LETTERS:
            start = i
            name = ch
            i += 1
            if i < n and source[i] in _DIGITS:
                name += source[i]
                i += 1
                if i < n and source[i] in _DIGITS:
                    raise ParseError(
                        "variable names take at most one trailing digit "
                        f"(got '{name}{source[i]}...') — this is ambiguous, not guessed",
                        position=start,
                        source=source,
                    )
            tokens.append(Token("VAR", name, start))
            continue
        if ch in _DIGITS:
            raise ParseError(
                f"a digit must immediately follow a single letter to form a variable "
                f"(e.g. 'A0'); '{ch}' at position {i} does not",
                position=i,
                source=source,
            )
        if ch == "'":
            tokens.append(Token("NOT", ch, i))
            i += 1
            continue
        if ch == "+":
            tokens.append(Token("OR", ch, i))
            i += 1
            continue
        if ch == "^":
            tokens.append(Token("XOR", ch, i))
            i += 1
            continue
        if ch == "(":
            tokens.append(Token("LPAREN", ch, i))
            i += 1
            continue
        if ch == ")":
            tokens.append(Token("RPAREN", ch, i))
            i += 1
            continue
        raise ParseError(
            f"unrecognized character {ch!r} at position {i}",
            position=i,
            source=source,
        )
    tokens.append(Token("END", "", n))
    return tokens


class _Parser:
    def __init__(self, tokens: list[Token], source: str):
        self._tokens = tokens
        self._source = source
        self._i = 0

    @property
    def _cur(self) -> Token:
        return self._tokens[self._i]

    def _advance(self) -> Token:
        tok = self._tokens[self._i]
        self._i += 1
        return tok

    def _error(self, message: str, tok: Token | None = None) -> ParseError:
        tok = tok or self._cur
        return ParseError(message, position=tok.pos, source=self._source)

    def parse(self) -> Expr:
        if self._cur.kind == "END":
            raise self._error("empty expression")
        node = self._or_expr()
        if self._cur.kind != "END":
            if self._cur.kind == "RPAREN":
                raise self._error("unmatched closing parenthesis ')'")
            raise self._error(f"unexpected '{self._cur.value}'")
        return node

    def _or_expr(self) -> Expr:
        operands = [self._xor_expr()]
        while self._cur.kind == "OR":
            self._advance()
            operands.append(self._xor_expr())
        return mk_or(operands)

    def _xor_expr(self) -> Expr:
        operands = [self._and_expr()]
        while self._cur.kind == "XOR":
            self._advance()
            operands.append(self._and_expr())
        return mk_xor(operands)

    def _and_expr(self) -> Expr:
        operands = [self._factor()]
        while self._cur.kind in ("VAR", "LPAREN"):
            operands.append(self._factor())
        return mk_and(operands)

    def _factor(self) -> Expr:
        node = self._primary()
        while self._cur.kind == "NOT":
            self._advance()
            node = Not(node)
        return node

    def _primary(self) -> Expr:
        tok = self._cur
        if tok.kind == "VAR":
            self._advance()
            return Var(tok.value)
        if tok.kind == "LPAREN":
            self._advance()
            if self._cur.kind == "RPAREN":
                raise self._error("empty parentheses '()' have no operand")
            node = self._or_expr()
            if self._cur.kind != "RPAREN":
                raise self._error("missing closing parenthesis ')'")
            self._advance()
            return node
        if tok.kind == "END":
            raise self._error("expected an operand, found end of expression")
        raise self._error(f"expected an operand, found '{tok.value}'")


def parse(source: str) -> Expr:
    """Parse a D8 textbook-notation expression into an AST.

    Raises ``ParseError`` on anything ambiguous or invalid: unknown
    characters, malformed variable names, unbalanced parens, dangling
    operators, or an empty expression.
    """
    tokens = tokenize(source)
    return _Parser(tokens, source).parse()
