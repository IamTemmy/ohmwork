"""Tests for D17 Phase A: the schematic layout model. Same style as
test_synth.py -- real `synthesize()` calls via `minterms_from_expr`, never a
hand-built SynthesisResult. Maps directly onto the D17 acceptance tests in
docs/decisions.md (1-7 here; 8 and 10 are Phase B/Playwright, not this file)."""

from __future__ import annotations

import dataclasses

import pytest

from ohmwork.derivation import all_assignments, evaluate
from ohmwork.network import conducts, dual, to_network
from ohmwork.parser import parse
from ohmwork.schematic import (
    CELL,
    Device,
    Point,
    WireSegment,
    _validate_topology_fidelity,
    build_schematic,
    complement_net_id,
    validate_layout_geometry,
    verify_layout,
)
from ohmwork.synth import synthesize
from ohmwork.verify import verify as verify_networks


def minterms_from_expr(var_order: list[str], expr_text: str) -> set[int]:
    ast = parse(expr_text)
    rows = all_assignments(var_order)
    return {i for i, row in enumerate(rows) if evaluate(ast, row)}


# --- D17 acceptance test 1: 3-input NAND -----------------------------------


def test_acceptance_1_nand3_shape():
    var_order = ["a", "b", "c"]
    minterms = minterms_from_expr(var_order, "(abc)'")
    result = synthesize(var_order, minterms)
    layout = build_schematic(result, "F")

    pun = [d for d in layout.devices if d.role == "pun"]
    pdn = [d for d in layout.devices if d.role == "pdn"]
    assert len(pun) == 3
    assert all(d.source_net == "VDD" and d.drain_net == "OUT" for d in pun)
    assert {d.gate_var for d in pun} == {"a", "b", "c"}

    assert len(pdn) == 3
    endpoints: dict[str, int] = {}
    for d in pdn:
        endpoints[d.source_net] = endpoints.get(d.source_net, 0) + 1
        endpoints[d.drain_net] = endpoints.get(d.drain_net, 0) + 1
    assert endpoints["OUT"] == 1
    assert endpoints["GND"] == 1
    internal = [v for k, v in endpoints.items() if k not in ("OUT", "GND")]
    assert internal == [2, 2]

    assert len(layout.devices) == 6 == result.total_transistors


# --- D17 acceptance test 2: 4-input NOR -------------------------------------


def test_acceptance_2_nor4_shape():
    var_order = ["a", "b", "c", "d"]
    minterms = minterms_from_expr(var_order, "(a+b+c+d)'")
    result = synthesize(var_order, minterms)
    layout = build_schematic(result, "F")

    pdn = [d for d in layout.devices if d.role == "pdn"]
    pun = [d for d in layout.devices if d.role == "pun"]
    assert len(pdn) == 4
    assert all(d.source_net == "GND" and d.drain_net == "OUT" for d in pdn)
    assert {d.gate_var for d in pdn} == {"a", "b", "c", "d"}

    assert len(pun) == 4
    endpoints: dict[str, int] = {}
    for d in pun:
        endpoints[d.source_net] = endpoints.get(d.source_net, 0) + 1
        endpoints[d.drain_net] = endpoints.get(d.drain_net, 0) + 1
    assert endpoints["VDD"] == 1
    assert endpoints["OUT"] == 1

    assert len(layout.devices) == 8 == result.total_transistors


# --- D17 acceptance test 3: AOI31 ------------------------------------------


def test_acceptance_3_aoi31_shape():
    var_order = ["a", "b", "c", "d"]
    minterms = minterms_from_expr(var_order, "(abc+d)'")
    result = synthesize(var_order, minterms)
    layout = build_schematic(result, "F")

    pdn = [d for d in layout.devices if d.role == "pdn"]
    abc_pdn = [d for d in pdn if d.gate_var in ("a", "b", "c")]
    d_pdn = [d for d in pdn if d.gate_var == "d"]
    assert {d.gate_var for d in abc_pdn} == {"a", "b", "c"}
    assert len(d_pdn) == 1
    # abc branch is a series chain from OUT to some shared node, in parallel with d
    endpoints: dict[str, int] = {}
    for dev in abc_pdn:
        endpoints[dev.source_net] = endpoints.get(dev.source_net, 0) + 1
        endpoints[dev.drain_net] = endpoints.get(dev.drain_net, 0) + 1
    assert endpoints["OUT"] == 1
    assert d_pdn[0].source_net == "GND"
    assert d_pdn[0].drain_net == "OUT"

    pun = [d for d in layout.devices if d.role == "pun"]
    abc_pun = [d for d in pun if d.gate_var in ("a", "b", "c")]
    d_pun = [d for d in pun if d.gate_var == "d"]
    assert len(abc_pun) == 3
    assert len(d_pun) == 1
    assert d_pun[0].drain_net == "OUT"

    assert len(layout.devices) == 8 == result.total_transistors


