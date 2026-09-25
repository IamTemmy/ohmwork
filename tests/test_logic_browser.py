"""D21 browser acceptance: interaction, exact signals, export and stale requests."""
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest
pytest.importorskip('playwright.sync_api')
from test_webui_browser import page, server_url


def build(page,expr=None,kind='AND',names='a,b'):
    page.click('.tab[data-tab=logic]')
    if expr is not None:
        page.select_option('#lg-mode','expr');page.fill('#lg-expr',expr)
    else:
        page.select_option('#lg-mode','basic');page.select_option('#lg-kind',kind);page.fill('#lg-vars',names)
    page.click('#lg-build');page.wait_for_selector('#lg-stage svg')


@pytest.mark.parametrize('width',[1280,390])
@pytest.mark.parametrize('theme',['light','dark'])
def test_logic_live_keyboard_layout_export(page,server_url,width,theme,tmp_path):
    page.set_viewport_size({'width':width,'height':900});page.emulate_media(color_scheme=theme)
    build(page,"(abc+de)'")
    assert page.locator('#lg-table tbody tr').count()==32
    toggle=page.locator('#lg-inputs button').first
    toggle.focus();toggle.press('Space')
    assert toggle.get_attribute('aria-pressed')=='true'
    assert page.locator('#lg-table tbody tr[aria-current=true]').inner_text().split()[:5]==['1','0','0','0','0']
    gate=page.locator('#lg-stage [data-gate-id=g0]');gate.focus();gate.press('Enter')
    assert gate.get_attribute('aria-expanded')=='true'
    assert 'Input 1 (a) = 1' in page.locator('#lg-detail-values').inner_text()
    page.locator('#lg-close').press('Escape')
    assert gate.evaluate('n=>n===document.activeElement')
    assert page.locator('#lg-detail').is_hidden()
    page.locator('#lg-gate-buttons button').last.click()
    page.locator('#lg-close').click()
    assert page.locator('#lg-gate-buttons button').last.evaluate('n=>n===document.activeElement')
    data=page.locator('#lg-stage svg').evaluate('''svg=>({
      clipped:[...svg.querySelectorAll('text')].filter(t=>{
        const b=t.getBBox(),m=t.getCTM(),a=new DOMPoint(b.x,b.y).matrixTransform(m),z=new DOMPoint(b.x+b.width,b.y+b.height).matrixTransform(m);
        return a.x<0||a.y<0||z.x>svg.viewBox.baseVal.width+1||z.y>svg.viewBox.baseVal.height+1;
      }).map(t=>t.textContent),overflow:document.documentElement.scrollWidth>innerWidth+1})''')
    assert data=={'clipped':[],'overflow':False}
    assert page.locator('#lg-stage svg').evaluate("""svg=>{
      const boxes=[...svg.querySelectorAll('text')].map(t=>{
        const b=t.getBBox(),m=t.getCTM(),a=new DOMPoint(b.x,b.y).matrixTransform(m),z=new DOMPoint(b.x+b.width,b.y+b.height).matrixTransform(m);
        return {x:a.x,y:a.y,r:z.x,b:z.y};
      });
      return boxes.every((a,i)=>boxes.slice(i+1).every(b=>Math.min(a.r,b.r)-Math.max(a.x,b.x)<.5 || Math.min(a.b,b.b)-Math.max(a.y,b.y)<.5));
    }""")

    assert page.locator('#lg-table td').first.evaluate('n=>n.getBoundingClientRect().width')>=40
    if width==390:
        assert page.locator('#lg-stage').evaluate('n=>n.scrollWidth>n.clientWidth')
        assert page.locator('.lg-table-scroll').evaluate('n=>n.scrollWidth>n.clientWidth')
    with page.expect_download() as download: page.click('#lg-download')
    path=tmp_path/'snapshot.svg';download.value.save_as(path)
    svg=ET.parse(path).getroot()
    assert len(svg.findall('{*}g'))==3
    assert 'a=1' in svg.find('{*}desc').text
    assert not any(n.get('tabindex') for n in svg.iter())
    assert svg.find('{*}polyline').get('data-value')=='1'
    # Open the file itself, without page JavaScript or styles.
    page.goto(path.as_uri());page.wait_for_selector('svg')
    artifact=Path('test-artifacts/logic');artifact.mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(artifact/f'standalone-{width}-{theme}.png'))
    page.goto(server_url);build(page,"(abc+de)'")
    page.screenshot(path=str(artifact/f'professor-{width}-{theme}.png'),full_page=True)


