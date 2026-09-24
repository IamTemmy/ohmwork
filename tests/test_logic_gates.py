"""D21 primitive truth tables, topology and independent verification regressions."""
from dataclasses import replace
import itertools
import os
import random
import subprocess
import sys

import pytest

from ohmwork.expr import Var
from ohmwork.logic_gates import (
    Circuit, Gate, Input, build_basic_gate, build_expression_circuit,
    evaluate_circuit, validate_circuit, verify_circuit,
)
from ohmwork.parser import parse


@pytest.mark.parametrize('kind', ['AND', 'OR', 'NAND', 'NOR', 'XOR', 'XNOR'])
@pytest.mark.parametrize('arity', range(2, 9))
def test_every_primitive_truth_table(kind, arity):
    result = build_basic_gate(kind, tuple('abcdefgh'[:arity]))
    assert result.gate_count == result.depth == 1
    assert len(result.rows) == 2**arity
    for row, bits in zip(result.rows, itertools.product((False, True), repeat=arity)):
        ones = bits.count(True)
        expected = {'AND': ones == arity, 'NAND': ones != arity,
                    'OR': ones != 0, 'NOR': ones == 0,
                    'XOR': ones % 2 == 1, 'XNOR': ones % 2 == 0}[kind]
        assert row.inputs == bits
        assert row.output is expected and row.gates == (expected,)


@pytest.mark.parametrize('kind', ['NOT', 'BUF'])
def test_unary(kind):
    result = build_basic_gate(kind, ('x',))
    assert [r.output for r in result.rows] == ([True, False] if kind == 'NOT' else [False, True])


@pytest.mark.parametrize('source,kinds,depth', [
    ('ab+c', ['AND', 'OR'], 2),
    ("(abc+de)'", ['AND', 'AND', 'NOR'], 2),
    ("(ab)'", ['NAND'], 1),
    ("(a+b)'", ['NOR'], 1),
    ("(a^b^c)'", ['XNOR'], 1),
    ("a''", ['NOT', 'NOT'], 2),
    ('a', [], 0),
    ('a^b^c^d^e^f^g^h', ['XOR'], 1),
])
def test_expression_structure(source, kinds, depth):
    result = build_expression_circuit(source)
    assert [g.kind for g in result.circuit.gates] == kinds
    assert result.depth == depth and result.gate_count == len(kinds)
    for row in result.rows:
        assignment = dict(zip((p.name for p in result.circuit.inputs), row.inputs))
        assert evaluate_circuit(result.circuit, assignment) == row


def test_repeated_operands_and_shared_subexpressions():
    repeated = build_expression_circuit('a^a')
    assert repeated.circuit.gates[0].inputs == ('i0', 'i0')
    assert all(not row.output for row in repeated.rows)
    shared = build_expression_circuit('(a+b)^(a+b)')
    assert shared.gate_count == 2
    assert shared.circuit.gates[-1].inputs == ('g0', 'g0')
    assert all(not row.output for row in shared.rows)


def test_case_and_first_appearance():
    result = build_expression_circuit('z+A+a0+a')
    assert [(p.id, p.name) for p in result.circuit.inputs] == [
        ('i0', 'z'), ('i1', 'A'), ('i2', 'a0'), ('i3', 'a')]
    assert result.rows[1].inputs == (False, False, False, True)


@pytest.mark.parametrize('kind,names', [
    ('BAD', ('a', 'b')), ('AND', ('a',)), ('NOT', ('a', 'b')),
    ('BUF', ()), ('OR', tuple('abcdefghi')), ('AND', ('a', 'a')),
    ('AND', ('a', 'F')), ('AND', ('a', 'two')),
])
def test_invalid_presets(kind, names):
    with pytest.raises(ValueError):
        build_basic_gate(kind, names)


@pytest.mark.parametrize('source', ['a'*4097, '('*65+'a'+')'*65, 'a'+"'"*65,
                                  'a+b+c+d+e+f+g+h+i'])
def test_source_limits(source):
    with pytest.raises(ValueError):
        build_expression_circuit(source)