# --- D17 acceptance test 4: complemented literal, shared inverter ----------


def test_acceptance_4_complemented_literal_shared_inverter():
    var_order = ["a", "b", "c"]
    minterms = minterms_from_expr(var_order, "(a'b+c)'")
    result = synthesize(var_order, minterms)
    layout = build_schematic(result, "F")

    inv = [d for d in layout.devices if d.role == "inverter"]
    assert len(inv) == 2
    assert {d.kind for d in inv} == {"n", "p"}
    assert all(d.gate_var == "a" and not d.gate_complemented for d in inv)
    drains = {d.drain_net for d in inv}
    assert len(drains) == 1

    complement_id = complement_net_id(layout, "a")
    assert complement_id is not None
    assert drains == {complement_id}

    users = [d for d in layout.devices if d.role in ("pdn", "pun") and d.gate_var == "a" and d.gate_complemented]
    assert users
    assert all(d.gate_net == complement_id for d in users)

    assert len(layout.devices) == 8 == result.total_transistors


# --- D17 acceptance test 5: same case, dual-rail ----------------------------


def test_acceptance_5_dual_rail_no_inverter_devices():
    var_order = ["a", "b", "c"]
    minterms = minterms_from_expr(var_order, "(a'b+c)'")
    result = synthesize(var_order, minterms, dual_rail=True)
    layout = build_schematic(result, "F")

    assert [d for d in layout.devices if d.role == "inverter"] == []

    complement_id = complement_net_id(layout, "a")
    assert complement_id is not None
    net = next(n for n in layout.nets if n.id == complement_id)
    assert net.kind == "gate_complement_external"
    assert any(d.gate_net == complement_id for d in layout.devices)

    assert len(layout.devices) == 6 == result.total_transistors


# --- D17 acceptance test 6: output name relabeling --------------------------


def test_acceptance_6_output_name_relabeling():
    var_order = ["a", "b", "c"]
    minterms = minterms_from_expr(var_order, "(abc)'")
    result = synthesize(var_order, minterms)
    layout_f = build_schematic(result, "F")
    layout_y = build_schematic(result, "Y")

    assert layout_f.devices == layout_y.devices
    assert layout_f.wires == layout_y.wires

    out_f = next(n for n in layout_f.nets if n.id == "OUT")
    out_y = next(n for n in layout_y.nets if n.id == "OUT")
    assert out_f.label == "F"
    assert out_y.label == "Y"
    assert dataclasses.replace(out_f, label="Y") == out_y

    others_f = {n.id: n for n in layout_f.nets if n.id != "OUT"}
    others_y = {n.id: n for n in layout_y.nets if n.id != "OUT"}
    assert others_f == others_y


# --- D17 acceptance test 7: per-input-vector connectivity (the crux test) --


_ACCEPTANCE_7_CASES = [
    (["a", "b", "c"], "(abc)'", {}),
    (["a", "b", "c", "d"], "(a+b+c+d)'", {}),
    (["a", "b", "c", "d"], "(abc+d)'", {}),
    (["a", "b", "c"], "(a'b+c)'", {}),
    (["a", "b", "c"], "(a'b+c)'", {"dual_rail": True}),
]


@pytest.mark.parametrize("var_order,expr_text,opts", _ACCEPTANCE_7_CASES)
def test_acceptance_7_layout_connectivity_matches_verified_function(var_order, expr_text, opts):
    minterms = minterms_from_expr(var_order, expr_text)
    result = synthesize(var_order, minterms, **opts)
    layout = build_schematic(result, "F")

    from ohmwork.schematic import simulate_layout

    for row in all_assignments(var_order):
        state = simulate_layout(layout, row)[layout.output_net_id]
        assert not state.shorted
        assert not state.floating
        assert state.value == conducts(result.pun, row)

    vr = verify_layout(layout, var_order, minterms)
    assert vr.passed
    assert vr.mismatches == ()
    assert vr.floating == ()
    assert vr.shorted == ()

    if "a'" in expr_text and not opts.get("dual_rail"):
        complement_id = complement_net_id(layout, "a")
        assert complement_id is not None
        for row in all_assignments(var_order):
            state = simulate_layout(layout, row)[complement_id]
            assert not state.floating
            assert not state.shorted
            assert state.value == (not row["a"])


