"""D17 Phase A: a testable transistor-level schematic layout model built
directly from a verified :class:`~ohmwork.synth.SynthesisResult` — explicit
named nets and typed device terminals with integer coordinates, not just a
picture, so the ``Network`` tree -> layout conversion is independently
checkable before any SVG exists (Phase B, not part of this module).

Four genuinely independent correctness gates run before :func:`build_schematic`
ever returns a :class:`Layout`, each blind to what the others check:

1. **Electrical behavior** (:func:`simulate_layout`, exhaustive over every
   input vector) -- net-ID reachability only, never touching wire geometry.
2. **Wire/geometry integrity** (:func:`validate_layout_geometry`) -- wire and
   junction structure, never touching what the electricity computes.
3. **Topology fidelity** (:func:`_validate_topology_fidelity`) -- proves the
   layout's own PDN/PUN device graph has the same series/parallel shape as
   ``result.pdn``/``result.pun``, independent of the exhaustive electrical
   check (a different, equal-cost, tied-minimal network can compute the same
   function without being the same *shape*).
4. **Source fidelity** (:func:`_validate_source_fidelity`) -- proves the
   layout's device counts, D12 inverter-mode/accounting, dimensions, and
   output label all match the *particular* ``result``/``output_name`` being
   rendered, not just some internally-consistent, same-shaped layout (e.g.
   the dual-rail build of the same function has an identical PDN/PUN core
   and passes gates 1-3, but has no inverter devices at all).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from ohmwork.derivation import all_assignments
from ohmwork.expr import Expr, Not, Var, render as render_expr
from ohmwork.network import Network, Parallel, Series, Transistor, conducts
from ohmwork.synth import SynthesisResult
from ohmwork.verify import VerificationResult

CELL = 100  # integer grid cell scale; every coordinate below is an exact integer

# Gate-signal routing (D17 Phase B polish round 2): every gate net's wire
# to its dedicated rail column travels through a one-row "lane" strictly
# above row 0 (for PMOS taps) or strictly below the last row (for NMOS
# taps) -- never through the row-height space the core's own devices
# occupy -- instead of the original same-row micro-offset scheme, which
# read as wires crossing the transistor network because it cruised at
# (almost) the same height as the row it left. GATE_LANE_CELLS is the
# number of extra grid rows reserved for this at the top and bottom of
# the diagram. GATE_LANE_SUB_STEP spaces different nets' cruise lines
# apart within a lane row; GATE_HOP_STEP spaces different nets' vertical
# hop-out tracks apart within a single column, both so distinct nets
# never run collinear with each other.
GATE_LANE_CELLS = 1
GATE_LANE_SUB_STEP = 6
GATE_HOP_STEP = 3

_NET_KINDS = frozenset(
    {
        "rail_vdd",
        "rail_gnd",
        "output",
        "gate_primary",
        "gate_complement_internal",
        "gate_complement_external",
        "junction",
    }
)
_DEVICE_KINDS = frozenset({"n", "p"})
_DEVICE_ROLES = frozenset({"pdn", "pun", "inverter"})


# --- Dataclasses -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Point:
    x: int
    y: int


@dataclass(frozen=True, slots=True)
class Net:
    id: str
    label: str
    kind: str  # one of _NET_KINDS


@dataclass(frozen=True, slots=True)
class Device:
    id: str
    kind: str  # "n" or "p"
    gate_var: str  # structured gate identity -- never inferred by parsing `literal`
    gate_complemented: bool
    literal: str  # display-only rendering (e.g. "a", "b'") -- never read for correctness
    gate_net: str
    source_net: str
    drain_net: str
    role: str  # "pdn" | "pun" | "inverter"
    x: int
    y: int
    origin: Point
    gate_point: Point
    source_point: Point
    drain_point: Point


@dataclass(frozen=True, slots=True)
class WireSegment:
    id: str
    net_id: str
    p1: Point
    p2: Point


@dataclass(frozen=True, slots=True)
class Junction:
    id: str
    net_id: str
    point: Point


@dataclass(frozen=True, slots=True)
class NamedPort:
    id: str
    net_id: str
    label: str
    device_id: str
    terminal: str  # gate, or drain on the PMOS half of a shared inverter
    point: Point


@dataclass(frozen=True, slots=True)
class Boundary:
    id: str
    net_id: str
    point: Point


@dataclass(frozen=True, slots=True)
class Layout:
    nets: tuple[Net, ...]
    devices: tuple[Device, ...]
    wires: tuple[WireSegment, ...]
    junctions: tuple[Junction, ...]
    var_order: tuple[str, ...]
    output_net_id: str
    vdd_net_id: str
    gnd_net_id: str
    primary_nets: tuple[tuple[str, str], ...]  # (var, net_id), var-sorted
    complement_nets: tuple[tuple[str, str], ...]  # (var, net_id), var-sorted
    inverter_driven_vars: tuple[str, ...]  # sorted -- immutable, JSON-serializable (not a frozenset)
    total_transistors: int
    width: int  # grid bounding box (includes gate-rail/inverter columns)
    height: int
    pun_height: int
    pdn_height: int
    style: str = "wired"
    ports: tuple[NamedPort, ...] = ()
    boundaries: tuple[Boundary, ...] = ()


@dataclass(frozen=True, slots=True)
class NetState:
    connects_vdd: bool
    connects_gnd: bool

    @property
    def shorted(self) -> bool:
        return self.connects_vdd and self.connects_gnd

    @property
    def floating(self) -> bool:
        return not self.connects_vdd and not self.connects_gnd

    @property
    def value(self) -> bool | None:
        return None if (self.shorted or self.floating) else self.connects_vdd


def primary_net_id(layout: Layout, var: str) -> str | None:
    return next((nid for v, nid in layout.primary_nets if v == var), None)


def complement_net_id(layout: Layout, var: str) -> str | None:
    return next((nid for v, nid in layout.complement_nets if v == var), None)


# --- Structured literal identity ----------------------------------------


def _var_and_complement(literal: Expr) -> tuple[str, bool]:
    if isinstance(literal, Var):
        return literal.name, False
    if isinstance(literal, Not) and isinstance(literal.operand, Var):
        return literal.operand.name, True
    raise TypeError(f"not a literal: {literal!r}")  # pragma: no cover


def _gate_net_id(var: str, complemented: bool) -> str:
    return f"net_{var}_n" if complemented else f"net_{var}"


def _complemented_var_names(network: Network) -> set[str]:
    """Every variable used as a complemented literal (v') anywhere in
    ``network`` -- a direct tree walk, independent of any bookkeeping field
    on SynthesisResult, used to cross-check that bookkeeping (amendment 5)."""
    names: set[str] = set()

    def walk(n: Network) -> None:
        if isinstance(n, Transistor):
            if isinstance(n.literal, Not) and isinstance(n.literal.operand, Var):
                names.add(n.literal.operand.name)
        elif isinstance(n, (Series, Parallel)):
            for b in n.branches:
                walk(b)
        else:  # pragma: no cover
            raise TypeError(f"unknown network node: {n!r}")

    walk(network)
    return names


def _validate_result_inverter_bookkeeping(result: SynthesisResult) -> None:
    found = _complemented_var_names(result.pdn) | _complemented_var_names(result.pun)
    declared = set(result.inverter_literals)

    if not found:
        if result.inverter_literals != () or result.inverter_transistors != 0:
            raise RuntimeError(
                "internal error: pdn/pun use no complemented literals but "
                f"inverter_literals={result.inverter_literals!r}, "
                f"inverter_transistors={result.inverter_transistors}"
            )
        return

    if result.inverter_transistors == 0:
        if not result.inverter_literals or declared != found:
            raise RuntimeError(
                "internal error: dual-rail bookkeeping mismatch -- pdn/pun's own "
                f"complemented literals are {sorted(found)!r} but "
                f"result.inverter_literals={result.inverter_literals!r}"
            )
        return

    if declared != found or result.inverter_transistors != 2 * len(result.inverter_literals):
        raise RuntimeError(
            "internal error: inverter bookkeeping mismatch -- pdn/pun's own "
            f"complemented literals are {sorted(found)!r}, "
            f"result.inverter_literals={result.inverter_literals!r}, "
            f"result.inverter_transistors={result.inverter_transistors} "
            f"(expected {2 * len(declared)})"
        )


# --- Sizing pass ---------------------------------------------------------


def _size(network: Network) -> tuple[int, int]:
    """(width, height) in grid cells -- mirrors network.stack_height's own
    sum-for-series/max-for-parallel recursion for height; width is the
    transpose (max-for-series/sum-for-parallel)."""
    if isinstance(network, Transistor):
        return 1, 1
    if isinstance(network, Series):
        sizes = [_size(b) for b in network.branches]
        return max(w for w, _ in sizes), sum(h for _, h in sizes)
    if isinstance(network, Parallel):
        sizes = [_size(b) for b in network.branches]
        return sum(w for w, _ in sizes), max(h for _, h in sizes)
    raise TypeError(f"unknown network node: {network!r}")  # pragma: no cover


# --- Mutable build context ------------------------------------------------


class _Ctx:
    __slots__ = (
        "devices",
        "wires",
        "nets",
        "gate_taps",
        "device_counter",
        "wire_counter",
        "pun_junction_counter",
        "pdn_junction_counter",
        "dual_rail_mode",
    )

    def __init__(self, dual_rail_mode: bool):
        self.devices: list[Device] = []
        self.wires: list[WireSegment] = []
        self.nets: dict[str, Net] = {}
        self.gate_taps: dict[str, list[tuple[Point, str]]] = {}
        self.device_counter = 0
        self.wire_counter = 0
        self.pun_junction_counter = 0
        self.pdn_junction_counter = 0
        self.dual_rail_mode = dual_rail_mode

    def ensure_gate_net(self, var: str, complemented: bool) -> str:
        net_id = _gate_net_id(var, complemented)
        if net_id not in self.nets:
            if complemented:
                kind = "gate_complement_external" if self.dual_rail_mode else "gate_complement_internal"
                label = f"{var}'"
            else:
                kind = "gate_primary"
                label = var
            self.nets[net_id] = Net(id=net_id, label=label, kind=kind)
        return net_id

    def new_junction_net(self, role: str) -> str:
        if role == "pun":
            n = self.pun_junction_counter
            self.pun_junction_counter += 1
        else:
            n = self.pdn_junction_counter
            self.pdn_junction_counter += 1
        net_id = f"{role}_j{n}"
        self.nets[net_id] = Net(id=net_id, label=net_id, kind="junction")
        return net_id

    def new_device_id(self) -> str:
        did = f"M{self.device_counter}"
        self.device_counter += 1
        return did

    def add_wire(self, net_id: str, p1: Point, p2: Point) -> None:
        if p1 == p2:
            return
        wid = f"W{self.wire_counter}"
        self.wire_counter += 1
        self.wires.append(WireSegment(id=wid, net_id=net_id, p1=p1, p2=p2))

    def record_gate_tap(self, net_id: str, point: Point, kind: str) -> None:
        self.gate_taps.setdefault(net_id, []).append((point, kind))


def _generate_bus(ctx: _Ctx, net_id: str, points: list[Point]) -> None:
    """Points that are all touches of ``net_id`` at the same boundary --
    emits one straight WireSegment spanning them if they aren't already
    coincident. Handles both horizontal (same y) and vertical (same x)
    buses uniformly."""
    if len(points) <= 1:
        return
    xs = {p.x for p in points}
    ys = {p.y for p in points}
    if len(xs) <= 1 and len(ys) <= 1:
        return
    if len(ys) == 1:
        y = next(iter(ys))
        ctx.add_wire(net_id, Point(min(p.x for p in points), y), Point(max(p.x for p in points), y))
    elif len(xs) == 1:
        x = next(iter(xs))
        ctx.add_wire(net_id, Point(x, min(p.y for p in points)), Point(x, max(p.y for p in points)))
    else:
        raise RuntimeError(
            f"internal error: bus points for net {net_id!r} are neither horizontally nor "
            f"vertically collinear: {points!r}"
        )


# --- Placement pass --------------------------------------------------------


def _expected_device_points(x: int, y: int, kind: str) -> tuple[Point, Point, Point, Point]:
    """(origin, gate_point, source_point, drain_point) for a device at grid
    cell (x, y) of the given kind -- the single source of truth for both the
    builder (below) and validate_layout_geometry's consistency check, so the
    two can never silently drift apart."""
    origin = Point(x * CELL, y * CELL)
    top = Point(x * CELL + CELL // 2, y * CELL)
    bottom = Point(x * CELL + CELL // 2, (y + 1) * CELL)
    gate = Point((x + 1) * CELL, y * CELL + CELL // 2)
    if kind == "p":
        source, drain = top, bottom
    else:
        drain, source = top, bottom
    return origin, gate, source, drain


def _place_transistor(
    ctx: _Ctx, transistor: Transistor, role: str, x0: int, y0: int, top_net: str, bottom_net: str
) -> tuple[list[Point], list[Point]]:
    var, complemented = _var_and_complement(transistor.literal)
    gate_net_id = ctx.ensure_gate_net(var, complemented)
    device_id = ctx.new_device_id()
    origin, gate_point, source_point, drain_point = _expected_device_points(x0, y0, transistor.kind)
    top_point = Point(x0 * CELL + CELL // 2, y0 * CELL)
    bottom_point = Point(x0 * CELL + CELL // 2, (y0 + 1) * CELL)
    if transistor.kind == "p":
        source_net, drain_net = top_net, bottom_net
    else:
        drain_net, source_net = top_net, bottom_net
    device = Device(
        id=device_id,
        kind=transistor.kind,
        gate_var=var,
        gate_complemented=complemented,
        literal=render_expr(transistor.literal),
        gate_net=gate_net_id,
        source_net=source_net,
        drain_net=drain_net,
        role=role,
        x=x0,
        y=y0,
        origin=origin,
        gate_point=gate_point,
        source_point=source_point,
        drain_point=drain_point,
    )
    ctx.devices.append(device)
    ctx.record_gate_tap(gate_net_id, gate_point, transistor.kind)
    return [top_point], [bottom_point]


def _place(
    ctx: _Ctx, network: Network, role: str, x0: int, y0: int, h: int, top_net: str, bottom_net: str
) -> tuple[list[Point], list[Point]]:
    """Recursively place ``network`` in the box starting at (x0, y0) with
    height ``h`` (width is derived per-node from `_size`, never needed by
    the caller). Returns (top_points, bottom_points): the exact points
    where top_net/bottom_net are physically realized by this subtree, used
    by the caller to bus them together."""
    if isinstance(network, Transistor):
        return _place_transistor(ctx, network, role, x0, y0, top_net, bottom_net)

    if isinstance(network, Series):
        branches = network.branches
        sizes = [_size(b) for b in branches]
        boundary_nets = [top_net] + [ctx.new_junction_net(role) for _ in range(len(branches) - 1)] + [bottom_net]
        y = y0
        top_points: list[Point] | None = None
        prev_bottom: list[Point] | None = None
        for i, b in enumerate(branches):
            bw, bh = sizes[i]
            tp, bp = _place(ctx, b, role, x0, y, bh, boundary_nets[i], boundary_nets[i + 1])
            if i == 0:
                top_points = tp
            if prev_bottom is not None:
                _generate_bus(ctx, boundary_nets[i], prev_bottom + tp)
            prev_bottom = bp
            y += bh
        assert top_points is not None and prev_bottom is not None
        return top_points, prev_bottom

    if isinstance(network, Parallel):
        branches = network.branches
        sizes = [_size(b) for b in branches]
        x = x0
        all_top: list[Point] = []
        all_bottom: list[Point] = []
        for i, b in enumerate(branches):
            bw, bh = sizes[i]
            tp, bp = _place(ctx, b, role, x, y0, bh, top_net, bottom_net)
            all_top.extend(tp)
            if bh < h:
                for pt in bp:
                    far = Point(pt.x, (y0 + h) * CELL)
                    ctx.add_wire(bottom_net, pt, far)
                    all_bottom.append(far)
            else:
                all_bottom.extend(bp)
            x += bw
        return all_top, all_bottom

    raise TypeError(f"unknown network node: {network!r}")  # pragma: no cover


def _place_inverter_pair(ctx: _Ctx, var: str, x: int, gnd_row_y: int) -> tuple[Point, Point]:
    """Placed at rows 1-2 (row 0 is the top gate-signal lane, matching the
    core's own +1 row shift -- see the module docstring's routing section).
    ``gnd_row_y`` is the real GND rail's own y coordinate (the row right
    after the core, *not* the bottom of the whole diagram -- the bottom
    gate-signal lane lives below that row), needed to know how far the
    inverter's own fixed 2-row block is from it."""
    primary_net = ctx.ensure_gate_net(var, False)
    complement_net = ctx.ensure_gate_net(var, True)

    p_origin, p_gate, p_source, p_drain = _expected_device_points(x, 1, "p")
    ctx.devices.append(
        Device(
            id=f"INV_{var}_P",
            kind="p",
            gate_var=var,
            gate_complemented=False,
            literal=var,
            gate_net=primary_net,
            source_net="VDD",
            drain_net=complement_net,
            role="inverter",
            x=x,
            y=1,
            origin=p_origin,
            gate_point=p_gate,
            source_point=p_source,
            drain_point=p_drain,
        )
    )
    ctx.record_gate_tap(primary_net, p_gate, "p")

    n_origin, n_gate, n_source, n_drain = _expected_device_points(x, 2, "n")
    ctx.devices.append(
        Device(
            id=f"INV_{var}_N",
            kind="n",
            gate_var=var,
            gate_complemented=False,
            literal=var,
            gate_net=primary_net,
            source_net="GND",
            drain_net=complement_net,
            role="inverter",
            x=x,
            y=2,
            origin=n_origin,
            gate_point=n_gate,
            source_point=n_source,
            drain_point=n_drain,
        )
    )
    ctx.record_gate_tap(primary_net, n_gate, "n")

    ctx.record_gate_tap(complement_net, p_drain, "p")  # p_drain == n_drain; record once

    if n_source.y != gnd_row_y:
        gnd_far = Point(x * CELL + CELL // 2, gnd_row_y)
        ctx.add_wire("GND", n_source, gnd_far)
    else:
        gnd_far = n_source

    return p_source, gnd_far


def _build_layout_unchecked(result: SynthesisResult, output_name: str) -> Layout:
    dual_rail_mode = result.inverter_transistors == 0 and bool(result.inverter_literals)
    ctx = _Ctx(dual_rail_mode)
    ctx.nets["VDD"] = Net(id="VDD", label="VDD", kind="rail_vdd")
    ctx.nets["GND"] = Net(id="GND", label="GND", kind="rail_gnd")
    ctx.nets["OUT"] = Net(id="OUT", label=output_name, kind="output")

    pun_width, pun_height = _size(result.pun)
    pdn_width, pdn_height = _size(result.pdn)
    core_width = max(pun_width, pdn_width)
    core_height = pun_height + pdn_height
    total_height_cells = GATE_LANE_CELLS + core_height + GATE_LANE_CELLS

    # The core is placed starting at row GATE_LANE_CELLS (not row 0), to
    # leave the top gate-signal lane free above it; everything below (VDD,
    # OUT, GND bus generation) flows from these already-shifted points.
    core_y0 = GATE_LANE_CELLS
    vdd_touches, out_touches_pun = _place(ctx, result.pun, "pun", 0, core_y0, pun_height, "VDD", "OUT")
    out_touches_pdn, gnd_touches = _place(
        ctx, result.pdn, "pdn", 0, core_y0 + pun_height, pdn_height, "OUT", "GND"
    )

    inverter_vars = tuple(sorted(result.inverter_literals)) if not dual_rail_mode else ()

    primary_used = {v for v in result.var_order if _gate_net_id(v, False) in ctx.gate_taps} | set(inverter_vars)
    complement_used = {v for v in result.var_order if _gate_net_id(v, True) in ctx.gate_taps}

    rail_net_ids: list[str] = []
    for v in result.var_order:
        if v in primary_used:
            rail_net_ids.append(_gate_net_id(v, False))
        if v in complement_used:
            rail_net_ids.append(_gate_net_id(v, True))
    num_gate_rail_cols = len(rail_net_ids)
    rail_col_index = {net_id: j for j, net_id in enumerate(rail_net_ids)}

    inverter_col_base = core_width + num_gate_rail_cols
    gnd_row_y = (core_y0 + core_height) * CELL
    for i, var in enumerate(inverter_vars):
        x = inverter_col_base + i
        p_touch, gnd_far = _place_inverter_pair(ctx, var, x, gnd_row_y)
        vdd_touches.append(p_touch)
        gnd_touches.append(gnd_far)

    _generate_bus(ctx, "VDD", vdd_touches)
    _generate_bus(ctx, "OUT", out_touches_pun + out_touches_pdn)
    _generate_bus(ctx, "GND", gnd_touches)

    total_width = core_width + num_gate_rail_cols + len(inverter_vars)

    # Each net's gate taps route: (1) a short sideways hop, at a track
    # offset unique to (column, net) so distinct nets sharing a column
    # never run collinear; (2) a full vertical run at that offset, straight
    # up (PMOS taps) or down (NMOS taps) to the lane; (3) a horizontal
    # cruise, at a lane sub-row unique to this net, over to the net's own
    # dedicated column -- entirely within the lane, never at core-row
    # height, so it never reads as crossing the transistor network. A tap
    # that plainly crosses another net's wire along the way (e.g. a rail
    # bus) shares no declared point with it there, which is the existing,
    # already-validated "clean crossing = not connected" convention.
    #
    # The hop normally goes right (+offset); a device whose gate_point
    # already sits at the layout's own right edge (only ever an inverter
    # device, the last column with any devices in it) would push the hop
    # past that edge, so it goes left (-offset) instead -- still a short,
    # local, column-scale move, never anywhere near the device's own
    # channel (GATE_GAP away from it, same as the symbol template itself).
    col_net_hop_offset: dict[tuple[int, str], int] = {}
    col_hop_count: dict[int, int] = {}

    def hop_offset(col_x: int, net_id: str) -> int:
        key = (col_x, net_id)
        if key not in col_net_hop_offset:
            col_hop_count[col_x] = col_hop_count.get(col_x, 0) + 1
            magnitude = col_hop_count[col_x] * GATE_HOP_STEP
            direction = -1 if col_x + magnitude > total_width * CELL else 1
            col_net_hop_offset[key] = direction * magnitude
        return col_net_hop_offset[key]

    for net_id in rail_net_ids:
        j = rail_col_index[net_id]
        rail_x = (core_width + j) * CELL + CELL // 2
        top_lane_y = GATE_LANE_SUB_STEP * (j + 1)
        bottom_lane_y = total_height_cells * CELL - GATE_LANE_SUB_STEP * (j + 1)
        used_top = used_bottom = False
        cruised_lane_points: set[Point] = set()  # two taps sharing a (column, net, kind) share this final leg
        for p, kind in ctx.gate_taps.get(net_id, []):
            hop_x = p.x + hop_offset(p.x, net_id)
            lane_y = top_lane_y if kind == "p" else bottom_lane_y
            hop = Point(hop_x, p.y)
            vert_end = Point(hop_x, lane_y)
            cruise_far = Point(rail_x, lane_y)
            ctx.add_wire(net_id, p, hop)
            ctx.add_wire(net_id, hop, vert_end)
            if vert_end not in cruised_lane_points:
                ctx.add_wire(net_id, vert_end, cruise_far)
                cruised_lane_points.add(vert_end)
            if kind == "p":
                used_top = True
            else:
                used_bottom = True
        if used_top and used_bottom:
            ctx.add_wire(net_id, Point(rail_x, top_lane_y), Point(rail_x, bottom_lane_y))
    total_height = total_height_cells

    junctions = _compute_junctions(ctx.devices, ctx.wires)

    primary_nets = tuple(sorted((v, _gate_net_id(v, False)) for v in primary_used))
    complement_nets = tuple(sorted((v, _gate_net_id(v, True)) for v in complement_used))
    inverter_driven_vars = inverter_vars

    return Layout(
        nets=tuple(ctx.nets.values()),
        devices=tuple(ctx.devices),
        wires=tuple(ctx.wires),
        junctions=junctions,
        var_order=tuple(result.var_order),
        output_net_id="OUT",
        vdd_net_id="VDD",
        gnd_net_id="GND",
        primary_nets=primary_nets,
        complement_nets=complement_nets,
        inverter_driven_vars=inverter_driven_vars,
        total_transistors=result.total_transistors,
        width=total_width,
        height=total_height,
        pun_height=pun_height,
        pdn_height=pdn_height,
    )


# --- Junction (degree>=3) computation, shared by builder and validator ----


def _terminal_touches(devices: tuple[Device, ...]) -> list[tuple[str, Point]]:
    touches = []
    for d in devices:
        touches.append((d.gate_net, d.gate_point))
        touches.append((d.source_net, d.source_point))
        touches.append((d.drain_net, d.drain_point))
    return touches


def _is_interior(point: Point, wire: WireSegment) -> bool:
    if wire.p1.x == wire.p2.x == point.x:
        lo, hi = sorted((wire.p1.y, wire.p2.y))
        return lo < point.y < hi
    if wire.p1.y == wire.p2.y == point.y:
        lo, hi = sorted((wire.p1.x, wire.p2.x))
        return lo < point.x < hi
    return False


def _degree_at(point: Point, net_id: str, devices: tuple[Device, ...], wires: tuple[WireSegment, ...]) -> int:
    count = 0
    for term_net, term_point in _terminal_touches(devices):
        if term_net == net_id and term_point == point:
            count += 1
    for w in wires:
        if w.net_id != net_id:
            continue
        if w.p1 == point or w.p2 == point:
            count += 1
        elif _is_interior(point, w):
            count += 2
    return count


def _required_junction_points(
    devices: tuple[Device, ...], wires: tuple[WireSegment, ...]
) -> set[tuple[str, Point]]:
    candidates: set[tuple[str, Point]] = set(_terminal_touches(devices))
    for w in wires:
        candidates.add((w.net_id, w.p1))
        candidates.add((w.net_id, w.p2))
    return {(net_id, p) for net_id, p in candidates if _degree_at(p, net_id, devices, wires) >= 3}


def _compute_junctions(devices: list[Device], wires: list[WireSegment]) -> tuple[Junction, ...]:
    required = sorted(_required_junction_points(tuple(devices), tuple(wires)), key=lambda t: (t[0], t[1].y, t[1].x))
    return tuple(
        Junction(id=f"J{i}", net_id=net_id, point=point) for i, (net_id, point) in enumerate(required)
    )


# --- Gate 1: electrical behavior (net-ID reachability, never touches wires) -----


def _reachable(devices: tuple[Device, ...], gate_values: dict[str, bool], start: str) -> set[str]:
    edges: dict[str, list[str]] = {}
    for d in devices:
        is_on = gate_values[d.gate_net] if d.kind == "n" else not gate_values[d.gate_net]
        if is_on:
            edges.setdefault(d.source_net, []).append(d.drain_net)
            edges.setdefault(d.drain_net, []).append(d.source_net)
    seen = {start}
    stack = [start]
    while stack:
        n = stack.pop()
        for m in edges.get(n, ()):
            if m not in seen:
                seen.add(m)
                stack.append(m)
    return seen


def simulate_layout(layout: Layout, assignment: dict[str, bool]) -> dict[str, NetState]:
    """Pure net-ID reachability -- deliberately independent of
    `ohmwork.network.conducts`/the Network tree AND of `layout.wires`, so it
    catches a tree->model conversion bug without trusting either the source
    tree or the drawn wire geometry."""
    gate_values: dict[str, bool] = {}
    for var, net_id in layout.primary_nets:
        gate_values[net_id] = assignment[var]
    for var, net_id in layout.complement_nets:
        if var not in layout.inverter_driven_vars:
            gate_values[net_id] = not assignment[var]

    if layout.inverter_driven_vars:
        inverter_devices = tuple(d for d in layout.devices if d.role == "inverter")
        reach_vdd = _reachable(inverter_devices, gate_values, layout.vdd_net_id)
        for var in layout.inverter_driven_vars:
            net_id = complement_net_id(layout, var)
            assert net_id is not None
            gate_values[net_id] = net_id in reach_vdd

    reach_vdd = _reachable(layout.devices, gate_values, layout.vdd_net_id)
    reach_gnd = _reachable(layout.devices, gate_values, layout.gnd_net_id)

    return {
        net.id: NetState(connects_vdd=net.id in reach_vdd, connects_gnd=net.id in reach_gnd)
        for net in layout.nets
    }


def verify_layout(
    layout: Layout, var_order: list[str], minterms: set[int], dont_cares: set[int] = frozenset()
) -> VerificationResult:
    """Mirrors ohmwork.verify.verify()'s classification logic exactly, but
    against `simulate_layout`'s net-ID reachability instead of
    `network.conducts` -- and reuses VerificationResult directly, since its
    fields already say everything this needs to say."""
    rows = all_assignments(var_order)
    mismatches: list[int] = []
    floating: list[int] = []
    shorted: list[int] = []
    dont_care_assignments: dict[int, bool] = {}
    for i, row in enumerate(rows):
        state = simulate_layout(layout, row)[layout.output_net_id]
        if state.shorted:
            shorted.append(i)
            continue
        if state.floating:
            floating.append(i)
            continue
        output = state.connects_vdd
        if i in dont_cares:
            dont_care_assignments[i] = output
        elif output != (i in minterms):
            mismatches.append(i)
    return VerificationResult(
        vector_count=len(rows),
        functional_pass=not mismatches,
        structural_pass=not floating and not shorted,
        mismatches=tuple(mismatches),
        floating=tuple(floating),
        shorted=tuple(shorted),
        dont_care_assignments=dont_care_assignments,
    )


# --- Gate 2: wire/geometry integrity ---------------------------------------


def validate_layout_geometry(layout: Layout) -> None:
    """Structural-only validator, independent of `simulate_layout` -- raises
    RuntimeError on the first violation found, in a fixed check order (see
    the module docstring / docs/decisions.md D17 for the full rationale)."""
    if layout.style not in ("wired", "textbook"):
        raise RuntimeError("unknown schematic style")
    if layout.style == "wired" and (layout.ports or layout.boundaries):
        raise RuntimeError("wired layout cannot contain named ports or boundaries")
    # 1. global id uniqueness
    owner: dict[str, str] = {}
    for kind, items in (
        ("net", layout.nets),
        ("device", layout.devices),
        ("wire", layout.wires),
        ("junction", layout.junctions),
        ("port", layout.ports),
        ("boundary", layout.boundaries),
    ):
        for item in items:
            if item.id in owner:
                raise RuntimeError(f"duplicate id {item.id!r} used by both a {owner[item.id]} and a {kind}")
            owner[item.id] = kind

    # 2. vocabulary
    net_by_id = {n.id: n for n in layout.nets}
    for n in layout.nets:
        if n.kind not in _NET_KINDS:
            raise RuntimeError(f"net {n.id!r} has unknown kind {n.kind!r}")
    for d in layout.devices:
        if d.kind not in _DEVICE_KINDS:
            raise RuntimeError(f"device {d.id!r} has unknown kind {d.kind!r}")
        if d.role not in _DEVICE_ROLES:
            raise RuntimeError(f"device {d.id!r} has unknown role {d.role!r}")

    # 3. no self-loop devices -- a device with source_net == drain_net is electrically
    # degenerate and would otherwise make _canonical_layout_topology's series-parallel
    # reduction (gate 3) loop forever on an internal node of degree 2 from the self-loop
    # alone; rejected here too so a malformed layout is refused before gate 3 ever runs
    for d in layout.devices:
        if d.source_net == d.drain_net:
            raise RuntimeError(
                f"device {d.id!r} has source_net == drain_net == {d.source_net!r} -- a self-loop "
                "device cannot be part of a valid circuit"
            )

    # 4. referential integrity
    for d in layout.devices:
        for net_id in (d.gate_net, d.source_net, d.drain_net):
            if net_id not in net_by_id:
                raise RuntimeError(f"device {d.id!r} references nonexistent net {net_id!r}")
    for w in layout.wires:
        if w.net_id not in net_by_id:
            raise RuntimeError(f"wire {w.id!r} references nonexistent net {w.net_id!r}")
    for j in layout.junctions:
        if j.net_id not in net_by_id:
            raise RuntimeError(f"junction {j.id!r} references nonexistent net {j.net_id!r}")

    # 5. required global nets -- id, kind, AND (for VDD/GND) label are all pinned to the
    # literal, stable strings D17's fixed schematic semantics require. Without this, a
    # globally-consistent relabeling (VDD/GND ids renamed everywhere, or just their Net.label
    # values swapped) is invisible to every other check here, to simulate_layout (which is
    # purely relative to whatever id is plugged into vdd_net_id/gnd_net_id), and to topology
    # fidelity (which never inspects net identity at all) -- Phase B's model-to-SVG bridge
    # would then faithfully render an already-mislabeled model.
    if layout.vdd_net_id != "VDD":
        raise RuntimeError(f"layout.vdd_net_id must be exactly 'VDD', got {layout.vdd_net_id!r}")
    if layout.gnd_net_id != "GND":
        raise RuntimeError(f"layout.gnd_net_id must be exactly 'GND', got {layout.gnd_net_id!r}")
    if layout.output_net_id != "OUT":
        raise RuntimeError(f"layout.output_net_id must be exactly 'OUT', got {layout.output_net_id!r}")

    for net_id, expected_kind, label in (
        (layout.vdd_net_id, "rail_vdd", "VDD"),
        (layout.gnd_net_id, "rail_gnd", "GND"),
        (layout.output_net_id, "output", "output"),
    ):
        net = net_by_id.get(net_id)
        if net is None or net.kind != expected_kind:
            raise RuntimeError(f"{label} net {net_id!r} missing or has wrong kind")

    vdd_net = net_by_id["VDD"]
    if vdd_net.label != "VDD":
        raise RuntimeError(f"VDD net's label must be exactly 'VDD', got {vdd_net.label!r}")
    gnd_net = net_by_id["GND"]
    if gnd_net.label != "GND":
        raise RuntimeError(f"GND net's label must be exactly 'GND', got {gnd_net.label!r}")

    # 6. device geometry consistency -- origin/gate/source/drain points must match the
    # documented coordinate formulas for (x, y, kind) (the same _expected_device_points
    # the builder itself uses), and `literal` must match the structured gate identity
    for d in layout.devices:
        expected_origin, expected_gate, expected_source, expected_drain = _expected_device_points(
            d.x, d.y, d.kind
        )
        if layout.style == "textbook":
            expected_origin, expected_gate, expected_source, expected_drain = _textbook_device_points(d.x, d.y, d.kind)
        if (d.origin, d.gate_point, d.source_point, d.drain_point) != (
            expected_origin,
            expected_gate,
            expected_source,
            expected_drain,
        ):
            raise RuntimeError(
                f"device {d.id!r} geometry does not match the documented coordinate formulas for "
                f"(x={d.x}, y={d.y}, kind={d.kind!r})"
            )
        expected_literal = f"{d.gate_var}'" if d.gate_complemented else d.gate_var
        if d.literal != expected_literal:
            raise RuntimeError(
                f"device {d.id!r} literal {d.literal!r} does not match its structured gate identity "
                f"(gate_var={d.gate_var!r}, gate_complemented={d.gate_complemented!r}, expected "
                f"{expected_literal!r})"
            )

    # 7. exact, bidirectional mapping validation -- derived only from layout.devices
    core_devices = [d for d in layout.devices if d.role in ("pdn", "pun")]
    inverter_devices = [d for d in layout.devices if d.role == "inverter"]
    inverter_vars_present = {d.gate_var for d in inverter_devices}
    complement_required = {d.gate_var for d in core_devices if d.gate_complemented}
    primary_required = {d.gate_var for d in core_devices if not d.gate_complemented} | inverter_vars_present

    primary_keys = [v for v, _ in layout.primary_nets]
    if len(primary_keys) != len(set(primary_keys)):
        raise RuntimeError(f"primary_nets has duplicate variable keys: {primary_keys!r}")
    if set(primary_keys) != primary_required:
        raise RuntimeError(
            f"primary_nets keys {sorted(primary_keys)!r} do not exactly match the required set "
            f"{sorted(primary_required)!r}"
        )
    primary_net_ids = [nid for _, nid in layout.primary_nets]
    if len(primary_net_ids) != len(set(primary_net_ids)):
        raise RuntimeError("primary_nets has two variables sharing the same net id")
    for v, nid in layout.primary_nets:
        if v not in layout.var_order:
            raise RuntimeError(f"primary_nets key {v!r} is not a member of var_order")
        if nid != f"net_{v}":
            raise RuntimeError(f"primary_nets[{v!r}] -> {nid!r} does not follow the net_{{var}} id convention")
        net = net_by_id.get(nid)
        if net is None or net.kind != "gate_primary":
            raise RuntimeError(f"primary_nets[{v!r}] -> {nid!r} is missing or not kind 'gate_primary'")
        if net.label != v:
            raise RuntimeError(f"net {nid!r} has label {net.label!r}, expected {v!r}")

    complement_keys = [v for v, _ in layout.complement_nets]
    if len(complement_keys) != len(set(complement_keys)):
        raise RuntimeError(f"complement_nets has duplicate variable keys: {complement_keys!r}")
    if set(complement_keys) != complement_required:
        raise RuntimeError(
            f"complement_nets keys {sorted(complement_keys)!r} do not exactly match the required "
            f"set {sorted(complement_required)!r}"
        )
    complement_net_ids = [nid for _, nid in layout.complement_nets]
    if len(complement_net_ids) != len(set(complement_net_ids)):
        raise RuntimeError("complement_nets has two variables sharing the same net id")
    for v, nid in layout.complement_nets:
        if v not in layout.var_order:
            raise RuntimeError(f"complement_nets key {v!r} is not a member of var_order")
        if nid != f"net_{v}_n":
            raise RuntimeError(f"complement_nets[{v!r}] -> {nid!r} does not follow the net_{{var}}_n id convention")
        net = net_by_id.get(nid)
        expected_kind = "gate_complement_internal" if v in inverter_vars_present else "gate_complement_external"
        if net is None or net.kind != expected_kind:
            raise RuntimeError(f"complement_nets[{v!r}] -> {nid!r} is missing or not kind {expected_kind!r}")
        if net.label != f"{v}'":
            raise RuntimeError(f"net {nid!r} has label {net.label!r}, expected {v!r}'")

    if layout.inverter_driven_vars != tuple(sorted(inverter_vars_present)):
        raise RuntimeError(
            f"inverter_driven_vars {list(layout.inverter_driven_vars)!r} does not match the actual "
            f"inverter device pairs found {sorted(inverter_vars_present)!r}"
        )

    # every core device's own gate_net must equal the net its own gate_var/gate_complemented
    # maps to -- catches both a device-level gate_net mismatch AND a swapped/wrong
    # primary_nets/complement_nets mapping table (neither is visible from the checks above
    # alone, since those only check each side's internal self-consistency independently)
    for d in core_devices:
        expected_gate_net = (
            complement_net_id(layout, d.gate_var) if d.gate_complemented else primary_net_id(layout, d.gate_var)
        )
        if d.gate_net != expected_gate_net:
            raise RuntimeError(
                f"device {d.id!r} (gate_var={d.gate_var!r}, gate_complemented={d.gate_complemented!r}) "
                f"has gate_net={d.gate_net!r}, but the {'complement' if d.gate_complemented else 'primary'} "
                f"mapping for {d.gate_var!r} is {expected_gate_net!r}"
            )

    # 8. role/kind/inverter-pair consistency, including supply nets
    for d in core_devices:
        if d.role == "pdn" and d.kind != "n":
            raise RuntimeError(f"PDN device {d.id!r} has kind {d.kind!r}, expected 'n'")
        if d.role == "pun" and d.kind != "p":
            raise RuntimeError(f"PUN device {d.id!r} has kind {d.kind!r}, expected 'p'")

    by_var: dict[str, list[Device]] = {}
    for d in inverter_devices:
        by_var.setdefault(d.gate_var, []).append(d)
    for var in inverter_vars_present:
        pair = by_var.get(var, [])
        if len(pair) != 2 or sorted(dd.kind for dd in pair) != ["n", "p"]:
            raise RuntimeError(f"inverter for {var!r} does not consist of exactly one PMOS and one NMOS device")
        p_dev = next(dd for dd in pair if dd.kind == "p")
        n_dev = next(dd for dd in pair if dd.kind == "n")
        primary_id = primary_net_id(layout, var)
        complement_id = complement_net_id(layout, var)
        for dd in (p_dev, n_dev):
            if dd.gate_var != var or dd.gate_complemented:
                raise RuntimeError(f"inverter device {dd.id!r} has the wrong gate identity")
            if dd.gate_net != primary_id:
                raise RuntimeError(f"inverter device {dd.id!r} gate_net does not match the primary net for {var!r}")
            if dd.drain_net != complement_id:
                raise RuntimeError(
                    f"inverter device {dd.id!r} drain_net does not match the shared complement net for {var!r}"
                )
        if p_dev.source_net != layout.vdd_net_id:
            raise RuntimeError(f"inverter PMOS {p_dev.id!r} source_net is not VDD ({layout.vdd_net_id!r})")
        if n_dev.source_net != layout.gnd_net_id:
            raise RuntimeError(f"inverter NMOS {n_dev.id!r} source_net is not GND ({layout.gnd_net_id!r})")

    # 9. junction net ownership: every junction-kind net must be touched (via source_net/
    # drain_net) exclusively by devices of one role (pun or pdn, never both, never an
    # inverter), follow the {role}_jN id convention for that role, and have label == id
    junction_owner_role: dict[str, str] = {}
    for n in layout.nets:
        if n.kind != "junction":
            continue
        touching_roles = {d.role for d in layout.devices if n.id in (d.source_net, d.drain_net)}
        if touching_roles != {"pun"} and touching_roles != {"pdn"}:
            raise RuntimeError(
                f"junction net {n.id!r} is not owned exclusively by one of pun/pdn (touched by "
                f"device roles {sorted(touching_roles)!r})"
            )
        owner_role = next(iter(touching_roles))
        junction_owner_role[n.id] = owner_role
        if not re.fullmatch(rf"{owner_role}_j\d+", n.id):
            raise RuntimeError(
                f"junction net {n.id!r} owned by {owner_role!r} does not follow the "
                f"{owner_role}_jN id convention"
            )
        if n.label != n.id:
            raise RuntimeError(f"junction net {n.id!r} has label {n.label!r}, expected {n.id!r}")

    # 10. core source/drain terminal-domain restriction: a PUN device's source_net/drain_net
    # may only be VDD, OUT, or a PUN-owned junction net; a PDN device's may only be OUT, GND,
    # or a PDN-owned junction net. In particular this means a core source/drain terminal can
    # never reference a primary/complement gate net (a "gate-to-diffusion" short that would
    # otherwise be invisible to simulate_layout, which only reads gate_net for conduction, and
    # to topology fidelity, which never looks at source_net/drain_net identity beyond
    # connectivity) nor the opposite network's rail or junction net.
    for d in core_devices:
        allowed = (
            {layout.vdd_net_id, layout.output_net_id}
            if d.role == "pun"
            else {layout.output_net_id, layout.gnd_net_id}
        )
        for terminal_name, net_id in (("source_net", d.source_net), ("drain_net", d.drain_net)):
            if net_id in allowed or junction_owner_role.get(net_id) == d.role:
                continue
            raise RuntimeError(
                f"{d.role.upper()} device {d.id!r} has {terminal_name}={net_id!r}, which is not "
                f"{'VDD/OUT' if d.role == 'pun' else 'OUT/GND'} or a {d.role}-owned junction net -- "
                "a core source/drain terminal must never reference a gate net or the opposite "
                "network's rail/junction"
            )

    # 11. net inventory closure: every declared net must be accounted for exactly once -- one
    # of the three special rails (exactly one net per special kind, matching the declared id),
    # a primary/complement net that actually appears in its mapping, or a junction net whose
    # ownership was validated above. Nothing else is permitted (no orphaned/unexpected nets).
    special_ids: dict[str, list[str]] = {}
    for n in layout.nets:
        if n.kind in ("rail_vdd", "rail_gnd", "output"):
            special_ids.setdefault(n.kind, []).append(n.id)
    for kind, expected_id, label in (
        ("rail_vdd", layout.vdd_net_id, "VDD"),
        ("rail_gnd", layout.gnd_net_id, "GND"),
        ("output", layout.output_net_id, "output"),
    ):
        ids = special_ids.get(kind, [])
        if ids != [expected_id]:
            raise RuntimeError(f"expected exactly one {label} net ({expected_id!r}), found {ids!r}")

    primary_net_id_set = {nid for _, nid in layout.primary_nets}
    complement_net_id_set = {nid for _, nid in layout.complement_nets}
    for n in layout.nets:
        if n.kind == "gate_primary" and n.id not in primary_net_id_set:
            raise RuntimeError(f"net {n.id!r} (kind gate_primary) does not appear in primary_nets")
        if n.kind in ("gate_complement_internal", "gate_complement_external") and n.id not in complement_net_id_set:
            raise RuntimeError(f"net {n.id!r} (kind {n.kind!r}) does not appear in complement_nets")

    accounted_for = (
        {layout.vdd_net_id, layout.gnd_net_id, layout.output_net_id}
        | primary_net_id_set
        | complement_net_id_set
        | set(junction_owner_role)
    )
    for n in layout.nets:
        if n.id not in accounted_for:
            raise RuntimeError(
                f"net {n.id!r} (kind {n.kind!r}) is not a declared special net, a mapped primary/"
                "complement net, or an owned junction net -- unused or unexpected"
            )

    # 12. device count -- the one place this is checked
    if len(layout.devices) != layout.total_transistors:
        raise RuntimeError(
            f"device count {len(layout.devices)} does not match total_transistors "
            f"{layout.total_transistors}"
        )

    # 13. segment shape sanity + point sanity
    seen_segments: set[tuple[str, frozenset]] = set()
    for w in layout.wires:
        if not (w.p1.x == w.p2.x or w.p1.y == w.p2.y):
            raise RuntimeError(f"wire {w.id!r} is not axis-aligned: {w.p1!r} -> {w.p2!r}")
        if w.p1 == w.p2:
            raise RuntimeError(f"wire {w.id!r} has zero length")
        for p in (w.p1, w.p2):
            if not (0 <= p.x <= layout.width * CELL and 0 <= p.y <= layout.height * CELL):
                raise RuntimeError(f"wire {w.id!r} endpoint {p!r} is out of bounds")
        key = (w.net_id, frozenset({(w.p1.x, w.p1.y), (w.p2.x, w.p2.y)}))
        if key in seen_segments:
            raise RuntimeError(f"wire {w.id!r} duplicates another segment on net {w.net_id!r}")
        seen_segments.add(key)
    for j in layout.junctions:
        if not (0 <= j.point.x <= layout.width * CELL and 0 <= j.point.y <= layout.height * CELL):
            raise RuntimeError(f"junction {j.id!r} point {j.point!r} is out of bounds")
    for d in layout.devices:
        for p in (d.origin, d.gate_point, d.source_point, d.drain_point):
            if not (0 <= p.x <= layout.width * CELL and 0 <= p.y <= layout.height * CELL):
                raise RuntimeError(f"device {d.id!r} point {p!r} is out of bounds")

    _validate_named_ports(layout, net_by_id)

    # 14. shared touch index, reused by checks 15-19
    touches: dict[Point, list[tuple[str, str, str]]] = {}

    def _add_touch(net_id: str, point: Point, source_kind: str, source_id: str) -> None:
        touches.setdefault(point, []).append((net_id, source_kind, source_id))

    for d in layout.devices:
        _add_touch(d.gate_net, d.gate_point, "device_gate", d.id)
        _add_touch(d.source_net, d.source_point, "device_source", d.id)
        _add_touch(d.drain_net, d.drain_point, "device_drain", d.id)
    for w in layout.wires:
        _add_touch(w.net_id, w.p1, "segment_endpoint", w.id)
        _add_touch(w.net_id, w.p2, "segment_endpoint", w.id)
    for p in layout.ports:
        _add_touch(p.net_id, p.point, "port", p.id)
    for b in layout.boundaries:
        _add_touch(b.net_id, b.point, "boundary", b.id)

    # 15. wire-endpoint anchoring
    junction_points = {(j.net_id, j.point) for j in layout.junctions}
    for w in layout.wires:
        for p in (w.p1, w.p2):
            same_net_entries = [e for e in touches.get(p, []) if e[0] == w.net_id]
            anchored = (w.net_id, p) in junction_points
            anchored = anchored or any(e[1] in ("device_gate", "device_source", "device_drain", "port", "boundary") for e in same_net_entries)
            anchored = anchored or any(e[1] == "segment_endpoint" and e[2] != w.id for e in same_net_entries)
            if not anchored:
                raise RuntimeError(
                    f"wire {w.id!r} endpoint {p!r} on net {w.net_id!r} is not anchored to any device "
                    "terminal, junction, or other wire -- a dangling stub"
                )

    # 16. accidental-short / cross-net check -- exact point coincidence between different nets
    for point, entries in touches.items():
        nets_here = {e[0] for e in entries}
        if len(nets_here) > 1:
            a, b = sorted(nets_here)
            raise RuntimeError(f"net {a!r} and net {b!r} both touch point {point!r} -- accidental short or wrong net_id")

    # 17. cross-net interior-touch check: a declared point of one net (a device terminal or
    # a wire endpoint -- everything in `touches`) must never lie on the strict interior of a
    # DIFFERENT net's wire segment. This also subsumes a same-line ("collinear") overlap
    # between two different-net segments, since two non-identical overlapping collinear
    # segments always put at least one endpoint of one strictly inside the other.
    #
    # A plain perpendicular crossing that shares no declared point with anything is still
    # allowed: in standard schematic convention, two wires crossing without a junction dot
    # are an explicit, unambiguous "not connected" -- that convention is exactly why the dot
    # exists, and `_required_junction_points` only ever considers a point a junction
    # candidate when it's a declared device terminal or wire endpoint, so a mid-span crossing
    # point never accidentally acquires one. A point *on the interior* of another net's wire
    # is different: it reads exactly like an unmarked T-tap, not a clean crossing, so it is
    # rejected here even though it isn't a "collinear" overlap.
    for w in layout.wires:
        for p, entries in touches.items():
            if p == w.p1 or p == w.p2:
                continue
            other_nets = {e[0] for e in entries if e[0] != w.net_id}
            if other_nets and _is_interior(p, w):
                raise RuntimeError(
                    f"point {p!r} (net {sorted(other_nets)[0]!r}) lies on the interior of segment "
                    f"{w.id!r} (net {w.net_id!r}) with no declared connection"
                )

    # 18. per-net connected-component check
    net_ids_touched = {e[0] for entries in touches.values() for e in entries}
    for net_id in sorted(net_ids_touched):
        points_for_net = [p for p, entries in touches.items() if any(e[0] == net_id for e in entries)]
        if len(points_for_net) <= 1:
            continue
        parent = {p: p for p in points_for_net}

        def find(x: Point) -> Point:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a: Point, b: Point) -> None:
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        net_wires = [w for w in layout.wires if w.net_id == net_id]
        for w in net_wires:
            if w.p1 in parent and w.p2 in parent:
                union(w.p1, w.p2)
        for w in net_wires:
            for p in points_for_net:
                if p != w.p1 and p != w.p2 and _is_interior(p, w):
                    union(p, w.p1)
        # Only explicitly validated, visible named ports may bridge components.
        # Every port's local stub was checked before this union, including its
        # terminal identity and geometry; a net-id match alone is insufficient.
        named = [p.point for p in layout.ports if p.net_id == net_id]
        for p in named[1:]:
            union(named[0], p)
        roots = {find(p) for p in points_for_net}
        if len(roots) > 1:
            raise RuntimeError(
                f"net {net_id!r} geometry is not a single connected component ({len(roots)} "
                "components found)"
            )

    # 19. junction completeness, both directions
    required = _required_junction_points(layout.devices, layout.wires)
    declared = {(j.net_id, j.point) for j in layout.junctions}
    missing = required - declared
    if missing:
        net_id, point = next(iter(sorted(missing, key=lambda t: (t[0], t[1].y, t[1].x))))
        raise RuntimeError(f"point {point!r} on net {net_id!r} has >=3 connections but no Junction is declared there")
    extra = declared - required
    if extra:
        net_id, point = next(iter(sorted(extra, key=lambda t: (t[0], t[1].y, t[1].x))))
        raise RuntimeError(
            f"Junction at {point!r} on net {net_id!r} does not correspond to a real 3-way (or more) connection"
        )

    # 20. domain minimums
    if not any(d.source_net == layout.vdd_net_id for d in layout.devices):
        raise RuntimeError("VDD net is not touched by any device")
    if not any(d.source_net == layout.gnd_net_id for d in layout.devices):
        raise RuntimeError("GND net is not touched by any device")
    out_roles = {
        d.role for d in layout.devices if layout.output_net_id in (d.source_net, d.drain_net)
    }
    if not {"pun", "pdn"} <= out_roles:
        raise RuntimeError(f"OUT net is not touched by both a PUN and a PDN device (touched by roles {sorted(out_roles)!r})")
    for v, nid in layout.primary_nets + layout.complement_nets:
        if not any(d.gate_net == nid for d in layout.devices):
            raise RuntimeError(f"net {nid!r} (for variable {v!r}) is not touched by any gate")
    for n in layout.nets:
        if n.kind == "junction":
            touching = {d.id for d in layout.devices if n.id in (d.gate_net, d.source_net, d.drain_net)}
            if len(touching) < 2:
                raise RuntimeError(f"internal junction net {n.id!r} is touched by fewer than 2 distinct devices")


