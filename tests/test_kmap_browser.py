"""Real D18 UI: actual SVG geometry, input races, interactions, and exports."""
import json
from pathlib import Path
import pytest

pytest.importorskip('playwright.sync_api')
from test_webui_browser import page, server_url


def submit(page, payload):
    page.click('.tab[data-tab=kmap]')
    page.select_option('#km-form',payload.get('form','SOP'))
    page.fill('#km-output-name',payload.get('output_name','F'))
    if 'expr' in payload:
        page.select_option('#km-mode','expr'); page.fill('#km-expr',payload['expr'])
    else:
        page.select_option('#km-mode','minterms')
        page.fill('#km-vars',payload['variables']); page.fill('#km-ones',payload['ones'])
        page.fill('#km-dc',payload.get('dc',''))
    page.click('#km-run');page.wait_for_selector('#km-result:not([hidden])')


def snapshot(page):
    return page.locator('svg.km-svg').evaluate('''svg=>({
      box:[svg.viewBox.baseVal.x,svg.viewBox.baseVal.y,svg.viewBox.baseVal.width,svg.viewBox.baseVal.height],
      cells:[...svg.querySelectorAll('[data-role=cells] > g')].map(g=>{
        const r=g.querySelector('rect');return {m:+g.dataset.minterm,value:g.dataset.value,
          assigned:+g.dataset.assignedValue,x:+r.getAttribute('x'),y:+r.getAttribute('y'),
          w:+r.getAttribute('width'),h:+r.getAttribute('height')};}),
      groups:[...svg.querySelectorAll('.km-group')].map(g=>({id:g.dataset.groupId,
        pieces:[...g.querySelectorAll('rect')].map(r=>({x:+r.getAttribute('x'),y:+r.getAttribute('y'),
          w:+r.getAttribute('width'),h:+r.getAttribute('height'),index:+r.dataset.pieceIndex,
          dash:r.getAttribute('stroke-dasharray')}))})),
      values:[...svg.querySelectorAll('[data-cell-text]')].map(t=>({m:+t.dataset.cellText,text:t.textContent})),
      memberships:[...svg.querySelectorAll('[data-membership]')].map(t=>({m:+t.dataset.memberCell,id:t.dataset.membership,text:t.textContent})),
      legends:[...svg.querySelectorAll('[data-legend-id]')].map(g=>({id:g.dataset.legendId,text:g.textContent})),
      pieceCount:svg.querySelectorAll('.km-piece').length,
      badgeCount:svg.querySelectorAll('.km-badge').length,
      badBadges:[...svg.querySelectorAll('.km-badge')].filter(r=>{
        const index=r.hasAttribute('data-index-badge'), cellId=index?r.dataset.indexBadge:r.dataset.badgeCell;
        const c=svg.querySelector(`[data-role=cells] [data-minterm="${cellId}"] rect`);
        if(!c || (!index && !r.dataset.groupBadge)) return true;
        const b=r.getBBox(), box=c.getBBox();
        const value=svg.querySelector(`[data-cell-text="${cellId}"]`).getBBox();
        const touchesValue=b.x<value.x+value.width && b.x+b.width>value.x && b.y<value.y+value.height && b.y+b.height>value.y;
        return b.width>(index?29:22) || b.height>(index?17:15) || b.x<box.x || b.y<box.y || b.x+b.width>box.x+box.width || b.y+b.height>box.y+box.height || touchesValue;
      }).length,
      unclassified:[...svg.querySelectorAll('rect')].filter(r=>!r.matches('.km-piece,.km-grid-cell,.km-badge')).length,
      clipped:[...svg.querySelectorAll('text')].filter(t=>{const b=t.getBBox(),v=svg.viewBox.baseVal;
        return b.x<v.x || b.y<v.y || b.x+b.width>v.x+v.width || b.y+b.height>v.y+v.height;}).map(t=>t.textContent),
      color:getComputedStyle(svg).color,
      cellFill:getComputedStyle(svg.querySelector('.km-grid-cell')).fill,
      pieceStroke:svg.querySelector('.km-piece')?getComputedStyle(svg.querySelector('.km-piece')).stroke:null
    })''')


