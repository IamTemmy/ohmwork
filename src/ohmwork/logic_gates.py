"""D21 ideal logic circuits, independent of CMOS synthesis and layout.

Builders return only exhaustively verified circuits. Signal rows are immutable
and ordered by the circuit's inputs/gates, ready for a presentation consumer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from ohmwork.derivation import all_assignments, evaluate, variables_in_order
from ohmwork.expr import And, Expr, Not, Or, Var, Xor
from ohmwork.parser import parse
from ohmwork.truth_table import parse_var_list

MAX_INPUTS = 8
MAX_GATES = 128
MAX_SOURCE_LENGTH = 4096
MAX_NESTING = 64
GATE_KINDS = frozenset({'AND', 'OR', 'NOT', 'NAND', 'NOR', 'XOR', 'XNOR', 'BUF'})


@dataclass(frozen=True)
class Input:
    id: str
    name: str


@dataclass(frozen=True)
class Gate:
    id: str
    kind: str
    inputs: tuple[str, ...]


@dataclass(frozen=True)
class Circuit:
    inputs: tuple[Input, ...]
    gates: tuple[Gate, ...]
    output: str


@dataclass(frozen=True)
class SignalRow:
    inputs: tuple[bool, ...]
    gates: tuple[bool, ...]
    output: bool


@dataclass(frozen=True)
class VerifiedCircuit:
    circuit: Circuit
    expression: Expr
    rows: tuple[SignalRow, ...]
    gate_count: int
    depth: int


def _check_ast(ast: Expr) -> None:
    # Check depth before any recursive evaluation, rendering or AST hashing.
    pending = [(ast, 0)]
    while pending:
        node, depth = pending.pop()
        if depth > MAX_NESTING:
            raise ValueError(f'Logic circuit nesting exceeds {MAX_NESTING}')
        if isinstance(node, Var):
            continue
        if isinstance(node, Not):
            children = (node.operand,)
        elif isinstance(node, (And, Or, Xor)):
            children = node.operands
            if not 2 <= len(children) <= MAX_INPUTS:
                raise ValueError('Logic gates require 2-8 operands; split larger gates explicitly')
        else:
            raise ValueError('Unsupported logic circuit expression node')
        pending.extend((child, depth + 1) for child in children)


def _parse_expression(source: str) -> Expr:
    if not isinstance(source, str):
        raise ValueError('Logic circuit expression must be text')
    if len(source) > MAX_SOURCE_LENGTH:
        raise ValueError(f'Logic circuit expression exceeds {MAX_SOURCE_LENGTH} characters')
    depth = 0
    for char in source:
        if char == '(':
            depth += 1
            if depth > MAX_NESTING:
                raise ValueError(f'Logic circuit nesting exceeds {MAX_NESTING}')
        elif char == ')':
            depth -= 1
    ast = parse(source)
    # Required before compiler recursion/hashing, not just final verification.
    _check_ast(ast)
    return ast


def validate_circuit(circuit: Circuit) -> None:
    """Reject ambiguous, non-topological, malformed or disconnected netlists."""
    if not isinstance(circuit.inputs, tuple) or not isinstance(circuit.gates, tuple):
        raise ValueError('Circuit collections must be immutable tuples')
    if not 1 <= len(circuit.inputs) <= MAX_INPUTS:
        raise ValueError('Logic circuits support 1-8 inputs')
    names = tuple(port.name for port in circuit.inputs)
    try:
        parsed_names = tuple(parse_var_list(','.join(names)))
    except ValueError as exc:
        raise ValueError(str(exc).replace('--vars contains', 'Input names contain').replace('--vars', 'Input names')) from exc
    if parsed_names != names:
        raise ValueError('Invalid input names')
    if len(circuit.gates) > MAX_GATES:
        raise ValueError(f'Logic circuit exceeds {MAX_GATES} gates')
    available: set[str] = set()
    for i, port in enumerate(circuit.inputs):
        if port.id != f'i{i}':
            raise ValueError('Input IDs must be unique and in canonical order')
        available.add(port.id)
    for i, gate in enumerate(circuit.gates):
        if not isinstance(gate.inputs, tuple):
            raise ValueError('Gate terminals must be an immutable tuple')
        if gate.id != f'g{i}':
            raise ValueError('Gate IDs must be unique and in canonical order')
        if gate.kind not in GATE_KINDS:
            raise ValueError('Unknown gate kind')
        arity = len(gate.inputs)
        if (gate.kind in {'NOT', 'BUF'} and arity != 1) or (
            gate.kind not in {'NOT', 'BUF'} and not 2 <= arity <= MAX_INPUTS
        ):
            raise ValueError('Invalid gate arity')
        if any(driver not in available for driver in gate.inputs):
            raise ValueError('Missing, cyclic or forward gate driver')
        available.add(gate.id)
    if circuit.output not in available:
        raise ValueError('Unknown output driver')
    by_id = {gate.id: gate for gate in circuit.gates}
    reachable: set[str] = set()
    pending = [circuit.output]
    while pending:
        driver = pending.pop()
        if driver in reachable:
            continue
        reachable.add(driver)
        if driver in by_id:
            pending.extend(by_id[driver].inputs)
    if any(gate.id not in reachable for gate in circuit.gates):
        raise ValueError('Unreachable gate')


def _run(circuit: Circuit, assignment: Mapping[str, bool]) -> SignalRow:
    values = {port.id: assignment[port.name] for port in circuit.inputs}
    for gate in circuit.gates:
        args = [values[driver] for driver in gate.inputs]
        if gate.kind in {'AND', 'NAND'}:
            value = all(args)
        elif gate.kind in {'OR', 'NOR'}:
            value = any(args)
        elif gate.kind in {'XOR', 'XNOR'}:
            value = sum(args) % 2 == 1
        else:
            value = args[0]
        if gate.kind in {'NAND', 'NOR', 'XNOR', 'NOT'}:
            value = not value
        values[gate.id] = value
    return SignalRow(tuple(values[p.id] for p in circuit.inputs),
                     tuple(values[g.id] for g in circuit.gates), values[circuit.output])


def evaluate_circuit(circuit: Circuit, assignment: Mapping[str, bool]) -> SignalRow:
    """Evaluate actual drivers, never the source AST; require exact Boolean inputs."""
    validate_circuit(circuit)
    if set(assignment) != {port.name for port in circuit.inputs}:
        raise ValueError('Assignment must contain exactly the circuit input names')
    if any(type(value) is not bool for value in assignment.values()):
        raise ValueError('Input values must be Boolean')
    return _run(circuit, assignment)


def verify_circuit(circuit: Circuit, expression: Expr) -> VerifiedCircuit:
    """Independently compare the netlist with its source at every input vector."""
    _check_ast(expression)
    validate_circuit(circuit)
    names = [port.name for port in circuit.inputs]
    if variables_in_order(expression) != names:
        raise ValueError('Circuit input order/names differ from the source expression')
    rows = []
    for assignment in all_assignments(names):
        row = _run(circuit, assignment)
        if row.output != evaluate(expression, assignment):
            raise ValueError(f'Circuit/source mismatch at input vector {row.inputs}')
        rows.append(row)
    depths = {port.id: 0 for port in circuit.inputs}
    for gate in circuit.gates:
        depths[gate.id] = 1 + max(depths[driver] for driver in gate.inputs)
    return VerifiedCircuit(circuit, expression, tuple(rows), len(circuit.gates), depths[circuit.output])


def build_expression_circuit(source: str) -> VerifiedCircuit:
    """Compile D8 structure with shared identical subexpressions; no minimization."""
    ast = _parse_expression(source)
    names = variables_in_order(ast)
    if not 1 <= len(names) <= MAX_INPUTS:
        raise ValueError('Logic circuits support 1-8 inputs')
    inputs = tuple(Input(f'i{i}', name) for i, name in enumerate(names))
    drivers = {port.name: port.id for port in inputs}
    memo: dict[Expr, str] = {}
    gates: list[Gate] = []

    def compile_node(node: Expr) -> str:
        if isinstance(node, Var):
            return drivers[node.name]
        if node in memo:
            return memo[node]
        if isinstance(node, Not):
            child = node.operand
            if isinstance(child, (And, Or, Xor)):
                kind = {And: 'NAND', Or: 'NOR', Xor: 'XNOR'}[type(child)]
                children = child.operands
            else:
                kind, children = 'NOT', (child,)
        else:
            kind = {And: 'AND', Or: 'OR', Xor: 'XOR'}[type(node)]
            children = node.operands
        terminals = tuple(compile_node(child) for child in children)
        if len(gates) >= MAX_GATES:
            raise ValueError(f'Logic circuit exceeds {MAX_GATES} gates')
        gate = Gate(f'g{len(gates)}', kind, terminals)
        gates.append(gate)
        memo[node] = gate.id
        return gate.id

    output = compile_node(ast)
    return verify_circuit(Circuit(inputs, tuple(gates), output), ast)


def build_basic_gate(kind: str, names: tuple[str, ...]) -> VerifiedCircuit:
    """Build one named primitive. Names follow D8 and determine binary row order."""
    if kind not in GATE_KINDS:
        raise ValueError('Unknown gate kind')
    inputs = tuple(Input(f'i{i}', name) for i, name in enumerate(names))
    gate = Gate('g0', kind, tuple(port.id for port in inputs))
    circuit = Circuit(inputs, (gate,), gate.id)
    # Validate preset arity/names before constructing its source AST.
    validate_circuit(circuit)
    operands = tuple(Var(name) for name in names)
    if kind in {'BUF', 'NOT'}:
        ast = operands[0]
    else:
        ast = {'AND': And, 'NAND': And, 'OR': Or, 'NOR': Or,
               'XOR': Xor, 'XNOR': Xor}[kind](operands)
    if kind in {'NOT', 'NAND', 'NOR', 'XNOR'}:
        ast = Not(ast)
    return verify_circuit(circuit, ast)
