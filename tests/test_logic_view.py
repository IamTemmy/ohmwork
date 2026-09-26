"""Exact terminal inventory, geometric endpoints and export snapshot checks."""
from collections import Counter
from dataclasses import replace
import xml.etree.ElementTree as ET
import pytest
from ohmwork.logic_gates import build_basic_gate, build_expression_circuit
from ohmwork.logic_view import build_logic_view, render_logic_svg

CASES=["xy'+x'y+xy+x'y'","a'b+a'c+d'e","(a'+b)(a'+c)","xy'+x'y","(a+b')(c'+d)","ab+ac","ab+ab'",'a','ab+c',"(abc+de)'",'a^a','(a+b)^(a+b)',"a''",'a+(b(c+d))','(ab+cd)(ef+gh)']

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
        aliases = [(p['x'],p['y']) for p in v.get('input_appearances',[])+v.get('signal_appearances',[]) if p['id']==route['driver']]
        assert pts[0] in (aliases or [outputs[route['driver']]])
        assert pts[-1]==(v['output_point'] if route['gate']=='F' else gates[route['gate']]['pins'][route['terminal']])
        for x,y in pts: assert 0<=x<=v['width'] and 0<=y<=v['height']
        for (x,y),(xx,yy) in zip(pts,pts[1:]):
            assert x==xx or y==yy
            for g in v['gates']:
                # No wire traverses a symbol's interior bounding rectangle.
                assert not (y==yy and g['y']<y<g['y']+g['height'] and max(x,xx)>g['x'] and min(x,xx)<g['x']+95*g.get('scale_x',1))
                assert not (x==xx and g['x']<x<g['x']+95*g.get('scale_x',1) and max(y,yy)>g['y'] and min(y,yy)<g['y']+g['height'])
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


def test_branch_labels_preserve_all_signals_without_duplicating_gates():
    result=build_expression_circuit("xy'+x'y");v=build_logic_view(result)
    assert v['layout']=='branches'
    assert len(v['inputs'])==2 and len(v['input_appearances'])==4
    assert len(v['gates'])==5
    assert [g['expression'] for g in v['gates']]==["y'","xy'","x'","x'y","xy' + x'y"]
    assert v['table_gates']==['g0','g1','g2','g3']
    for i,row in enumerate(result.rows):
        root=ET.fromstring(render_logic_svg(v,i))
        for p,value in zip(result.circuit.inputs,row.inputs):
            texts=root.findall(f"{{*}}text[@data-signal='{p.id}']")
            assert len(texts)==2
            assert all(t.text==str(int(value)) for t in texts)
        for g,value in zip(result.circuit.gates,row.gates):
            assert root.find(f"{{*}}text[@data-signal='{g.id}']").text==str(int(value))
    # Every input/literal-to-branch path is straight and horizontal.
    assert all(len(r['points'])==2 and r['points'][0][1]==r['points'][1][1]
               for r in v['routes'] if r['gate'] not in {result.circuit.output,'F'})


def test_shared_inverter_retains_one_symbol_with_labeled_connections():
    v=build_logic_view(build_expression_circuit("a'b+a'c"))
    assert v.get('layout')=='branches'
    assert len(v['shared_sources'])==1
    assert len(v['signal_appearances'])==2
    assert sum(g['kind']=='NOT' for g in v['gates'])==1


def test_single_gate_table_only_needs_final_output():
    v=build_logic_view(build_basic_gate('AND',tuple('abc')))
    assert v['table_gates']==[]
    from ohmwork.logic_view import format_logic_report
    assert format_logic_report(v).splitlines()[-9]=='a b c F'


def doubling_chain(count=128):
    """Valid shared graph whose textual expansion would contain 2**count terms."""
    from ohmwork.logic_gates import Circuit, Gate, Input, verify_circuit
    from ohmwork.expr import Var
    gates=tuple(Gate(f'g{i}','AND',('i0','i0') if i==0 else (f'g{i-1}',f'g{i-1}')) for i in range(count))
    return verify_circuit(Circuit((Input('i0','g0'),),gates,gates[-1].id),Var('g0'))


def test_fallback_references_have_delimiters_and_explicit_and_through_128_gates():
    from ohmwork.logic_view import format_logic_report
    v=build_logic_view(doubling_chain())
    for g in v['gates'][6:]:
        previous=int(g['id'][1:])-1
        assert g['expression']==f'[g{previous}] · [g{previous}]'
        assert len(g['expression'])<80
    assert v['gates'][-1]['expression']=='[g126] · [g126]'
    report=format_logic_report(v)
    assert '[g12] = [g11] · [g11]' in report
    assert '[g0]: AND(g0, g0)' in report


def test_input_named_like_gate_is_visually_distinct_everywhere():
    from ohmwork.logic_view import format_logic_report
    v=build_logic_view(build_expression_circuit("g0(a+b)(c+d)(e+f)+g0'"))
    assert 'g0' in [p['name'] for p in v['inputs']]
    assert v['gates'][0]['display_id']=='[g0]'
    assert v['gates'][3]['expression']=='g0(a + b)(c + d)(e + f)'
    svg=ET.fromstring(render_logic_svg(v))
    assert any(t.text=='g0' for t in svg.findall('{*}text[@data-input-name]'))
    assert svg.find('{*}g[@data-gate-id="g0"]/{*}text').text=='[g0] · OR'
    assert '[g3]: AND(g0, [g0], [g1], [g2])' in format_logic_report(v)


def test_four_products_keep_seven_gates_and_all_alias_values():
    r=build_expression_circuit("xy'+x'y+xy+x'y'");v=build_logic_view(r)
    assert r.gate_count==7 and len(v['gates'])==7
    assert len(v['shared_sources'])==2 and len(v['signal_appearances'])==4
    products=[g for g in v['gates'] if g['kind']=='AND']
    assert len(products)==4 and len({g['x'] for g in products})==1
    for i,row in enumerate(r.rows):
        assert row.output
        svg=ET.fromstring(render_logic_svg(v,i))
        for g,value in zip(r.circuit.gates,row.gates):
            signals=svg.findall(f"{{*}}text[@data-signal='{g.id}']")
            assert signals and all(t.text==str(int(value)) for t in signals)
            assert len(svg.findall(f"{{*}}g[@data-gate-id='{g.id}']"))==1
        for alias in v['signal_appearances']:
            text=svg.find(f"{{*}}text[@data-signal-alias][@data-driver='{alias['id']}']")
            assert text.text.startswith(f"[{alias['id']}]")


def test_shared_product_is_not_cloned_or_treated_as_an_input_inverter():
    v=build_logic_view(build_expression_circuit('(ab+c)(ab+d)'))
    assert v.get('layout')!='branches'
    assert len(v['gates'])==4
