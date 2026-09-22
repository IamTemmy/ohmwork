"""D18 Phase 1: immutable, verified K-map data; no UI or transistor design.

A map always displays the supplied F table. ``grouped_expression`` is the
SOP of its grouping target (F for SOP, F' for POS); ``expression`` is the
corresponding SOP/POS of F. Synthesis attaches its exact chosen F' AST.
Cell indices stay binary while their row/column positions use Gray code.

Production grouping reuses simplify.py. The verifier independently enumerates
Boolean cubes and solves the tiny set-cover problem, never calling QM/Petrick.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from itertools import product
import re

from ohmwork.search_budget import SearchBudget
from ohmwork.derivation import evaluate
from ohmwork.expr import And, Const, Expr, Not, Or, Var, mk_and, mk_or, render
from ohmwork.simplify import minimal_covers, minimize, prime_implicant_patterns
from ohmwork.synth import SynthesisResult, de_morgan_complement
from ohmwork.truth_table import parse_var_list


@dataclass(frozen=True, slots=True)
class Rectangle:
    row: int
    column: int
    rows: int
    columns: int
    plane: int = 0


@dataclass(frozen=True, slots=True)
class VariableFact:
    variable: str
    fixed_value: int | None  # None: both values occur, so this variable disappears


@dataclass(frozen=True, slots=True)
class Group:
    id: str
    pattern: str
    minterms: tuple[int, ...]
    used_dont_cares: tuple[int, ...]
    term: Expr  # product for SOP, sum for POS, always a term of F
    facts: tuple[VariableFact, ...]
    explanation: str
    essential_witnesses: tuple[int, ...]
    pieces: tuple[Rectangle, ...]  # one group can have 2 or 4 visible wrap pieces
    wraps_rows: bool
    wraps_columns: bool

    @property
    def crosses_planes(self) -> bool:
        return len({p.plane for p in self.pieces}) > 1

    @property
    def essential(self) -> bool:
        return bool(self.essential_witnesses)


@dataclass(frozen=True, slots=True)
class Cell:
    row: int
    column: int
    minterm: int
    value: str  # original F: '0', '1', 'X' (never overwrite an X)
    assigned_value: int  # the selected expression's F value, including on Xs
    group_ids: tuple[str, ...]
    plane: int = 0


@dataclass(frozen=True, slots=True)
class KMap:
    var_order: tuple[str, ...]
    minterms: tuple[int, ...]
    dont_cares: tuple[int, ...]
    output_name: str
    form: str  # SOP or POS for F
    row_variables: tuple[str, ...]
    column_variables: tuple[str, ...]
    row_labels: tuple[str, ...]
    column_labels: tuple[str, ...]
    cells: tuple[Cell, ...]  # row-major VISUAL order, not binary minterm order
    groups: tuple[Group, ...]
    grouped_expression: Expr
    expression: Expr
    origin: str  # standalone / synthesis-AOI / synthesis-OAI
    alternatives: tuple[Expr, ...]  # standalone tied F expressions; empty for synthesis
    selected_alternative: int | None
    synthesis_f_prime: Expr | None
    plane_variable: str | None = None
    plane_labels: tuple[str, ...] = ('',)

    @property
    def grouping_value(self) -> int:
        return int(self.form == 'SOP')

    @property
    def term_count(self) -> int:
        return len(self.groups)

    @property
    def literal_count(self) -> int:
        return sum(sum(c != '-' for c in g.pattern) for g in self.groups)


def _input(var_order, minterms, dont_cares, form, output_name):
    variables = tuple(var_order)
    if not 1 <= len(variables) <= 5:
        raise ValueError('kmap supports 1-5 variables')
    if any(not isinstance(v, str) for v in variables):
        raise ValueError('variables must be D8 variable names')
    if tuple(parse_var_list(','.join(variables))) != variables:
        raise ValueError('variable names must not contain whitespace')
    if form not in ('SOP', 'POS'):
        raise ValueError('K-map form must be SOP or POS')
    if not isinstance(output_name, str) or not re.fullmatch(r'[A-Za-z][0-9]?', output_name):
        raise ValueError('output name must be a letter with an optional digit')
    if output_name in variables:
        raise ValueError('output name must not collide with an input variable')
    ones, dc = frozenset(minterms), frozenset(dont_cares)
    if any(type(m) is not int or not 0 <= m < 2**len(variables) for m in ones | dc):
        raise ValueError('minterm indices must be integers in the map range')
    if ones & dc:
        raise ValueError('minterms and dont_cares must be disjoint')
    return variables, ones, dc


def _gray(bits: int) -> tuple[str, ...]:
    return tuple(format(i ^ (i >> 1), f'0{bits}b') if bits else '' for i in range(2**bits))


def _members(pattern: str) -> tuple[int, ...]:
    return tuple(i for i in range(2**len(pattern))
                 if all(c == '-' or int(c) == ((i >> (len(pattern)-j-1)) & 1)
                        for j, c in enumerate(pattern)))


def _patterns(sop: Expr, variables: tuple[str, ...]) -> tuple[str, ...]:
    """Read only literal-product SOP ASTs; never parse text or distribute."""
    if isinstance(sop, Const):
        return ('-' * len(variables),) if sop.value else ()
    terms = sop.operands if isinstance(sop, Or) else (sop,)
    patterns = []
    for term in terms:
        literals = term.operands if isinstance(term, And) else (term,)
        fixed = {}
        for lit in literals:
            if isinstance(lit, Var):
                name, value = lit.name, '1'
            elif isinstance(lit, Not) and isinstance(lit.operand, Var):
                name, value = lit.operand.name, '0'
            else:
                raise ValueError('expected a literal-product SOP, not a factored expression')
            if name not in variables or name in fixed:
                raise ValueError('SOP term has an unknown or repeated variable')
            fixed[name] = value
        if not literals:
            raise ValueError('empty SOP product')
        patterns.append(''.join(fixed.get(v, '-') for v in variables))
    if len(set(patterns)) != len(patterns):
        raise ValueError('duplicate SOP groups')
    return tuple(patterns)


def _term(facts: tuple[VariableFact, ...], form: str) -> Expr:
    literals = []
    for f in facts:
        if f.fixed_value is not None:
            positive = f.fixed_value == (1 if form == 'SOP' else 0)
            literals.append(Var(f.variable) if positive else Not(Var(f.variable)))
    if not literals:
        return Const(form == 'SOP')
    return mk_and(literals) if form == 'SOP' else mk_or(literals)


def _narrate(facts: tuple[VariableFact, ...], term: Expr, form: str, plane_variable: str | None = None) -> str:
    clauses = [f'{f.variable} changes between 0 and 1, so it is eliminated' if f.fixed_value is None
               else f'{f.variable} stays {f.fixed_value}' for f in facts]
    noun = 'product' if form == 'SOP' else 'sum'
    rule = ('For a 1-group, fixed 0 gives a complemented literal and fixed 1 an uncomplemented literal.'
            if form == 'SOP' else
            'For a 0-group, fixed 0 gives an uncomplemented literal and fixed 1 a complemented literal.')
    text = '; '.join(clauses) + f'. {rule} The {noun} term is {render(term)}.'
    if plane_variable is not None:
        plane_fact = next(f for f in facts if f.variable == plane_variable)
        if plane_fact.fixed_value is None:
            text += (f' This group spans matching positions in both {plane_variable}=0 and '
                     f'{plane_variable}=1 planes, eliminating {plane_variable}.')
        else:
            text += f' This group occupies only the {plane_variable}={plane_fact.fixed_value} plane.'
    return text


def _runs(indices):
    runs = []
    for i in sorted(set(indices)):
        if runs and i == runs[-1][0] + runs[-1][1]:
            runs[-1] = (runs[-1][0], runs[-1][1] + 1)
        else:
            runs.append((i, 1))
    return runs


def _assemble(variables, ones, dc, form, output_name, sop, origin, alternatives=(), chosen=None):
    plane_bits = int(len(variables) == 5)
    axis_variables = variables[plane_bits:]
    split = len(axis_variables)//2
    plane_labels = ('0', '1') if plane_bits else ('',)
    row_labels, column_labels = _gray(split), _gray(len(axis_variables)-split)
    positions = {int(p+r+c, 2):(pi, ri, ci) for pi,p in enumerate(plane_labels)
                 for ri,r in enumerate(row_labels) for ci,c in enumerate(column_labels)}
    target = ones if form == 'SOP' else frozenset(range(2**len(variables))) - ones - dc
    primes = prime_implicant_patterns(list(variables), set(target), set(dc))
    groups = []
    for index, pattern in enumerate(_patterns(sop, variables)):
        members = _members(pattern)
        facts = tuple(VariableFact(v, None if bit == '-' else int(bit))
                      for v, bit in zip(variables, pattern))
        term = _term(facts, form)
        planes = sorted({positions[m][0] for m in members})
        rs = {positions[m][1] for m in members}; cs = {positions[m][2] for m in members}
        pieces = tuple(Rectangle(r, c, h, w, plane) for plane in planes
                       for r,h in _runs(rs) for c,w in _runs(cs))
        witnesses = tuple(m for m in members if m in target and
                          sum(m in _members(p) for p in primes) == 1)
        groups.append(Group(f'G{index+1}', pattern, members, tuple(m for m in members if m in dc),
                            term, facts, _narrate(facts, term, form, variables[0] if plane_bits else None), witnesses, pieces,
                            len(_runs(rs)) > 1, len(_runs(cs)) > 1))
    expression = sop if form == 'SOP' else de_morgan_complement(sop)
    cells = tuple(Cell(ri, ci, int(p+r+c, 2),
                       'X' if int(p+r+c, 2) in dc else str(int(int(p+r+c, 2) in ones)),
                       int(evaluate(expression, dict(zip(variables, map(bool, map(int, p+r+c)))))),
                       tuple(g.id for g in groups if int(p+r+c, 2) in g.minterms), pi)
                  for pi,p in enumerate(plane_labels) for ri,r in enumerate(row_labels)
                  for ci,c in enumerate(column_labels))
    return KMap(variables, tuple(sorted(ones)), tuple(sorted(dc)), output_name, form,
                axis_variables[:split], axis_variables[split:], row_labels, column_labels,
                cells, tuple(groups), sop, expression, origin, alternatives,
                alternatives.index(expression) if alternatives else None, chosen,
                variables[0] if plane_bits else None, plane_labels)


def _finish(model, variables, ones, dc, form, output_name, sop):
    if (model.var_order, model.minterms, model.dont_cares, model.form, model.output_name,
        model.grouped_expression) != (variables, tuple(sorted(ones)), tuple(sorted(dc)),
                                     form, output_name, sop):
        raise RuntimeError('K-map source fidelity failed')
    validate_kmap(model)
    return model


def build_kmap(
    var_order: Sequence[str], minterms: Iterable[int], dont_cares: Iterable[int] = frozenset(),
    *, form: str = 'SOP', output_name: str = 'F',
) -> KMap:
    """Public one- through four-variable map until D20 Phase 2."""
    if not 1 <= len(var_order) <= 4:
        raise ValueError('kmap supports 1-4 variables')
    return _build_kmap(var_order, minterms, dont_cares, form=form, output_name=output_name)


def _build_kmap(var_order, minterms, dont_cares=frozenset(), *, form='SOP', output_name='F'):
    """Internal D20 model, using existing term/literal/D5 policy."""
    variables, ones, dc = _input(var_order, minterms, dont_cares, form, output_name)
    target = ones if form == 'SOP' else frozenset(range(2**len(variables))) - ones - dc
    covers = minimal_covers(list(variables), set(target), set(dc),
                            _budget=SearchBudget() if len(variables) == 5 else None)
    if covers is None:
        covers = [minimize(list(variables), set(target), set(dc))]
    # POS ordering follows the target SOP of F', exactly the existing D5 choice.
    sop = min(covers, key=str)
    alternatives = tuple(c if form == 'SOP' else de_morgan_complement(c) for c in covers)
    model = _assemble(variables, ones, dc, form, output_name, sop, 'standalone', alternatives)
    if model.origin != 'standalone' or model.alternatives != alternatives:
        raise RuntimeError('K-map standalone provenance failed')
    return _finish(model, variables, ones, dc, form, output_name, sop)


def build_synthesis_kmap(result: SynthesisResult, output_name: str = 'F') -> KMap:
    """Public synthesis map until D20's two-plane presentation ships."""
    if not 1 <= len(result.var_order) <= 4:
        raise ValueError('kmap supports 1-4 variables')
    return _build_synthesis_kmap(result, output_name)


