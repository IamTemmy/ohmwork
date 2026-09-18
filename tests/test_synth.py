"""Tests for M1b's synthesis core: AOI/OAI candidate generation, cost
comparison, gate naming, inverter accounting, and the minimality proof."""

import pytest

from ohmwork.derivation import all_assignments, evaluate
from ohmwork.expr import render as render_expr
from ohmwork.parser import parse
from ohmwork.synth import de_morgan_complement, synthesize


def minterms_from_expr(var_order: list[str], expr_text: str) -> set[int]:
    """Helper: derive a minterm set from a D8 expression, so acceptance-test
    gates can be specified the way the exam states them (e.g. "(abc)'")
    rather than as hand-computed bit patterns."""
    ast = parse(expr_text)
    rows = all_assignments(var_order)
    return {i for i, row in enumerate(rows) if evaluate(ast, row)}


# --- M1b acceptance test (docs/CHARTER.md §8): CPE 635 Fall 2026 Exam #1 ---


def test_acceptance_3_input_nand():
    var_order = ["a", "b", "c"]
    minterms = minterms_from_expr(var_order, "(abc)'")
    result = synthesize(var_order, minterms)
    assert result.gate_name == "3-input NAND"
    assert result.pdn_transistors == 3
    assert result.pun_transistors == 3
    assert result.inverter_transistors == 0
    assert result.total_transistors == 6
    assert result.minimality_proof is not None


def test_acceptance_4_input_nor():
    var_order = ["a", "b", "c", "d"]
    minterms = minterms_from_expr(var_order, "(a+b+c+d)'")
    result = synthesize(var_order, minterms)
    assert result.gate_name == "4-input NOR"
    assert result.pdn_transistors == 4
    assert result.pun_transistors == 4
    assert result.inverter_transistors == 0
    assert result.total_transistors == 8
    assert result.minimality_proof is not None


def test_acceptance_aoi31():
    var_order = ["a", "b", "c", "d"]
    minterms = minterms_from_expr(var_order, "(abc+d)'")
    result = synthesize(var_order, minterms)
    assert result.gate_name == "AOI31"
    assert result.pdn_transistors == 4
    assert result.pun_transistors == 4
    assert result.inverter_transistors == 0
    assert result.total_transistors == 8
    assert result.minimality_proof is not None


# --- Minimality proof wording is scoped to complementary static CMOS ---------
#
# A 2026-09-18 ChatGPT review (Q3 dogfooding against the exam) flagged the
# proof's old wording -- "no design in any search space could use fewer
# transistors" -- as broader than what's actually proven: the D6 argument
# only bounds complementary static CMOS (PDN+PUN transistors), not
# pass-transistor logic, ratioed logic, dynamic logic, or any other
# circuit family. Wording-only fix; the proof still fires on exactly the
# same cases (see the three acceptance tests above, all unaffected).


@pytest.mark.parametrize(
    "var_order,expr_text",
    [
        (["a", "b", "c"], "(abc)'"),
        (["a", "b", "c", "d"], "(a+b+c+d)'"),
        (["a", "b", "c", "d"], "(abc+d)'"),
    ],
)
def test_minimality_proof_is_scoped_to_complementary_static_cmos(var_order, expr_text):
    minterms = minterms_from_expr(var_order, expr_text)
    result = synthesize(var_order, minterms)
    proof = result.minimality_proof
    assert proof is not None
    assert "complementary static CMOS" in proof
    assert "any search space" not in proof


# --- de_morgan_complement ----------------------------------------------------


def test_de_morgan_complement_and_becomes_or_of_complements():
    assert str(de_morgan_complement(parse("ab"))) == "a' + b'"


def test_de_morgan_complement_or_becomes_and_of_complements():
    assert str(de_morgan_complement(parse("a+b"))) == "a'b'"


def test_de_morgan_complement_is_involutive():
    for expr_text in ["ab+c", "(a+b)cd", "a'b + c'"]:
        ast = parse(expr_text)
        assert de_morgan_complement(de_morgan_complement(ast)) == ast


# --- OAI candidate wins when factoring saves a shared literal --------------


