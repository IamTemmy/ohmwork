"""Standalone Phase 2: API, CLI, and concrete display geometry."""
import io
import json
from unittest.mock import patch

import pytest

from ohmwork.api import kmap_from_input
from ohmwork.cli import main
from ohmwork.kmap import build_kmap
from ohmwork.kmap_view import build_kmap_view, format_kmap_report
from ohmwork.webui import app, _PAGE


def request(payload, **overrides):
    raw=json.dumps(payload).encode()
    env={'REQUEST_METHOD':'POST','PATH_INFO':'/api/kmap','SERVER_PORT':'8888',
         'HTTP_HOST':'127.0.0.1:8888','CONTENT_TYPE':'application/json',
         'CONTENT_LENGTH':str(len(raw)),'wsgi.input':io.BytesIO(raw),**overrides}
    statuses=[]
    body=b''.join(app(env,lambda status,headers:statuses.append(status)))
    return statuses[0],body


def test_api_builds_once_and_has_both_presentations():
    import ohmwork.webui as web
    with patch.object(web,'kmap_from_input',wraps=web.kmap_from_input) as build:
        status,body=request({'variables':'a,b,c,d','ones':'0,2,8,10'})
    result=json.loads(body)
    assert status=='200 OK' and result['ok'] and build.call_count==1
    assert result['result']['groups'][0]['pattern']=='-0-0'
    assert "F = b'd'" in result['output']


@pytest.mark.parametrize('payload', [
    {'variables':'a,b','ones':''}, {'variables':'a,b','table':'XXXX','form':'POS'},
    {'expr':"(ab)'",'form':'POS'}, {'expr':'A0+b1','output_name':'Y9'},
])
def test_api_valid_input_modes(payload):
    assert json.loads(request(payload)[1])['ok']


@pytest.mark.parametrize('payload', [[],{'expr':12},{'expr':'abcdeg'},
    {'variables':'a,b','ones':'0','dc':'0'},{'expr':'ab','output_name':'a'},
    {'expr':'ab','form':'wrong'}])
def test_bad_requests_have_no_result(payload):
    result=json.loads(request(payload)[1])
    assert not result['ok'] and set(result)=={'ok','error'}


def test_verification_failure_never_leaks_partial_response():
    with patch('ohmwork.webui.kmap_from_input',side_effect=RuntimeError('verification failed')):
        result=json.loads(request({'expr':'ab'})[1])
    assert result=={'ok':False,'error':'verification failed'}


@pytest.mark.parametrize('headers,status', [
    ({'HTTP_ORIGIN':'https://evil.example'},'403'),
    ({'HTTP_HOST':'evil.example:8888'},'403'),
    ({'CONTENT_TYPE':'text/plain'},'415'),({'CONTENT_LENGTH':'999999'},'413'),
])
def test_kmap_uses_existing_transport_guards(headers,status):
    assert request({'expr':'ab'},**headers)[0].startswith(status)


def test_variable_cap_precedes_assignment_enumeration():
    with patch('ohmwork.api.all_assignments',side_effect=AssertionError('must cap first')):
        with pytest.raises(ValueError,match='1-5'): kmap_from_input(expr='abcdeg')


@pytest.mark.parametrize('form',['sop','pos'])
def test_cli_uses_same_verified_report(form,capsys):
    args=['kmap','--vars','a,b,c,d','--ones','0,2,8,10','--form',form,'--output-name','Y']
    assert main(args)==0
    out=capsys.readouterr()
    expected=format_kmap_report(kmap_from_input(variables='a,b,c,d',ones='0,2,8,10',form=form.upper(),output_name='Y'))
    assert out.out==expected+'\n' and not out.err


def test_cli_failure_is_nonzero(capsys):
    assert main(['kmap','--expr','abcdeg'])==1
    assert '1-5' in capsys.readouterr().err


def test_all_display_rectangles_cover_exactly_their_declared_cell_centres():
    # Include dense overlapping maps as well as opposite-edge corners.
    for mask in range(256):
        model=build_kmap(['a','b','c'],{i for i in range(8) if mask>>i&1})
        view=build_kmap_view(model)
        for g in view['groups']:
            hit=[]
            for p in g['pieces']:
                hit.extend(c['minterm'] for c in view['cells']
                           if p['x']<c['cx']<p['x']+p['width'] and p['y']<c['cy']<p['y']+p['height'])
            assert sorted(hit)==list(g['minterms'])
    view=build_kmap_view(build_kmap(list('abcd'),{0,2,8,10}))
    assert len(view['groups'][0]['pieces'])==4


def test_embedded_assets_are_in_one_script_and_safe_dom_only():
    assert _PAGE.count('<script>')==1 and _PAGE.count('</script>')==1
    from ohmwork.kmap_ui import JS
    assert 'innerHTML' not in JS
