"""The ``ohmwork`` command line, per D14: layered subcommands, not modes.

M1a shipped ``tt`` (the derivation table). M1b added ``synth`` (the
transistor layer) — ``kmap`` is still M1b+ and not registered yet. M1.1 adds
``ui``, a local web front end for the same two operations, for people who'd
rather use form fields than remember flags; it wraps ``ohmwork.api``, the
same UI-agnostic layer this module's own ``tt``/``synth`` handlers call, so
the two front ends can never drift into different behavior. D14 is explicit
that transistor content never appears unasked: ``synth`` is its own
subcommand, never a flag on ``tt``, and the UI keeps that same separation.
"""

from __future__ import annotations

import argparse
import sys

from ohmwork.api import render_synth, render_tt
from ohmwork.errors import ParseError


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

    ui = subparsers.add_parser(
        "ui",
        help="Start a local web page for tt/synth (M1.1) instead of the command line",
        description=(
            "Start a small local server hosting a form-based front end for tt and "
            "synth, and open it in your browser. A thin wrapper over the same "
            "ohmwork.api functions the CLI uses — nothing about tt/synth's own "
            "behavior changes."
        ),
    )
    ui.add_argument("--port", type=int, default=5757, help="Port to listen on (default: 5757)")
    ui.add_argument(
        "--no-browser", action="store_true", help="Don't automatically open the page in a browser"
    )

    return parser


def run_tt(args: argparse.Namespace, *, stdout, stderr) -> int:
    cols = None
    if args.cols is not None:
        cols = [c.strip() for c in args.cols.split(",")]
        if not cols or any(not c for c in cols):
            print("error: --cols must be a non-empty, comma-separated list of columns", file=stderr)
            return 1

    try:
        output = render_tt(args.expression, md=args.md, latex=args.latex, terse=args.terse, cols=cols)
    except (ParseError, ValueError) as e:
        print(f"error: {e}", file=stderr)
        return 1

    print(output, file=stdout)
    return 0


def run_synth(args: argparse.Namespace, *, stdout, stderr) -> int:
    try:
        output = render_synth(
            expr=args.expr,
            variables=args.vars,
            ones=args.ones,
            dc=args.dc,
            table=args.table,
            dual_rail=args.dual_rail,
            max_stack=args.max_stack,
        )
    except (ValueError, ParseError) as e:
        print(f"error: {e}", file=stderr)
        return 1
    except RuntimeError as e:
        # render_synth() only raises this if synthesize()'s own D7
        # verification failed — a bug in ohmwork, not bad input. Never
        # printed as a valid design.
        print(f"error: {e}", file=stderr)
        return 1

    print(output, file=stdout)
    return 0


def run_ui(args: argparse.Namespace, *, stdout, stderr) -> int:
    from ohmwork.webui import run_server  # imported lazily: only `ui` needs it

    run_server(port=args.port, open_browser=not args.no_browser, stdout=stdout)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    if args.command == "tt":
        return run_tt(args, stdout=sys.stdout, stderr=sys.stderr)
    if args.command == "synth":
        return run_synth(args, stdout=sys.stdout, stderr=sys.stderr)
    if args.command == "ui":
        return run_ui(args, stdout=sys.stdout, stderr=sys.stderr)

    parser.print_help()  # pragma: no cover - unreachable while every command is handled above
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