def bridge(s,view):
    assert s['box']==[0,0,view['width'],view['height']]
    assert not s['clipped'] and s['unclassified']==0 and s['badBadges']==0
    assert s['pieceCount']==sum(len(g['pieces']) for g in view['groups'])
    assert s['badgeCount']==len(view['cells'])+sum(len(c['group_ids']) for c in view['cells'])
    assert len(s['cells'])==len(view['cells']) and len(s['groups'])==len(view['groups'])
    assert {c['m'] for c in s['cells']}=={c['minterm'] for c in view['cells']}
    for a,b in zip(s['cells'],view['cells']):
        assert (a['m'],a['value'],a['assigned'],a['x'],a['y'],a['w'],a['h'])==(b['minterm'],b['value'],b['assigned_value'],b['x'],b['y'],view['grid']['cell'],view['grid']['cell'])
    assert s['values']==[{'m':c['minterm'],'text':c['value']} for c in view['cells']]
    assert s['memberships']==[{'m':c['minterm'],'id':g,'text':g} for c in view['cells'] for g in c['group_ids']]
    assert [g['id'] for g in s['groups']]==[g['id'] for g in view['groups']]
    for a,b in zip(s['groups'],view['groups']):
        assert len(a['pieces'])==len(b['pieces'])
        actual=[]
        for i,(rect,p) in enumerate(zip(a['pieces'],b['pieces'])):
            assert rect=={'x':p['x'],'y':p['y'],'w':p['width'],'h':p['height'],'index':i,'dash':b['dash']}
            # Check actual geometric enclosure, not data-group-id alone.
            actual.extend(c['m'] for c in s['cells'] if rect['x']<c['x']+c['w']/2<rect['x']+rect['w']
                          and rect['y']<c['y']+c['h']/2<rect['y']+rect['h'])
        assert sorted(actual)==b['minterms']
    assert [g['id'] for g in s['legends']]==[g['id'] for g in view['groups']]
    for a,b in zip(s['legends'],view['groups']):
        assert a['text'].startswith(b['id']+' · '+b['term'])


CASES=[
    ('corners',{'variables':'a,b,c,d','ones':'0,2,8,10'}),
    ('horizontal-wrap',{'variables':'a,b,c,d','ones':'0,2'}),
    ('vertical-wrap',{'variables':'a,b,c,d','ones':'0,8'}),
    ('overlap',{'expr':'a+b'}),
    ('six-overlaps',{'variables':'a,b,c,d','ones':'0,1,2,3,4,5,6,8,9,10,12'}),
    ('pos',{'expr':"(abc+d)'",'form':'POS'}),
    ('one-variable',{'expr':'a'}),
    ('all-zero',{'variables':'a,b','ones':''}),
    ('all-one',{'variables':'a,b','ones':'0,1,2,3'}),
    ('all-x',{'variables':'a,b','ones':'','dc':'0,1,2,3','form':'POS'}),
    ('used-unused-x',{'variables':'a,b,c','ones':'0','dc':'1,7'}),
    ('long-labels',{'expr':"A0'B1'C2'D3 + A0'B1'C2D3' + A0'B1C2'D3' + A0B1'C2'D3'",'output_name':'Y9'}),
    ('tied',{'variables':'a,b,c,d','ones':'7','dc':'3,4,8,12,13,14,15'}),
]


@pytest.mark.parametrize('name,payload',CASES)
def test_kmap_visual_bridge_and_export(page,server_url,tmp_path,name,payload):
    submit(page,payload)
    view=page.request.post(server_url+'/api/kmap',data=payload).json()['result']
    bridge(snapshot(page),view)
    folder=Path('test-artifacts/kmaps');folder.mkdir(parents=True,exist_ok=True)
    page.locator('svg.km-svg').screenshot(path=str(folder/(name+'.png')))
    if name in ('corners','six-overlaps'):
        page.screenshot(path=str(folder/(name+'-page.png')),full_page=True)
    if name=='six-overlaps':
        page.locator('.km-group-card').nth(4).click()
        page.locator('svg.km-svg').screenshot(path=str(folder/'six-overlaps-selected.png'))
        page.click('#km-show-all')
    before=page.locator('svg.km-svg').evaluate('svg=>new XMLSerializer().serializeToString(svg)')
    with page.expect_download() as info: page.click('#km-download')
    path=tmp_path/'map.svg';info.value.save_as(path)
    assert path.read_text()==before
    (folder/(name+'.svg')).write_text(before)
    page.goto(path.as_uri())
    bridge(snapshot(page),view)
    assert snapshot(page)['pieceStroke'] != 'none'