# --- Gate 3: topology fidelity ----------------------------------------------


def _canon_combine(tag: str, sigs: list[tuple]) -> tuple:
    flat = []
    for s in sigs:
        if s[0] == tag:
            flat.extend(s[1])
        else:
            flat.append(s)
    return (tag, tuple(sorted(flat)))


def _canonical_topology(network: Network) -> tuple:
    if isinstance(network, Transistor):
        var, complemented = _var_and_complement(network.literal)
        return ("T", network.kind, var, complemented)
    if isinstance(network, Series):
        return _canon_combine("S", [_canonical_topology(b) for b in network.branches])
    if isinstance(network, Parallel):
        return _canon_combine("P", [_canonical_topology(b) for b in network.branches])
    raise TypeError(f"unknown network node: {network!r}")  # pragma: no cover


def _canonical_layout_topology(devices: tuple[Device, ...], top_net: str, bottom_net: str) -> tuple:
    """Independently reconstructs a canonical series/parallel signature from
    the layout's own device graph via classic series-parallel graph
    reduction -- never touches layout.wires or any Network tree.

    Defensive against a malformed device graph: a self-loop edge
    (source_net == drain_net) at an internal node has degree 2 purely from
    itself, so the series-reduction step below would otherwise "reduce" it
    into a new self-loop of ever-deeper nested signature forever without the
    edge count ever dropping -- rejected explicitly here, and backed by a
    strict-decrease + iteration-bound check on every reduction step in case
    some other malformed shape hits a similar non-terminating case."""
    for d in devices:
        if d.source_net == d.drain_net:
            raise RuntimeError(
                f"device {d.id!r} has source_net == drain_net == {d.source_net!r} -- a self-loop "
                "device cannot be part of a valid two-terminal series-parallel network"
            )

    edges: list[tuple[str, str, tuple]] = [
        (d.source_net, d.drain_net, ("T", d.kind, d.gate_var, d.gate_complemented)) for d in devices
    ]

    def reduce_once(edges: list[tuple[str, str, tuple]]) -> tuple[list[tuple[str, str, tuple]], bool]:
        groups: dict[frozenset, list[int]] = {}
        for i, (u, v, _sig) in enumerate(edges):
            groups.setdefault(frozenset((u, v)), []).append(i)
        for key, idxs in groups.items():
            if len(idxs) > 1:
                merged = _canon_combine("P", [edges[i][2] for i in idxs])
                pts = tuple(key) if len(key) == 2 else (next(iter(key)),) * 2
                remaining = [e for i, e in enumerate(edges) if i not in idxs]
                remaining.append((pts[0], pts[1], merged))
                return remaining, True

        degree: dict[str, int] = {}
        incident: dict[str, list[int]] = {}
        for i, (u, v, _sig) in enumerate(edges):
            degree[u] = degree.get(u, 0) + 1
            degree[v] = degree.get(v, 0) + 1
            incident.setdefault(u, []).append(i)
            incident.setdefault(v, []).append(i)
        for node, deg in degree.items():
            if node in (top_net, bottom_net) or deg != 2:
                continue
            i1, i2 = incident[node]
            u1, v1, s1 = edges[i1]
            u2, v2, s2 = edges[i2]
            other1 = v1 if u1 == node else u1
            other2 = v2 if u2 == node else u2
            merged = _canon_combine("S", [s1, s2])
            remaining = [e for i, e in enumerate(edges) if i not in (i1, i2)]
            remaining.append((other1, other2, merged))
            return remaining, True
        return edges, False

    changed = True
    max_iterations = len(edges) + 1
    iterations = 0
    while changed:
        iterations += 1
        if iterations > max_iterations:
            raise RuntimeError(
                f"internal error: series-parallel reduction did not terminate within "
                f"{max_iterations} iterations for the device graph between {top_net!r} and "
                f"{bottom_net!r}"
            )
        before = len(edges)
        edges, changed = reduce_once(edges)
        if changed and len(edges) >= before:
            raise RuntimeError(
                f"internal error: a series-parallel reduction step did not decrease the edge "
                f"count ({before} -> {len(edges)}) for the device graph between {top_net!r} and "
                f"{bottom_net!r}"
            )

    if len(edges) != 1:
        raise RuntimeError(
            f"layout device graph between {top_net!r} and {bottom_net!r} did not reduce to a single "
            f"series-parallel signature ({len(edges)} edges remain) -- not a valid two-terminal "
            "series-parallel network between the expected boundaries"
        )
    u, v, sig = edges[0]
    if {u, v} != {top_net, bottom_net}:
        raise RuntimeError(
            f"layout device graph's final reduced edge endpoints {{{u!r}, {v!r}}} do not match the "
            f"expected boundaries {{{top_net!r}, {bottom_net!r}}}"
        )
    return sig


