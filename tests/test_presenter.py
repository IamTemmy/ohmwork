"""Tests for presenter.py — the student-facing structured view of a
SynthesisResult. Everything here checks facts read off the result object
graph, never text parsed from the CLI report."""

import pytest

from ohmwork.api import derive_from_input, synthesize_from_input
from ohmwork.presenter import build_schematic_view, build_synth_view, build_tt_view, validate_output_name
from ohmwork.schematic import CELL, build_schematic


# --- validate_output_name ----------------------------------------------------


def test_default_output_name_is_f():
    assert validate_output_name(None, ["a", "b"]) == "F"
    assert validate_output_name("", ["a", "b"]) == "F"
    assert validate_output_name("   ", ["a", "b"]) == "F"


def test_bare_f_is_a_valid_output_name():
    # D15 reserves "F" as an INPUT variable name (tt's derivation table);
    # it must NOT be rejected here, since it's the default output name.
    assert validate_output_name("F", ["a", "b"]) == "F"


def test_accepts_letter_plus_optional_digit():
    assert validate_output_name("Y", ["a", "b"]) == "Y"
    assert validate_output_name("M0", ["a", "b"]) == "M0"


def test_rejects_multi_character_name():
    with pytest.raises(ValueError, match="not a valid output name"):
        validate_output_name("Out", ["a", "b"])


def test_rejects_two_digit_suffix():
    with pytest.raises(ValueError, match="not a valid output name"):
        validate_output_name("M12", ["a", "b"])


def test_rejects_name_colliding_with_input_variable():
    with pytest.raises(ValueError, match="duplicates an input variable"):
        validate_output_name("a", ["a", "b"])


def test_strips_whitespace():
    assert validate_output_name("  Y  ", ["a", "b"]) == "Y"


# --- build_synth_view: the three exam questions -----------------------------


def test_q1_3_input_nand():
    result = synthesize_from_input(expr="(ABC)'")
    view = build_synth_view(result)
    assert view["gate_name"] == "3-input NAND"
    assert view["function"] == "F = (ABC)'"
    assert view["total_transistors"] == 6
    assert view["pdn"] == {"expression": "A·B·C", "transistors": 3, "stack_height": 3}
    assert view["pun"] == {"expression": "A + B + C", "transistors": 3, "stack_height": 1}
    assert view["inverters"] == {"count": 0, "literals": []}
    assert view["verification"]["vector_count"] == 8
    assert view["verification"]["functional_pass"] is True
    assert view["verification"]["structural_pass"] is True
    assert view["topology_note"] == "3 NMOS in series and 3 PMOS in parallel."
    assert view["verified_summary"] == "Verified for all 8 input combinations."


def test_q2_topology_note_reflects_nor_shape():
    result = synthesize_from_input(variables="A,B,C,D", table="1000000000000000")
    view = build_synth_view(result)
    assert view["topology_note"] == "4 NMOS in parallel and 4 PMOS in series."


def test_aoi_shape_has_no_topology_note():
    # A nested (non-flat) network shouldn't get an inaccurate one-liner.
    result = synthesize_from_input(expr="(ABC+D)'")
    view = build_synth_view(result)
    assert view["topology_note"] is None


def test_single_transistor_topology_note():
    result = synthesize_from_input(expr="a")
    view = build_synth_view(result)
    assert view["topology_note"] == "A single NMOS pull-down and a single PMOS pull-up."


def test_q1_candidates_are_deduplicated_with_provenance_preserved():
    result = synthesize_from_input(expr="(ABC)'")
    view = build_synth_view(result)
    alts = view["reasoning"]["alternatives"]
    # AOI and OAI both land on F'=ABC at 6 transistors -- one row, not two.
    assert len(alts) == 1
    assert alts[0]["expression"] == "ABC"
    assert set(alts[0]["labels"]) == {"AOI", "OAI"}
    assert alts[0]["is_chosen"] is True
    # The underlying (undeduplicated) list is untouched.
    assert len(result.other_candidates) == 2


def test_q1_selection_reasoning_notes_both_construction_paths():
    result = synthesize_from_input(expr="(ABC)'")
    view = build_synth_view(result)
    note = view["reasoning"]["selection_note"]
    assert "only one distinct realization" in note.lower()
    assert "AOI" in note and "OAI" in note


def test_q2_4_input_nor():
    result = synthesize_from_input(variables="A,B,C,D", table="1000000000000000")
    view = build_synth_view(result)
    assert view["gate_name"] == "4-input NOR"
    assert view["function"] == "F = (A + B + C + D)'"
    assert view["total_transistors"] == 8