def test_linked_hover_keyboard_and_overlap_memberships(page):
    submit(page,{'expr':'a+b'})
    assert positions()==before
    for group in ['G2','G3']:
        toggle=page.locator(f'[data-proof-toggle={group}]')
        toggle.focus();toggle.press('Enter')
        assert positions()==before
        assert page.locator('.km-proof-panel:not([hidden])').count()==1
        assert page.locator('[data-proof-toggle][aria-expanded=true]').count()==1
        assert page.locator('.km-proof-panel').get_attribute('data-proof-group')==group
        assert group in page.locator('.km-proof-panel h3').inner_text()
    page.locator('.km-proof-panel button').focus()
    page.locator('.km-proof-panel button').press('Escape')
    assert page.locator('[data-proof-toggle=G3]').evaluate('el=>el===document.activeElement')
    assert page.locator('.km-proof-panel').is_hidden()
    assert positions()==before
    page.locator('.km-group-card').nth(1).hover()
    assert page.locator('svg.km-svg').get_attribute('data-active-group')=='G2'
    assert page.locator('.km-group-card').nth(1).get_attribute('aria-pressed')=='true'
    group=page.locator('svg .km-group').first
    group.focus();group.press('Enter')
    assert page.locator('svg.km-svg').get_attribute('data-active-group')=='G1'
    assert 'G1' in page.locator('#km-selection').inner_text()
    group.press('Escape')
    assert page.locator('svg.km-svg').get_attribute('data-active-group')==''
    assert page.locator('[data-member-cell="3"]').count()==2


def test_grid_cycles_via_keyboard_and_submits_binary_order(page):
    page.click('.tab[data-tab=kmap]');page.select_option('#km-mode','grid');page.fill('#km-vars','a,b')
    cells=page.locator('#km-input-grid button')
    cells.nth(0).focus();cells.nth(0).press('Space');cells.nth(1).click();cells.nth(1).click()
    assert cells.nth(0).inner_text()=='1' and cells.nth(1).inner_text()=='X'
    page.click('#km-run');page.wait_for_selector('#km-result:not([hidden])')
    assert page.locator('#km-equation').inner_text()=="F = a'"
    assert 'm1 → 1 (grouped)' in page.locator('#km-assignments').inner_text()
    cells.nth(0).click()
    assert page.locator('svg.km-svg').count()==0


def test_edit_new_problem_and_tab_isolation(page):
    submit(page,{'expr':'a+b'})
    page.click('.tab[data-tab=tt]')
    assert not page.locator('svg.km-svg').is_visible()
    page.click('.tab[data-tab=kmap]');assert page.locator('svg.km-svg').is_visible()
    page.fill('#km-output-name','Y')
    assert page.locator('svg.km-svg').count()==0 and page.locator('#km-equation').inner_text()==''
    submit(page,{'expr':'a+b','form':'POS'})
    requests=[];page.on('request',lambda r:requests.append(r.url))
    page.click('#km-new')
    assert not any('/api/' in url for url in requests)
    assert page.input_value('#km-form')=='POS' and page.input_value('#km-expr')==''
    assert page.locator('#km-expr').evaluate('el=>document.activeElement===el')
    assert page.locator('svg.km-svg').count()==0


def test_pending_response_discarded_on_edit_and_new_problem(page):
    page.click('.tab[data-tab=kmap]')
    page.evaluate('''()=>{window.pending=[]; window.fetch=()=>new Promise(resolve=>window.pending.push(resolve));}''')
    page.fill('#km-expr','a');page.click('#km-run')
    page.fill('#km-expr','b');page.click('#km-new')
    page.evaluate('''()=>window.pending[0]({json:async()=>({ok:false,error:'stale failure'})})''')
    page.wait_for_timeout(100)
    assert page.locator('#km-error').inner_text()=='' and page.locator('svg.km-svg').count()==0
    assert not page.locator('#km-run').is_disabled()