def _validate_topology_fidelity(layout: Layout, result: SynthesisResult) -> None:
    """Proves the layout's own PDN/PUN device graph, reduced back to a
    canonical shape, matches result.pdn/result.pun's own canonical shape --
    independent of the exhaustive electrical check in build_schematic, which
    only proves *behavior* matches, not that the *shape* is the one
    synthesize() actually chose (a different, equal-cost, tied-minimal
    network can compute the identical function). Inverter devices are
    excluded -- their shape is pinned down by validate_layout_geometry's
    role/kind-pair check instead."""
    pun_devices = tuple(d for d in layout.devices if d.role == "pun")
    pdn_devices = tuple(d for d in layout.devices if d.role == "pdn")

    expected_pun = _canonical_topology(result.pun)
    expected_pdn = _canonical_topology(result.pdn)
    actual_pun = _canonical_layout_topology(pun_devices, layout.vdd_net_id, layout.output_net_id)
    actual_pdn = _canonical_layout_topology(pdn_devices, layout.output_net_id, layout.gnd_net_id)

    if actual_pun != expected_pun:
        raise RuntimeError(
            f"PUN layout topology does not match the synthesized network: expected {expected_pun!r}, "
            f"got {actual_pun!r}"
        )
    if actual_pdn != expected_pdn:
        raise RuntimeError(
            f"PDN layout topology does not match the synthesized network: expected {expected_pdn!r}, "
            f"got {actual_pdn!r}"
        )


