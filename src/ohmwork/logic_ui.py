"""D21 standalone logic panel. Browser selects server-verified signal rows."""
CSS = r'''
.tabs { flex-wrap:wrap; }
#panel-logic [hidden] { display:none !important; }
.lg-fields { display:flex; gap:1rem; flex-wrap:wrap; }
.lg-fields > label { flex:1; min-width:140px; }
#panel-logic select { font:inherit; color:inherit; background:transparent; padding:.6rem; width:100%; border:1px solid #8888; border-radius:6px; }
.lg-stage, .lg-table-scroll { overflow:auto; max-width:100%; border:1px solid #8886; border-radius:10px; margin:1rem 0; }
.lg-stage svg { display:block; margin:auto; }
.lg-stage { max-height:650px; }
.lg-table-scroll { max-height:350px; }
.lg-table-scroll table { margin:0; white-space:nowrap; border-collapse:collapse; font-variant-numeric:tabular-nums; }
#lg-table th, #lg-table td { padding:.55rem .85rem; min-width:1.4rem; text-align:center; border:1px solid #8885; }
#lg-table th { position:sticky; top:0; background:light-dark(#f1f3f8,#202631); }
#lg-table td:last-child, #lg-table th:last-child { font-weight:700; border-left:2px solid #6685ad; }
#lg-table tr[aria-current=true] { background:light-dark(#dfeaff,#263d62); font-weight:700; }
.lg-actions { display:flex; gap:.5rem; flex-wrap:wrap; align-items:center; margin:1rem 0; }
#panel-logic button { font:inherit; font-size:.95rem; padding:.55rem .8rem; margin:0; min-height:44px; border:1px solid #8886; border-radius:6px; background:#8881; color:inherit; cursor:pointer; }
#panel-logic button[aria-pressed=true] { background:light-dark(#d9f4e8,#164a3d); }
#panel-logic button:focus-visible { outline:3px solid #4487ff; outline-offset:3px; }
.lg-detail { border:1px solid #8887; border-radius:10px; padding:1rem; margin:1rem 0; }
.lg-detail h3 { margin-top:0; }
.lg-stage [data-highlight=true] { stroke:#397bf6; stroke-width:4; }
#lg-summary { overflow-wrap:anywhere; }
#lg-status { font-weight:600; }
#lg-error { color:light-dark(#a51c1c,#ff9898); }
'''
HTML = r'''
<form class="panel" id="panel-logic">
  <p>Explore ideal logic gates. Change inputs to follow verified signals through the circuit.</p>
  <div class="lg-fields">
    <label>Build from <select id="lg-mode"><option value="basic">Basic gate</option><option value="expr">Expression</option></select></label>
    <label id="lg-kind-field">Gate <select id="lg-kind"><option>AND</option><option>OR</option><option>NOT</option><option>NAND</option><option>NOR</option><option>XOR</option><option>XNOR</option><option>BUF</option></select></label>
  </div>
  <label id="lg-vars-field">Input names (comma-separated; up to 8)<input id="lg-vars" type="text" value="a,b" autocomplete="off" spellcheck="false"></label>
  <label id="lg-expr-field" hidden>Expression (D8 notation)<input id="lg-expr" type="text" placeholder="e.g. ab + c" maxlength="4096" autocomplete="off" spellcheck="false"></label>
  <div class="lg-actions"><button type="submit" id="lg-build">Build circuit</button><button type="button" id="lg-new">New problem</button></div>
  <p id="lg-error" role="alert"></p>
  <section id="lg-result" hidden aria-label="Logic circuit result">
    <h2 id="lg-summary"></h2><p id="lg-meta"></p>
    <p>Structure-preserving ideal logic. Gate count and depth are not transistor count or physical timing; no minimization is applied.</p>
    <div id="lg-inputs" class="lg-actions" role="group" aria-label="Circuit inputs"></div>
    <p id="lg-status" role="status" aria-live="polite"></p>
    <p>Green wires carry 1; gray wires carry 0. Numeric values are also shown. Select a gate to inspect its inputs and rule.</p>
    <div id="lg-stage" class="lg-stage" tabindex="0" aria-label="Circuit diagram; scroll to explore"></div>
    <div id="lg-gate-buttons" class="lg-actions" role="group" aria-label="Inspect gates"></div>
    <section id="lg-detail" class="lg-detail" hidden aria-label="Gate explanation">
      <h3 id="lg-detail-title"></h3><p id="lg-detail-rule"></p><p id="lg-detail-values"></p>
      <button id="lg-close" type="button">Close explanation</button>
    </section>
    <div class="lg-actions"><button id="lg-download" type="button" disabled>Download SVG</button><button id="lg-copy" type="button" disabled>Copy circuit report</button></div>
    <h3>Truth table and internal signals</h3>
    <p>The highlighted row matches the input switches. Internal columns use gate IDs from the diagram.</p>
    <div class="lg-table-scroll" tabindex="0" aria-label="Truth table; scroll to explore"><table id="lg-table"></table></div>
  </section>
</form>
'''
JS = r'''
(() => {
  const el = id => document.getElementById(id);
  let view=null, vector=0, generation=0, selected=null, opener=null, report='';
  function clear() {
    generation++; view=null; selected=null; opener=null; report=''; vector=0;
    el('lg-result').hidden=true; el('lg-stage').replaceChildren(); el('lg-table').replaceChildren();
    el('lg-detail').hidden=true; el('lg-download').disabled=true; el('lg-copy').disabled=true;
    el('lg-build').disabled=false; el('lg-error').textContent='';
  }
  function fields() {
    const basic=el('lg-mode').value==='basic';
    el('lg-kind-field').hidden=!basic;el('lg-vars-field').hidden=!basic;el('lg-expr-field').hidden=basic;
  }
  ['lg-mode','lg-kind','lg-vars','lg-expr'].forEach(id=>el(id).addEventListener('input',()=>{
    clear(); fields();
    if(id==='lg-kind') {
      const unary=['NOT','BUF'].includes(el(id).value);
      if(unary) el('lg-vars').value='a';
      else if(!el('lg-vars').value.includes(',')) el('lg-vars').value='a,b';
    }
  }));
  el('lg-new').addEventListener('click',()=>{
    clear();el('lg-expr').value='';el('lg-vars').value=['NOT','BUF'].includes(el('lg-kind').value)?'a':'a,b';
    el(el('lg-mode').value==='expr'?'lg-expr':'lg-vars').focus();
  });
  function close() {
    selected=null;el('lg-detail').hidden=true;
    el('lg-stage').querySelectorAll('[data-highlight]').forEach(n=>n.removeAttribute('data-highlight'));
    el('lg-gate-buttons').querySelectorAll('button').forEach(b=>b.setAttribute('aria-expanded','false'));
    el('lg-stage').querySelectorAll('[data-gate-id]').forEach(b=>b.setAttribute('aria-expanded','false'));
    if(opener?.isConnected) opener.focus();
  }
  el('lg-close').addEventListener('click',close);
  el('panel-logic').addEventListener('keydown',e=>{if(e.key==='Escape' && selected){e.preventDefault();close();}});
  function inspect(id,button) {
    if(selected===id){close();return;}
    selected=id;opener=button;el('lg-detail').hidden=false;
    const gate=view.gates.find(g=>g.id===id);
    el('lg-detail-title').textContent=gate.id+' · '+gate.kind;
    el('lg-detail-rule').textContent=gate.explanation;
    el('lg-gate-buttons').querySelectorAll('button').forEach(b=>b.setAttribute('aria-expanded',String(b.dataset.id===id)));
    el('lg-stage').querySelectorAll('[data-gate-id]').forEach(b=>b.setAttribute('aria-expanded',String(b.dataset.gateId===id)));
    el('lg-stage').querySelectorAll('.lg-wire').forEach(w=>w.dataset.highlight=String(w.dataset.gate===id || w.dataset.driver===id));
    update();
  }
  function update() {
    const row=view.rows[vector], values={};
    view.inputs.forEach((p,i)=>values[p.id]=row.inputs[i]);view.gates.forEach((g,i)=>values[g.id]=row.gates[i]);
    el('lg-inputs').querySelectorAll('button').forEach((b,i)=>{
      b.textContent=view.inputs[i].name+': '+Number(row.inputs[i]);b.setAttribute('aria-pressed',String(row.inputs[i]));
    });
    el('lg-stage').querySelectorAll('[data-signal]').forEach(t=>t.textContent=Number(values[t.dataset.signal]));
    el('lg-stage').querySelectorAll('.lg-wire').forEach(w=>w.dataset.value=Number(values[w.dataset.driver]));
    el('lg-stage').querySelector('[data-output-value]').textContent=Number(row.output);
    el('lg-status').textContent='Inputs '+view.inputs.map((p,i)=>p.name+'='+Number(row.inputs[i])).join(', ')+' → F='+Number(row.output);
    el('lg-table').querySelectorAll('tbody tr').forEach((tr,i)=>tr.setAttribute('aria-current',String(i===vector)));
    if(selected) {
      const g=view.gates.find(g=>g.id===selected);
      const names=Object.fromEntries(view.inputs.map(p=>[p.id,p.name]));
      el('lg-detail-values').textContent=g.inputs.map((d,i)=>'Input '+(i+1)+' ('+(names[d]||d)+') = '+Number(values[d])).join('; ')+'. Output '+g.id+' = '+Number(values[g.id])+'.';
    }
  }
  function cell(tag,text,parent) {const n=document.createElement(tag);n.textContent=text;parent.append(n);return n;}
  function render(data) {
    view=data.result; report=data.output; vector=0;
    el('lg-result').hidden=false;
    el('lg-summary').textContent='F = '+view.expression;
    el('lg-meta').textContent=view.gate_count+' gates · depth '+view.depth+' · verified for all '+view.rows.length+' input vectors';
    el('lg-stage').innerHTML=data.svg;
    const svg=el('lg-stage').querySelector('svg');svg.setAttribute('role','group');
    el('lg-inputs').replaceChildren();
    view.inputs.forEach((p,i)=>{
      const b=document.createElement('button');b.type='button';
      b.addEventListener('click',()=>{vector^=1<<(view.inputs.length-1-i);update();});el('lg-inputs').append(b);
    });
    el('lg-gate-buttons').replaceChildren();
    view.gates.forEach(g=>{
      const b=document.createElement('button');b.type='button';b.textContent=g.id+' · '+g.kind;b.dataset.id=g.id;
      b.setAttribute('aria-expanded','false');b.setAttribute('aria-controls','lg-detail');b.addEventListener('click',()=>inspect(g.id,b));
      el('lg-gate-buttons').append(b);
      const symbol=svg.querySelector('[data-gate-id="'+g.id+'"]');
      symbol.setAttribute('tabindex','0');symbol.setAttribute('role','button');symbol.setAttribute('aria-label','Inspect '+g.id+' '+g.kind);
      symbol.setAttribute('aria-expanded','false');symbol.setAttribute('aria-controls','lg-detail');
      symbol.addEventListener('click',()=>inspect(g.id,symbol));
      symbol.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();inspect(g.id,symbol);}});
    });
    const head=document.createElement('thead'),hr=document.createElement('tr');head.append(hr);
    [...view.inputs.map(p=>p.name),...view.gates.map(g=>g.id),'F'].forEach(t=>cell('th',t,hr).scope='col');
    const body=document.createElement('tbody');
    view.rows.forEach(r=>{const tr=document.createElement('tr');[...r.inputs,...r.gates,r.output].forEach(v=>cell('td',Number(v),tr));body.append(tr);});
    el('lg-table').replaceChildren(head,body);el('lg-download').disabled=false;el('lg-copy').disabled=false;update();
  }
  el('panel-logic').addEventListener('submit',async e=>{
    e.preventDefault();clear();const ticket=generation;el('lg-build').disabled=true;
    const payload=el('lg-mode').value==='expr'?{expr:el('lg-expr').value}:{kind:el('lg-kind').value,variables:el('lg-vars').value};
    try {
      const response=await fetch('/api/logic',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
      const data=await response.json();if(ticket!==generation)return;
      if(!data.ok)throw new Error(data.error);render(data);
    }catch(err){if(ticket===generation){clear();el('lg-error').textContent=err.message;}}
    finally{if(ticket===generation)el('lg-build').disabled=false;}
  });
  el('lg-download').addEventListener('click',()=>{
    if(!view)return;const svg=el('lg-stage').querySelector('svg').cloneNode(true);
    svg.setAttribute('role','img');svg.querySelectorAll('[data-highlight]').forEach(n=>n.removeAttribute('data-highlight'));
    svg.querySelectorAll('[data-gate-id]').forEach(n=>['tabindex','role','aria-label','aria-expanded','aria-controls'].forEach(a=>n.removeAttribute(a)));
    const desc=document.createElementNS('http://www.w3.org/2000/svg','desc');desc.textContent=el('lg-status').textContent;svg.prepend(desc);
    const url=URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(svg)],{type:'image/svg+xml'}));
    const a=document.createElement('a');a.href=url;a.download='ohmwork-logic.svg';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  });
  el('lg-copy').addEventListener('click',async()=>{
    if(!view)return;const ticket=generation;
    try{await navigator.clipboard.writeText(report);if(ticket===generation)el('lg-status').textContent='Circuit report copied.';}
    catch(err){if(ticket===generation)el('lg-error').textContent='Copy failed. Please try again.';}
  });
  fields();
})();
'''