def _build_synthesis_kmap(result: SynthesisResult, output_name: str = 'F') -> KMap:
    """Explain the exact chosen candidate; never run cover selection again."""
    if result.minterms is None or result.dont_cares is None:
        raise ValueError('synthesis result lacks original minterms/dont_cares')
    if not result.verification.passed:
        raise ValueError('cannot explain an unverified synthesis result')
    chosen = result.chosen
    if chosen.label not in ('AOI', 'OAI') or result.chosen_label != chosen.label or result.f_prime != chosen.f_prime:
        raise ValueError('inconsistent synthesis candidate provenance')
    form = 'POS' if chosen.label == 'AOI' else 'SOP'
    variables, ones, dc = _input(result.var_order, result.minterms, result.dont_cares, form, output_name)
    sop = chosen.f_prime if form == 'POS' else de_morgan_complement(chosen.f_prime)
    _patterns(sop, variables)  # reject unsupported future synthesis shapes explicitly
    if form == 'SOP' and de_morgan_complement(sop) != chosen.f_prime:
        raise ValueError('chosen expression cannot be reconstructed exactly')
    model = _assemble(variables, ones, dc, form, output_name, sop, 'synthesis-' + chosen.label,
                      chosen=chosen.f_prime)
    if model.origin != 'synthesis-' + chosen.label or model.synthesis_f_prime != chosen.f_prime:
        raise RuntimeError('K-map synthesis provenance failed')
    _finish(model, variables, ones, dc, form, output_name, sop)
    # The displayed F-to-F' equation must reconstruct the chosen AST in both
    # directions, including AOI's POS-for-F presentation.
    if de_morgan_complement(model.expression) != chosen.f_prime:
        raise RuntimeError('displayed expression cannot reconstruct the chosen PDN exactly')
    assigned = {c.minterm:bool(c.assigned_value) for c in model.cells if c.value == 'X'}
    if assigned != result.verification.dont_care_assignments:
        raise RuntimeError('K-map assignments differ from the verified circuit')
    return model


