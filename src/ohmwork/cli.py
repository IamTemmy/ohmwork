"""The ``ohmwork`` command line, per D14: layered subcommands, not modes.

M1a ships ``tt`` (the derivation table). ``kmap`` and ``synth`` are M1b+ and
are not registered yet — D14 is explicit that transistor content, and
anything past the derivation table, never appears unasked.
"""

from __future__ import annotations

import argparse
import sys

from ohmwork.derivation import build_table, variables_in_order
from ohmwork.errors import ParseError
from ohmwork.expr import render as render_expr
from ohmwork.parser import parse
from ohmwork.render import format_latex, format_markdown, format_terminal
from ohmwork.simplify import simplify


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ohmwork",
        description="Digital logic work at the speed of typing.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    tt = subparsers.add_parser(
        "tt",
        help="Show the derivation table for a Boolean expression",
        description=(
            "Parse a Boolean expression (D8 textbook notation) and print a "
            "column for every intermediate sub-expression (D9), plus the "
            "simplified result."
        ),
    )
    tt.add_argument("expression", help='e.g. "xy + xy\'"')
    output_format = tt.add_mutually_exclusive_group()
    output_format.add_argument("--md", action="store_true", help="Markdown table output")
    output_format.add_argument("--latex", action="store_true", help="LaTeX array output")

    column_selection = tt.add_mutually_exclusive_group()
    column_selection.add_argument(
        "--terse",
        action="store_true",
        help="Show only the top-level product-term columns and F, instead of the full D9 breakout.",
    )
    column_selection.add_argument(
        "--cols",
        metavar="LIST",
        help='Comma-separated explicit list of columns to show, e.g. "x,y,xy" (D9). F is always included.',
    )

    return parser


def run_tt(args: argparse.Namespace, *, stdout, stderr) -> int:
    try:
        ast = parse(args.expression)
    except ParseError as e:
        print(f"error: {e}", file=stderr)
        return 1

    cols = None
    if args.cols is not None:
        cols = [c.strip() for c in args.cols.split(",")]
        if not cols or any(not c for c in cols):
            print("error: --cols must be a non-empty, comma-separated list of columns", file=stderr)
            return 1

    try:
        table = build_table(ast, terse=args.terse, cols=cols)
    except ValueError as e:
        print(f"error: {e}", file=stderr)
        return 1

    if args.latex:
        print(format_latex(table), file=stdout)
    elif args.md:
        print(format_markdown(table), file=stdout)
    else:
        print(format_terminal(table), file=stdout)

    var_order = variables_in_order(ast)
    simplified = simplify(var_order, table.output.values)
    print(f"F = {render_expr(simplified)}", file=stdout)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    if args.command == "tt":
        return run_tt(args, stdout=sys.stdout, stderr=sys.stderr)

    parser.print_help()  # pragma: no cover - unreachable while "tt" is the only command
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
