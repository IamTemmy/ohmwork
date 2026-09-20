"""Named ports are a visible connection convention, never a metadata shortcut."""
from dataclasses import replace
import random

import pytest

from ohmwork.api import synthesize_from_input
from ohmwork.schematic import (
    Point, build_textbook_schematic, validate_layout_geometry, verify_layout,
)
from ohmwork.synth import synthesize


@pytest.mark.parametrize("expr,count", [("(abc)'",6),("(a+b+c+d)'",8),("(abc+d)'",8),
    ("(a'b+c)'",8),("a",4),("a'",2), ("(A0'b1+C2)'",8)])
def test_textbook_acceptance(expr, count):
    result = synthesize_from_input(expr=expr)
    layout = build_textbook_schematic(result, "Y")
    assert len(layout.devices) == count
    assert len([p for p in layout.ports if p.terminal == "gate"]) == count
    assert next(n for n in layout.nets if n.id == "OUT").label == "Y"
    assert all(abs(w.p1.x-w.p2.x) <= 90 and w.p1.y == w.p2.y
               for w in layout.wires if w.net_id.startswith("net_"))
    pun_bottom = max(p.y for d in layout.devices if d.role == "pun" for p in (d.source_point,d.drain_point))
    pdn_top = min(p.y for d in layout.devices if d.role == "pdn" for p in (d.source_point,d.drain_point))
    lead = next(w for w in layout.wires if w.id == "LEAD_OUT")
    assert pdn_top - pun_bottom == 200
    expected_y = {"(abc)'":536, "(a+b+c+d)'":1064, "(abc+d)'":664,
                  "(a'b+c)'":664, "a":500, "a'":500, "(A0'b1+C2)'":664}[expr]
    assert lead.p1.y == lead.p2.y == expected_y
    assert any(j.net_id == "OUT" and j.point == lead.p1 for j in layout.junctions)


def test_output_cannot_be_relocated_to_a_network_bus():
    l = build_textbook_schematic(synthesize_from_input(expr="(abc)'"), "F")
    b = next(b for b in l.boundaries if b.net_id == "OUT")
    l = replace(l, boundaries=tuple(replace(p,point=Point(p.point.x,p.point.y-100)) if p==b else p for p in l.boundaries))
    with pytest.raises(RuntimeError, match="halfway"):
        validate_layout_geometry(l)


def test_dual_rail_has_external_named_complements_without_inverter():
    l = build_textbook_schematic(synthesize_from_input(expr="(a'b+c)'", dual_rail=True), "F")
    assert len(l.devices) == 6
    assert all(p.terminal == "gate" for p in l.ports)
    assert next(n for n in l.nets if n.id == "net_a_n").kind == "gate_complement_external"


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "wrong_label", "wrong_net", "wrong_terminal", "anchor", "missing_stub", "wrong_supply", "missing_supply"])
def test_broken_visible_connections_are_rejected(mutation):
    l = build_textbook_schematic(synthesize_from_input(expr="(a'b+c)'"), "F")
    p = l.ports[0]
    if mutation == "missing": l = replace(l, ports=l.ports[1:])
    elif mutation == "duplicate": l = replace(l, ports=l.ports+(replace(p,id="EXTRA"),))
    elif mutation == "wrong_label": l = replace(l, ports=(replace(p,label="WRONG"),)+l.ports[1:])
    elif mutation == "wrong_net": l = replace(l, ports=(replace(p,net_id="VDD"),)+l.ports[1:])
    elif mutation == "wrong_terminal": l = replace(l, ports=(replace(p,terminal="source"),)+l.ports[1:])
    elif mutation == "anchor": l = replace(l, ports=(replace(p,point=Point(1,1)),)+l.ports[1:])
    elif mutation == "missing_stub": l = replace(l, wires=tuple(w for w in l.wires if w.id != "STUB_"+p.device_id))
    elif mutation == "wrong_supply": l = replace(l, wires=tuple(replace(w,net_id="OUT") if w.id=="LEAD_VDD" else w for w in l.wires))
    else: l = replace(l,boundaries=l.boundaries[1:])
    with pytest.raises(RuntimeError): validate_layout_geometry(l)


def test_shared_inverter_port_is_backed_by_both_real_drains():
    l = build_textbook_schematic(synthesize_from_input(expr="(a'b+c)'"), "F")
    p = next(p for p in l.ports if p.terminal == "drain")
    inv = [d for d in l.devices if d.role == "inverter"]
    assert len(inv) == 2
    assert inv[0].drain_point == inv[1].drain_point
    assert inv[0].drain_net == inv[1].drain_net == p.net_id


def test_output_name_changes_only_output_label():
    r = synthesize_from_input(expr="(a'b+c)'")
    a,b = (build_textbook_schematic(r,n) for n in ("F","Y"))
    assert replace(a,nets=b.nets) == b
    assert [(n.id,n.label) for n in a.nets if n.id != "OUT"] == [(n.id,n.label) for n in b.nets if n.id != "OUT"]


def test_textbook_builder_rejects_a_wired_layout_substitution(monkeypatch):
    monkeypatch.setattr("ohmwork.schematic._textbook_projection", lambda source: source)
    with pytest.raises(RuntimeError, match="wrong layout style"):
        build_textbook_schematic(synthesize_from_input(expr="(abc)'"), "F")


def test_exhaustive_small_functions_and_four_variable_dont_cares():
    rng = random.Random(635)
    cases = []
    for n in range(1,4):
        for bits in range(1, (1 << (1 << n))-1):
            cases.append((list("abc"[:n]), {i for i in range(1 << n) if bits >> i & 1}, set()))
    for _ in range(250):
        states = [rng.randrange(3) for _ in range(16)]
        cases.append((list("abcd"), {i for i,s in enumerate(states) if s==1}, {i for i,s in enumerate(states) if s==2}))
    checked=0
    for variables,ones,dc in cases:
        for dual in (False,True):
            try: r = synthesize(variables,ones,dc,dual_rail=dual)
            except ValueError: continue  # constant specifications are rejected by the engine
            l = build_textbook_schematic(r,"Y")
            assert verify_layout(l,variables,ones,dc).passed
            checked += 1
    assert checked >= 1000