def test_oai_beats_aoi_when_a_literal_can_be_shared():
    # ((a+b)c)': F' = (a+b)c uses c once (3 literals: a,b,c). Expanding F'
    # to flat minimal SOP (ac+bc) needs 4 literals instead. Minimizing F
    # itself and complementing it recovers the compact factored form.
    var_order = ["a", "b", "c"]
    minterms = minterms_from_expr(var_order, "((a+b)c)'")
    result = synthesize(var_order, minterms)
    assert result.chosen_label == "OAI"
    assert result.gate_name == "OAI21"
    assert result.pdn_transistors == 3
    assert result.pun_transistors == 3
    assert result.inverter_transistors == 0
    assert result.total_transistors == 6
    assert result.minimality_proof is not None  # 3 literals, 3 essential vars


# --- Inverter accounting (D2/D12) -------------------------------------------


def test_dual_rail_removes_inverter_cost():
    var_order = ["a", "b", "c"]
    minterms = minterms_from_expr(var_order, "(a'b+c)'")
    normal = synthesize(var_order, minterms)
    dual_rail = synthesize(var_order, minterms, dual_rail=True)
    assert normal.inverter_literals  # this function does need a complement
    assert dual_rail.inverter_transistors == 0
    assert normal.inverter_transistors == 2 * len(normal.inverter_literals)
    assert normal.total_transistors - dual_rail.total_transistors == normal.inverter_transistors
    # everything else about the chosen network is unaffected by dual-rail
    assert normal.pdn_transistors == dual_rail.pdn_transistors
    assert normal.pun_transistors == dual_rail.pun_transistors


def test_shared_inverter_counted_once_regardless_of_fanout():
    # a' appears in two product terms; D12 says one inverter, not two.
    var_order = ["a", "b", "c"]
    minterms = minterms_from_expr(var_order, "(a'b+a'c)'")
    result = synthesize(var_order, minterms)
    assert result.inverter_literals == ("a",)
    assert result.inverter_transistors == 2


# --- Don't-cares (D4) ---------------------------------------------------------


def test_dont_care_reduces_transistor_count():
    # F=1 on minterm 0 only, minterm 1 is don't-care (2 vars a,b): assigning
    # the don't-care to 1 lets QM combine {0,1} into the single literal a'.
    result = synthesize(["a", "b"], minterms={0}, dont_cares={1})
    assert result.total_transistors == 2  # a single-literal gate: 1 PDN + 1 PUN


# --- Stack height / D3 advisory ----------------------------------------------


def test_stack_advisory_absent_for_shallow_stacks():
    var_order = ["a", "b", "c"]
    minterms = minterms_from_expr(var_order, "(abc)'")
    result = synthesize(var_order, minterms)
    assert result.pdn_stack_height == 3
    assert result.stack_advisory is None  # 3 <= the threshold of 4


def test_max_stack_rejects_when_no_candidate_fits():
    var_order = ["a", "b", "c"]
    minterms = minterms_from_expr(var_order, "(abc)'")
    with pytest.raises(ValueError, match="max-stack"):
        synthesize(var_order, minterms, max_stack=1)


def test_max_stack_accepts_a_compliant_function():
    # A single-transistor gate is the only shape where BOTH PDN and PUN stay
    # at stack height 1 — any n>=2-input NAND/NOR has one side at height n
    # (e.g. NOR2's PUN, the series dual of its parallel PDN, is height 2).
    var_order = ["a"]
    minterms = minterms_from_expr(var_order, "a'")
    result = synthesize(var_order, minterms, max_stack=1)
    assert result.gate_name == "inverter (1 input)"
    assert result.pdn_stack_height == 1
    assert result.pun_stack_height == 1


# --- Gate naming: deeper AOI/OAI generalizations ----------------------------
#
# synth._gate_name also has a "custom complex gate" fallback for a PDN shape
# it doesn't recognize, but that path is currently unreachable through this
# module's public API: Quine-McCluskey always returns a flat 2-level SOP
# (Or-of-Ands, or its And-of-Ors complement), so the AOI candidate's PDN is
# always Parallel-of-(Transistor|flat-Series) and the OAI candidate's is
# always Series-of-(Transistor|flat-Parallel) — both are always nameable.
# The fallback exists for when a future factoring pass can produce deeper
# nesting; these two tests instead confirm naming generalizes correctly to
# more than two branch sizes.


def test_gate_naming_generalizes_to_more_than_two_terms():
    var_order = ["a", "b", "c", "d"]
    minterms = minterms_from_expr(var_order, "(ab+c+d)'")
    result = synthesize(var_order, minterms)
    assert result.gate_name == "AOI211"