# --- Gate 4: source fidelity -------------------------------------------------


def _validate_source_fidelity(layout: Layout, result: SynthesisResult, output_name: str) -> None:
    """Gate 4: fidelity to the *particular* SynthesisResult being rendered.

    Gates 1-3 all check either the layout's own internal self-consistency
    (electrical behavior, geometry) or, for topology fidelity, only the
    PDN/PUN *core* shape -- deliberately excluding inverters (their shape is
    pinned by validate_layout_geometry's role/kind-pair check instead). None
    of them ever cross-check the layout's D12 inverter-mode/accounting
    against the actual `result` object build_schematic was asked to render.
    That gap is real: the dual-rail layout for a function needing a shared
    inverter has an IDENTICAL core PDN/PUN topology and computes the
    IDENTICAL function (dual-rail's external complement net is definitionally
    correct by construction) -- so it passes gates 1-3 even when substituted
    for the normal, inverter-bearing result it doesn't actually belong to.
    This gate closes that by checking device counts, inverter accounting,
    dimensions, and the output label directly against `result`/`output_name`."""
    if layout.var_order != tuple(result.var_order):
        raise RuntimeError(
            f"layout.var_order {layout.var_order!r} does not match result.var_order "
            f"{tuple(result.var_order)!r}"
        )

    pun_count = sum(1 for d in layout.devices if d.role == "pun")
    if pun_count != result.pun_transistors:
        raise RuntimeError(
            f"layout has {pun_count} PUN devices, but result.pun_transistors is "
            f"{result.pun_transistors}"
        )
    pdn_count = sum(1 for d in layout.devices if d.role == "pdn")
    if pdn_count != result.pdn_transistors:
        raise RuntimeError(
            f"layout has {pdn_count} PDN devices, but result.pdn_transistors is "
            f"{result.pdn_transistors}"
        )
    inverter_count = sum(1 for d in layout.devices if d.role == "inverter")
    if inverter_count != result.inverter_transistors:
        raise RuntimeError(
            f"layout has {inverter_count} inverter devices, but result.inverter_transistors is "
            f"{result.inverter_transistors}"
        )
    if not (len(layout.devices) == layout.total_transistors == result.total_transistors):
        raise RuntimeError(
            f"device count mismatch: len(layout.devices)={len(layout.devices)}, "
            f"layout.total_transistors={layout.total_transistors}, "
            f"result.total_transistors={result.total_transistors}"
        )

    expected_inverter_driven = () if result.inverter_transistors == 0 else tuple(sorted(result.inverter_literals))
    if layout.inverter_driven_vars != expected_inverter_driven:
        raise RuntimeError(
            f"layout.inverter_driven_vars {layout.inverter_driven_vars!r} does not match the "
            f"expected {expected_inverter_driven!r} for this result"
        )

    if layout.pun_height != result.pun_stack_height:
        raise RuntimeError(
            f"layout.pun_height {layout.pun_height} != result.pun_stack_height "
            f"{result.pun_stack_height}"
        )
    if layout.pdn_height != result.pdn_stack_height:
        raise RuntimeError(
            f"layout.pdn_height {layout.pdn_height} != result.pdn_stack_height "
            f"{result.pdn_stack_height}"
        )
    expected_height = layout.pun_height + layout.pdn_height + 2 * GATE_LANE_CELLS
    if layout.style == "textbook":
        expected_height *= 2
    if layout.height != expected_height:
        raise RuntimeError(
            f"layout.height {layout.height} != layout.pun_height + layout.pdn_height + "
            f"2*GATE_LANE_CELLS ({expected_height})"
        )

    expected_pun_width, _ = _size(result.pun)
    expected_pdn_width, _ = _size(result.pdn)
    expected_core_width = max(expected_pun_width, expected_pdn_width)
    expected_num_rail_cols = len(layout.primary_nets) + len(layout.complement_nets)
    expected_num_inverter_cols = result.inverter_transistors // 2
    expected_width = expected_core_width + expected_num_rail_cols + expected_num_inverter_cols
    if layout.style == "textbook":
        expected_width = 2 * expected_core_width + 2 + (2 * expected_num_inverter_cols + 2 if expected_num_inverter_cols else 0)
    if layout.width != expected_width:
        raise RuntimeError(
            f"layout.width {layout.width} does not match the documented sizing formula (core "
            f"width {expected_core_width} + rail columns {expected_num_rail_cols} + inverter "
            f"columns {expected_num_inverter_cols} = {expected_width})"
        )

    out_net = next((n for n in layout.nets if n.id == layout.output_net_id), None)
    if out_net is None or out_net.label != output_name:
        got = out_net.label if out_net is not None else None
        raise RuntimeError(
            f"OUT net's label {got!r} does not match the requested output_name {output_name!r}"
        )


