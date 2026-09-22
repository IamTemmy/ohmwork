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
    dual,
    literal_count as net_literal_count,
    stack_height,
    to_network,
)
from ohmwork.simplify import minimal_covers, minimize
from ohmwork.verify import VerificationResult, verify

# D3: stacks taller than this get an advisory, not a rejection, by default.
STACK_ADVISORY_THRESHOLD = 4

# Charter §8: M1b's deliverable and acceptance test are scoped to 3-4
# variables ("Deliberately excluded from M1 entirely: ... 5+ variables").
# 1-2 variables are strictly simpler than the tested ceiling, so they're
# allowed too; only the upper bound is a hard scope line.
MIN_VARS = 1
MAX_VARS = 5


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
    core_cost: int  # PDN + PUN literal transistors only
    inverter_cost: int  # shared-inverter transistors (D12), 0 under --dual-rail
    total_cost: int  # core_cost + inverter_cost — what selection actually ranks on

    @property
    def complemented_names(self) -> frozenset[str]:
        return frozenset(_complemented_names(self.f_prime))


def _make_candidate(label: str, f_prime: Expr, *, dual_rail: bool) -> Candidate:
    core = 2 * _count_literals(f_prime)
    inverters = 0 if dual_rail else 2 * len(_complemented_names(f_prime))
    return Candidate(label, f_prime, core, inverters, core + inverters)


def _covers_for(var_order: list[str], target_minterms: set[int], dont_cares: set[int]) -> list[Expr]:
    """Every literal-minimal SOP for a target minterm set, or the single
    constant Expr if the function is constantly 0 or 1 (minimal_covers has
    no "covers" to offer in that case)."""
    if len(var_order) == 5:
        from ohmwork.search_budget import SearchBudget
        covers = minimal_covers(var_order, target_minterms, dont_cares, _budget=SearchBudget())
    else:
        covers = minimal_covers(var_order, target_minterms, dont_cares)
    if covers is None:
        return [minimize(var_order, target_minterms, dont_cares)]
    return covers


def _build_candidates(
    var_order: list[str], minterms: set[int], dont_cares: set[int], *, dual_rail: bool
) -> list[Candidate]:
    """Every AOI candidate (one per literal-minimal SOP of F') and every OAI
    candidate (one per literal-minimal SOP of F, De Morgan-complemented) —
    not just one of each. Two covers can tie on term/literal count while
    needing different numbers of complemented literals, which changes their
    *total* transistor cost once inverters are counted (D12); collecting
    every tie here, rather than letting minimize() silently commit to one
    via its own (inverter-blind) D5 tie-break, is what lets ``_select``
    below rank on the cost that actually matters for synthesis."""
    n_vars = len(var_order)
    full = set(range(2**n_vars))
    zeros = full - minterms - dont_cares

    aoi_f_primes = _covers_for(var_order, zeros, dont_cares)
    oai_f_sops = _covers_for(var_order, minterms, dont_cares)
    oai_f_primes = [de_morgan_complement(sop) for sop in oai_f_sops]

    candidates = [_make_candidate("AOI", fp, dual_rail=dual_rail) for fp in aoi_f_primes]
    candidates += [_make_candidate("OAI", fp, dual_rail=dual_rail) for fp in oai_f_primes]
    # minimal_covers() already returns each direction's covers in a fixed
    # (hash-seed-independent) order, but sort the combined list here too —
    # SynthesisResult.other_candidates is a public, caller-facing field, and
    # its order shouldn't depend on trusting an upstream module's internals.
    # Total cost first (cheapest-first reads naturally), then the rendered
    # form and label as a deterministic tie-break for equal-cost candidates.
    candidates.sort(key=lambda c: (c.total_cost, render_expr(c.f_prime), c.label))
    return candidates


def _select(candidates: list[Candidate]) -> Candidate:
    """Cheapest *total* cost (PDN + PUN + inverters, D2/D12) wins; D5's
    canonical-string tie-break applies only among candidates that are
    genuinely tied on that complete cost."""
    best_cost = min(c.total_cost for c in candidates)
    tied = [c for c in candidates if c.total_cost == best_cost]
    return min(tied, key=lambda c: render_expr(c.f_prime))


def _prove_minimal_or_none(chosen: Candidate, var_order: list[str]) -> str | None:
    """A narrow, honest minimality certificate (D6): if the chosen PDN uses
    exactly one literal per variable actually appearing in it, and that set
    covers every declared variable, no *complementary static CMOS*
    realization (single- or multi-stage) can use fewer PDN+PUN (core)
    transistors — each variable the function depends on must control at
    least one device in both networks. Returns the proof text, or None if
    this particular bound doesn't apply (the result may still be minimal;
    we just haven't proven it).

    Scoped deliberately to complementary static CMOS (a wording fix from a
    2026-09-18 ChatGPT review, Q3 dogfooding): the bound is on PDN+PUN
    (core) transistors specifically, never on `total_cost`. This matters
    because `inverter_cost` can be nonzero even when this exact certificate
    fires (a chosen PDN can use one literal per variable *and* need a
    shared inverter for a complemented one, D12) -- a second ChatGPT review
    caught this proof text (and, worse, presenter.py's short summary)
    implying the *whole* design was proven minimal in that case, when only
    the core is bounded and the inverter cost is not covered at all. When
    `chosen.inverter_cost` is nonzero, the text says so explicitly rather
    than leaving it to be inferred from "PDN+PUN" wording alone."""
    pdn_literals = _count_literals(chosen.f_prime)
    used_vars = _variable_names(chosen.f_prime)
    if pdn_literals == len(var_order) and used_vars == set(var_order):
        n = len(var_order)
        core_bound = 2 * n
        proof = (
            f"proven minimal for complementary static CMOS: every declared variable ({n}) "
            "appears exactly once as a literal, so each must control at least one "
            "transistor in both the pull-down and pull-up networks — no complementary "
            f"static CMOS realization (single- or multi-stage) could use fewer than {core_bound} "
            "PDN+PUN transistors for this function. This bound is specific to "
            "complementary static CMOS; it makes no claim about pass-transistor logic, "
            "ratioed logic, dynamic logic, or any other circuit family."
        )
        if chosen.inverter_cost:
            proof += (
                f" This bound covers the {core_bound} PDN+PUN (core) transistors only — it "
                f"does not cover the {chosen.inverter_cost} inverter transistor(s) this "
                f"realization also needs (D12), so the {core_bound + chosen.inverter_cost}-"
                "transistor total is NOT proven minimal by this argument."
            )
        return proof
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
    chosen: Candidate  # the exact winning candidate (identity-comparable against other_candidates)
    other_candidates: tuple[Candidate, ...]  # every candidate considered, for "show the work"
    verification: VerificationResult  # D7: always populated, always checked before return
    # D18: immutable input provenance; None distinguishes legacy/manual results
    # from a real empty set. Appended defaults preserve existing constructors.
    minterms: frozenset[int] | None = None
    dont_cares: frozenset[int] | None = None