# --- Supporting sanity tests -------------------------------------------------


def test_layout_dimensions_match_network_stack_heights():
    var_order = ["a", "b", "c", "d"]
    minterms = minterms_from_expr(var_order, "(abc+d)'")
    result = synthesize(var_order, minterms)
    layout = build_schematic(result, "F")

    assert layout.pun_height == result.pun_stack_height
    assert layout.pdn_height == result.pdn_stack_height
    assert layout.height == layout.pun_height + layout.pdn_height

    for d in layout.devices:
        for p in (d.origin, d.gate_point, d.source_point, d.drain_point):
            assert 0 <= p.x <= layout.width * CELL
            assert 0 <= p.y <= layout.height * CELL
    for w in layout.wires:
        for p in (w.p1, w.p2):
            assert 0 <= p.x <= layout.width * CELL
            assert 0 <= p.y <= layout.height * CELL
    for j in layout.junctions:
        assert 0 <= j.point.x <= layout.width * CELL
        assert 0 <= j.point.y <= layout.height * CELL


@pytest.mark.parametrize(
    "var_order,expr_text,opts",
    [
        (["a"], "a", {}),
        (["a", "b"], "a+b", {}),
        (["a", "b", "c"], "(abc)'", {}),
        (["a", "b", "c", "d"], "(a+b+c+d)'", {}),
        (["a", "b", "c", "d"], "(abc+d)'", {}),
        (["a", "b", "c"], "(a'b+c)'", {}),
        (["a", "b", "c"], "(a'b+c)'", {"dual_rail": True}),
        (["a", "b", "c", "d"], "(abc+d)'", {"max_stack": 3}),
    ],
)
def test_device_count_always_matches_total_transistors(var_order, expr_text, opts):
    minterms = minterms_from_expr(var_order, expr_text)
    result = synthesize(var_order, minterms, **opts)
    layout = build_schematic(result, "F")
    assert len(layout.devices) == result.total_transistors


