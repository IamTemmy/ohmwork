"""Worked Boolean reductions of verified K-map groups, never a new optimizer."""
from itertools import product
from ohmwork.expr import And, Or, Not, Var, Const
from ohmwork.derivation import evaluate

# Original wording and conventional identities, shared by UI and copy report.
LAWS = (
    ('Identity', 'x + 0 = x; x · 1 = x'),
    ('Complement', "x + x' = 1; x · x' = 0"),
    ('Idempotent', 'x + x = x; x · x = x'),
    ('Domination', 'x + 1 = 1; x · 0 = 0'),
    ('Double complement', "(x')' = x"),
    ('Commutative', 'x + y = y + x; x · y = y · x'),
    ('Associative', '(x + y) + z = x + (y + z); (x · y) · z = x · (y · z)'),
    ('Distributive', 'x · (y + z) = x · y + x · z; x + y · z = (x + y) · (x + z)'),
    ('De Morgan', "(x + y)' = x' · y'; (x · y)' = x' + y'"),
    ('Absorption', 'x + x · y = x; x · (x + y) = x'),
)


def _join(kind, terms):
    terms = tuple(terms)
    return terms[0] if len(terms) == 1 else kind(terms)


def _text(expr):
    """Explicit multiplication prevents a1 · 1 looking like a variable a11."""
    if isinstance(expr, Var): return expr.name
    if isinstance(expr, Const): return str(int(expr.value))
    if isinstance(expr, Not): return _text(expr.operand) + "'"
    sep = ' · ' if isinstance(expr, And) else ' + '
    return sep.join('(' + _text(t) + ')' if isinstance(expr, And) and isinstance(t, Or)
                    else _text(t) for t in expr.operands)


def group_work(model, group):
    """Pair cube terms, name the actual laws, verify every row independently.

    SOP sums minterms; POS multiplies maxterms. DC members are assigned only
    for this selected cover, never asserted to be specified input values.
    """
    sop = model.form == 'SOP'
    inner, outer = (And, Or) if sop else (Or, And)
    variables = model.var_order
    patterns = [format(m, f'0{len(variables)}b') for m in group.minterms]

    def term(pattern):
        literals = [Var(v) if (bit == '1') == sop else Not(Var(v))
                    for v, bit in zip(variables, pattern) if bit != '-']
        return _join(inner, literals) if literals else Const(sop)

    rows = []
    def add(expr, law, reason):
        rows.append((expr, {'expression': _text(expr), 'law': law, 'reason': reason}))

    add(_join(outer, map(term, patterns)), 'Expansion',
        'Write each cell as a minterm (1 only at that input).' if sop else
        'Write each cell as a maxterm (0 only at that input).')
    # Eliminate from the last variable backwards, like ordinary handwritten work.
    for axis in reversed(range(len(variables))):
        if group.pattern[axis] != '-': continue
        buckets = {}
        for p in patterns:
            key = p[:axis] + '-' + p[axis+1:]
            buckets.setdefault(key, []).append(p)
        if any(len(ps) != 2 or {p[axis] for p in ps} != {'0', '1'} for ps in buckets.values()):
            raise ValueError('worked group is not a complete Boolean cube')
        patterns = sorted(buckets)
        v = Var(variables[axis])
        pair = Or((Not(v), v)) if sop else And((v, Not(v)))
        add(_join(outer, (inner((term(p), pair)) for p in patterns)), 'Distributive',
            f'Pair terms differing only in {v.name}; factor their common literals (reordering as needed).')
        add(_join(outer, (inner((term(p), Const(sop))) for p in patterns)), 'Complement',
            f"{v.name}' + {v.name} = 1." if sop else f"{v.name} · {v.name}' = 0.")
        add(_join(outer, map(term, patterns)), 'Identity',
            'Remove multiplication by 1.' if sop else 'Remove addition of 0.')

    for bits in product((False, True), repeat=len(variables)):
        assignment = dict(zip(variables, bits))
        index = sum(int(b) << (len(bits)-i-1) for i,b in enumerate(bits))
        expected = (index in group.minterms) if sop else (index not in group.minterms)
        if any(bool(evaluate(expr, assignment)) != expected for expr, _ in rows):
            raise ValueError('worked group step failed independent cell-set verification')
        if bool(evaluate(group.term, assignment)) != expected:
            raise ValueError('worked reduction does not match the selected group term')
    prefix, separator = ('m', ' + ') if sop else ('M', ' · ')
    used = set(group.used_dont_cares)
    notation = separator.join(f'{prefix}{m}' + (' [X]' if m in used else '') for m in group.minterms)
    note = (f"[X] marks an original don't-care included as {model.grouping_value} for this cover. "
            'The equalities describe this selected group, not a fixed value in the original specification.') if used else ''
    return {'title': f'Group {group.id[1:]} ({group.id})', 'notation': notation,
            'steps': [row for _, row in rows], 'note': note,
            'result': _text(group.term)}
