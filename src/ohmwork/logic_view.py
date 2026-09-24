"""Deterministic, model-backed gate geometry and portable SVG (D21).

Each terminal has its own route, even when its driver is repeated. Long edges
travel above the gate field; adjacent-stage edges use the inter-column gutter.
Crossings without a junction dot are not connections.
"""
from __future__ import annotations

from dataclasses import asdict
from html import escape
from ohmwork.expr import render
from ohmwork.logic_gates import VerifiedCircuit, verify_circuit

EXPLANATIONS = {
    'AND': '1 only when every input is 1.',
    'OR': '1 when at least one input is 1.',
    'NOT': 'The opposite of its input.',
    'BUF': 'Copies its input unchanged.',
    'NAND': '0 only when every input is 1; the opposite of AND.',
    'NOR': '1 only when every input is 0; the opposite of OR.',
    'XOR': '1 when an odd number of inputs are 1 (odd parity).',
    'XNOR': '1 when an even number of inputs are 1 (even parity).',
}


def build_logic_view(result: VerifiedCircuit) -> dict:
    # Public presentation entry point also rejects a manually altered result.
    checked = verify_circuit(result.circuit, result.expression)
    if checked != result:
        raise ValueError('Logic circuit verification data was altered')
    circuit = result.circuit
    depths = {p.id: 0 for p in circuit.inputs}
    for gate in circuit.gates:
        depths[gate.id] = 1 + max(depths[d] for d in gate.inputs)
    long_edges = sum(depths[g.id] - depths[d] > 1 for g in circuit.gates for d in g.inputs)
    top = 90 + 14 * long_edges
    columns: dict[int, list] = {}
    for gate in circuit.gates:
        columns.setdefault(depths[gate.id], []).append(gate)
    field_height = max(50 * len(circuit.inputs),
                       max((sum(max(100, 24 * len(g.inputs)) + 70 for g in gs)
                            for gs in columns.values()), default=100))
    column_x = {}
    previous_right = 70
    for depth in sorted(columns):
        terminals = sum(len(g.inputs) for g in columns[depth])
        previous_count = len(columns.get(depth - 1, circuit.inputs))
        column_x[depth] = previous_right + 90 + 10 * (terminals + previous_count)
        previous_right = column_x[depth] + 110
    ports = []
    outputs = {}
    for i, port in enumerate(circuit.inputs):
        y = top + (i + .5) * field_height / len(circuit.inputs)
        ports.append({**asdict(port), 'x': 70, 'y': y})
        outputs[port.id] = (70, y)
    gates = []
    for depth, group in columns.items():
        sizes = [max(100, 24 * len(g.inputs)) for g in group]
        total = sum(sizes) + 70 * (len(group) - 1)
        y = top + (field_height - total) / 2
        for gate, height in zip(group, sizes):
            x = column_x[depth]
            pins = [(x - 20, y + (i + 1) * height / (len(gate.inputs) + 1))
                    for i in range(len(gate.inputs))]
            outputs[gate.id] = (x + 110, y + height / 2)
            gates.append({**asdict(gate), 'x': x, 'y': y, 'height': height,
                          'pins': pins, 'out': outputs[gate.id],
                          'explanation': EXPLANATIONS[gate.kind]})
            y += height + 70
    # For unshared first-stage inputs, align their wires with their actual
    # terminals. This avoids near-coincident horizontal runs and wasted height.
    destinations = {p.id:[] for p in circuit.inputs}
    for gate in gates:
        for driver,pin in zip(gate['inputs'],gate['pins']):
            if driver in destinations:
                destinations[driver].append((depths[gate['id']],pin[1]))
    if all(len(ds)==1 and ds[0][0]==1 for ds in destinations.values()):
        positions = sorted(ds[0][1] for ds in destinations.values())
        if all(b-a >= 24 for a,b in zip(positions,positions[1:])):
            for port in ports:
                port['y'] = destinations[port['id']][0][1]
                outputs[port['id']] = (port['x'],port['y'])
    # Coordinates use depth columns; signal rows retain canonical netlist order.
    gate_order = {g.id:i for i,g in enumerate(circuit.gates)}
    gates.sort(key=lambda g: gate_order[g['id']])
    routes = []
    long_index = 0
    lane_counts = {}
    source_lanes = {p.id: i for i,p in enumerate(circuit.inputs)}
    for group in columns.values():
        source_lanes.update({g.id:i for i,g in enumerate(group)})
    for gate in gates:
        for terminal, (driver, end) in enumerate(zip(gate['inputs'], gate['pins'])):
            start = outputs[driver]
            depth = depths[gate['id']]
            index = lane_counts.get(depth, 0)
            lane_counts[depth] = index + 1
            lane = end[0] - 20 - index * 10
            if depth - depths[driver] == 1:
                points = [start, (lane, start[1]), (lane, end[1]), end]
            else:
                lane_y = 65 + 14 * long_index
                long_index += 1
                exit_x = start[0] + 20 + source_lanes[driver] * 10
                points = [start, (exit_x, start[1]),
                          (exit_x, lane_y), (lane, lane_y), (lane, end[1]), end]
            routes.append({'driver': driver, 'gate': gate['id'], 'terminal': terminal,
                           'points': points})
    width = max(480, previous_right + 160)
    end = (width - 65, outputs[circuit.output][1])
    routes.append({'driver': circuit.output, 'gate': 'F', 'terminal': 0,
                   'points': [outputs[circuit.output], end]})
    view = {'expression': render(result.expression), 'inputs': ports, 'gates': gates,
            'routes': routes, 'output': circuit.output, 'output_point': end,
            'width': width, 'height': top + field_height + 60,
            'gate_count': result.gate_count, 'depth': result.depth,
            'rows': [asdict(row) for row in result.rows]}
    return view


