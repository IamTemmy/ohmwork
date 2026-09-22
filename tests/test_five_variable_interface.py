"""D20 Phase 2: review fixes, public flow, exact model/presentation bridge."""
from collections import Counter
from dataclasses import replace
from itertools import product
import json
from unittest.mock import patch

import pytest

from ohmwork import kmap
from ohmwork.api import kmap_from_input, synthesize_from_input
from ohmwork.cli import main
from ohmwork.expr import render
from ohmwork.kmap_view import build_kmap_view, format_kmap_report
from ohmwork.search_budget import SearchBudget, SearchLimitExceeded
from test_kmap_interface import request

ONES={3,5,6,7,8,9,12,13,18,19,21,22,25,26,29,30}
DC={1,4,10,11,14,16,23,27,31}


def test_duplicate_cell_and_wrong_eliminated_variable_rejected():
    m=kmap.build_kmap(list('abcde'),{0,16})
    with pytest.raises(RuntimeError,match='cell mapping'):
        kmap.validate_kmap(replace(m,cells=(m.cells[0],m.cells[0])+m.cells[2:]))
    g=m.groups[0]
    facts=(replace(g.facts[0],fixed_value=0),replace(g.facts[1],fixed_value=None),*g.facts[2:])
    with pytest.raises(RuntimeError,match='facts'):
        kmap.validate_kmap(replace(m,groups=(replace(g,facts=facts),)))


def test_full_synthesis_tied_inventory_and_d5_order():
    from ohmwork.synth import synthesize
    r=synthesize(list('abcde'),ONES,DC)
    assert Counter((c.label,c.total_cost) for c in r.other_candidates)=={('AOI',36):4,('OAI',44):149}
    keys=[(c.total_cost,render(c.f_prime),c.label) for c in r.other_candidates]
    assert len(set(keys))==153 and keys==sorted(keys)
    cheapest=[c for c in r.other_candidates if c.total_cost==36]
    assert r.chosen==min(cheapest,key=lambda c:render(c.f_prime))


def test_two_independent_search_allowances_are_explicit():
    import ohmwork.search_budget as budgets
    seen=[]
    class Counted(SearchBudget):
        def __init__(self):
            super().__init__();seen.append(self)
    with patch.object(budgets,'SearchBudget',Counted), patch.object(kmap,'SearchBudget',Counted):
        r=synthesize_from_input(variables='a,b,c,d,e',ones=','.join(map(str,ONES)),dc=','.join(map(str,DC)))
        assert len(seen)==2  # AOI/OAI production directions
        kmap.build_synthesis_kmap(r)
        assert len(seen)==2  # circuit-map verification does not optimize again
        seen.clear()
        kmap.build_kmap(list('abcde'),ONES,DC)
        assert len(seen)==2  # production + independent oracle
        assert all(b.work <= 2_000_000 for b in seen)


def test_oracle_exhaustion_is_a_failed_verified_build_not_a_partial_answer():
    with patch.object(kmap,'_optimal_covers',side_effect=SearchLimitExceeded('oracle exhausted')):
        with pytest.raises(SearchLimitExceeded,match='oracle exhausted'):
            kmap.build_kmap(list('abcde'),{0,16})


@pytest.mark.parametrize('endpoint,patched', [('/api/kmap','kmap_from_input'),('/api/synth','synthesize_from_input')])
def test_search_exhaustion_has_explicit_http_kind_and_no_partial_result(endpoint,patched):
    with patch('ohmwork.webui.'+patched,side_effect=SearchLimitExceeded('test limit')):
        status,body=request({'expr':'abcde'},PATH_INFO=endpoint)
    result=json.loads(body)
    assert status=='200 OK' and result=={'ok':False,'error_kind':'search_limit','error':'Search limit: test limit'}


@pytest.mark.parametrize('command,patched', [('kmap','kmap_from_input'),('synth','render_synth')])
def test_search_limit_cli_exit_is_distinct(command,patched,capsys):
    with patch('ohmwork.cli.'+patched,side_effect=SearchLimitExceeded('test limit')):
        assert main([command,'--expr','abcde'])==2
    streams=capsys.readouterr()
    assert streams.out=='' and streams.err=='search limit: test limit\n'


@pytest.mark.parametrize('form',['SOP','POS'])
def test_all_cubes_have_exact_rendered_plane_coverage(form):
    for bits in product('01-',repeat=5):
        members={i for i in range(32) if all(b=='-' or int(b)==((i>>(4-j))&1) for j,b in enumerate(bits))}
        m=kmap.build_kmap(list('abcde'),members if form=='SOP' else set(range(32))-members,form=form)
        v=build_kmap_view(m)
        g,=v['groups']
        drawn=[c['minterm'] for p in g['pieces'] for c in v['cells']
               if p['x']<c['cx']<p['x']+p['width'] and p['y']<c['cy']<p['y']+p['height']]
        assert set(drawn)==members and len(drawn)==len(members)
        assert all(p['width']>0 and p['height']>0 for p in g['pieces'])
        assert g['crosses_planes']==(bits[0]=='-')


@pytest.mark.parametrize('payload',[
    {'expr':"(abc+de)'"},
    {'variables':'a,b,c,d,e','ones':'16','dc':'0'},
    {'variables':'a,b,c,d,e','table':'X'+'0'*15+'1'+'0'*15},
])
def test_public_synthesis_and_standalone_modes(payload):
    for endpoint in ('/api/kmap','/api/synth'):
        body=json.loads(request(payload,PATH_INFO=endpoint)[1]);assert body['ok']
        v=body['result'] if endpoint=='/api/kmap' else body['kmap']['view']
        assert len(v['cells'])==32 and v['plane_labels']==['0','1']


def test_cli_two_planes_and_spice_download(capsys):
    assert main(['kmap','--expr',"(abc+de)'"])==0
    text=capsys.readouterr().out
    assert 'Plane a=0' in text and 'Plane a=1' in text and '32 input combinations' in text
    assert main(['synth','--expr',"(abc+de)'",'--netlist','example'])==0
    netlist=capsys.readouterr().out
    assert '.subckt' in netlist and len([l for l in netlist.splitlines() if l.startswith('m')])==10
