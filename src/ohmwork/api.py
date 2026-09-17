"""The UI-agnostic core operations behind both ``ohmwork``'s CLI and its
optional web UI (M1.1, ``ohmwork ui``): "render a tt report" and "render a
synth report" as plain functions returning text, so both front ends call
the exact same logic rather than reimplementing it.

Design principle 5.4 ("core is a library") already meant the engine itself
(parser/derivation/synth/verify) was UI-free; this module is the thin,
still-UI-free layer both `cli.py` and `webui.py` sit on top of, so that
"the web UI wraps the existing library without changing its logic" is true
by construction — there's only one place either behavior lives.

Every function here raises ``ParseError`` or ``ValueError`` on invalid
input (the same exceptions the underlying modules raise) rather than
handling them — printing an "error: ..." line and choosing an exit code is
a CLI concern, and rendering an error banner is a web-UI concern; neither
belongs here.
"""

from __future__ import annotations

from ohmwork.derivation import all_assignments, build_table, evaluate, variables_in_order
from ohmwork.expr import render as render_expr
from ohmwork.parser import parse
from ohmwork.render import format_latex, format_markdown, format_terminal
from ohmwork.report import format_synth_report
from ohmwork.simplify import simplify
from ohmwork.synth import SynthesisResult, synthesize
from ohmwork.truth_table import parse_index_list, parse_table_string, parse_var_list


def render_tt(
    expression: str,
    *,
    md: bool = False,
    latex: bool = False,
    terse: bool = False,
    cols: list[str] | None = None,
) -> str:
    """The full text ``ohmwork tt`` prints: the table (in whichever format)
    followed by ``F = ...``. Raises ``ParseError`` (bad expression) or
    ``ValueError`` (bad terse/cols combination, or an unknown column)."""
    ast = parse(expression)
    table = build_table(ast, terse=terse, cols=cols)

    if latex:
        body = format_latex(table)
    elif md:
        body = format_markdown(table)
    else:
        body = format_terminal(table)

    var_order = variables_in_order(ast)
    simplified = simplify(var_order, table.output.values)
    return f"{body}\nF = {render_expr(simplified)}"


def resolve_truth_table(
    *,
    expr: str | None = None,
    variables: str | None = None,
    ones: str | None = None,
    dc: str | None = None,
    table: str | None = None,
) -> tuple[list[str], set[int], set[int]]:
    """Work out (var_order, minterms, dont_cares) from whichever input mode
    was given: ``expr`` alone, or ``variables`` with ``ones``/``dc``, or
    ``variables`` with ``table``. Raises ``ValueError`` on any invalid or
    conflicting combination — rejected the same way ambiguous D8 input is,
    never guessed.

    Error text intentionally still names the CLI's own flags (``--expr``,
    ``--vars``, etc.) even though this function is also the web UI's path —
    it's the exact wording ``synth`` had before M1.1 (and its own tests
    pin), which this extraction must not silently change (a real regression
    ChatGPT's M1.1 review caught: the flag-oriented text had drifted to
    UI-neutral prose here, which broke the CLI's byte-for-byte output). A
    friendlier, front-end-specific rendering of these errors is future work
    for whenever the UI gets an actual design pass — not a reason to let
    the CLI's existing, already-signed-off behavior drift for free."""
    if expr is not None:
        if any(x is not None for x in (variables, ones, dc, table)):
            raise ValueError("--expr cannot be combined with --vars/--ones/--dc/--table")
        ast = parse(expr)
        var_order = variables_in_order(ast)
        if not var_order:
            raise ValueError("--expr must contain at least one variable")
        rows = all_assignments(var_order)
        minterms = {i for i, row in enumerate(rows) if evaluate(ast, row)}
        return var_order, minterms, set()

    if variables is None:
        raise ValueError("give --expr, or --vars together with --ones (or --table)")
    var_order = parse_var_list(variables)

    if table is not None:
        if ones is not None or dc is not None:
            raise ValueError("--table cannot be combined with --ones/--dc")
        minterms, dont_cares = parse_table_string(table, len(var_order))
        return var_order, minterms, dont_cares

    if ones is None:
        raise ValueError("give --ones (or --table) alongside --vars")
    minterm_set = parse_index_list(ones, len(var_order), "--ones")
    dont_care_set = parse_index_list(dc, len(var_order), "--dc") if dc is not None else set()
    overlap = minterm_set & dont_care_set
    if overlap:
        raise ValueError(f"index/indices {sorted(overlap)} listed in both --ones and --dc")
    return var_order, minterm_set, dont_care_set


def synthesize_from_input(
    *,
    expr: str | None = None,
    variables: str | None = None,
    ones: str | None = None,
    dc: str | None = None,
    table: str | None = None,
    dual_rail: bool = False,
    max_stack: int | None = None,
) -> SynthesisResult:
    """Resolve truth-table input and synthesize it — the raw, structured
    result, not text. Both ``render_synth`` below (the CLI's text report)
    and M1.2's ``presenter`` module (the web UI's structured student view)
    build on this single call, so a given request is synthesized exactly
    once and both presentations come from the *same* verified object —
    never two independent computations that could theoretically disagree.

    Raises ``ValueError`` (bad input, unsupported variable count, or no
    candidate fits ``max_stack``) or ``RuntimeError`` (D7 verification
    failed inside ``synthesize`` itself — a bug in ohmwork, never a valid
    design; see ``synth.synthesize``'s own docstring)."""
    var_order, minterms, dont_cares = resolve_truth_table(
        expr=expr, variables=variables, ones=ones, dc=dc, table=table
    )
    return synthesize(var_order, minterms, dont_cares, dual_rail=dual_rail, max_stack=max_stack)


def render_synth(
    *,
    expr: str | None = None,
    variables: str | None = None,
    ones: str | None = None,
    dc: str | None = None,
    table: str | None = None,
    dual_rail: bool = False,
    max_stack: int | None = None,
) -> str:
    """The full text ``ohmwork synth`` prints: candidates, gate name,
    transistor breakdown, schematic, and D7 verification. See
    ``synthesize_from_input`` for the exceptions this can raise."""
    result = synthesize_from_input(
        expr=expr, variables=variables, ones=ones, dc=dc, table=table,
        dual_rail=dual_rail, max_stack=max_stack,
    )
    # synthesize() already verified this design (D7) before returning it —
    # result.verification is guaranteed to have passed, or it would have
    # raised RuntimeError above instead of reaching this line.
    return format_synth_report(result, result.verification)