def test_gate_naming_generalizes_for_oai_too():
    var_order = ["a", "b", "c", "d"]
    minterms = minterms_from_expr(var_order, "((a+d)(b+c+d))'")
    result = synthesize(var_order, minterms)
    assert result.gate_name == "OAI32"


# --- Regressions from ChatGPT's M1b review ----------------------------------
#
# Selection previously compared only PDN+PUN cost, excluding inverters, and
# minimize() had already committed to one lexicographically-first cover
# before synthesis ever saw a cheaper (fewer-inverter) tied alternative.
# Both are exact reproducers from that review.


def test_selection_accounts_for_inverter_cost_not_just_core_cost():
    # One AOI cover and one OAI cover both core-tie at 10 transistors, but
    # need different numbers of complemented literals: 3 (16T total) vs 4
    # (18T total). The cheaper one must win regardless of which direction
    # found it -- picking the 18T design here was the exact reported bug.
    var_order = ["a", "b", "c", "d"]
    result = synthesize(var_order, minterms={1, 3, 4, 5, 11, 13, 14}, dont_cares={6, 7, 10, 12, 15})
    assert result.total_transistors == 16
    assert all(c.total_cost >= 16 for c in result.other_candidates)


def test_tied_covers_within_one_direction_are_compared_on_inverter_cost():
    # Two literal-minimal covers of F' both cost 6 core transistors (a'cd
    # and bcd), but only one needs an inverter -- the inverter-free cover
    # must win even though it doesn't sort first lexicographically.
    var_order = ["a", "b", "c", "d"]
    result = synthesize(var_order, minterms={0, 1, 2, 5, 6, 9, 10, 11}, dont_cares={3, 4, 8, 12, 13, 14, 15})
    assert result.total_transistors == 6
    assert result.inverter_transistors == 0
    assert render_expr(result.f_prime) == "bcd"


def test_verification_is_checked_before_a_result_is_ever_returned():
    # Every SynthesisResult carries a verification that has already passed
    # -- synthesize() itself is the gate (D7), not something layered on
    # after the fact by a caller that might forget to check it.
    var_order = ["a", "b", "c"]
    minterms = minterms_from_expr(var_order, "(abc)'")
    result = synthesize(var_order, minterms)
    assert result.verification.passed is True


def test_synthesize_raises_rather_than_return_a_design_that_fails_verification(monkeypatch):
    # A real failure can't occur through normal input (that's the point of
    # the fix) -- so this forces the internal verify() call to report one,
    # confirming synthesize() actually gates on it rather than trusting the
    # construction. ChatGPT's review found the CLI previously printed such
    # a design with exit code 0.
    import ohmwork.synth as synth_module
    from ohmwork.verify import VerificationResult

    fake = VerificationResult(
        vector_count=8,
        functional_pass=False,
        structural_pass=False,
        mismatches=(3,),
        floating=(1,),
        shorted=(2,),
        dont_care_assignments={},
    )
    monkeypatch.setattr(synth_module, "verify", lambda *a, **k: fake)
    with pytest.raises(RuntimeError, match="failed its own D7 verification"):
        synthesize(["a", "b", "c"], minterms=minterms_from_expr(["a", "b", "c"], "(abc)'"))


def test_synth_rejects_five_or_more_variables():
    with pytest.raises(ValueError, match="1-4 variables"):
        synthesize(["a", "b", "c", "d", "e"], minterms={0})


def test_synth_rejects_zero_variables():
    with pytest.raises(ValueError, match="1-4 variables"):
        synthesize([], minterms=set())


def test_false_minimality_claim_no_longer_occurs():
    # Third reproducer from the same review: the buggy selection previously
    # picked a 14-transistor design here and reported it "proven minimal";
    # a cheaper 12-transistor cover was available and should now win, and
    # since it doesn't use every declared variable (only 3 of 4), it must
    # NOT claim proof (D6) -- unlike the false claim before the fix.
    var_order = ["a", "b", "c", "d"]
    result = synthesize(var_order, minterms={7, 8, 12, 14, 15}, dont_cares={0, 1, 4, 6, 10})
    assert result.total_transistors == 12
    assert result.minimality_proof is None


def test_synth_allows_one_and_two_variables():
    assert synthesize(["a"], minterms={0}).gate_name == "inverter (1 input)"
    assert synthesize(["a", "b"], minterms={0}).gate_name is not None
