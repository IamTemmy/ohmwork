"""D20 internal capability: no five-variable public renderer enabled yet."""
from dataclasses import asdict, replace
from itertools import product
import json
import os
import random
import subprocess
import sys

import pytest

from ohmwork import api
from ohmwork.expr import render
from ohmwork.kmap import (_build_kmap, _build_synthesis_kmap, _legal_primes,
                          _optimal_covers, build_kmap, build_synthesis_kmap, validate_kmap)
from ohmwork.kmap_steps import group_work
from ohmwork.schematic import build_schematic, build_textbook_schematic
from ohmwork.search_budget import SearchBudget, SearchLimitExceeded
from ohmwork.simplify import _minimal_extra_cover, minimal_covers
from ohmwork.spice_exports import build_spice_exports
from ohmwork.synth import _synthesize, synthesize

VARS = list('abcde')
FULL = set(range(32))


def result_for(expr, **kwargs):
    return _synthesize(*api.resolve_truth_table(expr=expr), **kwargs)


def test_professor_case():
    r = result_for("(abc+de)'")
    assert (r.chosen_label, r.pdn_transistors, r.pun_transistors,
            r.inverter_transistors, r.total_transistors) == ('AOI', 5, 5, 0, 10)
    assert (r.pdn_stack_height, r.pun_stack_height) == (3, 2)
    assert 'fewer than 10' in r.minimality_proof
    expected = {16*a+8*b+4*c+2*d+e for a,b,c,d,e in product((0,1), repeat=5)
                if not (a*b*c or d*e)}
    assert r.minterms == expected and r.verification.passed
    m = _build_synthesis_kmap(r)
    assert m.form == 'POS' and render(m.grouped_expression) == 'abc + de'
    assert {g.pattern: g.crosses_planes for g in m.groups} == {'111--':False, '---11':True}
    for g in m.groups:
        group_work(m, g)  # independently evaluates every proof step on all 32 rows


@pytest.mark.parametrize('pattern', [''.join(p) for p in product('01-', repeat=5)])
def test_every_five_bit_cube(pattern):
    # Independent bit-product oracle, not production _members/Gray helpers.
    members = {sum(b << (4-i) for i,b in enumerate(bits))
               for bits in product(*[(0,1) if c == '-' else (int(c),) for c in pattern])}
    m = _build_kmap(VARS, members)
    g, = m.groups
    assert g.pattern == pattern and set(g.minterms) == members
    assert g.crosses_planes == (pattern[0] == '-')
    assert m.plane_variable == 'a' and m.plane_labels == ('0','1')
    codes = (0,1,3,2)
    for cell in m.cells:
        assert cell.minterm == 16*cell.plane + 4*codes[cell.row] + codes[cell.column]
    covered = [16*p.plane + 4*codes[row] + codes[col] for p in g.pieces
               for row in range(p.row,p.row+p.rows) for col in range(p.column,p.column+p.columns)]
    assert len(covered) == len(set(covered)) and set(covered) == members
    group_work(m, g)


@pytest.mark.parametrize('form', ['SOP','POS'])
def test_asymmetric_dont_care_across_planes(form):
    m = _build_kmap(VARS, {16} if form == 'SOP' else FULL-{0,16}, {0}, form=form)
    g, = m.groups
    assert g.pattern == '-0000' and g.used_dont_cares == (0,) and g.crosses_planes
    assert {c.minterm:c.value for c in m.cells if c.minterm in (0,16)} == {0:'X',16:str(m.grouping_value)}
    group_work(m, g)
    forbidden = _build_kmap(VARS, {16} if form == 'SOP' else FULL-{16}, form=form)
    assert forbidden.groups[0].pattern == '10000'
    assert not forbidden.groups[0].crosses_planes


@pytest.mark.parametrize('ones,dc', [(set(),set()), (FULL,set()), (set(),FULL)])
@pytest.mark.parametrize('form', ['SOP','POS'])
def test_constants_and_all_x(ones, dc, form):
    m = _build_kmap(VARS, ones, dc, form=form)
    assert len(m.cells) == 32
    for g in m.groups:
        group_work(m,g)


@pytest.mark.parametrize('mutation', [
    lambda m: replace(m, plane_variable='b'),
    lambda m: replace(m, plane_labels=('1','0')),
    lambda m: replace(m, cells=(replace(m.cells[0],plane=1),)+m.cells[1:]),
    lambda m: replace(m, cells=m.cells[:-1]),
    lambda m: replace(m, groups=(replace(m.groups[0],pieces=m.groups[0].pieces[:-1]),)),
    lambda m: replace(m, groups=(replace(m.groups[0],pieces=(replace(m.groups[0].pieces[0],plane=2),)+m.groups[0].pieces[1:]),)),
    lambda m: replace(m, groups=(replace(m.groups[0],minterms=(0,1,2,16)),)),
    lambda m: replace(m, groups=(replace(m.groups[0],wraps_columns=False),)),
])
def test_plane_mutations_rejected(mutation):
    m = _build_kmap(VARS, {0,2,16,18})
    with pytest.raises(RuntimeError): validate_kmap(mutation(m))


@pytest.mark.parametrize('expr', ["(abcde)'", "(a+b+c+d+e)'", "((a+b)(c+d)e)'",
                                  "a'b+c'd+e", "((ab+c)(d+e))'", 'a^b^c^d^e'])
