"""D21 API/CLI/HTTP coherence and rejection before returning partial diagrams."""
import json
import xml.etree.ElementTree as ET
from unittest.mock import patch
import pytest
from ohmwork.api import logic_from_input
from ohmwork.cli import main
from ohmwork.logic_view import build_logic_view
from test_kmap_interface import request

@pytest.mark.parametrize('payload',[{'expr':"(abc+de)'"},{'kind':'XNOR','variables':'a,b,c'}, {'expr':'a^a'}, {'expr':'a'}, {'expr':'A+a0'}])
def test_api_and_http_match(payload):
    expected=build_logic_view(logic_from_input(**payload))
    status,body=request(payload,PATH_INFO='/api/logic')
    response=json.loads(body)
    assert status=='200 OK' and response['ok']
    assert response['result']==json.loads(json.dumps(expected))
    ET.fromstring(response['svg'])
    assert f"{expected['gate_count']} logic gates" in response['output']

@pytest.mark.parametrize('payload',[[],{}, {'expr':4},{'expr':'a','kind':'BUF'}, {'kind':'AND','variables':'a,a'}, {'kind':'NOT','variables':'a,b'}, {'kind':'AND','variables':''}, {'expr':'a','unknown':'x'}])
def test_bad_http_input_has_no_result(payload):
    response=json.loads(request(payload,PATH_INFO='/api/logic')[1])
    assert not response['ok'] and set(response)=={'ok','error'}
    assert '--vars' not in response['error']


def test_logic_cli(capsys):
    assert main(['logic','--gate','XOR','--vars','a,b,c'])==0
    assert '8 input vectors' in capsys.readouterr().out
    assert main(['logic','--expr',"(abc+de)'",'--svg'])==0
    ET.fromstring(capsys.readouterr().out)
    assert main(['logic','--expr','a','--vars','a'])==1
    assert 'not both' in capsys.readouterr().err


def test_failed_verification_has_no_svg():
    with patch('ohmwork.webui.logic_from_input',side_effect=ValueError('Circuit/source mismatch')):
        response=json.loads(request({'expr':'ab'},PATH_INFO='/api/logic')[1])
    assert response=={'ok':False,'error':'Circuit/source mismatch'}


def test_logic_endpoint_uses_existing_origin_guard():
    status,_=request({'expr':'ab'},PATH_INFO='/api/logic',HTTP_ORIGIN='https://evil.example')
    assert status.startswith('403')
