"""Worked reductions must describe the group, not merely its final answer."""
from dataclasses import replace
from itertools import product
import pytest
from ohmwork.kmap import build_kmap
from ohmwork.kmap_steps import group_work
from ohmwork.kmap_view import build_kmap_view, format_kmap_report
from ohmwork.expr import Var


@pytest.mark.parametrize('form', ['SOP', 'POS'])
def test_every_cube_one_to_four_variables(form):
    for n in range(1,5):
        variables=tuple('abcd'[:n]); universe=set(range(2**n))
        for pattern in product('01-', repeat=n):
            cells={m for m in universe if all(p=='-' or p==b for p,b in zip(pattern,format(m,f'0{n}b')))}
            model=build_kmap(variables,cells if form=='SOP' else universe-cells,form=form)
            assert len(model.groups)==1
            work=group_work(model,model.groups[0])
            assert len(work['steps'])==1+3*pattern.count('-')
            assert work['steps'][-1]['expression']==work['result']
            assert ('m' if form=='SOP' else 'M')+str(min(cells)) in work['notation']


def test_actual_three_variable_example_and_named_laws():
    model=build_kmap(('a','b','c'),range(4))
    work=group_work(model,model.groups[0])
    assert work['notation']=='m0 + m1 + m2 + m3'
    assert work['steps'][0]['expression']=="(a' · b' · c') + (a' · b' · c) + (a' · b · c') + (a' · b · c)"
    assert [s['law'] for s in work['steps']]==['Expansion','Distributive','Complement','Identity','Distributive','Complement','Identity']
    assert work['result']=="a'"
    report=format_kmap_report(model)
    assert work['notation'] in report
    assert all(s['expression'] in report and s['reason'] in report for s in work['steps'])


@pytest.mark.parametrize('form', ['SOP','POS'])
def test_dont_cares_explicit_and_not_claimed_as_original_values(form):
    model=build_kmap(('a','b'),{0} if form=='SOP' else {2,3}, {1},form=form)
    work=group_work(model,model.groups[0])
    assert '[X]' in work['notation'] and 'original' in work['note']
    assert f'included as {model.grouping_value}' in work['note']
    assert next(c for c in model.cells if c.minterm==1).value=='X'


def test_rejects_wrong_term_and_incomplete_cube():
    model=build_kmap(('a','b','c'),range(4));group=model.groups[0]
    with pytest.raises(ValueError,match='selected group term'):
        group_work(model,replace(group,term=Var('a')))
    with pytest.raises(ValueError,match='complete Boolean cube'):
        group_work(model,replace(group,minterms=(0,1,2)))


def test_long_variable_labels_and_full_map_have_wrapped_export_lines():
    model=build_kmap(('A0','B1','C2','D3'),range(16))
    view=build_kmap_view(model)
    assert view['groups'][0]['work']['result']=='1'
    assert view['footer_y']>view['groups'][0]['legend_y']+22*len(view['groups'][0]['legend_lines'])
    assert view['laws']


def test_four_variable_pair_keeps_each_minterm_parenthesized_in_all_views():
    model=build_kmap(('a','b','c','d'),{0,2})
    expected="(a' · b' · c' · d') + (a' · b' · c · d')"
    work=group_work(model,model.groups[0])
    assert work['notation']=='m0 + m2'
    assert work['steps'][0]['expression']==expected
    assert expected in format_kmap_report(model)
    assert build_kmap_view(model)['groups'][0]['work']['steps'][0]['expression']==expected
