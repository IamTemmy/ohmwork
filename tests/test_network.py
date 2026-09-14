"""Tests for the series-parallel switch-network model (PDN/PUN construction,
duality, simulation)."""

import pytest

from ohmwork.expr import Not, Var
from ohmwork.network import (
    Parallel,
    Series,
    Transistor,
    collect_literals,
    conducts,
    dual,
    literal_count,
    render_network,
    stack_height,
    to_network,
)
from ohmwork.parser import parse


def test_and_becomes_series():
    net = to_network(parse("abc"), "n")
    assert net == Series((Transistor(Var("a"), "n"), Transistor(Var("b"), "n"), Transistor(Var("c"), "n")))


def test_or_becomes_parallel():
    net = to_network(parse("a+b"), "n")
    assert net == Parallel((Transistor(Var("a"), "n"), Transistor(Var("b"), "n")))


def test_bare_literal_becomes_single_transistor():
    assert to_network(parse("a"), "n") == Transistor(Var("a"), "n")
    assert to_network(parse("a'"), "n") == Transistor(Not(Var("a")), "n")


def test_aoi_shape_parallel_of_series():
    # (ab+c)': F' = ab+c -> parallel of [series(a,b), c]
    net = to_network(parse("ab+c"), "n")
    assert net == Parallel((Series((Transistor(Var("a"), "n"), Transistor(Var("b"), "n"))), Transistor(Var("c"), "n")))


def test_xor_has_no_switch_realization():
    with pytest.raises(ValueError, match="XOR"):
        to_network(parse("a^b"), "n")


def test_dual_swaps_series_and_parallel_and_kind():
    pdn = to_network(parse("ab+c"), "n")
    pun = dual(pdn, "p")
    assert pun == Series((Parallel((Transistor(Var("a"), "p"), Transistor(Var("b"), "p"))), Transistor(Var("c"), "p")))


def test_dual_is_involutive():
    pdn = to_network(parse("ab+c'd"), "n")
    assert dual(dual(pdn, "p"), "n") == pdn


# --- conducts(): NMOS on when literal=1, PMOS on when literal=0 ------------


def test_nmos_transistor_conducts_when_literal_true():
    t = Transistor(Var("a"), "n")
    assert conducts(t, {"a": True}) is True
    assert conducts(t, {"a": False}) is False


def test_pmos_transistor_conducts_when_literal_false():
    t = Transistor(Var("a"), "p")
    assert conducts(t, {"a": True}) is False
    assert conducts(t, {"a": False}) is True


def test_series_conducts_only_if_all_branches_conduct():
    net = to_network(parse("ab"), "n")
    assert conducts(net, {"a": True, "b": True}) is True
    assert conducts(net, {"a": True, "b": False}) is False


def test_parallel_conducts_if_any_branch_conducts():
    net = to_network(parse("a+b"), "n")
    assert conducts(net, {"a": False, "b": True}) is True
    assert conducts(net, {"a": False, "b": False}) is False


def test_pdn_and_dual_pun_are_always_complementary():
    # The defining property of complementary CMOS: for every input, exactly
    # one of PDN/PUN conducts. Checked here as a network-level invariant
    # (independent of ohmwork.verify's own end-to-end check).
    import itertools

    pdn = to_network(parse("(ab+c)(d+e')"), "n")
    pun = dual(pdn, "p")
    for bits in itertools.product([False, True], repeat=5):
        assignment = dict(zip("abcde", bits))
        assert conducts(pdn, assignment) != conducts(pun, assignment)


# --- literal_count / stack_height -------------------------------------------


def test_literal_count_counts_every_transistor():
    assert literal_count(to_network(parse("ab+c"), "n")) == 3
    assert literal_count(to_network(parse("abcd"), "n")) == 4


def test_stack_height_of_series_sums_branches():
    assert stack_height(to_network(parse("abc"), "n")) == 3


def test_stack_height_of_parallel_takes_the_worst_branch():
    # parallel of [series(a,b), c]: worst path is 2, not 2+1
    assert stack_height(to_network(parse("ab+c"), "n")) == 2


def test_stack_height_of_series_of_parallels_sums_the_worst_of_each():
    # series(parallel(a,b), parallel(c,d,e)): 1 (any of a/b) + 1 (any of c/d/e) = 2
    net = to_network(parse("(a+b)(c+d+e)"), "n")
    assert stack_height(net) == 2


# --- collect_literals --------------------------------------------------------


def test_collect_literals_deduplicates_and_preserves_order():
    net = to_network(parse("ab'+ab"), "n")
    names = [render_network(Transistor(lit, "n")) for lit in collect_literals(net)]
    assert names == ["a", "b'", "b"]


# --- render_network ----------------------------------------------------------


def test_render_series():
    assert render_network(to_network(parse("abc"), "n")) == "a·b·c"


def test_render_parallel():
    assert render_network(to_network(parse("a+b"), "n")) == "a + b"


def test_render_aoi_shape_parenthesizes_nested_parallel_inside_series():
    # series(parallel(a,b), c): the parallel branch needs parens since it's
    # nested inside a series (tighter-binding) context.
    net = to_network(parse("(a+b)c"), "n")
    assert render_network(net) == "(a + b)·c"


def test_render_aoi_shape_no_parens_needed_for_series_inside_parallel():
    net = to_network(parse("ab+c"), "n")
    assert render_network(net) == "a·b + c"
