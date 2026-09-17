"""M1.2: turns a verified :class:`~ohmwork.synth.SynthesisResult` into a
JSON-serializable, student-facing view — a *second presentation* of the
same object the CLI's ``format_synth_report`` already renders, not a
separate computation and not something built by parsing that report's
text. Every field here reads a fact directly off the result object graph;
nothing is inferred, reworded from prose, or guessed.

Design boundary (per the M1.2 review): ``SynthesisResult`` remains the
single canonical, verified engineering result. This module only selects,
labels, groups, and rephrases facts already on it — it never recomputes,
approximates, or overrides anything synth.py decided.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ohmwork.expr import Expr, Not, render as render_expr
from ohmwork.network import render_network
from ohmwork.synth import Candidate, SynthesisResult

# Same shape as D8's variable grammar (single letter, optional trailing
# digit) — deliberately NOT ohmwork.parser.parse(), because that enforces
# D15's reservation of the bare letter "F" as an *input variable* name
# (it collides with tt's derivation-table output column). Here "F" is the
# default *output name* — the exact case D15 exists to keep meaningful
# elsewhere must stay valid here.
_OUTPUT_NAME_RE = re.compile(r"^[A-Za-z][0-9]?$")

DEFAULT_OUTPUT_NAME = "F"


def validate_output_name(name: str | None, var_order: list[str]) -> str:
    """Validate a user-supplied output name (display metadata only — never
    touches ``SynthesisResult`` or any engine computation). Defaults to
    "F" when blank. Raises ``ValueError`` on anything outside D8's
    single-letter-plus-optional-digit shape, or a name that collides with
    one of the function's own input variables (which would make the
    printed expression read as if the output referenced itself)."""
    name = (name or "").strip()
    if not name:
        return DEFAULT_OUTPUT_NAME
    if not _OUTPUT_NAME_RE.match(name):
        raise ValueError(
            f"{name!r} is not a valid output name — use a single letter with an "
            "optional trailing digit (e.g. 'Y', 'M0'), the same shape D8 uses for "
            "variable names"
        )
    if name in var_order:
        raise ValueError(
            f"output name {name!r} duplicates an input variable name — choose a "
            "different name so the result doesn't read as self-referential"
        )
    return name


def _display_function(f_prime: Expr) -> Expr:
    """F, for display, from F' (what the PDN actually realizes): F = NOT(F').
    Collapses the one case that's structurally a double negation — when
    F' is itself a single complemented literal (e.g. F'=a', a degenerate
    "buffer" gate) — so the student sees "F = a", not "F = a''"."""
    if isinstance(f_prime, Not):
        return f_prime.operand
    return Not(f_prime)


@dataclass(frozen=True)
class CandidateGroup:
    labels: tuple[str, ...]  # every construction path that reached this expression, e.g. ("AOI", "OAI")
    expression: str
    core_cost: int
    inverter_cost: int
    total_cost: int
    is_chosen: bool


def _group_candidates(candidates: tuple[Candidate, ...], chosen: Candidate) -> list[CandidateGroup]:
    """Collapse candidates that are the exact same realization (same
    rendered expression AND same cost breakdown) reached by more than one
    construction path — Q1's 3-input NAND is the canonical case: AOI and
    OAI both land on F'=abc. This is presentation-only grouping; the
    underlying ``candidates`` tuple (still every candidate considered,
    ungrouped) is what Advanced Details shows, unaffected by this."""
    groups: dict[tuple[str, int, int, int], dict] = {}
    order: list[tuple[str, int, int, int]] = []
    for c in candidates:
        key = (render_expr(c.f_prime), c.core_cost, c.inverter_cost, c.total_cost)
        if key not in groups:
            groups[key] = {"labels": [], "is_chosen": False}
            order.append(key)
        groups[key]["labels"].append(c.label)
        if c is chosen:
            groups[key]["is_chosen"] = True

    result = []
    for key in order:
        expression, core, inverter, total = key
        g = groups[key]
        result.append(
            CandidateGroup(
                labels=tuple(g["labels"]),
                expression=expression,
                core_cost=core,
                inverter_cost=inverter,
                total_cost=total,
                is_chosen=g["is_chosen"],
            )
        )
    result.sort(key=lambda g: (g.total_cost, g.expression))
    return result


def _selection_reasoning(groups: list[CandidateGroup], *, max_stack_applied: bool) -> str:
    """A plain-English account of why the chosen realization was chosen —
    covering every real case, not a single "cheapest wins" sentence that
    would be false in the tied/degenerate cases."""
    chosen_group = next(g for g in groups if g.is_chosen)
    prefix = (
        "Selected from the candidates satisfying the current --max-stack "
        "constraint (some topologies may have been excluded by it): "
        if max_stack_applied
        else ""
    )

    if len(groups) == 1:
        base = "Only one distinct realization was found in the search space (D1/D16); no comparison was needed."
    else:
        tied = [g for g in groups if g is not chosen_group and g.total_cost == chosen_group.total_cost]
        if tied:
            base = (
                f"Tied at {chosen_group.total_cost} transistors with {len(tied)} other "
                "realization(s); selected via the canonical tie-break (D5)."
            )
        else:
            next_cheapest = min(g.total_cost for g in groups if g.total_cost > chosen_group.total_cost)
            base = (
                f"Chosen for its strictly lower transistor count "
                f"({chosen_group.total_cost} vs {next_cheapest} for the next alternative)."
            )

    if len(chosen_group.labels) > 1:
        base += f" Reached independently via both {' and '.join(chosen_group.labels)} construction."

    return prefix + base


def _minimality_summary(result: SynthesisResult) -> str:
    if result.minimality_proof:
        # pdn_transistors == the literal count of the chosen F' (one
        # transistor per literal, D16 point 1) -- PUN mirrors it exactly
        # (same literals, dual topology), so it's not counted twice here.
        return f"Proven minimal — {len(result.var_order)} essential variable(s), {result.pdn_transistors} literal(s)."
    return "Not proven minimal within this search space (D6) — a different factoring might do better."


def build_synth_view(
    result: SynthesisResult,
    *,
    output_name: str | None = None,
    max_stack_applied: bool = False,
) -> dict:
    """The student-facing structured view of ``result``. ``output_name``
    must already be validated (see :func:`validate_output_name`) — this
    function trusts it as given."""
    assert result.verification.passed, (
        "build_synth_view must only be called with a verified SynthesisResult (D7) — "
        "synthesize() itself guarantees this by raising before returning an unverified one"
    )

    name = output_name or DEFAULT_OUTPUT_NAME
    function_expr = _display_function(result.f_prime)
    groups = _group_candidates(result.other_candidates, result.chosen)
    v = result.verification

    return {
        "output_name": name,
        "function": f"{name} = {render_expr(function_expr)}",
        "function_uses_dont_cares": bool(v.dont_care_assignments),
        "gate_name": result.gate_name,
        "f_prime": render_expr(result.f_prime),
        "total_transistors": result.total_transistors,
        "pdn": {
            "expression": render_network(result.pdn),
            "transistors": result.pdn_transistors,
            "stack_height": result.pdn_stack_height,
        },
        "pun": {
            "expression": render_network(result.pun),
            "transistors": result.pun_transistors,
            "stack_height": result.pun_stack_height,
        },
        "inverters": {
            "count": result.inverter_transistors,
            "literals": list(result.inverter_literals),
        },
        "stack_advisory": result.stack_advisory,
        "reasoning": {
            "chosen_label": result.chosen_label,
            "selection_note": _selection_reasoning(groups, max_stack_applied=max_stack_applied),
            "minimality_summary": _minimality_summary(result),
            "minimality_detail": result.minimality_proof,
            "alternatives": [
                {
                    "labels": list(g.labels),
                    "expression": g.expression,
                    "core_cost": g.core_cost,
                    "inverter_cost": g.inverter_cost,
                    "total_cost": g.total_cost,
                    "is_chosen": g.is_chosen,
                }
                for g in groups
            ],
        },
        "verification": {
            "vector_count": v.vector_count,
            "functional_pass": v.functional_pass,
            "structural_pass": v.structural_pass,
            "mismatches": list(v.mismatches),
            "floating": list(v.floating),
            "shorted": list(v.shorted),
            "dont_care_assignments": {str(i): val for i, val in sorted(v.dont_care_assignments.items())},
        },
    }
