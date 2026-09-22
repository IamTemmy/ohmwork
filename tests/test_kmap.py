"""D18 Phase 1: source fidelity, independent algebra, geometry, and mutations."""
from dataclasses import replace
from itertools import product
import os
import random
import subprocess
import sys

import pytest

from ohmwork.api import synthesize_from_input
from ohmwork.derivation import evaluate
from ohmwork.expr import Const, Not, Var, render
from ohmwork.kmap import (
    Rectangle, VariableFact, build_kmap, build_synthesis_kmap, validate_kmap,
)
from ohmwork.simplify import minimize, prime_implicant_patterns
from ohmwork.synth import synthesize


@pytest.mark.parametrize('n', [1,2,3,4])
def test_gray_grid_has_exact_external_mapping(n):
    variables = ['z','A0','b2','q'][:n]
    m=build_kmap(variables,{0})
    row_bits=n//2; col_bits=n-row_bits
    codes={0:[''],1:['0','1'],2:['00','01','11','10']}
    assert m.row_labels==tuple(codes[row_bits])
    assert m.column_labels==tuple(codes[col_bits])
    seen=set()
    for cell in m.cells:
        rb=codes[row_bits][cell.row]; cb=codes[col_bits][cell.column]
        expected=sum(int(bit)*2**(n-i-1) for i,bit in enumerate(rb+cb))
        assert cell.minterm==expected
        assert cell.value==('1' if expected==0 else '0')
        seen.add(expected)
    assert seen==set(range(2**n))
    for axis in (m.row_labels,m.column_labels):
        if len(axis)>1:
            for a,b in zip(axis,axis[1:]+axis[:1]):
                assert sum(x!=y for x,y in zip(a,b))==1


@pytest.mark.parametrize('ones,pattern,pieces,wrap', [
    ({0},'0000',((0,0,1,1),),(False,False)),
    ({0,1},'000-',((0,0,1,2),),(False,False)),
    ({0,1,4,5},'0-0-',((0,0,2,2),),(False,False)),
    (set(range(8)),'0---',((0,0,2,4),),(False,False)),
    ({0,2},'00-0',((0,0,1,1),(0,3,1,1)),(False,True)),
    ({0,8},'-000',((0,0,1,1),(3,0,1,1)),(True,False)),
    ({0,2,8,10},'-0-0',((0,0,1,1),(0,3,1,1),(3,0,1,1),(3,3,1,1)),(True,True)),
])
def test_group_shapes_and_wrap_pieces(ones,pattern,pieces,wrap):
    m=build_kmap(['a','b','c','d'],ones)
    assert len(m.groups)==1
    g=m.groups[0]
    assert g.pattern==pattern and set(g.minterms)==ones
    assert g.pieces==tuple(Rectangle(*p) for p in pieces)
    assert (g.wraps_rows,g.wraps_columns)==wrap
    assert g.essential and g.essential_witnesses==tuple(sorted(ones))


def test_overlap_is_two_groups_with_shared_cell():
    m=build_kmap(['a','b'],{1,2,3})
    assert {g.pattern for g in m.groups}=={'1-','-1'}
    overlap=next(c for c in m.cells if c.minterm==3)
    assert overlap.group_ids==('G1','G2')
    assert all(3 not in g.essential_witnesses for g in m.groups)


@pytest.mark.parametrize('form', ['SOP','POS'])
def test_dont_cares_keep_original_state_and_selected_assignment(form):
    # 1 is useful for extending required 0; 7 is isolated, so remains unused.
    target={0}; dc={1,7}; full=set(range(8))
    ones=target if form=='SOP' else full-target-dc
    m=build_kmap(['a','b','c'],ones,dc,form=form)
    assert m.groups[0].used_dont_cares==(1,)
    cells={c.minterm:c for c in m.cells}
    assert cells[1].value==cells[7].value=='X'
    assert cells[1].assigned_value==int(form=='SOP')
    assert cells[7].assigned_value==int(form=='POS')
    assert cells[1].group_ids and not cells[7].group_ids
    assert m.groups[0].facts==(VariableFact('a',0),VariableFact('b',0),VariableFact('c',None))
    assert render(m.expression)==("a'b'" if form=='SOP' else 'a + b')


