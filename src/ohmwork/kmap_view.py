"""D18 Phase 2: JSON presentation and CLI text from one verified KMap.

Pixel geometry is explicit and testable. Each group's visible rectangle is
inset within exactly its declared cells; cell centres prove its coverage.
These are display coordinates only, never a second grouping algorithm.
"""
from __future__ import annotations

from dataclasses import asdict
from textwrap import wrap
from ohmwork.expr import render
from ohmwork.kmap import KMap
from ohmwork.kmap_steps import group_work, LAWS

CELL = 120
LEFT = 96
TOP = 112
COLORS = ('#2563eb', '#b45309', '#0f766e', '#be185d', '#7c3aed', '#4d7c0f', '#c2410c', '#475569')
DASHES = ('', '10 4', '3 4', '12 3 3 3', '8 3 2 3 2 3', '14 5', '2 3 8 3', '6 3')


def build_kmap_view(model: KMap) -> dict:
    """Flatten the already-verified model; add only presentation geometry."""
    rows, cols = len(model.row_labels), len(model.column_labels)
    two_planes = model.plane_variable is not None
    top = TOP + (28 if two_planes else 0)
    plane_width = max(480, LEFT+cols*CELL+32)
    stride = plane_width
    groups=[]
    for i,g in enumerate(model.groups):
        inset=min(8+2*i, 38)
        pieces=[{**asdict(p), 'x':LEFT+p.column*CELL+inset+p.plane*stride,
                 'y':top+p.row*CELL+inset, 'width':p.columns*CELL-2*inset,
                 'height':p.rows*CELL-2*inset} for p in g.pieces]
        groups.append({'id':g.id, 'pattern':g.pattern, 'minterms':g.minterms,
                       'used_dont_cares':g.used_dont_cares, 'term':render(g.term),
                       'explanation':g.explanation, 'essential':g.essential,
                       'witnesses':g.essential_witnesses,
                       'crosses_planes':g.crosses_planes, 'wraps_rows':g.wraps_rows, 'wraps_columns':g.wraps_columns,
                       'color':COLORS[i % len(COLORS)], 'dash':DASHES[i % len(DASHES)],
                       'pieces':pieces, 'work':group_work(model, g)})
    cells=[{**asdict(c), 'x':LEFT+c.column*CELL+c.plane*stride, 'y':top+c.row*CELL,
            'cx':LEFT+(c.column+.5)*CELL+c.plane*stride, 'cy':top+(c.row+.5)*CELL} for c in model.cells]
    target=model.output_name if model.form=='SOP' else model.output_name+"'"
    width=plane_width
    footer=wrap(f'{model.output_name} = {render(model.expression)}', width=int((width-48)/8.5))
    if model.synthesis_f_prime is not None:
        footer += wrap(
            f"PDN: {model.output_name}' = ({render(model.expression)})' = {render(model.synthesis_f_prime)}",
            width=int((width-48)/8.5))
    xs=[f'm{c.minterm}={c.assigned_value}' for c in sorted(model.cells,key=lambda c:c.minterm) if c.value=='X']
    if xs: footer+=wrap('Selected X values: '+', '.join(xs),width=int((width-48)/8.5))
    legend_y=top+rows*CELL+84
    cursor=legend_y
    for group in groups:
        work=group['work']
        lines=[f"{group['id']} · {group['term']} — {work['title']}"]
        lines+=wrap(work['notation'], width=int((width-104)/8.5))
        lines+=wrap(work['steps'][0]['expression']+' = '+work['result'], width=int((width-104)/8.5))
        edges=[name for flag,name in ((group['wraps_rows'],'top/bottom'),(group['wraps_columns'],'left/right')) if flag]
        if group['crosses_planes']: lines.append(f'Spans both {model.plane_variable}=0 and {model.plane_variable}=1 planes')
        if edges: lines.append('Wraps '+ ' + '.join(edges))
        lines+=wrap(work['note'], width=int((width-104)/8.5))
        group['legend_lines']=lines
        group['legend_y']=cursor
        cursor+=len(lines)*22+20
    footer_y=max(cursor,legend_y+34)+24
    return {'output_name':model.output_name, 'form':model.form, 'variables':model.var_order,
            'row_variables':model.row_variables, 'column_variables':model.column_variables,
            'row_labels':model.row_labels, 'column_labels':model.column_labels,
            'cells':cells, 'groups':groups, 'expression':render(model.expression),
            'grouped_expression':render(model.grouped_expression), 'grouped_target':target,
            'grouping_value':model.grouping_value, 'term_count':model.term_count,
            'literal_count':model.literal_count, 'alternatives':tuple(map(render,model.alternatives)),
            'selected_alternative':model.selected_alternative,
            'origin':model.origin, 'width':width*(2 if two_planes else 1),
            'plane_variable':model.plane_variable, 'plane_labels':model.plane_labels,
            'plane_stride':stride, 'plane_width':plane_width,
            'height':footer_y+len(footer)*20+24, 'footer_lines':footer, 'footer_y':footer_y,
            'grid':{'left':LEFT,'top':top,'cell':CELL,'rows':rows,'columns':cols},
            'legend_y':legend_y, 'laws':[{'name':name,'identity':identity} for name,identity in LAWS]}


def format_kmap_report(model: KMap) -> str:
    """CLI/export explanation; no frontend Boolean formatting or algebra."""
    lines=[f'{model.output_name} = {render(model.expression)}',
           f"{model.form}: group the {model.grouping_value}s. X = don't-care.",
           f"Rows: {', '.join(model.row_variables) or '(none)'}; columns: {', '.join(model.column_variables)}"]
    for plane,label in enumerate(model.plane_labels):
        if model.plane_variable is not None:
            lines.append(f'Plane {model.plane_variable}={label}')
        lines.append('\t'+'\t'.join(model.column_labels))
        for row,row_label in enumerate(model.row_labels):
            lines.append((row_label or '–')+'\t'+'\t'.join(c.value for c in model.cells if c.row==row and c.plane==plane))
    if model.plane_variable is not None:
        lines.append('The same position in the other map is adjacent. The displayed seam is not an extra adjacency.')
    if not model.groups:
        lines.append(f'No groups needed: the selected function is constant {render(model.expression)}.')
    for g in model.groups:
        lines.append(f'{g.id}: {render(g.term)}; cells {", ".join(map(str,g.minterms))}'
                     + ('; essential' if g.essential else ''))
        work=group_work(model,g)
        lines.append(work['title']+': '+work['notation'])
        if work['note']: lines.append(work['note'])
        for step in work['steps']:
            lines.append(step['expression']+' — '+step['law']+': '+step['reason'])
        lines.append(g.explanation)
        wrap=[]
        if g.wraps_rows: wrap.append('top/bottom')
        if g.wraps_columns: wrap.append('left/right')
        if wrap: lines.append('One group wraps across '+ ' and '.join(wrap)+' edges.')
    xs=[f'm{c.minterm}={c.assigned_value}'+(' (grouped)' if c.group_ids else ' (ungrouped)')
        for c in sorted(model.cells,key=lambda c:c.minterm) if c.value=='X']
    if xs: lines.append('Selected X assignments: '+', '.join(xs))
    if model.form=='POS' and model.synthesis_f_prime is None:
        lines.append(f"Zero-groups give {model.output_name}' = {render(model.grouped_expression)}; complementing gives the POS above.")
    lines.append(f'Verified across all {len(model.cells)} input combinations.')
    if model.alternatives:
        lines.append(f'{len(model.alternatives)} equally minimal cover(s); selected by the existing D5 target-SOP ordering.')
    return '\n'.join(lines)