# Independent checker: enumerate all 3^n cubes, not QM or the builder's members.
def _legal_primes(n, target, dc):
    legal = {}
    for pattern in product('01-', repeat=n):
        members = frozenset(sum(bit << (n-i-1) for i,bit in enumerate(bits))
                            for bits in product(*[(0,1) if ch == '-' else (int(ch),) for ch in pattern]))
        if members & target and members <= target | dc:
            legal[''.join(pattern)] = members
    return {p:ms for p,ms in legal.items() if not any(ms < other for other in legal.values())}


def _optimal_covers(primes, target, *, _budget=None):
    """Independent exact-cover oracle, with bounded five-variable storage."""
    budget = (_budget or SearchBudget()) if any(len(p) == 5 for p in primes) else None
    retained = 0
    @lru_cache(None)
    def search(remaining):
        nonlocal retained
        if budget:
            budget.check(items=retained + search.cache_info().currsize)
        if not remaining:
            return (0,0), frozenset({frozenset()})
        m = min(remaining)
        best = None; covers = set()
        for p, members in sorted(primes.items()):
            if budget:
                budget.check()
            if m not in members:
                continue
            cost, tails = search(remaining - members)
            score = (1 + cost[0], len(p)-p.count('-') + cost[1])
            if best is None or score < best:
                best, covers = score, set()
            if score == best:
                for t in sorted(tails, key=lambda t: tuple(sorted(t))):
                    covers.add(t | {p})
                    if budget:
                        budget.check(items=retained + len(covers) + search.cache_info().currsize)
        retained += len(covers)
        if budget:
            budget.check(work=0, items=retained + search.cache_info().currsize)
        return best, frozenset(covers)
    return search(frozenset(target))


