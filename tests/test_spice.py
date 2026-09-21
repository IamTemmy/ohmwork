"""D19 structural checks: text -> Layout, including deliberate export corruption."""
from dataclasses import replace
import json
import os
import re
import string
import subprocess
import sys

import pytest

from ohmwork.api import synthesize_from_input
from ohmwork.schematic import build_schematic, build_textbook_schematic
from ohmwork.spice import (build_spice_model, render_spice_template,
                           render_spice_example, validate_spice_export)

CASES = ["(abc)'", "(a+b+c+d)'", "(abc+d)'", "(a'b+c)'", "ab", "a", "a'",
         "((a+b)(c+d))'", "((ab+c)(a+d))'", "((a+bc)(b+d))'",
         "a'b'c'd + a'b'cd' + a'bc'd' + ab'c'd'", "(aA)'", "aA", "(a A a0)'"]


def layout_for(expr="(abc+d)'", dual=False):
    return build_textbook_schematic(synthesize_from_input(expr=expr, dual_rail=dual), "Y")


@pytest.mark.parametrize("expr", CASES)
@pytest.mark.parametrize("dual", [False, True])
def test_text_round_trip_directly_against_layout(expr, dual):
    result = synthesize_from_input(expr=expr, dual_rail=dual)
    layout = build_textbook_schematic(result, "Y")
    for educational, text in [(False, render_spice_template(layout)),
                              (True, render_spice_example(layout))]:
        validate_spice_export(layout, text, educational=educational)
        # Independent test parser does not use exporter records or validator.
        mapping = {parts[2]: json.loads(parts[3]) for line in text.splitlines()
                   if line.startswith("* node ") for parts in [line.split(" ", 3)]}
        device_map = {parts[2]: json.loads(parts[3]) for line in text.splitlines()
                      if line.startswith("* device ") for parts in [line.split(" ", 3)]}
        records = [line.split() for line in text.splitlines() if re.match(r"m\d+ ", line)]
        assert len(records) == result.total_transistors
        assert len({r[0].lower() for r in records}) == len(records)
        assert all(r[0].startswith("m") for r in records)
        assert len({n.lower() for n in mapping}) == len(mapping)
        expected = {d.id: d for d in layout.devices}
        for name, drain, gate, source, bulk, model, w, length in records:
            d = expected[device_map[name]]
            assert tuple(mapping[n][0] for n in (drain, gate, source)) == (
                d.drain_net, d.gate_net, d.source_net)
            assert mapping[bulk][0] == (layout.vdd_net_id if d.kind == "p" else layout.gnd_net_id)
            assert model == ("pmos_model" if d.kind == "p" else "nmos_model")
            assert w == ("W=10u" if educational else "W=TBD")
            assert length == ("L=1u" if educational else "L=TBD")
        ports = next(line.split()[2:] for line in text.splitlines() if line.startswith(".subckt"))
        assert [mapping[p][0] for p in ports[:3]] == ["OUT", "VDD", "GND"]
        assert mapping[ports[0]][1] == "Y"
        expected_primary = dict(layout.primary_nets)
        assert [mapping[p][0] for p in ports[3:3+len(layout.var_order)]] == [
            expected_primary.get(v) for v in layout.var_order]
        external = dict(layout.complement_nets)
        assert [mapping[p][0] for p in ports[3+len(layout.var_order):]] == [
            external[v] for v in layout.var_order
            if v in external and v not in layout.inverter_driven_vars]
        used = {n for r in records for n in r[1:5]}
        assert used <= mapping.keys()
        for n, (nid, label, role) in mapping.items():
            if nid is None:
                assert n in ports and n not in used
                assert role == "unconnected declared input"
        assert {v[0] for v in mapping.values() if v[0] is not None} == {n.id for n in layout.nets}


@pytest.mark.parametrize("expr", CASES)
@pytest.mark.parametrize("dual", [False, True])
def test_wired_and_textbook_export_identical_electrical_artifacts(expr, dual):
    result = synthesize_from_input(expr=expr, dual_rail=dual)
    a, b = build_schematic(result, "Y"), build_textbook_schematic(result, "Y")
    assert render_spice_template(a) == render_spice_template(b)
    assert render_spice_example(a) == render_spice_example(b)


def test_case_sensitive_inverter_ids_never_become_spice_instances():
    layout = layout_for("aA")
    assert {"INV_A_N", "INV_a_N", "INV_A_P", "INV_a_P"} <= {d.id for d in layout.devices}
    devices = build_spice_model(layout).devices
    assert all(d.name.startswith("m") for d in devices)
    assert len({d.name.lower() for d in devices}) == len(devices)


@pytest.mark.parametrize("kwargs, expected", [
    ({"variables": "a,b", "ones": "2,3"}, [("a", False), ("b", True)]),
    ({"expr": "a", "dual_rail": True}, [("a", True)]),
])
def test_unconnected_input_and_complement_only_regressions(kwargs, expected):
    model = build_spice_model(build_schematic(synthesize_from_input(**kwargs), "Y"))
    nodes = {n.name: n for n in model.nodes}
    assert [(p.variable, nodes[p.node].layout_id is None)
            for p in model.ports if p.role == "primary"] == expected
    assert all(int(n.name[1:]) >= sum(m.layout_id is not None for m in model.nodes)
               for n in model.nodes if n.layout_id is None)
    if kwargs.get("dual_rail"):
        assert model.ports[-1].role == "complement"
        assert nodes[model.ports[-1].node].layout_id == "net_a_n"