def test_q3_aoi31_shows_a_strictly_cheaper_reasoning():
    result = synthesize_from_input(expr="(ABC+D)'")
    view = build_synth_view(result)
    assert view["gate_name"] == "AOI31"
    assert view["function"] == "F = (ABC + D)'"
    assert view["total_transistors"] == 8
    note = view["reasoning"]["selection_note"]
    assert "strictly lower" in note.lower()
    assert "8" in note and "12" in note  # 8 chosen vs 12 for the OAI alternative
    alts = view["reasoning"]["alternatives"]
    assert len(alts) == 2  # AOI (chosen, 8T) and OAI (12T) are genuinely different here


# --- Custom output names -----------------------------------------------------


@pytest.mark.parametrize("name", ["F", "Y", "M"])
def test_custom_output_names(name):
    result = synthesize_from_input(expr="(ABC)'")
    view = build_synth_view(result, output_name=name)
    assert view["function"] == f"{name} = (ABC)'"
    assert view["output_name"] == name
    # Nothing else about the result changes with the display name.
    assert view["gate_name"] == "3-input NAND"
    assert view["total_transistors"] == 6


def test_output_name_does_not_affect_the_underlying_result():
    result = synthesize_from_input(expr="(ABC)'")
    view_f = build_synth_view(result, output_name="F")
    view_y = build_synth_view(result, output_name="Y")
    assert view_f["total_transistors"] == view_y["total_transistors"]
    assert view_f["pdn"] == view_y["pdn"]
    assert view_f["function"] != view_y["function"]


# --- Double-negation collapse for the degenerate buffer case ----------------


def test_buffer_case_collapses_double_negation():
    # F' = a' (a degenerate "buffer" gate): naively F = NOT(a') = a'' is
    # correct but unreadable -- must collapse to F = a.
    result = synthesize_from_input(expr="a")
    assert result.gate_name.startswith("buffer")
    view = build_synth_view(result)
    assert view["function"] == "F = a"


def test_inverter_case_is_not_affected_by_double_negation_logic():
    # F' = a (plain inverter): F = NOT(a) = a', no double negation involved.
    result = synthesize_from_input(expr="a'")
    assert result.gate_name.startswith("inverter")
    view = build_synth_view(result)
    assert view["function"] == "F = a'"


# --- Don't-cares --------------------------------------------------------------


def test_dont_care_assignments_are_surfaced_and_flagged():
    result = synthesize_from_input(variables="a,b", ones="0", dc="1")
    view = build_synth_view(result)
    assert view["function_uses_dont_cares"] is True
    assert view["verification"]["dont_care_assignments"] == {"1": True}


def test_no_dont_cares_flag_is_false_when_there_are_none():
    result = synthesize_from_input(expr="(ABC)'")
    view = build_synth_view(result)
    assert view["function_uses_dont_cares"] is False
    assert view["verification"]["dont_care_assignments"] == {}


# --- Inverters (D12) -----------------------------------------------------------


def test_inverter_literals_and_count_are_surfaced():
    result = synthesize_from_input(expr="(a'b+c)'")
    view = build_synth_view(result)
    assert view["inverters"]["literals"] == ["a"]
    assert view["inverters"]["count"] == 2


def test_dual_rail_shows_zero_inverter_count_cleanly():
    result = synthesize_from_input(expr="(a'b+c)'", dual_rail=True)
    view = build_synth_view(result)
    assert view["inverters"]["count"] == 0
    # Unlike the legacy report's own wording quirk, this doesn't claim an
    # inverter is needed while also saying the count is 0.
    assert view["inverters"]["literals"] == ["a"]  # still true a complement is used


# --- max_stack wording --------------------------------------------------------


def test_max_stack_reasoning_notes_the_constraint():
    result = synthesize_from_input(expr="(a+b)'", max_stack=2)
    view = build_synth_view(result, max_stack_applied=True)
    assert "--max-stack" in view["reasoning"]["selection_note"]


def test_no_max_stack_reasoning_has_no_constraint_caveat():
    result = synthesize_from_input(expr="(a+b)'")
    view = build_synth_view(result, max_stack_applied=False)
    assert "--max-stack" not in view["reasoning"]["selection_note"]


# --- Minimality summary -------------------------------------------------------


def test_minimality_summary_when_proven_and_no_inverters():
    # A 2026-09-18 ChatGPT review (Q3 dogfooding) caught this summary
    # always saying a flat "Proven minimal" even when the design needed
    # inverter transistors the certificate doesn't cover -- see the
    # core-only case below. This is the case where core cost == total
    # cost (no inverters), so the summary is unqualified.
    result = synthesize_from_input(expr="(ABC)'")
    view = build_synth_view(result)
    summary = view["reasoning"]["minimality_summary"]
    assert "proven minimal" in summary.lower()
    assert "complementary static cmos" in summary.lower()
    assert "3 essential variable" in summary
    assert "6 transistors total" in summary
    assert view["reasoning"]["minimality_detail"] == result.minimality_proof


