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


def _literal_count(terms) -> int:
    """Total literal count across a set/iterable of bit-pattern terms —
    every non-dash position is one literal."""
    return sum(len(t) - t.count("-") for t in terms)


def minimal_covers(
    var_order: list[str], minterms: set[int], dont_cares: set[int] = frozenset()
) -> list[Expr] | None:
    """Every minimal sum-of-products cover tied for minimum term count, then
    minimum literal count — i.e. every candidate :func:`minimize` would
    consider before applying D5's own canonical-string tie-break. Exposed
    separately so a caller with its own cost model (M1b's synth.py, which
    additionally weighs shared-inverter cost per D12) can pick among these
    on its own terms rather than being handed only D5's single choice.

    Each returned :class:`Expr` is an ``Or`` (or a bare term/literal) with
    its own operands already in D5's canonical order. Returns ``None`` for
    the two constant cases (0 or 1), which have no "covers" in this sense —
    callers should fall back to :func:`minimize` for those."""
    n_vars = len(var_order)
    full = set(range(2**n_vars))
    care_set = minterms | dont_cares
    if not minterms or care_set == full:
        return None

    primes = _prime_implicants(n_vars, care_set)
    essential, remaining = _essential_cover(primes, minterms, n_vars)
    extra_options = _minimal_extra_cover(primes, remaining, n_vars)

    # Petrick's method above only minimizes the number of terms. Standard
    # minimal-SOP practice ranks ties by total literal count next — so
    # filter to the literal-minimal covers, otherwise a candidate that
    # merely sorts first lexicographically could beat one with strictly
    # fewer literals (that final lexicographic pick is minimize()'s job,
    # not this function's).
    covers = [essential | extra for extra in extra_options]
    best_literal_count = min(_literal_count(c) for c in covers)
    covers = [c for c in covers if _literal_count(c) == best_literal_count]

    results = []
    for cover in covers:
        ordered = sorted(cover, key=lambda t: _canonical_sort_key(t, var_order))
        results.append(mk_or([_term_to_expr(t, var_order) for t in ordered]))
    return results


def minimize(
    var_order: list[str], minterms: set[int], dont_cares: set[int] = frozenset()
) -> Expr:
    """Return a minimal sum-of-products :class:`Expr` for a function of
    ``var_order`` (in D10 order) that is true on ``minterms``, false outside
    ``minterms | dont_cares``, and free to be either on ``dont_cares`` (D4:
    "assigned freely to minimize transistor count"). Each is an int in
    ``[0, 2**len(var_order))``, bit ``k`` from the top corresponding to
    ``var_order[k]`` — the same convention as
    :func:`ohmwork.derivation.all_assignments`.

    Among :func:`minimal_covers`' ties, picks the one whose rendered form is
    lexicographically smallest (D5's canonical tie-break) — this is the
    right choice for reporting a single "the simplified result" (M1a's
    ``tt``), but a cost model beyond term/literal count (like M1b's
    transistor-and-inverter cost) should call :func:`minimal_covers`
    directly instead of assuming this pick is the cheapest for its purposes."""
    n_vars = len(var_order)
    full = set(range(2**n_vars))
    care_set = minterms | dont_cares
    if not minterms:
        # Every don't-care can be assigned 0 too, so the constant-0 function
        # (zero literals) is always available and always optimal here.
        return Const(False)
    if care_set == full:
        # Every position is either a required 1 or free — assigning every
        # don't-care to 1 satisfies all constraints at zero literal cost.
        return Const(True)

    covers = minimal_covers(var_order, minterms, dont_cares)
    assert covers is not None  # the constant cases were handled above
    return min(covers, key=lambda e: str(e))


def simplify(var_order: list[str], values: list[bool]) -> Expr:
    """Simplify a fully-specified truth-table column (``values``, indexed
    the same way :func:`ohmwork.derivation.all_assignments` orders rows)
    into a minimal SOP expression."""
    minterms = {i for i, v in enumerate(values) if v}
    return minimize(var_order, minterms)
