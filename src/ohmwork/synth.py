"""M1b's synthesis core: truth table -> verified minimum-transistor static
CMOS design, within the search space D1 declares for v1 ("single-stage
complex gates (AOI/OAI and their generalizations)").

Two candidate PDN shapes are built and compared on transistor cost:

  - **AOI candidate**: minimize F' directly into a minimal SOP, then map it
    straight to a switch network (AND -> series, OR -> parallel). This gives
    a parallel-of-series ("AND-OR-INVERT") PDN shape.
  - **OAI candidate**: minimize F itself into a minimal SOP, then take its
    structural De Morgan complement (swap And/Or, complement each literal)
    to get an equivalent expression for F' — a series-of-parallels
    ("OR-AND-INVERT") PDN shape.

Both are valid realizations of the same function; they generally cost
different numbers of literals (transistors), so trying both and keeping the
cheaper one is what D1 means by "AOI/OAI and their generalizations." This is
*not* general algebraic factoring — a function whose cheapest realization
needs sharing a literal across product terms in a way neither minimal-SOP
candidate captures (e.g. ``((a+b)c)'`` some factorings) won't be found here,
which is exactly why results are labeled "not proven minimal" (D6) unless a
literal-count lower bound proves them so (see ``_prove_minimal_or_none``).
"""

from __future__ import annotations

from dataclasses import dataclass

from ohmwork.expr import And, Const, Expr, Not, Or, Var, mk_and, mk_or, render as render_expr
from ohmwork.network import (
    Network,
    Parallel,
    Series,
    Transistor,
    collect_literals,
    dual,
    literal_count as net_literal_count,
    render_network,
    stack_height,
    to_network,
)
from ohmwork.simplify import minimize

# D3: stacks taller than this get an advisory, not a rejection, by default.
STACK_ADVISORY_THRESHOLD = 4


def de_morgan_complement(expr: Expr) -> Expr:
    """Structurally complement a switching-algebra expression (And/Or/
    Not(Var)/Var/Const) by swapping And<->Or and complementing every
    literal — i.e. apply De Morgan's laws term by term rather than wrapping
    the whole thing in a fresh ``Not``.

    This is a deliberate, visible step in synthesis (building the OAI
    candidate from F's own minimal SOP), not the kind of silent identity
    rewrite D5 forbids in canonicalization/tie-breaking — those are a
    different concern (which of several already-equal-cost forms to print),
    while this produces a genuinely different network topology to compare
    on cost."""
    if isinstance(expr, Var):
        return Not(expr)
    if isinstance(expr, Not):
        assert isinstance(expr.operand, Var)  # QM output is always flat SOP
        return expr.operand
    if isinstance(expr, Const):
        return Const(not expr.value)
    if isinstance(expr, And):
        return mk_or([de_morgan_complement(o) for o in expr.operands])
    if isinstance(expr, Or):
        return mk_and([de_morgan_complement(o) for o in expr.operands])
    raise ValueError(f"de_morgan_complement is undefined for {expr!r} (not switching-algebra)")


def _count_literals(expr: Expr) -> int:
    if isinstance(expr, (Var, Not)):
        return 1
    if isinstance(expr, Const):
        return 0
    if isinstance(expr, (And, Or)):
        return sum(_count_literals(o) for o in expr.operands)
    raise TypeError(f"unexpected node in a switching-algebra expression: {expr!r}")


def _complemented_names(expr: Expr) -> set[str]:
    names: set[str] = set()

    def walk(e: Expr) -> None:
        if isinstance(e, Not) and isinstance(e.operand, Var):
            names.add(e.operand.name)
        elif isinstance(e, (And, Or)):
            for o in e.operands:
                walk(o)

    walk(expr)
    return names


def _variable_names(expr: Expr) -> set[str]:
    names: set[str] = set()

    def walk(e: Expr) -> None:
        if isinstance(e, Var):
            names.add(e.name)
        elif isinstance(e, Not):
            walk(e.operand)
        elif isinstance(e, (And, Or)):
            for o in e.operands:
                walk(o)

    walk(expr)
    return names