def test_minimality_summary_core_only_when_inverters_needed():
    # AOI21 for (a'b+c)': PDN/PUN use one literal per variable (the
    # certificate's condition), but the complemented literal a' needs a
    # shared inverter (D12) -- 6 core + 2 inverter = 8 total. The
    # certificate only ever bounds the 6-transistor core; the summary
    # must say the complete 8-transistor design is NOT proven minimal,
    # not just omit a number and imply it is.
    result = synthesize_from_input(expr="(a'b+c)'")
    assert result.inverter_transistors == 2
    assert result.total_transistors == 8
    view = build_synth_view(result)
    summary = view["reasoning"]["minimality_summary"]
    assert "core proven minimal" in summary.lower()
    assert "complementary static cmos" in summary.lower()
    assert "6 core transistor" in summary
    assert "2 inverter transistor" in summary
    assert "not proven minimal" in summary.lower()
    assert "8-transistor design" in summary
    assert view["reasoning"]["minimality_detail"] == result.minimality_proof
    assert "NOT proven minimal" in result.minimality_proof


def test_minimality_summary_when_not_proven():
    result = synthesize_from_input(variables="a,b", ones="0", dc="1")
    view = build_synth_view(result)
    assert "not proven" in view["reasoning"]["minimality_summary"].lower()
    assert view["reasoning"]["minimality_detail"] is None


# --- build_tt_view (M1.3) -----------------------------------------------------
#
# The student-facing structured table view of a DerivationResult -- ordered
# headers, ordered rows, the output column's index, and the simplified
# function. Every field here reads a fact directly off the already-
# computed DerivationTable; nothing is inferred or reparsed from rendered
# text, the same design boundary as build_synth_view above.


def test_build_tt_view_matches_the_acceptance_case():
    result = derive_from_input("xy + xy'")
    view = build_tt_view(result)
    assert view["headers"] == ["x", "y", "y'", "xy", "xy'", "F"]
    assert view["output_column_index"] == 5
    assert view["simplified_function"] == "F = x"
    assert len(view["rows"]) == 4
    # D9/D10 row order: binary count, first-listed variable = MSB.
    assert view["rows"] == [
        [False, False, True, False, False, False],  # x=0,y=0
        [False, True, False, False, False, False],  # x=0,y=1
        [True, False, True, False, True, True],  # x=1,y=0
        [True, True, False, True, False, True],  # x=1,y=1
    ]


def test_build_tt_view_terse_columns():
    result = derive_from_input("ab+c", terse=True)
    view = build_tt_view(result)
    assert view["headers"] == ["ab", "c", "F"]
    assert view["output_column_index"] == 2


def test_build_tt_view_custom_columns():
    result = derive_from_input("x'y + xy'", cols=["x", "x'"])
    view = build_tt_view(result)
    assert view["headers"] == ["x", "x'", "F"]
    assert view["output_column_index"] == 2


def test_build_tt_view_xor_intermediate_column():
    result = derive_from_input("(x^y)z")
    view = build_tt_view(result)
    assert "x ^ y" in view["headers"]
    assert view["headers"][-1] == "F"
    assert view["output_column_index"] == len(view["headers"]) - 1


def test_build_tt_view_row_count_matches_variable_count():
    result = derive_from_input("a'bc + d")
    view = build_tt_view(result)
    assert len(view["rows"]) == 16  # 4 variables -> 2^4 rows
    assert all(len(row) == len(view["headers"]) for row in view["rows"])


def test_build_tt_view_simplified_function_for_a_non_trivial_expression():
    result = derive_from_input("a'bc + ab'c + abc' + abc")  # simplifies to a majority-ish function
    view = build_tt_view(result)
    assert view["simplified_function"].startswith("F = ")


# --- build_schematic_view (D17 Phase B) --------------------------------------
#
# This is the JSON bridge between the already-four-gates-validated Layout
# model and the frontend's SVG renderer -- these tests check it's a lossless,
# unmodified read of `layout`'s own dataclasses (the field-by-field bijection
# the semantic model-to-SVG bridge, acceptance test 8, ultimately depends on),
# never a re-derivation.


def _q1_layout():
    result = synthesize_from_input(expr="(abc)'")
    return build_schematic(result, "F")


def test_build_schematic_view_top_level_fields_match_the_layout():
    layout = _q1_layout()
    view = build_schematic_view(layout)
    assert view["cell"] == CELL
    assert view["width"] == layout.width
    assert view["height"] == layout.height
    assert view["pun_height"] == layout.pun_height
    assert view["pdn_height"] == layout.pdn_height
    assert view["var_order"] == list(layout.var_order)
    assert view["output_net_id"] == layout.output_net_id
    assert view["vdd_net_id"] == layout.vdd_net_id
    assert view["gnd_net_id"] == layout.gnd_net_id
    assert view["total_transistors"] == layout.total_transistors == 6