@pytest.mark.parametrize('dual', [False,True])
def test_circuits_and_export_identity(expr, dual):
    r = result_for(expr, dual_rail=dual)
    assert r.verification.passed
    assert r.inverter_transistors == (0 if dual else 2*len(set(r.inverter_literals)))
    _build_synthesis_kmap(r, 'Y')
    wired, textbook = build_schematic(r,'Y'), build_textbook_schematic(r,'Y')
    assert len(wired.devices) == len(textbook.devices) == r.total_transistors
    assert build_spice_exports(wired) == build_spice_exports(textbook)


def test_stack_constraints_and_unused_case_sensitive_variables():
    with pytest.raises(ValueError, match='no AOI/OAI candidate'):
        result_for("(abc+de)'", max_stack=1)
    assert result_for("(abc+de)'", max_stack=3).total_transistors == 10
    v = ['a','A','a0','z','q']
    r = _synthesize(v, set(range(16,32)), dual_rail=True)
    m = _build_synthesis_kmap(r)
    assert m.var_order == tuple(v) and m.plane_variable == 'a'
    assert len(m.cells)==32 and r.total_transistors == 2
    build_spice_exports(build_textbook_schematic(r,'Y'))


def test_seeded_tied_inventory_and_circuit_assignments():
    rng = random.Random(20260922)
    tied = 0
    for _ in range(32):
        vals = [rng.choice('0011X') for _ in range(32)]
        ones = {i for i,v in enumerate(vals) if v=='1'}
        dc = {i for i,v in enumerate(vals) if v=='X'}
        for form in ('SOP','POS'):
            m = _build_kmap(VARS,ones,dc,form=form)
            tied += len(m.alternatives)>1
        for dual in (False,True):
            r = _synthesize(VARS,ones,dc,dual_rail=dual)
            m = _build_synthesis_kmap(r)
            assert {c.minterm:bool(c.assigned_value) for c in m.cells if c.value=='X'} == r.verification.dont_care_assignments
    assert tied > 0


def test_search_work_and_storage_exhaustion_never_returns_partial_covers():
    ones={0,1,2,5,6,7,8,9,10,14,17,19,21,23,25,27,28,30}
    primes = _legal_primes(5,ones,set())
    for budget in (SearchBudget(max_work=0), SearchBudget(max_items=0)):
        with pytest.raises(SearchLimitExceeded, match='no partial result'):
            _minimal_extra_cover(set(primes),ones,5,_budget=budget)
    for budget in (SearchBudget(max_work=0), SearchBudget(max_items=0)):
        with pytest.raises(SearchLimitExceeded, match='no partial result'):
            _optimal_covers(primes,ones,_budget=budget)


def test_search_failure_propagates_to_builders(monkeypatch):
    def fail(*args, **kwargs):
        raise SearchLimitExceeded('test exhaustion: no partial result')
    monkeypatch.setattr(SearchBudget,'check',fail)
    ones={0,1,2,5,6,7,8,9,10,14,17,19,21,23,25,27,28,30}
    with pytest.raises(SearchLimitExceeded): _build_kmap(VARS,ones)
    with pytest.raises(SearchLimitExceeded): _synthesize(VARS,ones)


@pytest.mark.parametrize('expr', ['abcde','abcdef'])
def test_public_boundary_rejects_before_truth_enumeration(expr, monkeypatch):
    def forbidden(*a, **kw): raise AssertionError('enumerated unsupported truth table')
    monkeypatch.setattr(api,'all_assignments',forbidden)
    for call in (api.synthesize_from_input, api.kmap_from_input):
        with pytest.raises(ValueError,match='supports'): call(expr=expr)
    with pytest.raises(ValueError): synthesize(list(expr), {0})
    with pytest.raises(ValueError): build_kmap(list(expr),{0})
    with pytest.raises(ValueError): build_synthesis_kmap(result_for_private())


def result_for_private():
    return _synthesize(VARS, {0})


def test_six_variables_rejected_in_internal_builders():
    with pytest.raises(ValueError): _synthesize(list('abcdef'),{0})
    with pytest.raises(ValueError): _build_kmap(list('abcdef'),{0})


def test_hash_seed_determinism_including_plane_metadata():
    script = '''
import json
from dataclasses import asdict
from ohmwork.kmap import _build_kmap
m = _build_kmap(list('abcde'),{0,1,2,5,6,7,8,9,10,14,17,19,21,23,25,27,28,30})
print(json.dumps(asdict(m), sort_keys=True))
'''
    outputs = [subprocess.check_output([sys.executable,'-c',script],env={**os.environ,'PYTHONHASHSEED':s})
               for s in ('0','1','982451653')]
    assert outputs[0] == outputs[1] == outputs[2]


def test_presentation_cannot_silently_flatten_two_planes():
    from ohmwork.kmap_view import build_kmap_view, format_kmap_report
    m = _build_kmap(VARS,{0,16})
    for call in (build_kmap_view, format_kmap_report):
        with pytest.raises(ValueError, match='Phase 2'): call(m)


def test_dense_dont_care_regression_preserves_all_149_ties():
    # This measured fixture exhausted the first naive Petrick work budget.
    # The independent oracle verifies the full family, not just the winner.
    ones={3,5,6,7,8,9,12,13,18,19,21,22,25,26,29,30}
    dc={1,4,10,11,14,16,23,27,31}
    m=_build_kmap(VARS,ones,dc)
    assert len(m.alternatives)==149
    assert len(_build_kmap(VARS,ones,dc,form='POS').alternatives)==4