def test_bits_mode_errors_and_recovery(page):
    page.click('.tab[data-tab=kmap]');page.select_option('#km-mode','bits');page.fill('#km-vars','a,b')
    page.fill('#km-bits','100');page.click('#km-run')
    page.wait_for_function("document.querySelector('#km-error').textContent.length>0")
    assert page.locator('svg.km-svg').count()==0
    page.fill('#km-bits','1000');page.click('#km-run');page.wait_for_selector('#km-result:not([hidden])')
    assert page.locator('#km-error').inner_text()==''


def test_mobile_dark_mode_copy_and_standalone_style(page):
    page.set_viewport_size({'width':360,'height':820});page.emulate_media(color_scheme='dark')
    submit(page,CASES[0][1])
    dark=snapshot(page)['color']
    page.screenshot(path='test-artifacts/kmaps/mobile-dark.png',full_page=True)
    page.set_viewport_size({'width':900,'height':1000})
    page.locator('svg.km-svg').screenshot(path='test-artifacts/kmaps/corners-dark.png')
    page.set_viewport_size({'width':360,'height':820})
    assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
    assert page.locator('#km-stage').evaluate('el=>el.scrollWidth>el.clientWidth')
    page.emulate_media(color_scheme='light')
    assert snapshot(page)['color']!=dark
    page.evaluate("()=>Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async t=>{window.copied=t}}})")
    page.click('#km-copy')
    page.wait_for_function('!!window.copied')
    assert 'G1' in page.evaluate('window.copied') and 'wraps' in page.evaluate('window.copied')


def test_newer_success_wins_when_responses_arrive_out_of_order(page,server_url):
    first=page.request.post(server_url+'/api/kmap',data={'expr':'a'}).json()
    second=page.request.post(server_url+'/api/kmap',data={'expr':'b'}).json()
    page.click('.tab[data-tab=kmap]')
    page.evaluate('''()=>{window.pending=[];window.fetch=()=>new Promise(resolve=>window.pending.push(resolve));}''')
    page.fill('#km-expr','a');page.click('#km-run')
    page.fill('#km-expr','b');page.click('#km-run')
    page.evaluate('data=>window.pending[1]({json:async()=>data})',second)
    page.wait_for_selector('#km-result:not([hidden])')
    assert page.locator('#km-equation').inner_text()=='F = b'
    page.evaluate('data=>window.pending[0]({json:async()=>data})',first)
    page.wait_for_timeout(100)
    assert page.locator('#km-equation').inner_text()=='F = b'


def test_copy_fallback_clears_and_selected_export_keeps_same_state(page,tmp_path):
    submit(page,{'expr':'a+b'})
    page.evaluate("()=>Object.defineProperty(navigator,'clipboard',{configurable:true,value:undefined})")
    page.click('#km-copy')
    assert 'G1' in page.locator('#km-result .copy-fallback').inner_text()
    page.locator('.km-group-card').first.click()
    before=page.locator('svg.km-svg').evaluate('svg=>new XMLSerializer().serializeToString(svg)')
    with page.expect_download() as info: page.click('#km-download')
    path=tmp_path/'selected.svg';info.value.save_as(path)
    assert path.read_text()==before
    page.fill('#km-expr','ab')
    assert page.locator('#km-result .copy-fallback').count()==0