@dataclass(frozen=True)
class Candidate:
    label: str  # "AOI" or "OAI" — which construction produced it
    f_prime: Expr  # the switching-algebra expression realized by the PDN
    transistor_cost: int  # PDN + PUN literal transistors, inverters excluded

    @property
    def complemented_names(self) -> frozenset[str]:
        return frozenset(_complemented_names(self.f_prime))


def _build_candidates(var_order: list[str], minterms: set[int], dont_cares: set[int]) -> list[Candidate]:
    n_vars = len(var_order)
    full = set(range(2**n_vars))
    zeros = full - minterms - dont_cares

    aoi_f_prime = minimize(var_order, zeros, dont_cares)  # F' minimized directly
    oai_f_sop = minimize(var_order, minterms, dont_cares)  # F minimized, then complemented
    oai_f_prime = de_morgan_complement(oai_f_sop)

    candidates = [
        Candidate("AOI", aoi_f_prime, 2 * _count_literals(aoi_f_prime)),
        Candidate("OAI", oai_f_prime, 2 * _count_literals(oai_f_prime)),
    ]
    return candidates


def _select(candidates: list[Candidate]) -> Candidate:
    """D5 tie-break: cheapest transistor cost; ties broken by canonical
    (rendered) form of the realized F', compared lexicographically."""
    best_cost = min(c.transistor_cost for c in candidates)
    tied = [c for c in candidates if c.transistor_cost == best_cost]
    return min(tied, key=lambda c: render_expr(c.f_prime))


def _prove_minimal_or_none(chosen: Candidate, var_order: list[str]) -> str | None:
    """A narrow, honest minimality certificate (D6): if the chosen PDN uses
    exactly one literal per variable actually appearing in it, and that set
    covers every declared variable, no realization (in ANY search space,
    single- or multi-stage) can use fewer transistors — each variable the
    function depends on must appear as at least one literal somewhere.
    Returns the proof text, or None if this particular bound doesn't apply
    (the result may still be minimal; we just haven't proven it)."""
    pdn_literals = _count_literals(chosen.f_prime)
    used_vars = _variable_names(chosen.f_prime)
    if pdn_literals == len(var_order) and used_vars == set(var_order):
        return (
            f"proven minimal: every declared variable ({len(var_order)}) appears exactly "
            "once as a literal, and a network realizing a function that depends on n "
            "variables needs at least n literals — no design in any search space could "
            "use fewer transistors."
        )
    return None


def _gate_name(pdn: Network) -> str:
    """D14: name the gate from its PDN shape, glossing the generalization.
    Recognizes NAND/NOR/AOI/OAI and their higher-input generalizations;
    anything else is reported honestly as unnamed rather than guessed."""

    def branch_size(b: Network) -> int | None:
        if isinstance(b, Transistor):
            return 1
        if isinstance(b, Series):
            return len(b.branches) if all(isinstance(x, Transistor) for x in b.branches) else None
        if isinstance(b, Parallel):
            return len(b.branches) if all(isinstance(x, Transistor) for x in b.branches) else None
        return None

    if isinstance(pdn, Transistor):
        if isinstance(pdn.literal, Var):
            return "inverter (1 input)"
        return "buffer (degenerate: complemented input realized directly)"

    if isinstance(pdn, Series) and all(isinstance(b, Transistor) for b in pdn.branches):
        n = len(pdn.branches)
        return f"{n}-input NAND"

    if isinstance(pdn, Parallel) and all(isinstance(b, Transistor) for b in pdn.branches):
        n = len(pdn.branches)
        return f"{n}-input NOR"

    if isinstance(pdn, Parallel):
        sizes = [branch_size(b) for b in pdn.branches]
        if all(s is not None for s in sizes):
            sizes = sorted(sizes, reverse=True)
            return "AOI" + "".join(str(s) for s in sizes)

    if isinstance(pdn, Series):
        sizes = [branch_size(b) for b in pdn.branches]
        if all(s is not None for s in sizes):
            sizes = sorted(sizes, reverse=True)
            return "OAI" + "".join(str(s) for s in sizes)

    return "custom complex gate (no standard AOI/OAI/NAND/NOR name)"


