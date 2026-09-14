"""The series-parallel switch-network model used to build and simulate a
static CMOS gate's PDN (pull-down, NMOS) and PUN (pull-up, PMOS).

A network is one of:
  - ``Transistor(literal, kind)``: a single switch, gated by a D8 literal
    (a ``Var`` or ``Not(Var)``), that conducts when that literal is true (an
    "n"-kind/NMOS device) or false (a "p"-kind/PMOS device).
  - ``Series(branches)``: conducts only if every branch conducts (AND).
  - ``Parallel(branches)``: conducts if any branch conducts (OR).

``to_network`` builds one of these directly from a Boolean expression built
only from And/Or/Not(Var)/Var (i.e. a switching-algebra expression, not a
general D8 expression — Xor has no series-parallel switch realization and
is rejected). ``dual`` produces the complementary-CMOS partner network: same
literals, series and parallel swapped, NMOS/PMOS swapped — the textbook
construction that makes PUN conduct in exactly the input combinations PDN
does not (D7's structural-validity guarantee is a property of this
construction, but M1b still simulates both networks to check it rather than
assume it — see ohmwork.verify)."""

from __future__ import annotations

from dataclasses import dataclass

from ohmwork.derivation import evaluate
from ohmwork.expr import And, Const, Expr, Not, Or, Var, render as render_expr

Kind = str  # "n" (NMOS) or "p" (PMOS)


class Network:
    """Base class for a switch network."""

    __slots__ = ()


@dataclass(frozen=True, slots=True)
class Transistor(Network):
    literal: Expr  # Var or Not(Var)
    kind: Kind  # "n" or "p"


@dataclass(frozen=True, slots=True)
class Series(Network):
    branches: tuple[Network, ...]


@dataclass(frozen=True, slots=True)
class Parallel(Network):
    branches: tuple[Network, ...]


def _is_literal(expr: Expr) -> bool:
    return isinstance(expr, Var) or (isinstance(expr, Not) and isinstance(expr.operand, Var))


def to_network(expr: Expr, kind: Kind) -> Network:
    """Map a switching-algebra expression (And/Or/Not(Var)/Var only) to a
    series-parallel switch network: AND -> series, OR -> parallel, each
    literal -> one transistor of the given ``kind``."""
    if _is_literal(expr):
        return Transistor(expr, kind)
    if isinstance(expr, And):
        return Series(tuple(to_network(o, kind) for o in expr.operands))
    if isinstance(expr, Or):
        return Parallel(tuple(to_network(o, kind) for o in expr.operands))
    if isinstance(expr, Const):
        raise ValueError(
            f"'{render_expr(expr)}' is a constant function — it needs no switch network "
            "(tie the output directly to VDD or GND), not a synthesizable gate"
        )
    raise ValueError(
        f"'{render_expr(expr)}' cannot become a switch network: only AND/OR/complement of "
        "literals has a series-parallel realization (e.g. XOR does not)"
    )


def dual(network: Network, kind: Kind) -> Network:
    """The complementary-CMOS dual: same literals, series<->parallel
    swapped, every transistor's kind replaced with ``kind`` (typically "p"
    when dualizing an "n" PDN into a PUN, or vice versa)."""
    if isinstance(network, Transistor):
        return Transistor(network.literal, kind)
    if isinstance(network, Series):
        return Parallel(tuple(dual(b, kind) for b in network.branches))
    if isinstance(network, Parallel):
        return Series(tuple(dual(b, kind) for b in network.branches))
    raise TypeError(f"unknown network node: {network!r}")  # pragma: no cover


def conducts(network: Network, assignment: dict[str, bool]) -> bool:
    """Whether ``network`` conducts (is "on") under a variable assignment."""
    if isinstance(network, Transistor):
        gate = evaluate(network.literal, assignment)
        return gate if network.kind == "n" else not gate
    if isinstance(network, Series):
        return all(conducts(b, assignment) for b in network.branches)
    if isinstance(network, Parallel):
        return any(conducts(b, assignment) for b in network.branches)
    raise TypeError(f"unknown network node: {network!r}")  # pragma: no cover


def literal_count(network: Network) -> int:
    """Transistor count — one per literal/leaf."""
    if isinstance(network, Transistor):
        return 1
    if isinstance(network, (Series, Parallel)):
        return sum(literal_count(b) for b in network.branches)
    raise TypeError(f"unknown network node: {network!r}")  # pragma: no cover


def stack_height(network: Network) -> int:
    """Longest chain of transistors in series along any conducting path
    (D3): a ``Series`` adds its branches' heights; a ``Parallel`` takes the
    worst of its branches, since only one is traversed at a time."""
    if isinstance(network, Transistor):
        return 1
    if isinstance(network, Series):
        return sum(stack_height(b) for b in network.branches)
    if isinstance(network, Parallel):
        return max((stack_height(b) for b in network.branches), default=0)
    raise TypeError(f"unknown network node: {network!r}")  # pragma: no cover


def collect_literals(network: Network) -> list[Expr]:
    """Every distinct literal gating some transistor in the network, in
    first-encountered order (used for D12's shared-inverter accounting)."""
    seen: dict[str, Expr] = {}

    def walk(n: Network) -> None:
        if isinstance(n, Transistor):
            seen.setdefault(render_expr(n.literal), n.literal)
        elif isinstance(n, (Series, Parallel)):
            for b in n.branches:
                walk(b)
        else:  # pragma: no cover
            raise TypeError(f"unknown network node: {n!r}")

    walk(network)
    return list(seen.values())


def _wrap_if_parallel(n: Network) -> str:
    s = render_network(n)
    return f"({s})" if isinstance(n, Parallel) else s


def render_network(network: Network) -> str:
    """Compact D8-flavored notation: series as juxtaposition-by-dot, parallel
    as ``+``. A ``Parallel`` nested inside a ``Series`` is parenthesized
    (looser precedence); the reverse never needs it."""
    if isinstance(network, Transistor):
        return render_expr(network.literal)
    if isinstance(network, Series):
        return "·".join(_wrap_if_parallel(b) for b in network.branches)
    if isinstance(network, Parallel):
        return " + ".join(render_network(b) for b in network.branches)
    raise TypeError(f"unknown network node: {network!r}")  # pragma: no cover