# --- Public entry point -----------------------------------------------------


def _textbook_device_points(x: int, y: int, kind: str) -> tuple[Point, Point, Point, Point]:
    """Generous two-cell pitch; gates face left, diffusion flows down.

    Terminal locations are electrical model geometry. The shorter channel,
    electrode and bent source/drain leads inside this box are symbol geometry.
    """
    origin = Point(200 * x + 100, 200 * y)
    top = Point(origin.x + 100, origin.y)
    bottom = Point(top.x, top.y + 200)
    gate = Point(top.x - 55, top.y + 100)
    return origin, gate, top if kind == "p" else bottom, bottom if kind == "p" else top


def _validate_named_ports(layout: Layout, nets: dict[str, Net]) -> None:
    if layout.style != "textbook":
        return
    devices = {d.id: d for d in layout.devices}
    expected = {(d.id, "gate") for d in layout.devices}
    expected |= {(d.id, "drain") for d in layout.devices if d.role == "inverter" and d.kind == "p"}
    found = [(p.device_id, p.terminal) for p in layout.ports]
    if len(found) != len(set(found)) or set(found) != expected:
        raise RuntimeError("named ports must cover every gate and each shared inverter output exactly once")
    for var in layout.inverter_driven_vars:
        pair = [d for d in layout.devices if d.role == "inverter" and d.gate_var == var]
        if len(pair) != 2 or pair[0].drain_point != pair[1].drain_point:
            raise RuntimeError("shared inverter drains must visibly meet before the named output port")
    for p in layout.ports:
        d = devices[p.device_id]
        net_id = getattr(d, p.terminal + "_net")
        terminal = getattr(d, p.terminal + "_point")
        n = nets.get(p.net_id)
        if n is None or not n.kind.startswith("gate_") or p.net_id != net_id or p.label != n.label:
            raise RuntimeError("named port label/net/terminal identity mismatch")
        expected_point = Point(terminal.x - 35, terminal.y) if p.terminal == "gate" else Point(terminal.x + 90, terminal.y)
        if p.point != expected_point:
            raise RuntimeError("named port anchor differs from its local terminal stub")
        matching = [w for w in layout.wires if w.net_id == net_id and {w.p1, w.p2} == {terminal, p.point}]
        if len(matching) != 1:
            raise RuntimeError("named port must visibly meet its own terminal through exactly one local stub")
    labels = [n.label for n in layout.nets if n.kind.startswith("gate_")]
    if len(labels) != len(set(labels)):
        raise RuntimeError("different gate nets have the same visible label")
    if len(layout.boundaries) != 3 or {b.net_id for b in layout.boundaries} != {"VDD", "GND", "OUT"}:
        raise RuntimeError("textbook layout needs exactly VDD/GND/OUT boundaries")
    for b in layout.boundaries:
        if not any(w.net_id == b.net_id and b.point in (w.p1, w.p2) for w in layout.wires):
            raise RuntimeError("supply/output boundary has no continuous wire")
    for p in [p.point for p in layout.ports] + [b.point for b in layout.boundaries]:
        if not (0 <= p.x <= layout.width * CELL and 0 <= p.y <= layout.height * CELL):
            raise RuntimeError("port or boundary is out of bounds")


