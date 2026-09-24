"""Exact terminal inventory, geometric endpoints and export snapshot checks."""
from collections import Counter
from dataclasses import replace
import xml.etree.ElementTree as ET
import pytest
from ohmwork.logic_gates import build_basic_gate, build_expression_circuit
from ohmwork.logic_view import build_logic_view, render_logic_svg

CASES=['a','ab+c',"(abc+de)'",'a^a','(a+b)^(a+b)',"a''",'a+(b(c+d))','(ab+cd)(ef+gh)']

@pytest.mark.parametrize('source',CASES)
def test_exact_model_geometry_svg_bridge(source):
    result=build_expression_circuit(source);v=build_logic_view(result)
    assert [g['id'] for g in v['gates']]==[g.id for g in result.circuit.gates]
    expected=Counter((d,g.id,i) for g in result.circuit.gates for i,d in enumerate(g.inputs))
    expected[(result.circuit.output,'F',0)]+=1
    assert Counter((r['driver'],r['gate'],r['terminal']) for r in v['routes'])==expected
    outputs={p['id']:(p['x'],p['y']) for p in v['inputs']}
    outputs.update({g['id']:g['out'] for g in v['gates']})
    gates={g['id']:g for g in v['gates']}
    for route in v['routes']:
        pts=route['points']
        assert pts[0]==outputs[route['driver']]
        assert pts[-1]==(v['output_point'] if route['gate']=='F' else gates[route['gate']]['pins'][route['terminal']])
        for x,y in pts: assert 0<=x<=v['width'] and 0<=y<=v['height']
        for (x,y),(xx,yy) in zip(pts,pts[1:]):
            assert x==xx or y==yy
            for g in v['gates']:
                # No wire traverses a symbol's interior bounding rectangle.
                assert not (y==yy and g['y']<y<g['y']+g['height'] and max(x,xx)>g['x'] and min(x,xx)<g['x']+95)
                assert not (x==xx and g['x']<x<g['x']+95 and max(y,yy)>g['y'] and min(y,yy)<g['y']+g['height'])
    svg=ET.fromstring(render_logic_svg(v,len(v['rows'])-1))
    routes=svg.findall('{*}polyline')
    assert Counter((r.get('data-driver'),r.get('data-gate'),int(r.get('data-terminal'))) for r in routes)==expected
    assert [(g.get('data-gate-id'),g.get('data-kind')) for g in svg.findall('{*}g')]==[(g['id'],g['kind']) for g in v['gates']]
    values={**dict(zip([p.id for p in result.circuit.inputs],result.rows[-1].inputs)),**dict(zip([g.id for g in result.circuit.gates],result.rows[-1].gates))}
    assert all(int(r.get('data-value'))==values[r.get('data-driver')] for r in routes)

@pytest.mark.parametrize('kind',['AND','OR','NOT','NAND','NOR','XOR','XNOR','BUF'])
def test_all_symbols_and_terminal_counts(kind):
    r=build_basic_gate(kind,('a',) if kind in {'NOT','BUF'} else tuple('abcdefgh'))
    root=ET.fromstring(render_logic_svg(build_logic_view(r)))
    g=root.find('{*}g')
    assert len([p for p in g.findall('{*}path') if p.get('data-pin') is not None])==len(r.circuit.inputs)
    assert len(g.findall('{*}circle'))==int(kind in {'NOT','NAND','NOR','XNOR'})


def test_altered_verified_rows_rejected():
    r=build_expression_circuit('ab')
    with pytest.raises(ValueError,match='altered'):
        build_logic_view(replace(r,rows=r.rows[:-1]))


def test_names_are_not_cli_flavored():
    with pytest.raises(ValueError,match='Input names contain duplicate'):
        build_basic_gate('AND',('a','a'))


def test_depth_columns_preserve_internal_row_identity_for_every_vector():
    result=build_expression_circuit('(ab+cd)(ef+gh)');view=build_logic_view(result)
    for i,row in enumerate(result.rows):
        root=ET.fromstring(render_logic_svg(view,i))
        shown={n.get('data-signal'):int(n.text) for n in root.findall('{*}text') if n.get('data-signal')}
        assert all(shown[g.id]==int(value) for g,value in zip(result.circuit.gates,row.gates))
