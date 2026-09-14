"""The ``ohmwork`` command line, per D14: layered subcommands, not modes.

M1a shipped ``tt`` (the derivation table). M1b adds ``synth`` (the
transistor layer) — ``kmap`` is still M1b+ and not registered yet. D14 is
explicit that transistor content never appears unasked: ``synth`` is its own
subcommand, never a flag on ``tt``.
"""

from __future__ import annotations

import argparse
import sys

from ohmwork.derivation import all_assignments, build_table, evaluate, variables_in_order
from ohmwork.errors import ParseError
from ohmwork.expr import render as render_expr
from ohmwork.parser import parse
from ohmwork.render import format_latex, format_markdown, format_terminal
from ohmwork.report import format_synth_report
from ohmwork.simplify import simplify
from ohmwork.synth import synthesize
from ohmwork.truth_table import parse_index_list, parse_table_string, parse_var_list
from ohmwork.verify import verify


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

    synth = subparsers.add_parser(
        "synth",
        help="Synthesize a verified static CMOS gate from a truth table",
        description=(
            "Synthesize a single-stage static CMOS complex gate (D1: AOI/OAI and "
            "their generalizations) from a truth table, with transistor count, "
            "gate name, an ASCII schematic, and independent verification (D7)."
        ),
    )
    synth.add_argument("--expr", metavar="EXPR", help='Derive the truth table from a D8 expression, e.g. "(abc)\'"')
    synth.add_argument("--vars", metavar="LIST", help='Variable names, e.g. "a,b,c" (with --ones or --table)')
    synth.add_argument("--ones", metavar="LIST", help="Minterm indices where F=1, e.g. \"0,1,4\"")
    synth.add_argument("--dc", metavar="LIST", help="Don't-care minterm indices (D4), e.g. \"2,6\"")
    synth.add_argument("--table", metavar="BITS", help='Row-ordered bit string, e.g. "1100011x" (0/1/x or -)')
    synth.add_argument(
        "--dual-rail",
        action="store_true",
        help="Assume complemented inputs are provided free (D2); don't count inverters",
    )
    synth.add_argument(
        "--max-stack",
        type=int,
        metavar="N",
        help="Reject any candidate whose series stack height exceeds N (D3's opt-in constraint)",
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


def _resolve_synth_input(args: argparse.Namespace) -> tuple[list[str], set[int], set[int]]:
    """Work out (var_order, minterms, dont_cares) from whichever of
    --expr / --vars+--ones / --vars+--table the user gave. Raises
    ``ValueError`` on any invalid or conflicting combination — rejected
    the same way ambiguous D8 input is, never guessed."""
    if args.expr is not None:
        if any(x is not None for x in (args.vars, args.ones, args.dc, args.table)):
            raise ValueError("--expr cannot be combined with --vars/--ones/--dc/--table")
        ast = parse(args.expr)
        var_order = variables_in_order(ast)
        if not var_order:
            raise ValueError("--expr must contain at least one variable")
        rows = all_assignments(var_order)
        minterms = {i for i, row in enumerate(rows) if evaluate(ast, row)}
        return var_order, minterms, set()

    if args.vars is None:
        raise ValueError("give --expr, or --vars together with --ones (or --table)")
    var_order = parse_var_list(args.vars)

    if args.table is not None:
        if args.ones is not None or args.dc is not None:
            raise ValueError("--table cannot be combined with --ones/--dc")
        minterms, dont_cares = parse_table_string(args.table, len(var_order))
        return var_order, minterms, dont_cares

    if args.ones is None:
        raise ValueError("give --ones (or --table) alongside --vars")
    minterms = parse_index_list(args.ones, len(var_order), "--ones")
    dont_cares = parse_index_list(args.dc, len(var_order), "--dc") if args.dc is not None else set()
    overlap = minterms & dont_cares
    if overlap:
        raise ValueError(f"index/indices {sorted(overlap)} listed in both --ones and --dc")
    return var_order, minterms, dont_cares


def run_synth(args: argparse.Namespace, *, stdout, stderr) -> int:
    try:
        var_order, minterms, dont_cares = _resolve_synth_input(args)
    except (ValueError, ParseError) as e:
        print(f"error: {e}", file=stderr)
        return 1

    try:
        result = synthesize(
            var_order, minterms, dont_cares, dual_rail=args.dual_rail, max_stack=args.max_stack
        )
    except ValueError as e:
        print(f"error: {e}", file=stderr)
        return 1

    verification = verify(result.pdn, result.pun, var_order, minterms, dont_cares)
    print(format_synth_report(result, verification), file=stdout)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    if args.command == "tt":
        return run_tt(args, stdout=sys.stdout, stderr=sys.stderr)
    if args.command == "synth":
        return run_synth(args, stdout=sys.stdout, stderr=sys.stderr)

    parser.print_help()  # pragma: no cover - unreachable while every command is handled above
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
