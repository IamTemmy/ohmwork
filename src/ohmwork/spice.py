"""D19: deterministic SPICE exports of a verified schematic Layout.

No synthesis, geometry inference, or transistor sizing optimization occurs here.
The editing template is deliberately non-runnable. Only the separately labelled
educational example supplies analog assumptions. See docs/spice.md.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from collections.abc import Mapping

from .schematic import Layout, validate_layout_geometry

SUBCIRCUIT = "ohmwork_gate"
MODEL_SOURCE = (
    "https://github.com/ngspice/ngspice/blob/"
    "032b1c32c4dbad45ff132bcfac1dbecadbd8abb0/"
    "examples/TransmissionLines/ltra1_1_line.sp"
)
# Numeric parameters reproduced from the cited ngspice example (names changed).
# LEVEL and TNOM are explicit; IS/JS/RD/RS/RSH pin the DC defaults used here.
# The source's nonzero GAMMA intentionally retains Level-1 body effect.
EDUCATIONAL_MODELS = (
    ".model nmos_model NMOS (LEVEL=1 VTO=0.8 KP=48U GAMMA=0.30 PHI=0.55",
    "+ LAMBDA=0.00 CGSO=0 CGDO=0 CJ=0 CJSW=0 TOX=18000N LD=0.0U",
    "+ TNOM=27 IS=1e-14 JS=0 RD=0 RS=0 RSH=0 KF=0 AF=1",
    "+ CBD=0 CBS=0 CGBO=0 PB=0.8 MJ=0.5 MJSW=0.5 FC=0.5)",
    ".model pmos_model PMOS (LEVEL=1 VTO=-0.8 KP=21U GAMMA=0.45 PHI=0.61",
    "+ LAMBDA=0.00 CGSO=0 CGDO=0 CJ=0 CJSW=0 TOX=18000N LD=0.0U",
    "+ TNOM=27 IS=1e-14 JS=0 RD=0 RS=0 RSH=0 KF=0 AF=1",
    "+ CBD=0 CBS=0 CGBO=0 PB=0.8 MJ=0.5 MJSW=0.5 FC=0.5)",
)
_ROLES = {
    "rail_vdd": "supply", "rail_gnd": "ground", "output": "output",
    "gate_primary": "primary input",
    "gate_complement_internal": "internally generated complement",
    "gate_complement_external": "external complement input",
    "junction": "internal junction",
}


@dataclass(frozen=True, slots=True)
class SpiceNode:
    name: str
    layout_id: str | None
    label: str
    role: str


@dataclass(frozen=True, slots=True)
class SpicePort:
    node: str
    role: str
    variable: str | None = None


@dataclass(frozen=True, slots=True)
class SpiceDevice:
    name: str
    layout_id: str
    drain: str
    gate: str
    source: str
    bulk: str
    model: str


@dataclass(frozen=True, slots=True)
class SpiceModel:
    nodes: tuple[SpiceNode, ...]
    ports: tuple[SpicePort, ...]
    devices: tuple[SpiceDevice, ...]
    var_order: tuple[str, ...]


def build_spice_model(layout: Layout) -> SpiceModel:
    """Project Layout electrical identities to case-insensitive-safe names.

    Callers should pass a Layout returned by build_schematic or
    build_textbook_schematic, which validate it against the synthesis result.
    Recheck structural validity here; this is not a new synthesis verifier.
    """
    validate_layout_geometry(layout)
    nodes = [SpiceNode(f"n{i}", n.id, n.label, _ROLES[n.kind])
             for i, n in enumerate(layout.nets)]
    names = {n.layout_id: n.name for n in nodes}
    primary = dict(layout.primary_nets)
    complement = dict(layout.complement_nets)
    ports = [SpicePort(names[nid], role) for nid, role in (
        (layout.output_net_id, "output"), (layout.vdd_net_id, "supply"),
        (layout.gnd_net_id, "ground"))]
    for var in layout.var_order:
        if var in primary:
            node = names[primary[var]]
        else:
            node = f"n{len(nodes)}"
            nodes.append(SpiceNode(node, None, var, "unconnected declared input"))
        ports.append(SpicePort(node, "primary", var))
    for var in layout.var_order:
        if var in complement and var not in layout.inverter_driven_vars:
            ports.append(SpicePort(names[complement[var]], "complement", var))
    devices = tuple(SpiceDevice(
        f"m{i}", d.id, names[d.drain_net], names[d.gate_net], names[d.source_net],
        names[layout.vdd_net_id if d.kind == "p" else layout.gnd_net_id],
        "pmos_model" if d.kind == "p" else "nmos_model",
    ) for i, d in enumerate(layout.devices))
    return SpiceModel(tuple(nodes), tuple(ports), devices, layout.var_order)


def _subcircuit(model: SpiceModel, *, educational: bool) -> list[str]:
    # JSON escaping keeps arbitrary display labels on one comment line and
    # preserves them exactly for traceability, without SPICE syntax injection.
    lines = ["* Node mapping: synthetic name, Layout id, label, role"]
    for n in model.nodes:
        lines.append(f"* node {n.name} " + json.dumps(
            [n.layout_id, n.label, n.role], ensure_ascii=True))
    for d in model.devices:
        lines.append(f"* device {d.name} " + json.dumps(d.layout_id, ensure_ascii=True))
    lines.append(f".subckt {SUBCIRCUIT} " + " ".join(p.node for p in model.ports))
    sizing = "W=10u L=1u" if educational else "W=TBD L=TBD"
    lines.extend(f"{d.name} {d.drain} {d.gate} {d.source} {d.bulk} {d.model} {sizing}"
                 for d in model.devices)
    lines.append(f".ends {SUBCIRCUIT}")
    return lines


def render_spice_template(layout: Layout) -> str:
    """An editing template, not a runnable simulation or a sizing recommendation."""
    model = build_spice_model(layout)
    text = "\n".join([
        "* Ohmwork connectivity template - NOT RUNNABLE AS-IS",
        "* Replace every W=TBD L=TBD and supply nmos_model/pmos_model cards.",
        "* Pin order: output, supply, ground, declared inputs, external complements.",
        "* Both supply and ground are caller-supplied pins; no global rails.",
        *_subcircuit(model, educational=False), "",
    ])
    validate_spice_export(layout, text)
    return text


def render_spice_example(layout: Layout, inputs: Mapping[str, bool | int] | None = None) -> str:
    """Runnable educational DC operating point, defaulting to all logical inputs 0.

    ``inputs`` must specify exactly var_order, with bool or integer 0/1 values.
    Every external complement is driven automatically to NOT its primary value.
    """
    model = build_spice_model(layout)
    values = dict.fromkeys(model.var_order, False) if inputs is None else dict(inputs)
    if set(values) != set(model.var_order) or any(
        type(v) not in (bool, int) or v not in (0, 1) for v in values.values()
    ):
        raise ValueError("inputs must give exactly the declared variables as 0 or 1")
    ground = model.ports[2].node
    lines = [
        "Ohmwork educational DC example - not a fabrication design",
        "* Illustrative 5 V supply; uniform arbitrary W=10u L=1u; no sizing optimization.",
        "* Numeric model source (original parameter values retained):",
        f"* {MODEL_SOURCE}",
        "* Renamed models; Explicit LEVEL/TNOM and diode, resistance, capacitance, noise defaults; see docs/spice.md.",
        "* GAMMA retains body effect; LAMBDA=0 disables channel-length modulation.",
        "* DC only, unloaded output; no timing, parasitic, power or process claims.",
        "* The educational example is tested with ngspice. Portable SPICE3-style",
        "* syntax is intended for other simulators, which are untested.",
        "* Input vector: " + json.dumps(values, sort_keys=True),
        *_subcircuit(model, educational=True),
        *EDUCATIONAL_MODELS,
        "x0 " + " ".join("0" if p.node == ground else p.node for p in model.ports)
        + f" {SUBCIRCUIT}",
        f"v0 {model.ports[1].node} 0 DC 5",
    ]
    for i, port in enumerate(model.ports[3:], 1):
        value = bool(values[port.variable])
        if port.role == "complement":
            value = not value
        lines.append(f"v{i} {port.node} 0 DC {5 if value else 0}")
    lines.extend([".temp 27", ".options GMIN=1e-12 RELTOL=1e-3 ABSTOL=1e-12 VNTOL=1e-6",
                  ".op", ".end", ""])
    text = "\n".join(lines)
    validate_spice_export(layout, text, educational=True)
    return text


def validate_spice_export(layout: Layout, text: str, *, educational: bool = False) -> None:
    """Strict structural round-trip of our export dialect directly against Layout.

    Does not call build_spice_model and does not trust mapping comments to define
    electrical identity. An independent positional allocation from Layout pins
    their meaning. Not a general SPICE parser or an analog verification claim.
    """
    def require(condition: bool, message: str) -> None:
        if not condition:
            raise RuntimeError("SPICE export: " + message)

    node_map = {n.id: f"n{i}" for i, n in enumerate(layout.nets)}
    require(len(node_map) == len(layout.nets), "duplicate Layout net id")
    primary, complement = dict(layout.primary_nets), dict(layout.complement_nets)
    extra = {v: f"n{len(node_map) + i}" for i, v in enumerate(
        v for v in layout.var_order if v not in primary)}
    expected_ports = [node_map[n] for n in (
        layout.output_net_id, layout.vdd_net_id, layout.gnd_net_id)]
    expected_ports += [node_map[primary[v]] if v in primary else extra[v]
                       for v in layout.var_order]
    expected_ports += [node_map[complement[v]] for v in layout.var_order
                       if v in complement and v not in layout.inverter_driven_vars]
    expected_nodes = {node_map[n.id]: [n.id, n.label, _ROLES[n.kind]] for n in layout.nets}
    expected_nodes.update({name: [None, var, "unconnected declared input"]
                           for var, name in extra.items()})
    seen_nodes, seen_devices, mos_lines = {}, {}, []
    subckts, ends, inside = [], [], False
    for line_number, line in enumerate(text.splitlines()):
        if line.startswith("* node ") or line.startswith("* device "):
            _, kind, name, payload = line.split(" ", 3)
            seen = seen_nodes if kind == "node" else seen_devices
            require(name not in seen, "duplicate mapping")
            try:
                seen[name] = json.loads(payload)
            except ValueError as exc:
                raise RuntimeError("SPICE export: invalid mapping") from exc
        elif line.lower().startswith(".subckt "):
            require(not inside, "nested subcircuit")
            inside = True
            subckts.append(line.split())
        elif line.lower().startswith(".ends"):
            require(inside, "unexpected subcircuit end")
            inside = False
            ends.append(line.split())
        elif inside and line.strip() and not line.startswith("*"):
            mos_lines.append(line.split())
        elif line.strip() and not line.startswith("*"):
            require(educational, "unexpected template content")
            # The title is the first line in a standalone SPICE deck.
            if line_number != 0:
                keyword = line.split()[0]
                require(keyword in {".model", "+", "x0", ".temp", ".options", ".op", ".end"}
                        or (keyword.startswith("v") and keyword[1:].isdigit()),
                        "unexpected top-level content")
    require(not inside, "unterminated subcircuit")
    require(subckts == [[".subckt", SUBCIRCUIT, *expected_ports]], "port identity/order")
    require(ends == [[".ends", SUBCIRCUIT]], "subcircuit inventory")
    require(seen_nodes == expected_nodes, "node mapping/inventory")
    require(len(layout.devices) == layout.total_transistors, "Layout transistor count")
    require(len(mos_lines) == len(layout.devices), "device count")
    require(seen_devices == {f"m{i}": d.id for i, d in enumerate(layout.devices)},
            "device mapping/inventory")
    size = ["W=10u", "L=1u"] if educational else ["W=TBD", "L=TBD"]
    for i, (tokens, d) in enumerate(zip(mos_lines, layout.devices)):
        expected = [f"m{i}", node_map[d.drain_net], node_map[d.gate_net],
                    node_map[d.source_net],
                    node_map[layout.vdd_net_id if d.kind == "p" else layout.gnd_net_id],
                    "pmos_model" if d.kind == "p" else "nmos_model", *size]
        require(tokens == expected, f"device m{i} terminal/model/sizing identity")
    if not educational:
        require(not any(line.lower().startswith(".model") for line in text.splitlines()),
                "template must not define models")