def synthesize(
    var_order: list[str],
    minterms: set[int],
    dont_cares: set[int] = frozenset(),
    *,
    dual_rail: bool = False,
    max_stack: int | None = None,
) -> SynthesisResult:
    """Synthesize a single-stage static CMOS complex gate for a function
    given as a truth table (D4: don't-cares assigned freely). Compares every
    AOI and OAI candidate (D1, D16) and returns the one with the cheapest
    *complete* transistor cost (PDN + PUN + shared inverters, D2/D12),
    D5-tie-broken.

    D20 supports 1–5 declared variables; raises ValueError outside that range.
    Five-variable exact-search exhaustion raises SearchLimitExceeded; it is an
    expected resource limit, not an internal verification failure.

    Verifies the chosen design (D7) before returning it — per charter §4,
    "every emitted network is exhaustively simulated... before it is
    returned." A verification failure here means a bug in this module, not
    bad input, so it raises rather than returning a result callers might
    mistake for valid; ``result.verification`` still lets a caller re-check
    independently rather than take that guarantee on faith.

    Raises ``ValueError`` if ``max_stack`` (D3's opt-in engineering
    constraint) rules out every candidate — this tool declines to guess at
    a multi-stage decomposition it hasn't built, per D6."""
    if not (MIN_VARS <= len(var_order) <= MAX_VARS):
        raise ValueError(
            f"synth supports {MIN_VARS}-{MAX_VARS} variables; got {len(var_order)} ({', '.join(var_order)})"
        )

    return _synthesize(var_order, minterms, dont_cares, dual_rail=dual_rail, max_stack=max_stack)


def _synthesize(var_order, minterms, dont_cares=frozenset(), *, dual_rail=False, max_stack=None):
    """Shared synthesis implementation for up to five declared variables."""
    if not 1 <= len(var_order) <= 5:
        raise ValueError('synth supports 1-5 variables')

    candidates = _build_candidates(var_order, minterms, dont_cares, dual_rail=dual_rail)

    if max_stack is not None:
        def fits(c: Candidate) -> bool:
            pdn = to_network(c.f_prime, "n")
            return stack_height(pdn) <= max_stack and stack_height(dual(pdn, "p")) <= max_stack

        compliant = [c for c in candidates if fits(c)]
        if not compliant:
            heights = ", ".join(
                f"{c.label} stack {stack_height(to_network(c.f_prime, 'n'))}" for c in candidates
            )
            raise ValueError(
                f"no AOI/OAI candidate fits within --max-stack {max_stack} ({heights}); "
                "a multi-stage NAND/NOR decomposition might, but that search isn't "
                "implemented yet — reporting nothing rather than guessing one (D6)"
            )
        candidates = compliant

    chosen = _select(candidates)
    pdn = to_network(chosen.f_prime, "n")
    pun = dual(pdn, "p")

    complemented = sorted(chosen.complemented_names)

    pdn_h = stack_height(pdn)
    pun_h = stack_height(pun)
    advisory = None
    if max(pdn_h, pun_h) > STACK_ADVISORY_THRESHOLD:
        advisory = (
            f"stack height {max(pdn_h, pun_h)} exceeds {STACK_ADVISORY_THRESHOLD} — fine for "
            "textbook/coursework use (D3 default is unconstrained), but production designs "
            "typically cap here for speed and robustness; pass --max-stack to enforce a limit"
        )

    verification = verify(pdn, pun, var_order, minterms, dont_cares)
    if not verification.passed:
        raise RuntimeError(
            "internal error: the synthesized design failed its own D7 verification "
            f"(functional_pass={verification.functional_pass}, "
            f"structural_pass={verification.structural_pass}) — this is a bug in ohmwork's "
            "synthesis, not a problem with your input; per charter §4 no unverified design "
            "is ever returned, so this raises instead of handing back a result"
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
        inverter_transistors=chosen.inverter_cost,
        total_transistors=net_literal_count(pdn) + net_literal_count(pun) + chosen.inverter_cost,
        pdn_stack_height=pdn_h,
        pun_stack_height=pun_h,
        stack_advisory=advisory,
        minimality_proof=_prove_minimal_or_none(chosen, var_order),
        chosen=chosen,
        other_candidates=tuple(candidates),
        verification=verification,
        minterms=frozenset(minterms),
        dont_cares=frozenset(dont_cares),
    )
