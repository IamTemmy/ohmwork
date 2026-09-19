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
    GATE_LANE_CELLS,
    Device,
    Junction,
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

import ohmwork.schematic as _schematic_module

# Captured once, before any test monkeypatches _build_layout_unchecked -- a
# monkeypatch fixture only reverts the attribute at the END of a test, so
# re-reading `_schematic_module._build_layout_unchecked` mid-test would pick
# up an already-patched version if a test patches more than once.
_ORIGINAL_BUILD_LAYOUT_UNCHECKED = _schematic_module._build_layout_unchecked


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
    # +2*GATE_LANE_CELLS: a one-row gate-signal lane above the core (for
    # PMOS gate cruises) and another below it (for NMOS), keeping that
    # cruise routing off the core's own row-height space -- see
    # schematic.py's module-level GATE_LANE_CELLS comment.
    assert layout.height == layout.pun_height + layout.pdn_height + 2 * GATE_LANE_CELLS

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
    rail row (the row right after the core -- not `layout.height`, which
    also includes the bottom gate-signal lane past GND), not left stranded
    at the inverter's own fixed 2-row block."""
    var_order = ["a", "b", "c", "d"]
    minterms = minterms_from_expr(var_order, "(a'bc+d)'")
    result = synthesize(var_order, minterms)
    layout = build_schematic(result, "F")
    gnd_row_y = (GATE_LANE_CELLS + layout.pun_height + layout.pdn_height) * CELL
    assert layout.height * CELL > gnd_row_y  # sanity: the core really is taller than the inverter's own block

    inv = [d for d in layout.devices if d.role == "inverter" and d.kind == "n"]
    assert len(inv) == 1
    n_dev = inv[0]
    expected_p1 = Point(n_dev.x * CELL + CELL // 2, (n_dev.y + 1) * CELL)
    expected_p2 = Point(n_dev.x * CELL + CELL // 2, gnd_row_y)
    assert expected_p1 != expected_p2  # otherwise this test would vacuously pass
    stub = next(
        (w for w in layout.wires if w.net_id == "GND" and {w.p1, w.p2} == {expected_p1, expected_p2}),
        None,
    )
    assert stub is not None, "expected an explicit GND stub from the inverter's own row down to the real GND rail row"


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
    # net_a's two real declared points are the PUN "a" device's gate_point
    # (100, 150) and the PDN "a" device's gate_point (100, 250) -- b/c's own
    # PUN-row gate_points sit at (200, 150)/(300, 150), directly on the
    # interior of WA1's path below.
    rerouted = (
        WireSegment(id="WA1", net_id="net_a", p1=Point(100, 150), p2=Point(350, 150)),
        WireSegment(id="WA2", net_id="net_a", p1=Point(100, 250), p2=Point(350, 250)),
        WireSegment(id="WA3", net_id="net_a", p1=Point(350, 150), p2=Point(350, 250)),
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


# --- Second corrective round: terminal-domain / net-inventory closure ------
#
# A fifth gap: nothing restricted which KIND of net a core device's
# source_net/drain_net could reference. A PDN device's diffusion terminal
# could be wired to reuse a primary GATE net in place of its own internal
# junction net -- fully self-consistent geometry (no dangling, no exact-point
# short, a real Junction where needed), so it slipped past every existing
# check. simulate_layout only reads gate_net for conduction (never notices a
# source/drain terminal quietly sharing a gate net's identity), and topology
# fidelity only cares about graph shape, not which net-kind backs each edge.


def test_regression_gate_net_reused_as_pdn_diffusion_junction():
    """Exact reproduction: NAND3's internal PDN junction pdn_j0 (which joins
    the 'a' and 'b' PDN transistors) is replaced by the primary gate net
    net_a, with fully consistent wire geometry (including the two Junctions
    the new degree-3 points require) connecting the diffusion terminals into
    net_a's existing gate-rail structure. Electrical simulation and topology
    fidelity both still pass; only the terminal-domain check catches it."""
    var_order, minterms, layout = _built_layout()
    m3 = next(d for d in layout.devices if d.id == "M3")
    m4 = next(d for d in layout.devices if d.id == "M4")
    assert m3.source_net == "pdn_j0" and m4.drain_net == "pdn_j0"

    new_devices = tuple(
        dataclasses.replace(d, source_net="net_a")
        if d.id == "M3"
        else dataclasses.replace(d, drain_net="net_a")
        if d.id == "M4"
        else d
        for d in layout.devices
    )
    new_wires = tuple(
        dataclasses.replace(w, net_id="net_a") if w.net_id == "pdn_j0" else w for w in layout.wires
    ) + (
        WireSegment(id="WX1", net_id="net_a", p1=m3.source_point, p2=Point(m3.source_point.x, m3.gate_point.y)),
        WireSegment(
            id="WX2",
            net_id="net_a",
            p1=Point(m3.source_point.x, m3.gate_point.y),
            p2=m3.gate_point,
        ),
    )
    new_nets = tuple(n for n in layout.nets if n.id != "pdn_j0")
    new_junctions = layout.junctions + (
        Junction(id="JX1", net_id="net_a", point=m3.gate_point),
        Junction(id="JX2", net_id="net_a", point=m3.source_point),
    )
    broken = dataclasses.replace(
        layout, devices=new_devices, wires=new_wires, nets=new_nets, junctions=new_junctions
    )

    # confirm it's a genuinely clean reproduction: both other gates still pass
    assert verify_layout(broken, var_order, minterms).passed
    _validate_topology_fidelity(broken, synthesize(var_order, minterms))

    with pytest.raises(RuntimeError, match="must never reference a gate net"):
        validate_layout_geometry(broken)


def test_regression_pun_device_uses_gnd():
    var_order, minterms, layout = _built_layout()
    dev = next(d for d in layout.devices if d.role == "pun" and d.source_net == "VDD")
    broken_dev = dataclasses.replace(dev, source_net=layout.gnd_net_id)
    broken = dataclasses.replace(layout, devices=tuple(broken_dev if d.id == dev.id else d for d in layout.devices))
    with pytest.raises(RuntimeError, match="not VDD/OUT"):
        validate_layout_geometry(broken)


def test_regression_pdn_device_uses_vdd():
    var_order, minterms, layout = _built_layout()
    dev = next(d for d in layout.devices if d.role == "pdn" and d.source_net == "GND")
    broken_dev = dataclasses.replace(dev, source_net=layout.vdd_net_id)
    broken = dataclasses.replace(layout, devices=tuple(broken_dev if d.id == dev.id else d for d in layout.devices))
    with pytest.raises(RuntimeError, match="not OUT/GND"):
        validate_layout_geometry(broken)


def test_regression_orphan_unexpected_net():
    # An orphaned gate_primary net is caught by the more specific reverse-mapping
    # check (it must appear in primary_nets) before ever reaching the generic
    # "unused or unexpected" fallback -- both are part of the same net-inventory
    # closure and either is a correct rejection of an orphaned net.
    from ohmwork.schematic import Net

    var_order, minterms, layout = _built_layout()
    orphan = Net(id="net_orphan", label="orphan", kind="gate_primary")
    broken = dataclasses.replace(layout, nets=layout.nets + (orphan,))
    with pytest.raises(RuntimeError, match="does not appear in primary_nets"):
        validate_layout_geometry(broken)


def test_regression_duplicate_vdd_net():
    from ohmwork.schematic import Net

    var_order, minterms, layout = _built_layout()
    duplicate = Net(id="VDD2", label="VDD", kind="rail_vdd")
    broken = dataclasses.replace(layout, nets=layout.nets + (duplicate,))
    with pytest.raises(RuntimeError, match="expected exactly one VDD net"):
        validate_layout_geometry(broken)


# --- Third corrective round: VDD/GND/OUT literal identity -------------------
#
# A sixth gap: nothing pinned layout.vdd_net_id/gnd_net_id/output_net_id, or
# the VDD/GND nets' own labels, to the literal, stable strings D17's fixed
# schematic semantics require -- every other check here is purely relative
# to whatever those fields happen to say, so a globally-consistent rename or
# a plain label swap was invisible to validate_layout_geometry,
# simulate_layout, and _validate_topology_fidelity alike. Phase B's
# model-to-SVG bridge would then faithfully render an already-mislabeled
# model, since correctness there is defined relative to this one.


def test_regression_vdd_gnd_labels_swapped():
    var_order, minterms, layout = _built_layout()
    swapped = tuple(
        dataclasses.replace(n, label="GND")
        if n.id == "VDD"
        else dataclasses.replace(n, label="VDD")
        if n.id == "GND"
        else n
        for n in layout.nets
    )
    broken = dataclasses.replace(layout, nets=swapped)
    with pytest.raises(RuntimeError, match="VDD net's label must be exactly 'VDD'"):
        validate_layout_geometry(broken)


def test_regression_special_net_ids_consistently_renamed():
    """VDD/GND renamed to SUPPLY/RETURN everywhere -- Layout.vdd_net_id/
    gnd_net_id, every Net/Device/WireSegment/Junction that referenced them --
    a fully self-consistent global rename, so only an explicit literal-string
    check (not anything relative) can catch it."""
    var_order, minterms, layout = _built_layout()

    def rn(net_id: str) -> str:
        return "SUPPLY" if net_id == "VDD" else "RETURN" if net_id == "GND" else net_id

    broken = dataclasses.replace(
        layout,
        vdd_net_id="SUPPLY",
        gnd_net_id="RETURN",
        nets=tuple(dataclasses.replace(n, id=rn(n.id), label=rn(n.label)) for n in layout.nets),
        devices=tuple(
            dataclasses.replace(d, source_net=rn(d.source_net), drain_net=rn(d.drain_net), gate_net=rn(d.gate_net))
            for d in layout.devices
        ),
        wires=tuple(dataclasses.replace(w, net_id=rn(w.net_id)) for w in layout.wires),
        junctions=tuple(dataclasses.replace(j, net_id=rn(j.net_id)) for j in layout.junctions),
    )
    with pytest.raises(RuntimeError, match="layout.vdd_net_id must be exactly 'VDD'"):
        validate_layout_geometry(broken)


def test_regression_output_label_mismatch(monkeypatch):
    """validate_layout_geometry alone can't check this (no output_name to
    compare against) -- build_schematic must, so this monkeypatches the
    unchecked builder the same way the topology-fidelity full-pipeline test
    does, to exercise build_schematic's own gating, not just a helper."""
    var_order = ["a", "b", "c"]
    minterms = minterms_from_expr(var_order, "(abc)'")
    result = synthesize(var_order, minterms)

    import ohmwork.schematic as schematic_module

    real_unchecked = schematic_module._build_layout_unchecked

    def fake_build(result, output_name):
        layout = real_unchecked(result, output_name)
        bogus_out = dataclasses.replace(next(n for n in layout.nets if n.id == "OUT"), label="WRONG")
        return dataclasses.replace(layout, nets=tuple(bogus_out if n.id == "OUT" else n for n in layout.nets))

    monkeypatch.setattr(schematic_module, "_build_layout_unchecked", fake_build)
    with pytest.raises(RuntimeError, match="does not match the requested output_name"):
        schematic_module.build_schematic(result, "F")


# --- Fourth corrective round: source fidelity (gate 4) ----------------------
#
# A seventh gap: gates 1-3 never cross-check against the PARTICULAR
# SynthesisResult build_schematic was asked to render. The dual-rail layout
# for a function needing a shared inverter has an IDENTICAL PDN/PUN core
# topology and computes the IDENTICAL function (dual-rail's external
# complement net is correct by construction, no inverter needed) -- so it
# passes electrical behavior, geometry integrity, AND topology fidelity
# (which deliberately excludes inverters) when substituted for the normal,
# inverter-bearing result it doesn't actually belong to.


def _monkeypatched_build(monkeypatch, result, output_name, mutate_layout):
    """Patches _build_layout_unchecked so build_schematic's own pipeline
    (not just a helper called directly) receives `mutate_layout(real
    layout)` -- the same pattern the topology-fidelity full-pipeline test
    uses, to prove build_schematic itself gates on this, not just that a
    gate function works in isolation. Always builds from the ORIGINAL
    unpatched function, even if called more than once in the same test --
    monkeypatch.setattr only reverts at the end of the test, so re-reading
    the (possibly already-patched) module attribute here would compound
    mutations across repeated calls within one test."""

    def fake_build(result, output_name):
        return mutate_layout(_ORIGINAL_BUILD_LAYOUT_UNCHECKED(result, output_name))

    monkeypatch.setattr(_schematic_module, "_build_layout_unchecked", fake_build)
    return _schematic_module


def test_regression_dual_rail_layout_substituted_for_normal_result(monkeypatch):
    var_order = ["a", "b", "c"]
    minterms = minterms_from_expr(var_order, "(a'b+c)'")
    normal_result = synthesize(var_order, minterms)
    dual_result = synthesize(var_order, minterms, dual_rail=True)
    assert normal_result.total_transistors == 8
    assert normal_result.inverter_literals == ("a",)

    dual_layout = build_schematic(dual_result, "F")
    assert len(dual_layout.devices) == 6
    assert dual_layout.inverter_driven_vars == ()

    schematic_module = _monkeypatched_build(monkeypatch, normal_result, "F", lambda _layout: dual_layout)
    with pytest.raises(RuntimeError, match="inverter devices"):
        schematic_module.build_schematic(normal_result, "F")


def test_regression_normal_layout_substituted_for_dual_rail_result(monkeypatch):
    var_order = ["a", "b", "c"]
    minterms = minterms_from_expr(var_order, "(a'b+c)'")
    normal_result = synthesize(var_order, minterms)
    dual_result = synthesize(var_order, minterms, dual_rail=True)

    normal_layout = build_schematic(normal_result, "F")

    schematic_module = _monkeypatched_build(monkeypatch, dual_result, "F", lambda _layout: normal_layout)
    with pytest.raises(RuntimeError, match="inverter devices"):
        schematic_module.build_schematic(dual_result, "F")


def test_regression_source_fidelity_mutated_var_order(monkeypatch):
    var_order = ["a", "b", "c"]
    minterms = minterms_from_expr(var_order, "(abc)'")
    result = synthesize(var_order, minterms)

    def mutate(layout):
        return dataclasses.replace(layout, var_order=("b", "a", "c"))

    schematic_module = _monkeypatched_build(monkeypatch, result, "F", mutate)
    with pytest.raises(RuntimeError, match="var_order"):
        schematic_module.build_schematic(result, "F")


def test_regression_source_fidelity_mutated_transistor_count_metadata(monkeypatch):
    # Bumping layout.total_transistors alone (device list unchanged) makes
    # len(layout.devices) disagree with layout.total_transistors itself --
    # that's already gate 2's own internal-consistency check (validated
    # before gate 4 ever runs), so it's what actually fires here. Gate 4's
    # OWN contribution to transistor-count fidelity -- catching an
    # internally-consistent layout whose counts still disagree with a
    # DIFFERENT result -- is what the dual-rail substitution tests above
    # exercise instead (there's no way to construct the narrower case
    # without breaking gate 2's own invariant, since the builder always
    # stamps layout.total_transistors from whatever result built it).
    var_order = ["a", "b", "c"]
    minterms = minterms_from_expr(var_order, "(abc)'")
    result = synthesize(var_order, minterms)

    def mutate(layout):
        return dataclasses.replace(layout, total_transistors=layout.total_transistors + 2)

    schematic_module = _monkeypatched_build(monkeypatch, result, "F", mutate)
    with pytest.raises(RuntimeError, match="does not match total_transistors"):
        schematic_module.build_schematic(result, "F")


def test_regression_source_fidelity_mutated_stack_height_and_dimensions(monkeypatch):
    var_order = ["a", "b", "c", "d"]
    minterms = minterms_from_expr(var_order, "(abc+d)'")
    result = synthesize(var_order, minterms)

    def mutate_pun_height(layout):
        return dataclasses.replace(layout, pun_height=layout.pun_height + 1)

    schematic_module = _monkeypatched_build(monkeypatch, result, "F", mutate_pun_height)
    with pytest.raises(RuntimeError, match="pun_height"):
        schematic_module.build_schematic(result, "F")

    def mutate_width(layout):
        return dataclasses.replace(layout, width=layout.width + 1)

    schematic_module = _monkeypatched_build(monkeypatch, result, "F", mutate_width)
    with pytest.raises(RuntimeError, match="documented sizing formula"):
        schematic_module.build_schematic(result, "F")

    def mutate_height(layout):
        return dataclasses.replace(layout, height=layout.height + 1)

    schematic_module = _monkeypatched_build(monkeypatch, result, "F", mutate_height)
    with pytest.raises(RuntimeError, match="pun_height \\+ layout.pdn_height"):
        schematic_module.build_schematic(result, "F")


def test_layout_construction_is_deterministic_within_a_process():
    var_order = ["a", "b", "c", "d"]
    minterms = minterms_from_expr(var_order, "(a'bc+d)'")
    result_1 = synthesize(var_order, minterms)
    result_2 = synthesize(var_order, minterms)
    layout_1 = build_schematic(result_1, "F")
    layout_2 = build_schematic(result_2, "F")

    assert layout_1.nets == layout_2.nets
    assert layout_1.devices == layout_2.devices
    assert layout_1.wires == layout_2.wires
    assert layout_1.junctions == layout_2.junctions
    assert [d.id for d in layout_1.devices] == [d.id for d in layout_2.devices]
    assert [n.id for n in layout_1.nets] == [n.id for n in layout_2.nets]


def test_layout_construction_is_deterministic_across_hash_seeds():
    """Phase B's eventual data-device-id/data-net-id bridge (D17 acceptance
    test 8) depends on stable ids/ordering -- verify the builder never
    depends on set/dict iteration order that PYTHONHASHSEED could perturb,
    by running the exact same build in fresh subprocesses under different
    hash seeds and diffing a full repr of the result."""
    import os
    import subprocess
    import sys

    script = (
        "from ohmwork.synth import synthesize\n"
        "from ohmwork.schematic import build_schematic\n"
        "from ohmwork.derivation import all_assignments, evaluate\n"
        "from ohmwork.parser import parse\n"
        "var_order = ['a', 'b', 'c', 'd']\n"
        "ast = parse(\"(a'bc+d)'\")\n"
        "rows = all_assignments(var_order)\n"
        "minterms = {i for i, row in enumerate(rows) if evaluate(ast, row)}\n"
        "result = synthesize(var_order, minterms)\n"
        "layout = build_schematic(result, 'F')\n"
        "print(repr(layout))\n"
    )

    outputs = []
    for seed in ("0", "1", "982451653"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        proc = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, env=env, check=True
        )
        outputs.append(proc.stdout)

    assert len(outputs) == 3
    assert len(set(outputs)) == 1, "layout construction is not deterministic across PYTHONHASHSEED values"


# --- Routing sweep (D17 Phase B polish round 2: gate-signal lane routing) ---


def test_gate_signal_lane_routing_sweep_zero_false_rejections():
    """The lane-based gate-signal routing (schematic.py's GATE_LANE_CELLS
    section) replaced the original same-row micro-offset routing entirely --
    a new routing algorithm needs the same "no false rejections across a
    real corpus" validation Phase A's own routing got. Exhaustive over every
    1-3 variable function (every minterm subset, both normal and dual-rail
    mode) -- 540 real synthesized layouts, each independently gated by
    build_schematic()'s own four correctness checks. A `ValueError` here
    (e.g. a constant function `synthesize()` itself refuses) is an expected,
    upstream rejection, not a schematic bug -- only a schematic-side
    exception would fail this test."""
    import itertools

    checked = 0
    for n in range(1, 4):
        var_order = [chr(ord("a") + i) for i in range(n)]
        all_rows = list(range(2**n))
        for r in range(len(all_rows) + 1):
            for minterms in itertools.combinations(all_rows, r):
                for dual_rail in (False, True):
                    try:
                        result = synthesize(var_order, set(minterms), dual_rail=dual_rail)
                    except ValueError:
                        continue
                    build_schematic(result, "F")  # raises on any of the four gates failing
                    checked += 1

    assert checked > 500  # sanity: this really did exercise a large corpus, not a no-op loop