def test_d8_identifier_alphabet_and_digit_suffixes():
    for var in [c + suffix for c in string.ascii_letters for suffix in ("", *string.digits)]:
        if var == "F":  # D15 reserves this output-column name
            continue
        model = build_spice_model(layout_for(var))
        assert [n.name for n in model.nodes] == [f"n{i}" for i in range(len(model.nodes))]
        assert [d.name for d in model.devices] == [f"m{i}" for i in range(len(model.devices))]


@pytest.mark.parametrize("mutation", ["bulk", "swap", "missing", "merged_net", "merged_device",
                                      "ports", "unused_wired", "model", "mapping", "injected"])
def test_export_validator_rejects_mutations(mutation):
    layout = build_schematic(synthesize_from_input(variables="a,b", ones="2,3"), "Y")
    lines = render_spice_template(layout).splitlines()
    i = next(i for i, line in enumerate(lines) if line.startswith("m0 "))
    tokens = lines[i].split()
    if mutation == "bulk":
        tokens[4] = "n1" if tokens[4] != "n1" else "n0"
    elif mutation == "swap":
        tokens[1], tokens[3] = tokens[3], tokens[1]
    elif mutation == "missing":
        lines.pop(i)
    elif mutation == "merged_net":
        lines = [re.sub(r"\bn2\b", "n0", line) for line in lines]
    elif mutation == "merged_device":
        lines = [line.replace("m1 ", "m0 ") for line in lines]
    elif mutation == "ports":
        j = next(j for j, l in enumerate(lines) if l.startswith(".subckt"))
        ports = lines[j].split()
        ports[2], ports[3] = ports[3], ports[2]
        lines[j] = " ".join(ports)
    elif mutation == "unused_wired":
        tokens[2] = build_spice_model(layout).ports[-1].node
    elif mutation == "model":
        tokens[5] = "nmos_model" if tokens[5] == "pmos_model" else "pmos_model"
    elif mutation == "mapping":
        lines = [line.replace('"OUT"', '"WRONG"') for line in lines]
    elif mutation == "injected":
        lines.insert(i, "r0 n0 n1 1")
    if mutation in {"bulk", "swap", "unused_wired", "model"}:
        lines[i] = " ".join(tokens)
    with pytest.raises(RuntimeError, match="SPICE export"):
        validate_spice_export(layout, "\n".join(lines))


def test_display_label_cannot_inject_directives():
    layout = layout_for()
    layout = replace(layout, nets=tuple(replace(n, label="Y\n.end\nVevil 0 1 5")
                                        if n.id == "OUT" else n for n in layout.nets))
    text = render_spice_template(layout)
    assert "\nVevil" not in text
    assert r"Y\n.end\nVevil" in text


@pytest.mark.parametrize("inputs", [{}, {"a": 2}, {"a": "0"}, {"a": 0.0}, {"a": 1, "b": 0}])
def test_example_rejects_incomplete_or_non_binary_inputs(inputs):
    with pytest.raises(ValueError):
        render_spice_example(layout_for("a"), inputs)


def test_cross_process_determinism():
    script = """from ohmwork.api import synthesize_from_input
from ohmwork.schematic import build_textbook_schematic
from ohmwork.spice import render_spice_template, render_spice_example
l = build_textbook_schematic(synthesize_from_input(expr='aA'), 'Y')
print(render_spice_template(l)); print(render_spice_example(l))
"""
    outputs = [subprocess.check_output([sys.executable, "-c", script],
               env={**os.environ, "PYTHONHASHSEED": str(seed)}) for seed in [0, 1, 42, 999]]
    assert len(set(outputs)) == 1


def test_extra_top_level_device_is_rejected():
    layout = layout_for()
    for educational, text in [(False, render_spice_template(layout)), (True, render_spice_example(layout))]:
        with pytest.raises(RuntimeError, match="unexpected"):
            validate_spice_export(layout, text + "m99 n0 n1 n2 n1 nmos_model W=10u L=1u\n",
                                  educational=educational)


def test_shared_inverter_export_has_one_driver_and_all_consumers():
    layout = layout_for("(a'b+c)'")
    model = build_spice_model(layout)
    assert layout.inverter_driven_vars == ("a",)
    assert len([d for d in layout.devices if d.role == "inverter"]) == 2
    complement_id = dict(layout.complement_nets)["a"]
    complement = next(n.name for n in model.nodes if n.layout_id == complement_id)
    assert sum(d.drain == complement for d in model.devices) == 2
    assert sum(d.gate == complement for d in model.devices) == sum(
        d.gate_net == complement_id for d in layout.devices)


def test_model_cards_match_review_documentation_and_stay_out_of_template():
    from pathlib import Path
    from ohmwork.spice import EDUCATIONAL_MODELS, MODEL_SOURCE
    documentation = (Path(__file__).resolve().parents[1] / "docs/spice.md").read_text()
    assert "\n".join(EDUCATIONAL_MODELS) in documentation
    layout = layout_for()
    example, template = render_spice_example(layout), render_spice_template(layout)
    assert MODEL_SOURCE in example
    assert "\n".join(EDUCATIONAL_MODELS) in example
    assert ".model" not in template.lower()
    assert ".temp 27\n" in example
    assert ".options GMIN=1e-12 RELTOL=1e-3 ABSTOL=1e-12 VNTOL=1e-6\n" in example
    assert ".control" not in example