@pytest.mark.parametrize('form,ones,dc,expected,groups', [
    ('SOP',set(),set(),False,0),('POS',set(),set(),False,1),
    ('SOP',{0,1,2,3},set(),True,1),('POS',{0,1,2,3},set(),True,0),
    ('SOP',set(),{0,1,2,3},False,0),('POS',set(),{0,1,2,3},True,0),
    ('SOP',{0},{1,2,3},True,1),('POS',set(),{1,2,3},False,1),
])
def test_constants(form,ones,dc,expected,groups):
    m=build_kmap(['a','b'],ones,dc,form=form)
    assert m.expression==Const(expected) and len(m.groups)==groups
    assert all(c.assigned_value==int(expected) for c in m.cells)


def test_tie_is_not_confused_with_selected_cover_essentiality():
    m=build_kmap(['a','b','c','d'],{7},{3,4,8,12,13,14,15})
    assert tuple(map(render,m.alternatives))==("a'cd",'bcd')
    assert m.selected_alternative==0
    assert not m.groups[0].essential  # only selected group, but NOT an essential prime


def test_synthesis_tie_preserves_inverter_aware_choice_without_reminimizing(monkeypatch):
    import ohmwork.kmap as km
    variables=['a','b','c','d']; dc={3,4,8,12,13,14,15}
    ones=set(range(16))-{7}-dc
    r=synthesize(variables,ones,dc)
    assert r.chosen.label=='AOI' and render(r.chosen.f_prime)=='bcd'
    standalone=build_kmap(variables,ones,dc,form='POS')
    assert render(standalone.grouped_expression)=="a'cd"
    def forbidden(*args,**kwargs):
        raise AssertionError('synthesis adapter must not select covers')
    monkeypatch.setattr(km,'minimal_covers',forbidden)
    monkeypatch.setattr(km,'minimize',forbidden)
    m=build_synthesis_kmap(r,'Y')
    assert m.output_name=='Y' and m.grouped_expression==r.chosen.f_prime
    assert m.groups[0].pattern=='-111'
    assert not m.alternatives and m.selected_alternative is None
    assert {c.minterm:bool(c.assigned_value) for c in m.cells if c.value=='X'}==r.verification.dont_care_assignments


@pytest.mark.parametrize('expr,label,form', [
    ("(abc)'",'AOI','POS'),("(a+b+c+d)'",'AOI','POS'),
    ("(abc+d)'",'AOI','POS'),("((a+b)(c+d))'",'OAI','SOP'),
    ('a','AOI','POS'),("a'",'AOI','POS'),('ab','AOI','POS'),
])
def test_exact_synthesis_reconstruction(expr,label,form):
    r=synthesize_from_input(expr=expr)
    m=build_synthesis_kmap(r)
    assert r.chosen.label==label and m.form==form
    assert m.synthesis_f_prime is r.chosen.f_prime
    for c in m.cells:
        row={v:bool(c.minterm & (1 << (len(m.var_order)-i-1))) for i,v in enumerate(m.var_order)}
        assert c.assigned_value==int(not evaluate(r.chosen.f_prime,row))


def test_source_sets_are_snapshot_copies_and_input_order_is_preserved():
    variables=['z','a']; ones={0}; dc={1}
    r=synthesize(variables,ones,dc)
    m=build_kmap(variables,ones,dc)
    variables.reverse(); ones.add(3); dc.clear()
    assert r.minterms==frozenset({0}) and r.dont_cares==frozenset({1})
    assert m.var_order==('z','a') and m.minterms==(0,) and m.dont_cares==(1,)
    renamed=build_kmap(['z','a'],{0},{1},output_name='Y9')
    assert replace(renamed,output_name='F')==m