@pytest.mark.parametrize('kind',['AND','OR','NOT','NAND','NOR','XOR','XNOR','BUF'])
def test_basic_gate_controls_every_vector(page,server_url,kind):
    names='a' if kind in {'NOT','BUF'} else 'a,b,c'
    build(page,kind=kind,names=names)
    rows=page.request.post(server_url+'/api/logic',data={'kind':kind,'variables':names}).json()['result']['rows']
    for index,row in enumerate(rows):
        page.evaluate('''inputs=>{document.querySelectorAll('#lg-inputs button').forEach((b,i)=>{if((b.getAttribute('aria-pressed')==='true')!==inputs[i])b.click();});}''',row['inputs'])
        assert page.locator('#lg-stage [data-output-value]').text_content()==str(int(row['output']))
        assert page.locator('#lg-stage [data-signal=g0]').text_content()==str(int(row['gates'][0]))
        assert page.locator('#lg-table tbody tr[aria-current=true]').count()==1
        assert page.locator('#lg-table tbody tr').nth(index).get_attribute('aria-current')=='true'


def test_eight_inputs_all_256_rows_and_repeated_connections(page,server_url):
    build(page,kind='XNOR',names='a,b,c,d,e,f,g,h')
    result=page.evaluate('''()=>{
      const buttons=[...document.querySelectorAll('#lg-inputs button')];let checked=0;
      for(let i=0;i<256;i++){
        buttons.forEach((b,j)=>{const on=!!(i&(1<<(7-j)));if((b.getAttribute('aria-pressed')==='true')!==on)b.click();});
        const actual=Number(document.querySelector('#lg-stage [data-output-value]').textContent);
        const ones=i.toString(2).replaceAll('0','').length;
        if(actual!==Number(ones%2===0))throw Error('wrong vector '+i);checked++;
      }return checked;
    }''')
    assert result==256
    build(page,'(a+b)^(a+b)')
    assert page.locator('#lg-stage [data-gate-id]').count()==2
    assert page.locator('#lg-stage .lg-wire[data-driver=g0][data-gate=g1]').count()==2
    page.locator('#lg-inputs button').first.click()
    assert page.locator('#lg-stage [data-signal=g0]').text_content()=='1'
    assert page.locator('#lg-stage [data-output-value]').text_content()=='0'
    build(page,'a')
    assert page.locator('#lg-stage [data-gate-id]').count()==0
    page.locator('#lg-inputs button').click()
    assert page.locator('#lg-stage [data-output-value]').text_content()=='1'


def test_edits_reset_errors_and_delayed_response(page):
    build(page,'ab+c')
    page.fill('#lg-expr','ab')
    assert page.locator('#lg-result').is_hidden() and page.locator('#lg-download').is_disabled()
    page.click('#lg-build');page.wait_for_selector('#lg-stage svg')
    page.click('#lg-new')
    assert page.locator('#lg-result').is_hidden() and page.locator('#lg-copy').is_disabled()
    page.select_option('#lg-mode','basic');page.fill('#lg-vars','a,a');page.click('#lg-build')
    page.wait_for_function("document.querySelector('#lg-error').textContent.includes('duplicate')")
    assert '--vars' not in page.locator('#lg-error').inner_text()
    assert page.locator('#lg-result').is_hidden()
    def delayed(route):
        response=route.fetch()
        page.evaluate("document.querySelector('#lg-new').click()")
        route.fulfill(response=response)
    page.route('**/api/logic',delayed)
    page.fill('#lg-vars','a,b');page.click('#lg-build')
    page.wait_for_timeout(250)
    assert page.locator('#lg-result').is_hidden()
    assert page.locator('#lg-stage svg').count()==0


def test_multilevel_signal_identity_matches_verified_rows(page,server_url):
    source='(ab+cd)(ef+gh)';build(page,source)
    rows=page.request.post(server_url+'/api/logic',data={'expr':source}).json()['result']['rows']
    page.evaluate('''rows=>{
      const buttons=[...document.querySelectorAll('#lg-inputs button')];
      for(const row of rows){
        buttons.forEach((b,i)=>{if((b.getAttribute('aria-pressed')==='true')!==row.inputs[i])b.click();});
        row.gates.forEach((value,i)=>{if(Number(document.querySelector('[data-signal=g'+i+']').textContent)!==Number(value))throw Error('wrong internal signal g'+i);});
        const current=document.querySelector('#lg-table tbody tr[aria-current=true]');
        if(current.textContent!==[...row.inputs,...row.gates.slice(0,-1),row.output].map(Number).join(''))throw Error('wrong table row');
      }
    }''',rows)