def _textbook_projection(source: Layout) -> Layout:
    """Re-layout the validated topology, replacing ONLY gate distribution wires.

    No resynthesis and no expression parsing. Original source/drain net IDs,
    device identities and source/drain wires are preserved. Shared inverter
    drain ports retain the locally coincident PMOS/NMOS drain connection.
    """
    core_width = source.width - len(source.primary_nets) - len(source.complement_nets) - len(source.inverter_driven_vars)
    rail_cols = len(source.primary_nets) + len(source.complement_nets)
    inverter_start = (core_width + rail_cols) * CELL

    def transform(p: Point) -> Point:
        x = 2 * p.x + 100
        if p.x >= inverter_start:
            x += 200 - 200 * rail_cols
        return Point(x, 2 * p.y)

    devices = []
    for d in source.devices:
        x = d.x - rail_cols + 1 if d.role == "inverter" else d.x
        origin, gate, src, drain = _textbook_device_points(x, d.y, d.kind)
        devices.append(replace(d, x=x, origin=origin, gate_point=gate, source_point=src, drain_point=drain))
    gate_nets = {n.id for n in source.nets if n.kind.startswith("gate_")}
    wires = [replace(w, p1=transform(w.p1), p2=transform(w.p2)) for w in source.wires if w.net_id not in gate_nets]
    ports = []
    nets = {n.id: n for n in source.nets}
    for d in devices:
        anchor = Point(d.gate_point.x - 35, d.gate_point.y)
        ports.append(NamedPort(f"PORT_{d.id}", d.gate_net, nets[d.gate_net].label, d.id, "gate", anchor))
        wires.append(WireSegment(f"STUB_{d.id}", d.gate_net, d.gate_point, anchor))
        if d.role == "inverter" and d.kind == "p":
            anchor = Point(d.drain_point.x + 90, d.drain_point.y)
            ports.append(NamedPort(f"PORT_OUT_{d.id}", d.drain_net, nets[d.drain_net].label, d.id, "drain", anchor))
            wires.append(WireSegment(f"STUB_OUT_{d.id}", d.drain_net, d.drain_point, anchor))
    boundaries = []
    for net_id in ("VDD", "GND", "OUT"):
        points = [getattr(d, terminal + "_point") for d in devices if d.role != "inverter"
                  for terminal in ("source", "drain") if getattr(d, terminal + "_net") == net_id]
        if net_id == "OUT":
            start = max(points, key=lambda p: p.x)
            anchor = Point(core_width * 200 + 65, start.y)
        else:
            rail_y = min(p.y for p in points) if net_id == "VDD" else max(p.y for p in points)
            rail_points = [p for p in points if p.y == rail_y]
            start = Point((min(p.x for p in rail_points) + max(p.x for p in rail_points)) // 2, rail_y)
            anchor = Point(start.x, start.y + (-65 if net_id == "VDD" else 65))
            # Split the bus at a new supply tee so its connection is explicit.
            for i, w in enumerate(wires):
                if w.net_id == net_id and _is_interior(start, w):
                    wires[i:i+1] = [replace(w, p2=start), replace(w, id=w.id + "_tail", p1=start)]
                    break
        wires.append(WireSegment(f"LEAD_{net_id}", net_id, start, anchor))
        boundaries.append(Boundary(f"BOUNDARY_{net_id}", net_id, anchor))
    inv_count = len(source.inverter_driven_vars)
    return replace(source, devices=tuple(devices), wires=tuple(wires),
                   junctions=_compute_junctions(devices, wires), ports=tuple(ports), boundaries=tuple(boundaries),
                   style="textbook", width=2 * core_width + 2 + (2 * inv_count + 2 if inv_count else 0), height=2 * source.height)


def build_textbook_schematic(result: SynthesisResult, output_name: str) -> Layout:
    """A named-port schematic, independently gated after the geometry transform."""
    source = build_schematic(result, output_name)
    layout = _textbook_projection(source)
    if layout.style != "textbook":
        raise RuntimeError("textbook projection returned the wrong layout style")
    validate_layout_geometry(layout)
    _validate_topology_fidelity(layout, result)
    _validate_source_fidelity(layout, result, output_name)
    for row in all_assignments(result.var_order):
        state = simulate_layout(layout, row)[layout.output_net_id]
        if state.floating or state.shorted or state.value != conducts(result.pun, row):
            raise RuntimeError("textbook layout failed electrical verification")
    return layout


def build_schematic(result: SynthesisResult, output_name: str) -> Layout:
    """Builds a schematic Layout for `result`, running all four
    correctness gates before ever returning -- see the module docstring."""
    _validate_result_inverter_bookkeeping(result)
    layout = _build_layout_unchecked(result, output_name)

    validate_layout_geometry(layout)  # gate 2: wire/geometry integrity

    for row in all_assignments(result.var_order):  # gate 1: electrical behavior
        state = simulate_layout(layout, row)[layout.output_net_id]
        if state.floating or state.shorted:
            raise RuntimeError(
                f"internal error: schematic output net floats/shorts for input {row} "
                f"(connects_vdd={state.connects_vdd}, connects_gnd={state.connects_gnd})"
            )
        if state.value != conducts(result.pun, row):
            raise RuntimeError(
                f"internal error: schematic output value for input {row} ({state.value}) disagrees "
                f"with the verified PUN network ({conducts(result.pun, row)})"
            )

    _validate_topology_fidelity(layout, result)  # gate 3: topology fidelity

    _validate_source_fidelity(layout, result, output_name)  # gate 4: source fidelity

    return layout