def test_limits_precede_exhaustive_work(monkeypatch):
    import ohmwork.logic_gates as module
    monkeypatch.setattr(module, 'all_assignments', lambda _: pytest.fail('enumeration ran'))
    with pytest.raises(ValueError, match='1-8 inputs'):
        build_expression_circuit('(a+b+c+d)+(e+f+g+h)i')
    monkeypatch.setattr(module, 'MAX_GATES', 1)
    with pytest.raises(ValueError, match='exceeds 1 gates'):
        build_expression_circuit('ab+c')


def test_real_gate_limit():
    rng = random.Random(21128)
    def tree(depth):
        if not depth:
            return rng.choice('abcdefgh')
        return '('+tree(depth-1)+rng.choice(['+', '^'])+tree(depth-1)+')'
    source = tree(8)
    assert len(source) < 4096
    with pytest.raises(ValueError, match='exceeds 128 gates'):
        build_expression_circuit(source)


@pytest.mark.parametrize('mutation', ['duplicate_input', 'duplicate_gate', 'missing_driver',
    'forward_driver', 'self_cycle', 'bad_kind', 'bad_arity', 'bad_output',
    'unreachable', 'mutable_terminals'])
def test_topology_mutations(mutation):
    circuit = build_expression_circuit('ab+c').circuit
    inputs, gates, output = circuit.inputs, list(circuit.gates), circuit.output
    if mutation == 'duplicate_input': inputs = (inputs[0], inputs[0], inputs[2])
    if mutation == 'duplicate_gate': gates[1] = replace(gates[1], id='g0')
    if mutation == 'missing_driver': gates[0] = replace(gates[0], inputs=('i0', 'missing'))
    if mutation == 'forward_driver': gates[0] = replace(gates[0], inputs=('i0', 'g1'))
    if mutation == 'self_cycle': gates[0] = replace(gates[0], inputs=('i0', 'g0'))
    if mutation == 'bad_kind': gates[0] = replace(gates[0], kind='FLIPFLOP')
    if mutation == 'bad_arity': gates[0] = replace(gates[0], inputs=())
    if mutation == 'bad_output': output = 'missing'
    if mutation == 'unreachable': output = 'g0'
    if mutation == 'mutable_terminals': gates[0] = replace(gates[0], inputs=['i0', 'i1'])
    with pytest.raises(ValueError):
        validate_circuit(Circuit(inputs, tuple(gates), output))


@pytest.mark.parametrize('mutation', ['kind', 'wire', 'output'])
def test_structurally_valid_wrong_function_rejected(mutation):
    result = build_expression_circuit('ab+c')
    circuit = result.circuit
    gates = list(circuit.gates)
    if mutation == 'kind': gates[0] = replace(gates[0], kind='OR')
    if mutation == 'wire': gates[1] = replace(gates[1], inputs=('g0', 'i0'))
    if mutation == 'output':
        circuit = replace(circuit, output='i0', gates=())
    else:
        circuit = replace(circuit, gates=tuple(gates))
    validate_circuit(circuit)
    with pytest.raises(ValueError, match='mismatch'):
        verify_circuit(circuit, result.expression)


@pytest.mark.parametrize('assignment', [{}, {'a': True, 'b': False}, {'a': 1}, {'a': '0'}])
def test_strict_assignments(assignment):
    with pytest.raises(ValueError):
        evaluate_circuit(build_expression_circuit('a').circuit, assignment)


def test_wrong_source_names():
    with pytest.raises(ValueError, match='input order/names'):
        verify_circuit(build_expression_circuit('a').circuit, Var('b'))


def test_determinism_across_processes():
    script = "from ohmwork.logic_gates import build_expression_circuit; print(build_expression_circuit('(a+b)^(a+b)'))"
    outputs = [subprocess.check_output([sys.executable, '-c', script],
               env={**os.environ, 'PYTHONHASHSEED': seed}, text=True) for seed in ('1', '29', '311')]
    assert len(set(outputs)) == 1
