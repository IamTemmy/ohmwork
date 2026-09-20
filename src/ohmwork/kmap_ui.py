"""Standalone D18 UI assets, embedded by webui without another asset route."""
CSS = r"""
  #panel-kmap .km-input-row { display:flex; gap:1rem; flex-wrap:wrap; align-items:end; }
  #panel-kmap .km-input-row > label { flex:1; min-width:140px; }
  #panel-kmap select { color:inherit; background:transparent; border:1px solid #8886; border-radius:6px; padding:.65rem; width:100%; font:inherit; }
  #panel-kmap [hidden] { display:none !important; }
  .km-error { color:#d14343; margin:.8rem 0; }
  .km-summary { margin-top:1.5rem; border-left:3px solid #5686ef; padding:.2rem 1rem; }
  .km-summary h2 { font-size:1.4rem; margin:.2rem 0; overflow-wrap:anywhere; }
  .km-meta { font-size:.85rem; opacity:.75; }
  .km-stage { overflow-x:auto; border:1px solid #8884; border-radius:12px; margin:1rem 0; background:light-dark(#fcfdff,#161a23); }
  .km-stage svg { display:block; margin:auto; }
  .km-group-list { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr)); gap:.7rem; margin:1rem 0; }
  .km-group-card { color:inherit; background:transparent; border:1px solid #8885; border-left:4px solid var(--group-color); border-radius:8px; padding:.8rem; cursor:pointer; text-align:left; font:inherit; }
  .km-group-card[aria-pressed=true] { outline:2px solid var(--group-color); background:#8881; }
  .km-group-card strong { display:block; margin-bottom:.3rem; }
  .km-group-card small { display:block; opacity:.8; line-height:1.5; }
  .km-group-card:focus-visible, #panel-kmap button:focus-visible { outline:3px solid #5686ef; outline-offset:3px; }
  #panel-kmap > .km-actions { margin-top:1rem; }
  .km-actions { display:flex; flex-wrap:wrap; gap:.5rem; }
  .km-input-grid { overflow-x:auto; max-height:320px; margin-bottom:1rem; }
  .km-input-grid th { position:sticky; top:0; background:light-dark(white,#161616); }
"""
HTML = r"""
<form class="panel" id="panel-kmap">
  <p class="hint">See how adjacent cells become simpler terms. Select a group to follow its explanation.</p>
  <div class="km-input-row">
    <label>Start from
      <select id="km-mode"><option value="expr">Expression</option><option value="grid">Truth-table grid</option><option value="minterms">Minterms &amp; don't-cares</option><option value="bits">Bit string</option></select>
    </label>
    <label>Result form
      <select id="km-form"><option value="SOP">Sum of products · group 1s</option><option value="POS">Product of sums · group 0s</option></select>
    </label>
    <label>Output name <input type="text" id="km-output-name" value="F" maxlength="2" autocomplete="off"></label>
  </div>
  <label id="km-expr-field">Expression
    <input type="text" id="km-expr" placeholder="e.g. ab + a'c" autocomplete="off" spellcheck="false">
  </label>
  <div id="km-truth-fields" hidden>
    <label>Variables in order (1–4, comma-separated)<input type="text" id="km-vars" placeholder="a, b, c" autocomplete="off" spellcheck="false"></label>
    <div class="km-input-grid" id="km-input-grid"></div>
    <div id="km-minterm-fields" hidden>
      <label>1-cell indices (leave empty for none)<input type="text" id="km-ones" placeholder="0, 2, 8, 10" autocomplete="off"></label>
      <label>Don't-care indices (optional)<input type="text" id="km-dc" placeholder="1, 3" autocomplete="off"></label>
    </div>
    <label id="km-bits-field" hidden>Values in binary row order (0/1/X)<input type="text" id="km-bits" placeholder="00010111" autocomplete="off" spellcheck="false"></label>
  </div>
  <div class="km-actions"><button type="submit" class="submit" id="km-run">Build K-map</button><button type="button" class="copy-btn" id="km-new">New problem</button></div>
  <p id="km-error" class="km-error" role="alert"></p>
  <section id="km-result" hidden aria-label="K-map result">
    <div class="km-summary"><h2 id="km-equation"></h2><p id="km-summary" class="km-meta"></p></div>
    <p id="km-direction" class="hint"></p>
    <div class="km-stage" id="km-stage" tabindex="0" aria-label="K-map diagram; scroll horizontally if needed"></div>
    <div class="km-actions"><button type="button" class="copy-btn" id="km-show-all">Show all groups</button><button type="button" class="copy-btn" id="km-download">Download SVG</button><button type="button" class="copy-btn" id="km-copy">Copy explanation</button></div>
    <p id="km-selection" class="km-meta" aria-live="polite"></p>
    <div id="km-groups" class="km-group-list"></div>
    <p id="km-assignments" class="km-meta"></p>
    <details id="km-alternatives"><summary>Other equally minimal covers</summary><ul id="km-alternative-list"></ul></details>
  </section>
</form>
"""
JS = r"""
// D18: no algebra in JavaScript. The renderer consumes one verified view.
const KM_SVG_STYLE = `
.km-svg { color:#172238; background:#fcfdff; font-family:system-ui,-apple-system,sans-serif; }
.km-grid-cell { fill:transparent; stroke:#8b96a855; stroke-width:1; }
.km-value { fill:currentColor; font-size:28px; font-weight:650; text-anchor:middle; dominant-baseline:middle; }
.km-badge { fill:#fcfdff; }
.km-index { fill:currentColor; opacity:.55; font-size:11px; }
.km-axis { fill:currentColor; font-size:16px; text-anchor:middle; }
.km-small { fill:currentColor; font-size:12px; }
.km-title { fill:currentColor; font-size:21px; font-weight:650; }
.km-piece { stroke-width:2.5; cursor:pointer; }
.km-group:focus { outline:none; }
.km-group:focus .km-piece { stroke-width:4; }
.km-group[data-selected=true] .km-piece { stroke-width:4; fill-opacity:.14; }
.km-active-cell .km-grid-cell { fill:#5686ef14; }
.km-legend { cursor:pointer; }
.km-legend text { fill:currentColor; font-size:14px; }
@media (prefers-color-scheme:dark) {
 .km-svg { color:#e6edf8; background:#161a23; }
 .km-badge { fill:#161a23; }
 .km-piece { filter:brightness(1.6) saturate(.8); }
 .km-legend line { filter:brightness(1.6) saturate(.8); }
}
`;
function renderKmap(view, host, cards, onSelection) {
  const ns = 'http://www.w3.org/2000/svg';
  const node = (tag, attrs={}, text=null, parent=null) => {
    const el=document.createElementNS(ns,tag);
    for (const [k,v] of Object.entries(attrs)) el.setAttribute(k,String(v));
    if (text !== null) el.textContent=text;
    if (parent) parent.appendChild(el);
    return el;
  };
  const svg=node('svg',{xmlns:ns,viewBox:`0 0 ${view.width} ${view.height}`,role:'group',
    'aria-label':`Karnaugh map of ${view.output_name}, ${view.form}, grouping ${view.grouping_value}s`,
    'data-kmap-svg':'true',class:'km-svg'});
  // Fixed readable scale; the enclosing region scrolls instead of shrinking text.
  svg.style.width=view.width+'px'; svg.style.height=view.height+'px';
  node('style',{},KM_SVG_STYLE,svg);
  node('title',{},`${view.output_name} = ${view.expression}`,svg);
  node('desc',{},`Gray-code axes. Matching group IDs and stroke patterns identify one group, including split pieces across opposite edges. X means don't-care.`,svg);
  node('text',{x:24,y:34,class:'km-title'},`${view.output_name} · Karnaugh map`,svg);
  node('text',{x:24,y:58,class:'km-small'},`${view.form} · group ${view.grouping_value}s · ${view.groups.length} ${view.groups.length===1?'group':'groups'} · X = don't-care`,svg);
  const grid=view.grid;
  node('text',{x:grid.left+grid.columns*grid.cell/2,y:82,class:'km-axis'},view.column_variables.join(''),svg);
  node('text',{x:32,y:grid.top+grid.rows*grid.cell/2,class:'km-axis'},view.row_variables.join('') || '—',svg);
  view.column_labels.forEach((label,i)=>node('text',{x:grid.left+(i+.5)*grid.cell,y:103,class:'km-axis'},label,svg));
  view.row_labels.forEach((label,i)=>node('text',{x:70,y:grid.top+(i+.5)*grid.cell+5,class:'km-axis'},label || '—',svg));
  const cellLayer=node('g',{'data-role':'cells'},null,svg);
  for (const c of view.cells) {
    const g=node('g',{'data-minterm':c.minterm,'data-value':c.value,'data-assigned-value':c.assigned_value},null,cellLayer);
    node('rect',{x:c.x,y:c.y,width:grid.cell,height:grid.cell,class:'km-grid-cell'},null,g);
    node('title',{},`m${c.minterm}: ${c.value}${c.value==='X'?`, selected value ${c.assigned_value}`:''}; groups ${c.group_ids.join(', ') || 'none'}`,g);
  }
  const groupNodes=[]; const legendNodes=[]; const buttons=[];
  const groupLayer=node('g',{'data-role':'groups'},null,svg);
  for (const group of view.groups) {
    const g=node('g',{'data-group-id':group.id,class:'km-group',tabindex:0,role:'button',
      'aria-label':`${group.id}: ${group.term}, cells ${group.minterms.join(', ')}${group.wraps_rows||group.wraps_columns?', wraps across edges':''}`,
      'aria-pressed':'false'},null,groupLayer);
    node('title',{},`${group.id} · ${group.term}`,g);
    group.pieces.forEach((p,i)=>node('rect',{x:p.x,y:p.y,width:p.width,height:p.height,rx:14,
      fill:group.color,'fill-opacity':.07,stroke:group.color,'stroke-dasharray':group.dash,
      class:'km-piece','data-piece-index':i},null,g));
    // Repeated G badges go in dedicated per-cell strips below the values;
    // they identify every overlapping group without mixing color meanings.
    groupNodes.push(g);
  }
  // Text is always above tinted group regions, never obscured by their fills.
  for (const c of view.cells) {
    node('text',{x:c.cx,y:c.cy,class:'km-value','data-cell-text':c.minterm},c.value,svg);
    node('rect',{x:c.x+3,y:c.y+3,width:29,height:17,rx:2,class:'km-badge','data-index-badge':c.minterm},null,svg);
    node('text',{x:c.x+7,y:c.y+15,class:'km-index','data-index-text':c.minterm},`m${c.minterm}`,svg);
    const count=c.group_ids.length;
    c.group_ids.forEach((id,i)=>{
      const row=Math.floor(i/4), rowCount=Math.min(4,count-row*4);
      const x=c.cx+(i%4-(rowCount-1)/2)*24, y=c.cy+30+row*16;
      node('rect',{x:x-11,y:y-11,width:22,height:15,rx:3,class:'km-badge','data-group-badge':id,'data-badge-cell':c.minterm},null,svg);
      node('text',{x,y,class:'km-small','text-anchor':'middle','font-weight':600,
        'data-membership':id,'data-member-cell':c.minterm},id,svg);
    });
  }
  node('text',{x:24,y:grid.top+grid.rows*grid.cell+28,class:'km-small'},
    'Same group ID = one group. Opposite edges are adjacent.',svg);
  if (!view.groups.length) node('text',{x:24,y:view.legend_y,class:'km-small'},'No groups needed: the selected function is constant.',svg);
  view.groups.forEach((group,i)=>{
    const y=view.legend_y+i*34;
    const legend=node('g',{class:'km-legend','data-legend-id':group.id},null,svg);
    node('line',{x1:24,y1:y-5,x2:66,y2:y-5,stroke:group.color,'stroke-width':3,'stroke-dasharray':group.dash},null,legend);
    const wrap=[group.wraps_rows?'top/bottom':'',group.wraps_columns?'left/right':''].filter(Boolean).join(' + ');
    node('text',{x:80,y},`${group.id} · ${group.term}${wrap?' · wraps '+wrap:''}`,legend);
    legendNodes.push(legend);
    const button=document.createElement('button'); button.type='button'; button.className='km-group-card';
    button.dataset.groupId=group.id; button.style.setProperty('--group-color',group.color);
    button.setAttribute('aria-pressed','false');
    const strong=document.createElement('strong'); strong.textContent=`${group.id} · ${group.term}`; button.appendChild(strong);
    const detail=document.createElement('small'); detail.textContent=`Cells ${group.minterms.join(', ')}${group.essential?' · essential group':''}${wrap?' · wraps '+wrap:''}`;
    button.appendChild(detail);
    const why=document.createElement('small'); why.textContent=group.explanation; button.appendChild(why);
    cards.appendChild(button); buttons.push(button);
  });
  view.footer_lines.forEach((line,i)=>node('text',{x:24,y:view.footer_y+i*20,class:'km-small',
    'font-family':'ui-monospace,monospace','font-size':14},line,svg));
  host.appendChild(svg);
  let pinned=null;
  function highlight(id) {
    svg.dataset.activeGroup=id || '';
    view.groups.forEach((group,i)=>{
      const active=group.id===id;
      groupNodes[i].style.opacity=id && !active?'.2':'1';
      groupNodes[i].dataset.selected=String(active); groupNodes[i].setAttribute('aria-pressed',String(active));
      buttons[i].setAttribute('aria-pressed',String(active));
      legendNodes[i].style.opacity=id && !active?'.4':'1';
    });
    cellLayer.querySelectorAll('[data-minterm]').forEach(el=>{
      const cell=view.cells.find(c=>String(c.minterm)===el.dataset.minterm);
      el.classList.toggle('km-active-cell',!!id && cell.group_ids.includes(id));
    });
    svg.querySelectorAll('[data-membership]').forEach(el=>{
      el.style.opacity=id && el.dataset.membership!==id?'.2':'1';
    });
    const group=view.groups.find(g=>g.id===id);
    onSelection(group ? `${group.id} → ${group.term}. ${group.explanation}` : 'Select a group or term to isolate it. Select again, or press Escape, to show all.');
  }
  view.groups.forEach((group,i)=>{
    for (const el of [groupNodes[i],legendNodes[i],buttons[i]]) {
      el.addEventListener('mouseenter',()=>highlight(group.id));
      el.addEventListener('mouseleave',()=>highlight(pinned));
      el.addEventListener('focus',()=>highlight(group.id));
      el.addEventListener('blur',()=>highlight(pinned));
      el.addEventListener('click',()=>{pinned=pinned===group.id?null:group.id;highlight(pinned);});
      el.addEventListener('keydown',e=>{
        if (e.key==='Escape') {pinned=null;highlight(null);}
        // Native HTML buttons already synthesize click on Space/Enter.
        if (el===groupNodes[i] && ['Enter',' '].includes(e.key)) {e.preventDefault();el.dispatchEvent(new MouseEvent('click'));}
      });
    }
  });
  highlight(null);
  return {svg,reset:()=>{pinned=null;highlight(null);}};
}
(function setupKmap() {
  const $k=id=>document.getElementById(id);
  let token=0, diagram=null, report='', gridValues=[];
  function clearResult() {
    token++; diagram=null;report='';
    $k('km-result').hidden=true; $k('km-error').textContent='';
    ['km-equation','km-summary','km-direction','km-stage','km-groups','km-selection','km-assignments','km-alternative-list'].forEach(id=>$k(id).replaceChildren());
    $k('km-alternatives').open=false;
    $k('km-run').disabled=false;$k('km-run').textContent='Build K-map';
    $k('km-copy').textContent='Copy explanation'; removeCopyFallbackFor($k('km-copy'));
  }
  function buildInputGrid() {
    const names=$k('km-vars').value.split(',').map(x=>x.trim());
    const host=$k('km-input-grid'); host.replaceChildren(); gridValues=[];
    if (!names.length || names.length>4 || names.some(n=>! /^[A-Za-z][0-9]?$/.test(n) || n==='F') || new Set(names).size!==names.length) {
      host.textContent='Enter 1–4 distinct variables to build the table.'; return;
    }
    gridValues=Array(2**names.length).fill('0');
    const t=document.createElement('table');t.className='truth-grid';t.setAttribute('aria-label','K-map input truth table');
    const head=t.createTHead().insertRow();
    [...names,'Output'].forEach(name=>{const th=document.createElement('th');th.scope='col';th.textContent=name;head.appendChild(th);});
    const body=t.createTBody();
    gridValues.forEach((_,i)=>{
      const row=body.insertRow();const bits=i.toString(2).padStart(names.length,'0');
      [...bits].forEach(bit=>row.insertCell().textContent=bit);
      const button=document.createElement('button');button.type='button';button.className='cell-btn';button.textContent='0';
      const label=()=>button.setAttribute('aria-label',`m${i}, ${bits}, output ${gridValues[i]}; activate to cycle 0, 1, X`);
      label();button.addEventListener('click',()=>{clearResult();gridValues[i]={'0':'1','1':'X','X':'0'}[gridValues[i]];button.textContent=gridValues[i];label();});
      row.insertCell().appendChild(button);
    });host.appendChild(t);
  }
  function showInput() {
    const mode=$k('km-mode').value;
    $k('km-expr-field').hidden=mode!=='expr';$k('km-truth-fields').hidden=mode==='expr';
    $k('km-input-grid').hidden=mode!=='grid';$k('km-minterm-fields').hidden=mode!=='minterms';$k('km-bits-field').hidden=mode!=='bits';
  }
  $k('panel-kmap').querySelectorAll('input').forEach(el=>el.addEventListener('input',clearResult));
  $k('km-vars').addEventListener('input',buildInputGrid);
  ['km-mode','km-form'].forEach(id=>$k(id).addEventListener('change',()=>{clearResult();showInput();}));
  $k('km-new').addEventListener('click',()=>{
    ['km-expr','km-vars','km-ones','km-dc','km-bits'].forEach(id=>$k(id).value='');
    $k('km-output-name').value='F';clearResult();buildInputGrid();
    $k($k('km-mode').value==='expr'?'km-expr':'km-vars').focus();
  });
  $k('panel-kmap').addEventListener('submit',async e=>{
    e.preventDefault();clearResult();const current=token;
    const payload={form:$k('km-form').value,output_name:$k('km-output-name').value || 'F'};
    const mode=$k('km-mode').value;
    if(mode==='expr') payload.expr=$k('km-expr').value;
    else {
      payload.variables=$k('km-vars').value;
      if(mode==='minterms') {payload.ones=$k('km-ones').value;payload.dc=$k('km-dc').value;}
      else payload.table=mode==='grid'?gridValues.join(''):$k('km-bits').value;
    }
    $k('km-run').disabled=true;$k('km-run').textContent='Building…';
    const response=await postJSON('/api/kmap',payload);
    if(current!==token) return;
    $k('km-run').disabled=false;$k('km-run').textContent='Build K-map';
    if(!response.ok) {$k('km-error').textContent=response.error || 'Could not build the map.';return;}
    const view=response.result;report=response.output;
    $k('km-equation').textContent=`${view.output_name} = ${view.expression}`;
    $k('km-summary').textContent=`${view.form} · ${view.term_count} ${view.term_count===1?'group':'groups'} · ${view.literal_count} ${view.literal_count===1?'literal':'literals'} · verified for all ${view.cells.length} inputs`;
    $k('km-direction').textContent=view.form==='SOP'?'Group the 1s. Each colored group contributes one product term.':
      `Group the 0s. Their products give ${view.grouped_target} = ${view.grouped_expression}; complementing gives the POS above.`;
    diagram=renderKmap(view,$k('km-stage'),$k('km-groups'),text=>$k('km-selection').textContent=text);
    const xs=view.cells.filter(c=>c.value==='X').sort((a,b)=>a.minterm-b.minterm);
    $k('km-assignments').textContent=xs.length?'Selected X assignments: '+xs.map(c=>`m${c.minterm} → ${c.assigned_value} (${c.group_ids.length?'grouped':'ungrouped'})`).join('; '):'';
    $k('km-alternatives').hidden=view.alternatives.length<2;
    view.alternatives.forEach((expr,i)=>{const li=document.createElement('li');li.textContent=`${view.output_name} = ${expr}${i===view.selected_alternative?' — selected by deterministic target-SOP ordering':''}`;$k('km-alternative-list').appendChild(li);});
    $k('km-result').hidden=false;
  });
  $k('km-show-all').addEventListener('click',()=>diagram?.reset());
  $k('km-download').addEventListener('click',()=>{
    if(!diagram) return;
    const clone=diagram.svg.cloneNode(true);
    const url=URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(clone)],{type:'image/svg+xml;charset=utf-8'}));
    const a=document.createElement('a');a.href=url;a.download='ohmwork-kmap.svg';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
  // Snapshot text at click; a later input edit prevents stale fallback/feedback.
  $k('km-copy').addEventListener('click',async()=>{
    const text=report,current=token;if(!text) return;
    try {
      if(!navigator.clipboard?.writeText) throw new Error('clipboard unavailable');
      await navigator.clipboard.writeText(text);
      if(current===token) $k('km-copy').textContent='Copied!';
    } catch (_) {if(current===token) showCopyFallback($k('km-copy'),text);}
  });
  showInput();buildInputGrid();
})();
"""