@pytest.mark.parametrize('kwargs', [
    {'var_order':[]}, {'var_order':['a','b','c','d','e','g']}, {'var_order':['a','a']},
    {'var_order':['a','F']}, {'var_order':['abc']}, {'minterms':{-1}},
    {'minterms':{4}}, {'minterms':{True}}, {'minterms':{1.0}},
    {'minterms':{1},'dont_cares':{1}}, {'output_name':'a'}, {'output_name':'<x>'},
    {'form':'BAD'},
])
def test_bad_input_rejected(kwargs):
    args={'var_order':['a','b'],'minterms':{0}}; args.update(kwargs)
    with pytest.raises(ValueError): build_kmap(**args)


@pytest.mark.parametrize('mutation', [
    'members','diagonal','pattern','facts','explanation','term','essential','dc',
    'pieces','extra_piece','wrap','duplicate','missing','ids','axis','cell_index',
    'cell_value','assignment','links','expression','polarity','alternatives','selection',
])
def test_checker_rejects_mutations(mutation):
    m=build_kmap(['a','b'],{0,1,2})
    g=m.groups[0]
    changes={
        'members': {'minterms':(0,)}, 'diagonal':{'minterms':(0,3)},
        'pattern':{'pattern':'--'}, 'facts':{'facts':()},
        'explanation':{'explanation':'a disappears because it is constant'},
        'term':{'term':Var('a')}, 'essential':{'essential_witnesses':()},
        'dc':{'used_dont_cares':(0,)}, 'pieces':{'pieces':(Rectangle(0,0,2,2),)},
        'extra_piece':{'pieces':g.pieces+g.pieces}, 'wrap':{'wraps_rows':True},
        'ids':{'id':'G100'},
    }
    if mutation in changes:
        m=replace(m,groups=(replace(g,**changes[mutation]),)+m.groups[1:])
    elif mutation=='duplicate': m=replace(m,groups=m.groups+(g,))
    elif mutation=='missing': m=replace(m,groups=m.groups[:-1])
    elif mutation=='axis': m=replace(m,column_labels=('1','0'))
    elif mutation in ('cell_index','cell_value','assignment','links'):
        key,value={'cell_index':('minterm',3),'cell_value':('value','0'),
                   'assignment':('assigned_value',0),'links':('group_ids',())}[mutation]
        m=replace(m,cells=(replace(m.cells[0],**{key:value}),)+m.cells[1:])
    elif mutation=='expression': m=replace(m,expression=Not(m.expression))
    elif mutation=='polarity': m=replace(m,form='POS')
    elif mutation=='alternatives': m=replace(m,alternatives=(Const(False),))
    elif mutation=='selection': m=replace(m,selected_alternative=10)
    with pytest.raises(RuntimeError): validate_kmap(m)


def test_builders_gate_source_substitution_and_unverified_results(monkeypatch):
    import ohmwork.kmap as km
    good=build_kmap(['a','b'],{0})
    monkeypatch.setattr(km,'_assemble',lambda *a,**kw:replace(good,output_name='Y'))
    with pytest.raises(RuntimeError,match='source fidelity'):
        km.build_kmap(['a','b'],{0})
    r=synthesize_from_input(expr="(ab)'")
    with pytest.raises(ValueError,match='lacks original'):
        build_synthesis_kmap(replace(r,minterms=None))
    with pytest.raises(ValueError,match='unverified'):
        build_synthesis_kmap(replace(r,verification=replace(r.verification,functional_pass=False)))
    with pytest.raises(ValueError,match='provenance'):
        build_synthesis_kmap(replace(r,f_prime=Var('a')))


def test_prime_query_omits_dont_care_only_cubes():
    assert prime_implicant_patterns(['a','b','c'],{0},{1,7})==('00-',)