def validate_kmap(model: KMap) -> None:
    """Reject malformed data, false algebra/narration, and visual cell drift.

    Raises RuntimeError. This gate runs before either public builder returns.
    For source identity relative to an external input/result, builders also run
    _finish and the synthesis provenance/assignment checks above.
    """
    def check(ok, message):
        if not ok:
            raise RuntimeError('invalid K-map: ' + message)
    try:
        variables, ones, dc = _input(model.var_order, model.minterms, model.dont_cares,
                                     model.form, model.output_name)
    except ValueError as exc:
        raise RuntimeError('invalid K-map input: ' + str(exc)) from exc
    n = len(variables); plane_bits = int(n == 5)
    axis_variables = variables[plane_bits:]
    split = len(axis_variables)//2; full = frozenset(range(2**n))
    check(model.minterms == tuple(sorted(ones)) and model.dont_cares == tuple(sorted(dc)), 'source sets')
    axes = {0:('',), 1:('0','1'), 2:('00','01','11','10')}
    rows, cols = axes[split], axes[n-plane_bits-split]
    planes = ('0','1') if plane_bits else ('',)
    check((model.plane_variable, model.plane_labels) ==
          (variables[0] if plane_bits else None, planes), 'plane metadata')
    check((model.row_variables,model.column_variables,model.row_labels,model.column_labels) ==
          (axis_variables[:split],axis_variables[split:],rows,cols), 'axis mapping')
    expected_cells = [(pi,ri,ci,int(p+r+c,2)) for pi,p in enumerate(planes) for ri,r in enumerate(rows) for ci,c in enumerate(cols)]
    check(all(type(c.plane) is int for c in model.cells), 'cell plane type')
    check([(c.plane,c.row,c.column,c.minterm) for c in model.cells] == expected_cells, 'cell mapping')
    target = ones if model.form == 'SOP' else full - ones - dc
    primes = _legal_primes(n, target, dc)
    check(model.origin in ('standalone','synthesis-AOI','synthesis-OAI'), 'origin')
    check(tuple(g.id for g in model.groups) == tuple(f'G{i+1}' for i in range(len(model.groups))), 'group IDs')
    check(len({g.pattern for g in model.groups}) == len(model.groups), 'duplicate groups')
    covered = set(); expected_sop_terms = []; expected_terms = []
    for g in model.groups:
        check(g.pattern in primes, 'group is not a relevant prime cube')
        members = primes[g.pattern]
        check(g.minterms == tuple(sorted(members)), 'group membership')
        covered.update(members)
        facts = []
        for i,v in enumerate(variables):
            values = {(m >> (n-i-1)) & 1 for m in members}
            facts.append(VariableFact(v, next(iter(values)) if len(values)==1 else None))
        facts = tuple(facts)
        check(g.facts == facts, 'fixed/varying variable facts')
        # AST built directly from recomputed member-bit facts; compare structure
        # as well as evaluation, so reordered/wrong group explanations cannot hide.
        term = _term(facts, model.form)
        expected_terms.append(term); expected_sop_terms.append(_term(facts, 'SOP'))
        check(g.term == term and g.explanation == _narrate(facts, term, model.form, model.plane_variable), 'term or explanation')
        check(g.used_dont_cares == tuple(sorted(members & dc)), 'used dont-cares')
        witnesses = tuple(sorted(m for m in members & target if sum(m in ms for ms in primes.values()) == 1))
        check(g.essential_witnesses == witnesses, 'essential witnesses')
        positions = {(c.plane,c.row,c.column) for c in model.cells if c.minterm in members}
        drawn = []
        for p in g.pieces:
            check(all(type(v) is int for v in (p.plane,p.row,p.column,p.rows,p.columns)), 'piece integer geometry')
            check(0 <= p.plane < len(planes) and 0 <= p.row < len(rows) and 0 <= p.column < len(cols) and p.rows > 0 and p.columns > 0
                  and p.row+p.rows <= len(rows) and p.column+p.columns <= len(cols), 'piece bounds')
            drawn.extend((p.plane,r,c) for r in range(p.row,p.row+p.rows) for c in range(p.column,p.column+p.columns))
        check(len(drawn)==len(set(drawn)) and set(drawn)==positions, 'piece cell coverage')
        # Maximal visible components, so splitting an ordinary rectangle is rejected.
        pending = set(positions); components = []
        while pending:
            seed = min(pending); pending.remove(seed); component={seed}; queue=[seed]
            while queue:
                plane,r,c=queue.pop()
                for point in ((plane,r-1,c),(plane,r+1,c),(plane,r,c-1),(plane,r,c+1)):
                    if point in pending:
                        pending.remove(point); component.add(point); queue.append(point)
            rs=[p[1] for p in component]; cs=[p[2] for p in component]
            components.append(Rectangle(min(rs),min(cs),max(rs)-min(rs)+1,max(cs)-min(cs)+1,seed[0]))
        check(g.pieces == tuple(sorted(components,key=lambda p:(p.plane,p.row,p.column))), 'piece fragmentation/order')
        rs={p[1] for p in positions}; cs={p[2] for p in positions}
        wr=len(rs)<len(rows) and 0 in rs and len(rows)-1 in rs
        wc=len(cs)<len(cols) and 0 in cs and len(cols)-1 in cs
        check((g.wraps_rows,g.wraps_columns)==(wr,wc), 'wrap flags')
    check(target <= covered, 'missing required coverage')
    sop = mk_or(expected_sop_terms) if expected_sop_terms else Const(False)
    expression = (mk_or(expected_terms) if model.form=='SOP' else mk_and(expected_terms)) if expected_terms else Const(model.form=='POS')
    check(model.grouped_expression == sop and model.expression == expression, 'cover expression/polarity')
    for c in model.cells:
        check(c.value == ('X' if c.minterm in dc else str(int(c.minterm in ones))), 'original cell value')
        assignment = {v:bool((c.minterm >> (n-i-1))&1) for i,v in enumerate(variables)}
        value = int(evaluate(model.expression, assignment))
        check(type(c.assigned_value) is int and c.assigned_value==value, 'selected cell value')
        check(c.minterm in dc or value==int(c.minterm in ones), 'functional equivalence')
        check(c.group_ids==tuple(g.id for g in model.groups if c.minterm in g.minterms), 'cell group links')
    if model.origin == 'standalone':
        check(model.synthesis_f_prime is None, 'unexpected synthesis expression')
        cost, optimal = _optimal_covers(primes,target)
        check((model.term_count,model.literal_count)==cost, 'nonminimal standalone cover')
        check(len(model.alternatives)>0 and type(model.selected_alternative) is int, 'alternative selection')
        check(0 <= model.selected_alternative < len(model.alternatives), 'alternative index')
        check(model.alternatives[model.selected_alternative]==model.expression, 'selected alternative')
        alternative_patterns=[]; keys=[]
        for alt in model.alternatives:
            target_expr = alt if model.form=='SOP' else de_morgan_complement(alt)
            try:
                ps = _patterns(target_expr,variables)
            except ValueError as exc:
                raise RuntimeError('invalid K-map alternative') from exc
            ordered = sorted(ps, key=lambda p: tuple({'0':0, '1':1, '-':2}[c] for c in p))
            terms = [_term(tuple(VariableFact(v, None if c == '-' else int(c))
                                 for v,c in zip(variables,p)), 'SOP') for p in ordered]
            canonical = mk_or(terms) if terms else Const(False)
            check(target_expr == canonical, 'alternative is not in D5 canonical form')
            alternative_patterns.append(frozenset(ps)); keys.append(str(target_expr))
        check(len(alternative_patterns)==len(set(alternative_patterns)) and set(alternative_patterns)==set(optimal), 'tied cover inventory')
        check(keys==sorted(keys) and model.selected_alternative==0, 'D5 tie ordering')
    else:
        check(not model.alternatives and model.selected_alternative is None, 'synthesis must not reselect alternatives')
        check(model.form==('POS' if model.origin=='synthesis-AOI' else 'SOP'), 'synthesis grouping direction')
        fp=sop if model.form=='POS' else de_morgan_complement(sop)
        check(model.synthesis_f_prime==fp, 'exact chosen AST reconstruction')