def test_build_schematic_view_nets_are_a_lossless_copy():
    layout = _q1_layout()
    view = build_schematic_view(layout)
    assert len(view["nets"]) == len(layout.nets)
    by_id = {n.id: n for n in layout.nets}
    for n in view["nets"]:
        model_net = by_id[n["id"]]
        assert n["label"] == model_net.label
        assert n["kind"] == model_net.kind


def test_build_schematic_view_devices_carry_exact_model_coordinates():
    layout = _q1_layout()
    view = build_schematic_view(layout)
    assert len(view["devices"]) == len(layout.devices) == layout.total_transistors
    by_id = {d.id: d for d in layout.devices}
    for d in view["devices"]:
        model_dev = by_id[d["id"]]
        assert d["kind"] == model_dev.kind
        assert d["role"] == model_dev.role
        assert d["gate_var"] == model_dev.gate_var
        assert d["gate_complemented"] == model_dev.gate_complemented
        assert d["literal"] == model_dev.literal
        assert d["gate_net"] == model_dev.gate_net
        assert d["source_net"] == model_dev.source_net
        assert d["drain_net"] == model_dev.drain_net
        assert (d["origin"]["x"], d["origin"]["y"]) == (model_dev.origin.x, model_dev.origin.y)
        assert (d["gate_point"]["x"], d["gate_point"]["y"]) == (model_dev.gate_point.x, model_dev.gate_point.y)
        assert (d["source_point"]["x"], d["source_point"]["y"]) == (
            model_dev.source_point.x,
            model_dev.source_point.y,
        )
        assert (d["drain_point"]["x"], d["drain_point"]["y"]) == (model_dev.drain_point.x, model_dev.drain_point.y)


def test_build_schematic_view_wires_carry_exact_model_endpoints():
    layout = _q1_layout()
    view = build_schematic_view(layout)
    assert len(view["wires"]) == len(layout.wires)
    by_id = {w.id: w for w in layout.wires}
    for w in view["wires"]:
        model_wire = by_id[w["id"]]
        assert w["net_id"] == model_wire.net_id
        assert (w["p1"]["x"], w["p1"]["y"]) == (model_wire.p1.x, model_wire.p1.y)
        assert (w["p2"]["x"], w["p2"]["y"]) == (model_wire.p2.x, model_wire.p2.y)


def test_build_schematic_view_junctions_carry_exact_model_points():
    result = synthesize_from_input(expr="(a'b+c)'")  # AOI21 -- has internal series junctions
    layout = build_schematic(result, "F")
    view = build_schematic_view(layout)
    assert len(layout.junctions) > 0  # otherwise this test would vacuously pass
    assert len(view["junctions"]) == len(layout.junctions)
    by_id = {j.id: j for j in layout.junctions}
    for j in view["junctions"]:
        model_junction = by_id[j["id"]]
        assert j["net_id"] == model_junction.net_id
        assert (j["point"]["x"], j["point"]["y"]) == (model_junction.point.x, model_junction.point.y)


@pytest.mark.parametrize('expr,options,expected,absent', [
    ("(abc+d)'", {}, ['Why group 0s?', 'AND–OR–Invert', 'AOI: 8 transistors', 'OAI: 12 transistors', 'lowest-cost circuit'], ['tie-break']),
    ("a'bc+b'c'd'", {}, ['Why group 1s?', 'OR–AND–Invert', 'AOI: 20 transistors', 'OAI: 16 transistors', '12 core + 4'], ['tie-break']),
    ('a^b', {}, ['Distinct circuits tie at 12', 'deterministic tie-break', 'AOI: 12', 'OAI: 12', 'no saving'], ['lowest-cost circuit']),
    ("(abc)'", {}, ['AOI and OAI both produce the same 6-transistor circuit', 'Neither construction saves'], ['Best total', 'comparison', 'tie-break']),
    ("a'bc+b'c'd'", {'dual_rail': True}, ['AOI: 16', 'OAI: 12', '12 core + 0'], ['12 core + 4']),
    ('ab+cd', {'max_stack': 2}, ['--max-stack constraint', 'Only one distinct circuit', 'OAI, with 16 transistors'], ['AOI: 24', 'Best total', 'comparison']),
])
def test_kmap_selection_explanation_uses_actual_candidate_costs(expr, options, expected, absent):
    result = synthesize_from_input(expr=expr, **options)
    reasoning = build_synth_view(result, max_stack_applied='max_stack' in options)['reasoning']
    text = reasoning['kmap_selection_note']
    # The K-map explains its direction without copying the Reasoning paragraph.
    # Its own text must still stand alone when copied separately.
    assert reasoning['selection_note'] not in text
    for phrase in expected:
        assert phrase in text
    for phrase in absent:
        assert phrase not in text
