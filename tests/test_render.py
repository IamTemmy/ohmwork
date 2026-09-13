"""Tests for terminal/Markdown/LaTeX table rendering."""

from ohmwork.derivation import build_table
from ohmwork.parser import parse
from ohmwork.render import format_latex, format_markdown, format_terminal


def test_latex_escapes_complement_as_prime():
    # "x'y" keeps x' as its own intermediate column (D9); the root ("x'y")
    # is relabeled "F", so this is the case that actually exercises the
    # complement escape on a real header.
    table = build_table(parse("x'y"))
    out = format_latex(table)
    assert "x^{\\prime}" in out
    assert "'" not in out


def test_latex_xor_column_uses_oplus_not_bare_caret():
    # Regression: a XOR sub-expression's column header used to render as the
    # literal string "a ^ b", and a bare `^` inside a LaTeX math array is the
    # superscript operator, not XOR — it must become \oplus. Root-level XOR
    # (e.g. plain "a^b") gets relabeled "F" and never shows the raw label, so
    # this needs XOR as a non-root sub-expression to actually exercise it.
    table = build_table(parse("a^b+c"))
    out = format_latex(table)
    assert r"a \oplus b" in out
    assert "^" not in out.replace(r"\oplus", "")


def test_latex_xor_and_complement_together_do_not_collide():
    # A table can carry both an XOR column and a complemented-literal column
    # at once; neither escape should corrupt the other.
    table = build_table(parse("a^b + c'"))
    out = format_latex(table)
    assert r"a \oplus b" in out
    assert "c^{\\prime}" in out


def test_markdown_and_terminal_keep_literal_xor_caret():
    # Only LaTeX needs escaping — Markdown/terminal output is plain text
    # matching D8 notation, where `^` is the correct XOR spelling.
    table = build_table(parse("a^b+c"))
    assert "a ^ b" in format_markdown(table)
    assert "a ^ b" in format_terminal(table)