def test_inverter_rail_continuity():
    """A core stack taller than 2 rows, needing a shared inverter: the
    inverter's NMOS supply must be routed all the way down to the real GND
    rail row, not left stranded at row 2."""
    var_order = ["a", "b", "c", "d"]
    minterms = minterms_from_expr(var_order, "(a'bc+d)'")
    result = synthesize(var_order, minterms)
    layout = build_schematic(result, "F")
    assert layout.height > 2

    inv = [d for d in layout.devices if d.role == "inverter" and d.kind == "n"]
    assert len(inv) == 1
    n_dev = inv[0]
    expected_p1 = Point(n_dev.x * CELL + CELL // 2, 2 * CELL)
    expected_p2 = Point(n_dev.x * CELL + CELL // 2, layout.height * CELL)
    stub = next(
        (w for w in layout.wires if w.net_id == "GND" and {w.p1, w.p2} == {expected_p1, expected_p2}),
        None,
    )
    assert stub is not None, "expected an explicit GND stub from row 2 down to the real GND rail row"


# --- Topology fidelity -------------------------------------------------------


def test_topology_fidelity_positive_case():
    var_order = ["a", "b", "c", "d"]
    minterms = minterms_from_expr(var_order, "(abc+d)'")
    result = synthesize(var_order, minterms)
    layout = build_schematic(result, "F")  # must not raise
    _validate_topology_fidelity(layout, result)  # must not raise, called directly too


def _tied_alternate_candidate(result):
    from ohmwork.expr import render as render_expr

    chosen_render = render_expr(result.chosen.f_prime)
    return next(
        c
        for c in result.other_candidates
        if c.total_cost == result.chosen.total_cost
        and render_expr(c.f_prime) != chosen_render
        and c.complemented_names == result.chosen.complemented_names
    )


def test_topology_fidelity_isolated_gate_adversarial():
    # Pinned: a 4-variable function whose other_candidates includes a tied-cost,
    # same-complemented-set, but differently-shaped alternate PDN/PUN.
    var_order = ["a", "b", "c", "d"]
    minterms = {0, 7}
    original_result = synthesize(var_order, minterms)
    alt_candidate = _tied_alternate_candidate(original_result)

    alt_pdn = to_network(alt_candidate.f_prime, "n")
    alt_pun = dual(alt_pdn, "p")
    assert verify_networks(alt_pdn, alt_pun, var_order, minterms).passed

    alternate_result = dataclasses.replace(
        original_result, pdn=alt_pdn, pun=alt_pun, chosen=alt_candidate, f_prime=alt_candidate.f_prime
    )

    original_layout = build_schematic(original_result, "F")
    alternate_layout = build_schematic(alternate_result, "F")
    assert len(original_layout.devices) == len(alternate_layout.devices)

    with pytest.raises(RuntimeError, match="topology does not match"):
        _validate_topology_fidelity(alternate_layout, original_result)


def test_topology_fidelity_full_pipeline_adversarial(monkeypatch):
    var_order = ["a", "b", "c", "d"]
    minterms = {0, 7}
    original_result = synthesize(var_order, minterms)
    alt_candidate = _tied_alternate_candidate(original_result)

    alt_pdn = to_network(alt_candidate.f_prime, "n")
    alt_pun = dual(alt_pdn, "p")
    alternate_result = dataclasses.replace(
        original_result, pdn=alt_pdn, pun=alt_pun, chosen=alt_candidate, f_prime=alt_candidate.f_prime
    )
    alternate_layout = build_schematic(alternate_result, "F")

    import ohmwork.schematic as schematic_module

    def fake_build(result, output_name):
        return alternate_layout

    monkeypatch.setattr(schematic_module, "_build_layout_unchecked", fake_build)

    with pytest.raises(RuntimeError, match="topology does not match"):
        build_schematic(original_result, "F")


# --- validate_layout_geometry mutation / adversarial tests ------------------


def _built_layout():
    var_order = ["a", "b", "c"]
    minterms = minterms_from_expr(var_order, "(abc)'")
    result = synthesize(var_order, minterms)
    return var_order, minterms, build_schematic(result, "F")


def _assert_electrically_untouched(layout, broken, var_order, minterms):
    assert verify_layout(broken, var_order, minterms).passed


def test_mutation_removed_gate_wire():
    var_order, minterms, layout = _built_layout()
    dev = layout.devices[0]
    stub = next(w for w in layout.wires if w.p1 == dev.gate_point or w.p2 == dev.gate_point)
    broken = dataclasses.replace(layout, wires=tuple(w for w in layout.wires if w.id != stub.id))
    with pytest.raises(RuntimeError, match="not anchored"):
        validate_layout_geometry(broken)
    _assert_electrically_untouched(layout, broken, var_order, minterms)


def test_mutation_source_drain_wire_moved():
    var_order, minterms, layout = _built_layout()
    dev, w, is_p1 = next(
        (d, w, w.p1 == p)
        for d in layout.devices
        for p in (d.source_point, d.drain_point)
        for w in layout.wires
        if w.p1 == p or w.p2 == p
    )
    if is_p1:
        moved = dataclasses.replace(w, p1=Point(w.p1.x, w.p1.y + CELL))
    else:
        moved = dataclasses.replace(w, p2=Point(w.p2.x, w.p2.y + CELL))
    broken = dataclasses.replace(layout, wires=tuple(moved if x.id == w.id else x for x in layout.wires))
    with pytest.raises(RuntimeError):
        validate_layout_geometry(broken)
    _assert_electrically_untouched(layout, broken, var_order, minterms)


def test_mutation_wire_wrong_net_id():
    # A freshly relabeled wire has no OTHER geometry backing it under its new
    # (wrong) net at either endpoint, so check 10 (anchoring) rejects it before
    # check 11 (accidental-short) would even run -- still a correct rejection
    # of the mutation, just via a different (also legitimate) diagnostic.
    var_order, minterms, layout = _built_layout()
    dev = layout.devices[0]
    w = next(w for w in layout.wires if w.net_id == dev.gate_net and (w.p1 == dev.gate_point or w.p2 == dev.gate_point))
    other_net = next(n.id for n in layout.nets if n.id != w.net_id and n.id not in ("VDD", "GND", "OUT"))
    wrong = dataclasses.replace(w, net_id=other_net)
    broken = dataclasses.replace(layout, wires=tuple(wrong if x.id == w.id else x for x in layout.wires))
    with pytest.raises(RuntimeError):
        validate_layout_geometry(broken)
    _assert_electrically_untouched(layout, broken, var_order, minterms)


def test_mutation_extra_wire_unintended_connection():
    var_order, minterms, layout = _built_layout()
    net_a = layout.nets[0]
    dev = next(d for d in layout.devices if d.gate_net != net_a.id)
    extra = WireSegment(id="W_extra", net_id=net_a.id, p1=layout.wires[0].p1, p2=dev.gate_point)
    broken = dataclasses.replace(layout, wires=layout.wires + (extra,))
    with pytest.raises(RuntimeError):
        validate_layout_geometry(broken)
    _assert_electrically_untouched(layout, broken, var_order, minterms)


def test_mutation_missing_required_junction():
    var_order, minterms, layout = _built_layout()
    assert layout.junctions, "fixture should have at least one real junction"
    target = layout.junctions[0]
    broken = dataclasses.replace(layout, junctions=tuple(j for j in layout.junctions if j.id != target.id))
    with pytest.raises(RuntimeError, match="no Junction is declared there"):
        validate_layout_geometry(broken)
    _assert_electrically_untouched(layout, broken, var_order, minterms)


def test_mutation_dangling_wire_stub():
    var_order, minterms, layout = _built_layout()
    net = layout.nets[0]
    dangling = WireSegment(
        id="W_dangling", net_id=net.id, p1=Point(-CELL, -CELL), p2=Point(-CELL, -2 * CELL)
    )
    broken = dataclasses.replace(layout, wires=layout.wires + (dangling,))
    with pytest.raises(RuntimeError):
        validate_layout_geometry(broken)
    _assert_electrically_untouched(layout, broken, var_order, minterms)


def _built_inverter_layout():
    var_order = ["a", "b", "c"]
    minterms = minterms_from_expr(var_order, "(a'b+c)'")
    result = synthesize(var_order, minterms)
    return var_order, minterms, build_schematic(result, "F")


def test_mutation_inverter_pmos_source_swapped():
    var_order, minterms, layout = _built_inverter_layout()
    p_dev = next(d for d in layout.devices if d.role == "inverter" and d.kind == "p")
    swapped = dataclasses.replace(p_dev, source_net=layout.gnd_net_id)
    broken = dataclasses.replace(layout, devices=tuple(swapped if d.id == p_dev.id else d for d in layout.devices))
    with pytest.raises(RuntimeError, match="source_net is not VDD"):
        validate_layout_geometry(broken)


def test_mutation_inverter_nmos_source_swapped():
    var_order, minterms, layout = _built_inverter_layout()
    n_dev = next(d for d in layout.devices if d.role == "inverter" and d.kind == "n")
    swapped = dataclasses.replace(n_dev, source_net=layout.vdd_net_id)
    broken = dataclasses.replace(layout, devices=tuple(swapped if d.id == n_dev.id else d for d in layout.devices))
    with pytest.raises(RuntimeError, match="source_net is not GND"):
        validate_layout_geometry(broken)


# --- Corrective regressions (ChatGPT review round on commit 0dc480a) --------
#
# Four adversarial gaps: (1) a wire routed through another net's declared
# point (not just collinear overlap) was accepted; (2) a self-loop device
# made the topology-fidelity graph reduction loop forever; (3) nothing
# cross-checked a device's own gate_net against the net its gate_var/
# gate_complemented actually maps to, so a device-level or mapping-table-level
# identity swap slipped through all three gates; (4) device geometry
# (origin/points/orientation) and the `literal` display field were never
# checked against the documented coordinate formulas / structured identity.


def test_regression_wire_routed_through_other_net_gate_terminals():
    """A NAND3 net_a rerouted along the same row as b/c's gate terminals,
    passing directly through their (interior, not endpoint) points -- fully
    self-consistent otherwise (no dangling, no exact-point short), so only
    the interior-touch check (not the old collinear-overlap-only check) can
    catch it."""
    var_order, minterms, layout = _built_layout()
    others = tuple(w for w in layout.wires if w.net_id != "net_a")
    rerouted = (
        WireSegment(id="WA1", net_id="net_a", p1=Point(100, 50), p2=Point(350, 50)),
        WireSegment(id="WA2", net_id="net_a", p1=Point(100, 150), p2=Point(350, 150)),
        WireSegment(id="WA3", net_id="net_a", p1=Point(350, 50), p2=Point(350, 150)),
    )
    broken = dataclasses.replace(layout, wires=others + rerouted)
    with pytest.raises(RuntimeError, match="lies on the interior of segment"):
        validate_layout_geometry(broken)
    _assert_electrically_untouched(layout, broken, var_order, minterms)


def test_regression_self_loop_device_raises_promptly_instead_of_hanging():
    from ohmwork.schematic import _canonical_layout_topology

    def make_device(id, kind, gate_var, source_net, drain_net):
        return Device(
            id=id,
            kind=kind,
            gate_var=gate_var,
            gate_complemented=False,
            literal=gate_var,
            gate_net=f"net_{gate_var}",
            source_net=source_net,
            drain_net=drain_net,
            role="pdn",
            x=0,
            y=0,
            origin=Point(0, 0),
            gate_point=Point(CELL, CELL // 2),
            source_point=Point(CELL // 2, 0),
            drain_point=Point(CELL // 2, CELL),
        )

    devices = (make_device("M0", "n", "a", "J", "J"),)
    with pytest.raises(RuntimeError, match="self-loop"):
        _canonical_layout_topology(devices, "OUT", "GND")


def test_regression_self_loop_device_rejected_by_validator():
    var_order, minterms, layout = _built_layout()
    dev = layout.devices[0]
    looped = dataclasses.replace(dev, drain_net=dev.source_net)
    broken = dataclasses.replace(layout, devices=tuple(looped if d.id == dev.id else d for d in layout.devices))
    with pytest.raises(RuntimeError, match="self-loop"):
        validate_layout_geometry(broken)


def test_regression_swapped_primary_mapping_table():
    """A pure primary_nets mapping-table swap (devices and wires entirely
    untouched) for a symmetric NAND3 -- functionally invisible to
    simulate_layout (AND is commutative) and to the topology-fidelity gate
    (which never reads primary_nets), so only a direct device-gate_net-to-
    mapping cross-check can catch it."""
    var_order, minterms, layout = _built_layout()
    by_var = dict(layout.primary_nets)
    swapped = tuple(
        (v, by_var["b"] if v == "a" else by_var["a"] if v == "b" else nid) for v, nid in layout.primary_nets
    )
    broken = dataclasses.replace(layout, primary_nets=swapped)
    with pytest.raises(RuntimeError, match="does not follow the net_\\{var\\} id convention|mapping for"):
        validate_layout_geometry(broken)
    assert verify_layout(broken, var_order, minterms).passed


def test_regression_device_x_changed_without_updating_points():
    var_order, minterms, layout = _built_layout()
    dev = layout.devices[0]
    broken_dev = dataclasses.replace(dev, x=dev.x + 1)
    broken = dataclasses.replace(layout, devices=tuple(broken_dev if d.id == dev.id else d for d in layout.devices))
    with pytest.raises(RuntimeError, match="geometry does not match the documented coordinate formulas"):
        validate_layout_geometry(broken)


def test_regression_device_origin_inconsistent_with_x_y():
    var_order, minterms, layout = _built_layout()
    dev = layout.devices[0]
    broken_dev = dataclasses.replace(dev, origin=Point(dev.origin.x + CELL, dev.origin.y))
    broken = dataclasses.replace(layout, devices=tuple(broken_dev if d.id == dev.id else d for d in layout.devices))
    with pytest.raises(RuntimeError, match="geometry does not match the documented coordinate formulas"):
        validate_layout_geometry(broken)


def test_regression_device_terminal_orientation_swapped():
    """Swapping a device's own source_point/drain_point (not its kind)
    violates the documented PMOS-source-toward-top/NMOS-drain-toward-top
    orientation formula."""
    var_order, minterms, layout = _built_layout()
    dev = layout.devices[0]
    broken_dev = dataclasses.replace(dev, source_point=dev.drain_point, drain_point=dev.source_point)
    broken = dataclasses.replace(layout, devices=tuple(broken_dev if d.id == dev.id else d for d in layout.devices))
    with pytest.raises(RuntimeError, match="geometry does not match the documented coordinate formulas"):
        validate_layout_geometry(broken)


def test_regression_device_literal_mismatched():
    var_order, minterms, layout = _built_layout()
    dev = layout.devices[0]
    broken_dev = dataclasses.replace(dev, literal="zzz")
    broken = dataclasses.replace(layout, devices=tuple(broken_dev if d.id == dev.id else d for d in layout.devices))
    with pytest.raises(RuntimeError, match="does not match its structured gate identity"):
        validate_layout_geometry(broken)