@dataclass(frozen=True)
class SynthesisResult:
    var_order: list[str]
    chosen_label: str  # "AOI" or "OAI"
    f_prime: Expr
    pdn: Network
    pun: Network
    gate_name: str
    pdn_transistors: int
    pun_transistors: int
    inverter_literals: tuple[str, ...]  # variable names needing a shared inverter
    inverter_transistors: int
    total_transistors: int
    pdn_stack_height: int
    pun_stack_height: int
    stack_advisory: str | None
    minimality_proof: str | None
    other_candidates: tuple[Candidate, ...]  # every candidate considered, for "show the work"


def synthesize(
    var_order: list[str],
    minterms: set[int],
    dont_cares: set[int] = frozenset(),
    *,
    dual_rail: bool = False,
    max_stack: int | None = None,
) -> SynthesisResult:
    """Synthesize a single-stage static CMOS complex gate for a function
    given as a truth table (D4: don't-cares assigned freely). Compares the
    AOI and OAI candidates (D1) and returns the cheaper, D5-tie-broken one.

    Raises ``ValueError`` if ``max_stack`` (D3's opt-in engineering
    constraint) rules out every candidate — this tool declines to guess at
    a multi-stage decomposition it hasn't built, per D6."""
    candidates = _build_candidates(var_order, minterms, dont_cares)

    if max_stack is not None:
        compliant = [
            c
            for c in candidates
            if stack_height(to_network(c.f_prime, "n")) <= max_stack
            and stack_height(dual(to_network(c.f_prime, "n"), "p")) <= max_stack
        ]
        if not compliant:
            raise ValueError(
                f"no single-stage AOI/OAI candidate fits within --max-stack {max_stack} "
                f"(AOI stack {stack_height(to_network(candidates[0].f_prime, 'n'))}, "
                f"OAI stack {stack_height(to_network(candidates[1].f_prime, 'n'))}); "
                "a multi-stage NAND/NOR decomposition might, but that search isn't "
                "implemented yet — reporting nothing rather than guessing one (D6)"
            )
        candidates = compliant

    chosen = _select(candidates)
    pdn = to_network(chosen.f_prime, "n")
    pun = dual(pdn, "p")

    complemented = sorted(chosen.complemented_names)
    inverter_transistors = 0 if dual_rail else 2 * len(complemented)

    pdn_h = stack_height(pdn)
    pun_h = stack_height(pun)
    advisory = None
    if max(pdn_h, pun_h) > STACK_ADVISORY_THRESHOLD:
        advisory = (
            f"stack height {max(pdn_h, pun_h)} exceeds {STACK_ADVISORY_THRESHOLD} — fine for "
            "textbook/coursework use (D3 default is unconstrained), but production designs "
            "typically cap here for speed and robustness; pass --max-stack to enforce a limit"
        )

    return SynthesisResult(
        var_order=list(var_order),
        chosen_label=chosen.label,
        f_prime=chosen.f_prime,
        pdn=pdn,
        pun=pun,
        gate_name=_gate_name(pdn),
        pdn_transistors=net_literal_count(pdn),
        pun_transistors=net_literal_count(pun),
        inverter_literals=tuple(complemented),
        inverter_transistors=inverter_transistors,
        total_transistors=net_literal_count(pdn) + net_literal_count(pun) + inverter_transistors,
        pdn_stack_height=pdn_h,
        pun_stack_height=pun_h,
        stack_advisory=advisory,
        minimality_proof=_prove_minimal_or_none(chosen, var_order),
        other_candidates=tuple(candidates),
    )