def _symbol(kind: str, height: float) -> str:
    h = height
    if kind in {'NOT', 'BUF'}:
        path = f'M0 0 L90 {h/2} L0 {h} Z'
    elif kind in {'AND', 'NAND'}:
        path = f'M0 0 H45 C105 0 105 {h} 45 {h} H0 Z'
    else:
        path = f'M0 0 Q60 0 95 {h/2} Q60 {h} 0 {h} Q30 {h/2} 0 0 Z'
    out = f'<path class="lg-body" d="{path}"/>'
    if kind in {'XOR', 'XNOR'}:
        out += f'<path d="M-9 0 Q21 {h/2} -9 {h}" fill="none"/>'
    if kind in {'NOT', 'NAND', 'NOR', 'XNOR'}:
        center = 96 if kind in {'NOT', 'NAND'} else 101
        out += f'<circle class="lg-body" cx="{center}" cy="{h/2}" r="6"/>'
    return out


def render_logic_svg(view: dict, row_index: int = 0) -> str:
    """Export the complete diagram with an explicit input-vector snapshot."""
    row = view['rows'][row_index]
    values = dict(zip([p['id'] for p in view['inputs']], row['inputs']))
    values.update(zip([g['id'] for g in view['gates']], row['gates']))
    def text(x, y, value, extra=''):
        return f'<text x="{x}" y="{y}" {extra}>{escape(str(value))}</text>'
    svg = [f'<svg class="lg-diagram" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Logic circuit" '
           f'viewBox="0 0 {view["width"]} {view["height"]}" width="{view["width"]}" height="{view["height"]}">',
           '<title>Verified ideal Boolean circuit</title>',
           '<style>.lg-diagram{background:#fff;color:#172334;font:14px system-ui,sans-serif} '
           '.lg-diagram text{fill:currentColor;stroke:none} .lg-body{fill:#fff} '
           '.lg-wire{fill:none;stroke:#596675;stroke-width:2} '
           '.lg-wire[data-value="1"]{stroke:#007a60;stroke-width:3} '
           '.lg-junction{fill:#596675}.lg-junction[data-value="1"]{fill:#007a60} '
           '.lg-gate{stroke:currentColor;stroke-width:2} '
           '.lg-gate:focus{outline:none;stroke:#2463eb;stroke-width:3} '
           '@media(prefers-color-scheme:dark){.lg-diagram{background:#161a23;color:#e9eef6} '
           '.lg-body{fill:#161a23}.lg-wire{stroke:#a3afc0}.lg-wire[data-value="1"]{stroke:#49d6b5} '
           '.lg-junction{fill:#a3afc0}.lg-junction[data-value="1"]{fill:#49d6b5}}</style>',
           text(24, 28, 'Ideal logic · crossings without dots are not junctions')]
    for route in view['routes']:
        points = ' '.join(f'{x},{y}' for x,y in route['points'])
        svg.append(f'<polyline class="lg-wire" data-driver="{route["driver"]}" '
                   f'data-gate="{route["gate"]}" data-terminal="{route["terminal"]}" '
                   f'data-value="{int(values[route["driver"]])}" points="{points}"/>')
    # Only actual same-net branching points receive junction dots. Merely
    # crossing a different route never creates an electrical connection.
    for driver in values:
        segments = [(a,b) for r in view['routes'] if r['driver'] == driver
                    for a,b in zip(r['points'],r['points'][1:]) if a != b]
        candidates = {tuple(p) for segment in segments for p in segment}
        for x,y in sorted(candidates):
            directions = set()
            for (ax,ay),(bx,by) in segments:
                if ay == by == y and min(ax,bx) <= x <= max(ax,bx):
                    if min(ax,bx) < x: directions.add('left')
                    if max(ax,bx) > x: directions.add('right')
                if ax == bx == x and min(ay,by) <= y <= max(ay,by):
                    if min(ay,by) < y: directions.add('up')
                    if max(ay,by) > y: directions.add('down')
            if len(directions) > 2:
                svg.append(f'<circle class="lg-wire lg-junction" data-driver="{driver}" '
                           f'data-value="{int(values[driver])}" cx="{x}" cy="{y}" r="3"/>')
    for port in view['inputs']:
        x,y=port['x'],port['y']
        svg.append(text(x-48,y-10,port['name']))
        svg.append(text(x-48,y+12,int(values[port['id']]), f'data-signal="{port["id"]}"'))
        svg.append(f'<circle cx="{x}" cy="{y}" r="3" fill="currentColor"/>')
    for gate in view['gates']:
        x,y,h=gate['x'],gate['y'],gate['height']
        svg.append(f'<g class="lg-gate" data-gate-id="{gate["id"]}" '
                   f'data-kind="{gate["kind"]}" transform="translate({x} {y})">')
        for i,(_,py) in enumerate(gate['pins']):
            # OR-family terminals meet the curved input edge, not an empty gap.
            t=(py-y)/h
            px=60*t*(1-t) if gate['kind'] in {'OR','NOR','XOR','XNOR'} else 0
            svg.append(f'<path data-pin="{i}" d="M-20 {py-y} H{px}" fill="none"/>')
        svg.append(_symbol(gate['kind'],h))
        edge=(102 if gate['kind'] in {'NOT','NAND'} else 107) if gate['kind'] in {'NOT','NAND','NOR','XNOR'} else (95 if gate['kind'] in {'OR','XOR'} else 90)
        svg.append(f'<path d="M{edge} {h/2} H110"/>')
        svg.append(text(0,-14,f'{gate["id"]} · {gate["kind"]}'))
        svg.append('</g>')
        svg.append(text(x+115,y+h/2-9,int(values[gate['id']]),f'data-signal="{gate["id"]}"'))
    x,y=view['output_point']
    svg.extend([text(x+8,y-10,'F'),text(x+8,y+12,int(row['output']),'data-output-value="true"'),'</svg>'])
    return ''.join(svg)


def format_logic_report(view: dict) -> str:
    lines=[f'F = {view["expression"]}',
           f'{view["gate_count"]} logic gates; depth {view["depth"]}; verified {len(view["rows"])} input vectors.',
           'Structure-preserving ideal logic; no minimization or transistor-cost claim.']
    lines += [f'{g["id"]}: {g["kind"]}({", ".join(g["inputs"])}) — {g["explanation"]}' for g in view['gates']]
    lines += [' '.join([p['name'] for p in view['inputs']]+[g['id'] for g in view['gates']]+['F'])]
    lines += [' '.join(str(int(v)) for v in (*r['inputs'],*r['gates'],r['output'])) for r in view['rows']]
    return '\n'.join(lines)
