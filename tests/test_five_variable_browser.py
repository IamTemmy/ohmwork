"""Live D20 two-plane layout, interaction, export and input-state gates."""
import json
from pathlib import Path
import pytest

pytest.importorskip('playwright.sync_api')
from test_webui_browser import page, server_url
from test_kmap_browser import submit


def check_planes(page, selector, width):
    page.wait_for_function("([s,layout])=>document.querySelector(s)?.dataset.planeLayout===layout",
                           arg=[selector,'side-by-side' if width==1280 else 'stacked'])
    data=page.locator(selector).evaluate('''svg=>{
      const cells=[...svg.querySelectorAll('[data-role=cells] > g')].map(g=>{
        const b=g.querySelector('rect').getBoundingClientRect();
        return {m:+g.dataset.minterm,p:+g.dataset.plane,x:b.x,y:b.y,w:b.width,h:b.height};
      });
      const groups=[...svg.querySelectorAll('.km-group')].map(g=>({id:g.dataset.groupId,
        members:[...g.querySelectorAll('rect')].flatMap(r=>{
          const b=r.getBoundingClientRect();
          return cells.filter(c=>c.x+c.w/2>b.x && c.x+c.w/2<b.right && c.y+c.h/2>b.y && c.y+c.h/2<b.bottom).map(c=>c.m);
        })}));
      const v=svg.viewBox.baseVal;
      const clipped=[...svg.querySelectorAll('text')].filter(t=>{
        const b=t.getBBox(), matrix=t.getCTM();
        const pts=[new DOMPoint(b.x,b.y),new DOMPoint(b.x+b.width,b.y+b.height)].map(p=>p.matrixTransform(matrix));
        return pts[0].x<-.5 || pts[0].y<-.5 || pts[1].x>v.width+.5 || pts[1].y>v.height+.5;
      }).map(t=>t.textContent);
      return {cells,groups,clipped,heads:[...svg.querySelectorAll('[data-plane-heading]')].map(t=>t.textContent),
        overflow:document.documentElement.scrollWidth>innerWidth+1};
    }''')
    assert not data['clipped'],data['clipped']
    assert not data['overflow']
    assert data['heads']==['a=0','a=1']
    assert sorted(c['m'] for c in data['cells'])==list(range(32))
    a,b=data['cells'][0],data['cells'][16]
    if width==1280: assert a['y']==b['y'] and a['x']<b['x']
    else: assert a['x']==b['x'] and a['y']<b['y']
    return data


@pytest.mark.parametrize('width',[1280,390])
@pytest.mark.parametrize('theme',['light','dark'])
@pytest.mark.parametrize('consumer',['standalone','synthesis'])
def test_professor_two_planes_interaction_and_export(page,server_url,width,theme,consumer,tmp_path):
    page.set_viewport_size({'width':width,'height':900});page.emulate_media(color_scheme=theme)
    if consumer=='standalone':
        submit(page,{'expr':"(abc+de)'",'form':'POS'})
        stage='#km-stage';cards='#km-groups';download='#km-download';endpoint='/api/kmap'
        response=page.request.post(server_url+endpoint,data={'expr':"(abc+de)'",'form':'POS'}).json()
        view=response['result']
    else:
        page.click('.tab[data-tab=synth]');page.fill('#synth-expr',"(abc+de)'")
        page.click('#panel-synth button[type=submit]')
        page.wait_for_selector('#synth-km-stage svg')
        stage='#synth-km-stage';cards='#synth-km-groups';download='#synth-km-download'
        response=page.request.post(server_url+'/api/synth',data={'expr':"(abc+de)'"}).json()
        view=response['kmap']['view']
        assert response['result'] and len(response['schematic']['devices'])==10
    selector=stage+' svg'
    data=check_planes(page,selector,width)
    assert {g['id']:sorted(g['members']) for g in data['groups']}=={g['id']:g['minterms'] for g in view['groups']}
    cross=next(g for g in view['groups'] if g['crosses_planes'])['id']
    button=page.locator(cards+f' .km-group-card[data-group-id="{cross}"]')
    button.hover()
    assert page.locator(selector).get_attribute('data-active-group')==cross
    button.focus();page.keyboard.press('Enter')
    selected=page.locator(selector+f' .km-group[data-group-id="{cross}"]')
    assert selected.get_attribute('data-selected')=='true'
    assert selected.locator('[data-plane="0"]').count()>0 and selected.locator('[data-plane="1"]').count()>0
    toggle=page.locator(cards+f' [data-proof-toggle="{cross}"]');toggle.click()
    page.locator(cards+' .km-proof-panel button').press('Escape')
    assert toggle.evaluate('(el)=>el===document.activeElement')
    assert toggle.get_attribute('aria-expanded')=='false'
    artifact=Path('test-artifacts/kmaps');artifact.mkdir(parents=True,exist_ok=True)
    page.screenshot(path=str(artifact/f'five-{consumer}-{width}-{theme}.png'),full_page=True)
    with page.expect_download() as download_info: page.click(download)
    path=tmp_path/'map.svg';download_info.value.save_as(path)
    xml=path.read_text();(artifact/f'five-{consumer}-{width}-{theme}.svg').write_text(xml)
    assert 'a=0' in xml and 'a=1' in xml and 'same position in the other map is adjacent' in xml
    assert 'data-selected="true"' not in xml
    # Re-render actual exported file without the app or any of its JavaScript.
    page.set_content(xml)
    exported=page.locator('svg')
    assert exported.locator('[data-role=cells] > g').count()==32
    assert exported.locator('[data-plane-heading]').all_text_contents()==['a=0','a=1']
    page.set_viewport_size({'width':1300,'height':900})
    exported.screenshot(path=str(artifact/f'five-export-{consumer}-{width}-{theme}.png'))


@pytest.mark.parametrize('expr', ['a^b^c^d^e', "b'd'e'"])
def test_dense_groups_and_cross_plane_wrap(page,expr):
    page.set_viewport_size({'width':390,'height':900})
    payload={'expr':expr} if '^' in expr else {'variables':'a,b,c,d,e','ones':'0,4,16,20'}
    submit(page,payload)
    data=check_planes(page,'#km-stage svg',390)
    if '^' in expr:
        assert len(data['groups'])==16
        page.locator('#km-groups [data-group-id="G9"]').hover()
        assert page.locator('#km-stage .km-group[data-group-id="G1"]').get_attribute('data-selected')=='false'
    else: assert sorted(data['groups'][0]['members'])==[0,4,16,20]


def test_five_variable_grids_and_stale_result(page):
    page.click('.tab[data-tab=kmap]');page.select_option('#km-mode','grid')
    page.fill('#km-vars','a,b,c,d,e')
    assert page.locator('#km-input-grid tbody tr').count()==32
    submit(page,{'variables':'a,b,c,d,e','ones':'16','dc':'0'})
    assert page.locator('#km-stage [data-minterm="0"]').get_attribute('data-value')=='X'
    page.fill('#km-ones','17')
    assert page.locator('#km-result').is_hidden() and page.locator('#km-stage svg').count()==0
    page.click('.tab[data-tab=synth]');page.check('input[name="synth-mode"][value="table"]')
    page.fill('#synth-vars','a,b,c,d,e')
    assert page.locator('#synth-grid-wrap tbody tr').count()==32