@pytest.mark.parametrize('form', ['SOP','POS'])
def test_worked_group_steps_reference_copy_and_reset(page,server_url,form):
    payload={'variables':'a,b,c','ones':'0,1,2,3','form':form}
    submit(page,payload)
    view=page.request.post(server_url+'/api/kmap',data=payload).json()['result']
    work=view['groups'][0]['work']
    details=page.locator('[data-proof-group=G1]')
    page.locator('[data-proof-toggle=G1]').click()
    rows=details.locator('tbody tr')
    assert rows.count()==len(work['steps'])
    for i,step in enumerate(work['steps']):
        assert rows.nth(i).locator('td').nth(0).inner_text()==step['expression']
        assert rows.nth(i).locator('td').nth(1).inner_text()==step['law']+': '+step['reason']
    assert work['notation'] in page.locator('.km-group-card').first.inner_text()
    page.locator('.km-group-card').first.hover()
    assert page.locator('svg.km-svg').get_attribute('data-active-group')=='G1'
    page.locator('[data-boolean-reference] summary').click()
    assert "x + x' = 1" in page.locator('[data-boolean-reference]').inner_text()
    page.evaluate("()=>Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async t=>{window.copied=t}}})")
    page.click('#km-copy')
    page.wait_for_function('!!window.copied')
    assert work['steps'][0]['expression'] in page.evaluate('window.copied')
    assert 'Distributive' in page.evaluate('window.copied')
    page.screenshot(path=f'test-artifacts/kmaps/worked-{form}.png',full_page=True)
    with page.expect_download() as info: page.click('#km-download')
    assert work['notation'] in Path(info.value.path()).read_text()
    page.click('#km-new')
    assert page.locator('[data-proof-group]').count()==0
    assert page.locator('[data-boolean-reference]').count()==0


@pytest.mark.parametrize('width', [1280,360])
def test_multi_group_worked_explanation_has_readable_space(page,width):
    page.set_viewport_size({'width':width,'height':900})
    page.emulate_media(color_scheme='dark')
    submit(page,{'variables':'a,b,c,d','ones':'0,2,4,6,8,10,12'})
    assert page.locator('.km-group-section').count()==3
    positions=lambda: page.locator('.km-group-section').evaluate_all(
        "els=>els.map(el=>{const r=el.getBoundingClientRect();return [r.x+scrollX,r.y+scrollY,r.width,r.height]})")
    before=positions()
    details=page.locator('[data-proof-group=G1]')
    page.locator('[data-proof-toggle=G1]').click()
    assert positions()==before
    assert details.evaluate('el=>el.getBoundingClientRect().top+scrollY')>=max(r[1]+r[3] for r in before)
    section=page.locator('.km-group-section').first
    assert abs(details.bounding_box()['width']-page.locator('#km-groups').bounding_box()['width'])<2
    reason=details.locator('tbody tr').nth(1).locator('td').nth(1)
    assert reason.bounding_box()['width']>=220
    assert reason.bounding_box()['height']<200
    assert reason.evaluate('el=>getComputedStyle(el).overflowWrap')=='normal'
    if width==360:
        expression=details.locator('tbody tr').nth(1).locator('td').first
        assert reason.bounding_box()['y']>=expression.bounding_box()['y']+expression.bounding_box()['height']-1
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    assert details.locator('tbody tr').first.locator('td').first.inner_text().startswith("(a' · b' · c' · d') + (")
    page.screenshot(path=f'test-artifacts/kmaps/readable-steps-{width}.png',full_page=True)
    page.locator('[data-proof-toggle=G1]').click()
    if width==1280:
        assert section.bounding_box()['width']<page.locator('#km-groups').bounding_box()['width']/2
    assert positions()==before
    for group in ['G2','G3']:
        toggle=page.locator(f'[data-proof-toggle={group}]')
        toggle.focus();toggle.press('Enter')
        assert positions()==before
        assert page.locator('.km-proof-panel:not([hidden])').count()==1
        assert page.locator('[data-proof-toggle][aria-expanded=true]').count()==1
        assert page.locator('.km-proof-panel').get_attribute('data-proof-group')==group
        assert group in page.locator('.km-proof-panel h3').inner_text()
    page.locator('.km-proof-panel button').focus()
    page.locator('.km-proof-panel button').press('Escape')
    assert page.locator('[data-proof-toggle=G3]').evaluate('el=>el===document.activeElement')
    assert page.locator('.km-proof-panel').is_hidden()
    assert positions()==before
    page.locator('.km-group-card').nth(1).hover()
    assert page.locator('svg.km-svg').get_attribute('data-active-group')=='G2'
