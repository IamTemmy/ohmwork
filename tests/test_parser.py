"""Tests for the D8 expression parser (docs/decisions.md D8)."""

import pytest

from ohmwork.errors import ParseError
from ohmwork.expr import And, Not, Or, Var, Xor, render
from ohmwork.parser import parse


def test_single_variable():
    assert parse("x") == Var("x")


def test_juxtaposition_is_and():
    ast = parse("xy")
    assert ast == And((Var("x"), Var("y")))


def test_multi_letter_juxtaposition_is_unambiguous_and():
    # D8: ABC unambiguously means A AND B AND C.
    ast = parse("ABC")
    assert ast == And((Var("A"), Var("B"), Var("C")))


def test_complement():
    assert parse("x'") == Not(Var("x"))


def test_complement_binds_to_preceding_variable_only():
    ast = parse("xy'")
    assert ast == And((Var("x"), Not(Var("y"))))


def test_double_complement_chains():
    assert parse("x''") == Not(Not(Var("x")))


def test_or():
    assert parse("x+y") == Or((Var("x"), Var("y")))


def test_xor():
    assert parse("x^y") == Xor((Var("x"), Var("y")))


def test_variable_with_trailing_digit():
    assert parse("A0") == Var("A0")
    assert parse("B2") == Var("B2")


def test_variables_with_digits_are_distinct_and_juxtaposed():
    ast = parse("A0B2")
    assert ast == And((Var("A0"), Var("B2")))


@pytest.mark.parametrize(
    "expr, expected",
    [
        ("xy + xy'", "xy + xy'"),
        ("x'y + xy'", "x'y + xy'"),
        ("(x+y)'", "(x + y)'"),
        ("x'+y", "x' + y"),
    ],
)
def test_roundtrip_render(expr, expected):
    assert render(parse(expr)) == expected


def test_precedence_and_binds_tighter_than_or():
    # xy + z means (xy) + z, not x(y+z)
    ast = parse("xy+z")
    assert ast == Or((And((Var("x"), Var("y"))), Var("z")))


def test_precedence_complement_binds_tighter_than_and():
    ast = parse("x'y")
    assert ast == And((Not(Var("x")), Var("y")))


def test_precedence_and_binds_tighter_than_xor():
    ast = parse("xy^z")
    assert ast == Xor((And((Var("x"), Var("y"))), Var("z")))


def test_precedence_xor_binds_tighter_than_or():
    ast = parse("x+y^z")
    assert ast == Or((Var("x"), Xor((Var("y"), Var("z")))))


def test_parens_override_precedence():
    ast = parse("x(y+z)")
    assert ast == And((Var("x"), Or((Var("y"), Var("z")))))


def test_paren_grouped_complement_differs_from_ungrouped():
    # Charter D8: (ABC + D)' and (ABC)' + D are different functions.
    grouped = parse("(ABC + D)'")
    ungrouped = parse("(ABC)' + D")
    assert grouped != ungrouped
    assert grouped == Not(Or((And((Var("A"), Var("B"), Var("C"))), Var("D"))))
    assert ungrouped == Or((Not(And((Var("A"), Var("B"), Var("C")))), Var("D")))


def test_nested_parens():
    ast = parse("((x+y)z)'")
    assert ast == Not(And((Or((Var("x"), Var("y"))), Var("z"))))


# --- Ambiguous / invalid input: rejected, never guessed ---------------------


def test_rejects_two_digit_variable_suffix():
    with pytest.raises(ParseError):
        parse("A12")


def test_rejects_leading_digit():
    with pytest.raises(ParseError):
        parse("2x")


def test_rejects_unknown_character():
    with pytest.raises(ParseError):
        parse("x&y")


def test_rejects_empty_expression():
    with pytest.raises(ParseError):
        parse("")


def test_rejects_whitespace_only_expression():
    with pytest.raises(ParseError):
        parse("   ")


def test_rejects_empty_parens():
    with pytest.raises(ParseError):
        parse("()")


def test_rejects_unclosed_paren():
    with pytest.raises(ParseError):
        parse("(x+y")


def test_rejects_unmatched_closing_paren():
    with pytest.raises(ParseError):
        parse("x+y)")


def test_rejects_trailing_operator():
    with pytest.raises(ParseError):
        parse("x+")


def test_rejects_leading_binary_operator():
    with pytest.raises(ParseError):
        parse("+x")


def test_rejects_consecutive_binary_operators():
    with pytest.raises(ParseError):
        parse("x++y")


def test_rejects_complement_with_no_operand():
    with pytest.raises(ParseError):
        parse("'x")


# --- D15: "F" is reserved (collides with the output column) -----------------


def test_rejects_bare_f_as_a_variable():
    with pytest.raises(ParseError, match="reserved"):
        parse("F")


def test_rejects_bare_f_anywhere_in_the_expression():
    with pytest.raises(ParseError, match="reserved"):
        parse("F + y")
    with pytest.raises(ParseError, match="reserved"):
        parse("AF")  # F need not be the whole expression to collide


def test_allows_f_with_a_trailing_digit():
    assert parse("F0") == Var("F0")
    assert parse("F1") == Var("F1")


def test_allows_lowercase_f():
    assert parse("f") == Var("f")


def test_parse_error_has_a_human_readable_message():
    with pytest.raises(ParseError) as exc_info:
        parse("A12")
    message = str(exc_info.value)
    assert message
    assert "ambiguous" in message.lower()