def test_all_small_functions_and_ternary_maps():
    # 2*(4+16+256) fully specified maps, plus all 1/2-variable ternary maps.
    for n in (1,2,3):
        variables=list('abc'[:n]); full=range(2**n)
        for mask in range(2**(2**n)):
            ones={m for m in full if mask & (1<<m)}
            for form in ('SOP','POS'):
                model=build_kmap(variables,ones,form=form)
                assert all(c.assigned_value==int(c.minterm in ones) for c in model.cells)
                target=ones if form=='SOP' else set(full)-ones
                assert model.grouped_expression==minimize(variables,target)
    for n in (1,2):
        for values in product('01X',repeat=2**n):
            ones={i for i,v in enumerate(values) if v=='1'}; dc={i for i,v in enumerate(values) if v=='X'}
            for form in ('SOP','POS'):
                build_kmap(list('ab'[:n]),ones,dc,form=form)


def test_seeded_four_variable_maps_and_synthesis_sources():
    rng=random.Random(180635)
    checked=0
    for _ in range(160):
        values=[rng.choice('000111X') for _ in range(16)]
        ones={i for i,v in enumerate(values) if v=='1'}; dc={i for i,v in enumerate(values) if v=='X'}
        for form in ('SOP','POS'): build_kmap(['d','c','b','a'],ones,dc,form=form)
        if not ones or len(ones|dc)==16 or not (set(range(16))-ones-dc):
            continue  # existing synthesis deliberately cannot build constant networks
        for dual in (False,True):
            r=synthesize(['d','c','b','a'],ones,dc,dual_rail=dual)
            build_synthesis_kmap(r,'Y9'); checked+=1
    assert checked>=300


def test_hash_seed_determinism():
    script="""
from dataclasses import asdict
import json
from ohmwork.kmap import build_kmap, build_synthesis_kmap
from ohmwork.synth import synthesize
v=['a','b','c','d']; dc={3,4,8,12,13,14,15}; ones=set(range(16))-{7}-dc
models=[build_kmap(v,ones,dc,form=f) for f in ('SOP','POS')]
models.append(build_synthesis_kmap(synthesize(v,ones,dc)))
print(json.dumps([asdict(m) for m in models],sort_keys=True))
"""
    outputs=[subprocess.check_output([sys.executable,'-c',script],env={**os.environ,'PYTHONHASHSEED':seed})
             for seed in ('0','1','982451653')]
    assert outputs[0]==outputs[1]==outputs[2]


def test_synthesis_dont_care_assignment_drift_is_rejected():
    r=synthesize(['a','b'],{0},{1})
    bad=replace(r.verification,dont_care_assignments={1:False})
    assert r.verification.dont_care_assignments=={1:True}
    with pytest.raises(RuntimeError,match='assignments differ'):
        build_synthesis_kmap(replace(r,verification=bad))


def test_hypercube_checker_rejects_fake_power_of_two_group():
    # Four occupied cells can form a disconnected diagonal pattern, not a cube.
    m=build_kmap(['a','b','c','d'],{0,3,12,15})
    assert len(m.groups)==4
    fake=replace(m.groups[0],minterms=(0,3,12,15),pattern='----')
    with pytest.raises(RuntimeError): validate_kmap(replace(m,groups=(fake,)))


@pytest.mark.parametrize('expr', ["(abc+d)'","((a+b)(c+d))'"])
def test_displayed_complement_reconstruction_is_runtime_gated(monkeypatch,expr):
    import ohmwork.kmap as km
    result=synthesize_from_input(expr=expr)
    model=build_synthesis_kmap(result)
    original=km.de_morgan_complement
    def broken_complement(expression):
        return Const(False) if expression==model.expression else original(expression)
    monkeypatch.setattr(km,'de_morgan_complement',broken_complement)
    with pytest.raises((ValueError,RuntimeError),match='reconstruct'):
        build_synthesis_kmap(result)