@pytest.mark.parametrize('width',[1280,390])
@pytest.mark.parametrize('theme',['light','dark'])
def test_branch_layout_aliases_and_descriptive_table(page,server_url,width,theme,tmp_path):
    page.set_viewport_size({'width':width,'height':900});page.emulate_media(color_scheme=theme)
    build(page,"xy'+x'y")
    assert page.locator('#lg-table th').all_text_contents()==['x','y',"[g0]: y'","[g1]: xy'","[g2]: x'","[g3]: x'y",'F']
    assert page.locator('#lg-stage [data-input-name]').all_text_contents()==['x','y','x','y']
    rows=page.request.post(server_url+'/api/logic',data={'expr':"xy'+x'y"}).json()['result']['rows']
    for row in rows:
        page.evaluate("""row=>{
          document.querySelectorAll('#lg-inputs button').forEach((b,i)=>{if((b.getAttribute('aria-pressed')==='true')!==row.inputs[i])b.click();});
          row.inputs.forEach((v,i)=>document.querySelectorAll('[data-signal=i'+i+']').forEach(n=>{if(Number(n.textContent)!==Number(v))throw Error('wrong alias');}));
          row.gates.forEach((v,i)=>{if(Number(document.querySelector('[data-signal=g'+i+']').textContent)!==Number(v))throw Error('wrong gate');});
        }""",row)
        assert page.locator('#lg-table tbody tr[aria-current=true]').inner_text().split()==[str(int(v)) for v in (*row['inputs'],*row['gates'][:-1],row['output'])]
    assert page.locator('#lg-stage svg').evaluate("""svg=>{
      const boxes=[...svg.querySelectorAll('text')].map(t=>{
        const b=t.getBBox(),m=t.getCTM(),a=new DOMPoint(b.x,b.y).matrixTransform(m),z=new DOMPoint(b.x+b.width,b.y+b.height).matrixTransform(m);
        return {x:a.x,y:a.y,r:z.x,b:z.y};
      });
      return boxes.every((a,i)=>a.x>=0&&a.y>=0&&a.r<=svg.viewBox.baseVal.width&&a.b<=svg.viewBox.baseVal.height&&boxes.slice(i+1).every(b=>Math.min(a.r,b.r)-Math.max(a.x,b.x)<.5 || Math.min(a.b,b.b)-Math.max(a.y,b.y)<.5));
    }""")
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    artifact=Path('test-artifacts/logic');artifact.mkdir(parents=True,exist_ok=True)
    page.locator('#lg-stage svg').screenshot(path=str(artifact/f'branches-{width}-{theme}.png'))
    with page.expect_download() as download: page.click('#lg-download')
    path=tmp_path/'branches.svg';download.value.save_as(path)
    svg=ET.parse(path).getroot()
    assert len(svg.findall("{*}text[@data-input-name]"))==4
    assert len(svg.findall("{*}g[@data-gate-id]"))==5
    build(page,kind='AND',names='a,b,c')
    assert page.locator('#lg-table th').all_text_contents()==['a','b','c','F']
    assert '1 gate ·' in page.locator('#lg-meta').inner_text()


def test_input_gate_name_collision_in_live_table_diagram_and_inspector(page):
    build(page,"g0(a+b)(c+d)(e+f)+g0'")
    headers=page.locator('#lg-table th').all_text_contents()
    assert 'g0' in headers and '[g0]: a + b' in headers
    assert '[g3]: g0(a + b)(c + d)(e + f)' in headers
    assert page.locator('#lg-stage [data-gate-id=g0] text').text_content()=='[g0] · OR'
    page.locator('#lg-gate-buttons button[data-id=g3]').click()
    detail=page.locator('#lg-detail-values').inner_text()
    assert 'Input 1 (g0)' in detail and 'Input 2 ([g0])' in detail
    assert 'Output [g3]' in detail


def test_double_digit_fallback_labels_in_browser(page):
    # Inject a server-verified graph response: the expression compiler flattens
    # associative AND, so use the supported Circuit model to exercise this DAG.
    from test_logic_view import doubling_chain
    from ohmwork.logic_view import build_logic_view,render_logic_svg,format_logic_report
    view=build_logic_view(doubling_chain(20))
    page.route('**/api/logic',lambda route:route.fulfill(json={
        'ok':True,'result':view,'svg':render_logic_svg(view),'output':format_logic_report(view)}))
    build(page,'g0')
    headers=page.locator('#lg-table th').all_text_contents()
    assert 'g0' in headers and '[g12]: [g11] · [g11]' in headers
    page.locator('#lg-inputs button').click()
    assert set(page.locator('#lg-table tbody tr[aria-current=true] td').all_text_contents())=={'1'}
    assert page.locator('#lg-stage [data-signal=g19]').text_content()=='1'
