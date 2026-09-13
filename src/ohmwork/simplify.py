"""Minimal-SOP simplification via Quine-McCluskey, used to report the
"simplified result" that M1a's `tt` command shows alongside the derivation
table.

This is intentionally a plain, textbook Quine-McCluskey + Petrick's method
implementation, scoped to what M1a needs: a correct minimal sum-of-products
for a fully-specified function of a handful of variables. It does not weigh
transistor cost — that is M1b's job (D1, D12) once the synthesis engine
exists. Where multiple minimal SOP covers tie on term count and literal
count, D5's canonicalization (shallow, cost-preserving, no identity
rewrites) breaks the tie deterministically.
"""

from __future__ import annotations

from itertools import combinations

from ohmwork.expr import Const, Expr, Not, Var, mk_and, mk_or


def _combine_terms(a: str, b: str) -> str | None:
    """Combine two bit-pattern terms (chars '0', '1', '-') if they differ in
    exactly one non-dash position; otherwise return None."""
    if len(a) != len(b):
        raise ValueError("terms must be the same length")
    diff_at = -1
    for i, (ca, cb) in enumerate(zip(a, b)):
        if ca != cb:
            if ca == "-" or cb == "-":
                return None  # dashes must line up to combine
            if diff_at != -1:
                return None  # more than one differing bit
            diff_at = i
    if diff_at == -1:
        return None  # identical terms, not a combination
    return a[:diff_at] + "-" + a[diff_at + 1 :]


def _prime_implicants(n_vars: int, minterms: set[int]) -> set[str]:
    """All prime implicants of the given minterms, as bit-pattern strings."""
    if not minterms:
        return set()
    terms = {format(m, f"0{n_vars}b") for m in minterms}
    primes: set[str] = set()
    current = terms
    while current:
        combined: set[str] = set()
        used: set[str] = set()
        current_list = list(current)
        for a, b in combinations(current_list, 2):
            merged = _combine_terms(a, b)
            if merged is not None:
                combined.add(merged)
                used.add(a)
                used.add(b)
        primes |= current - used
        current = combined
    return primes


def _term_covers(term: str, minterm: int, n_vars: int) -> bool:
    bits = format(minterm, f"0{n_vars}b")
    return all(t == "-" or t == b for t, b in zip(term, bits))


def _essential_cover(
    primes: set[str], minterms: set[int], n_vars: int
) -> tuple[set[str], set[int]]:
    """Pick every essential prime implicant (the only PI covering some
    minterm), returning the chosen implicants and the minterms still left
    to cover."""
    chart: dict[int, list[str]] = {
        m: [p for p in primes if _term_covers(p, m, n_vars)] for m in minterms
    }
    essential: set[str] = set()
    for m, covering in chart.items():
        if len(covering) == 1:
            essential.add(covering[0])
    covered: set[int] = set()
    for p in essential:
        covered |= {m for m in minterms if _term_covers(p, m, n_vars)}
    return essential, minterms - covered


def _minimal_extra_cover(
    primes: set[str], remaining: set[int], n_vars: int
) -> list[set[str]]:
    """All minimum-size sets of primes (from ``primes``) covering every
    minterm in ``remaining``, via Petrick's method. Returns every tie for
    the minimum size so the caller can break ties per D5."""
    if not remaining:
        return [set()]
    candidates = [p for p in primes if any(_term_covers(p, m, n_vars) for m in remaining)]
    # Petrick's method: product of sums -> sum of products, kept minimal.
    clauses = [
        frozenset(p for p in candidates if _term_covers(p, m, n_vars)) for m in remaining
    ]
    products: set[frozenset[str]] = {frozenset()}
    for clause in clauses:
        new_products: set[frozenset[str]] = set()
        for prod_set in products:
            for lit in clause:
                new_products.add(prod_set | {lit})
        # keep the search bounded: drop any product that is a strict
        # superset of another already found (it can never be minimal).
        minimal: set[frozenset[str]] = set()
        for p in new_products:
            if any(other < p for other in new_products):
                continue
            minimal.add(p)
        products = minimal
    best_size = min(len(p) for p in products)
    return [set(p) for p in products if len(p) == best_size]


def _term_to_expr(term: str, var_order: list[str]) -> Expr:
    literals: list[Expr] = []
    for ch, name in zip(term, var_order):
        if ch == "1":
            literals.append(Var(name))
        elif ch == "0":
            literals.append(Not(Var(name)))
    if not literals:
        return Const(True)  # every bit is a don't-care: the term is always true
    return mk_and(literals)


# A term's bit-pattern positions already line up with D10 variable order
# (position k is var_order[k]), so ranking each character and comparing the
# resulting tuples left-to-right sorts terms by D10 order directly: whichever
# term pins down an earlier variable sorts first (0 before 1 before don't-care
# at that position), matching the standard Quine-McCluskey convention of
# listing implicants by the smallest minterm they cover.
_CHAR_RANK = {"0": 0, "1": 1, "-": 2}


def _canonical_sort_key(term: str, var_order: list[str]) -> tuple:
    # D5: sort by D10 variable order, then string — applied here to the
    # term's own bit-pattern rather than a rendered AST, which is a direct,
    # deterministic proxy for the same ordering.
    return tuple(_CHAR_RANK[c] for c in term)


def minimize(var_order: list[str], minterms: set[int]) -> Expr:
    """Return a minimal sum-of-products :class:`Expr` for a function of
    ``var_order`` (in D10 order) that is true exactly on ``minterms``
    (each an int in ``[0, 2**len(var_order))``, bit ``k`` from the top
    corresponding to ``var_order[k]``)."""
    n_vars = len(var_order)
    full = set(range(2**n_vars))
    if minterms == full:
        return Const(True)
    if not minterms:
        return Const(False)

    primes = _prime_implicants(n_vars, minterms)
    essential, remaining = _essential_cover(primes, minterms, n_vars)
    extra_options = _minimal_extra_cover(primes, remaining, n_vars)

    best_terms: list[str] | None = None
    for extra in extra_options:
        candidate = sorted(essential | extra, key=lambda t: _canonical_sort_key(t, var_order))
        if best_terms is None:
            best_terms = candidate
            continue
        # D5 tie-break: canonical (rendered) form, compared lexicographically.
        candidate_str = " + ".join(str(_term_to_expr(t, var_order)) for t in candidate)
        best_str = " + ".join(str(_term_to_expr(t, var_order)) for t in best_terms)
        if candidate_str < best_str:
            best_terms = candidate

    assert best_terms is not None
    term_exprs = [_term_to_expr(t, var_order) for t in best_terms]
    return mk_or(term_exprs)


def simplify(var_order: list[str], values: list[bool]) -> Expr:
    """Simplify a fully-specified truth-table column (``values``, indexed
    the same way :func:`ohmwork.derivation.all_assignments` orders rows)
    into a minimal SOP expression."""
    minterms = {i for i, v in enumerate(values) if v}
    return minimize(var_order, minterms)
