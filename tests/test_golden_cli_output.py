"""Golden regression fixtures: exact CLI stdout/stderr captured from
commit 3daab17 (the last signed-off state before M1.2), before any
refactor touched api.py/webui.py for the M1.2 presenter work.

These pin *historical* behavior, not just internal self-consistency --
test_api.py's own byte-identical checks only prove the CLI and api.py
agree with each other post-refactor; they could drift together and
still pass. These fixtures catch that: any change to the actual bytes
a pre-M1.2 user would have seen fails here, regardless of whether the
CLI and the API layer still agree with each other."""

import contextlib
import io

import pytest

from ohmwork.cli import main


def run(args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(args)
    return code, out.getvalue(), err.getvalue()

_GOLDEN_Q1 = "Candidates considered (D1/D16: every literal-minimal AOI/OAI cover):\n  AOI: F' = ABC (6 core + 0 inverter = 6 transistors) <- chosen\n  OAI: F' = ABC (6 core + 0 inverter = 6 transistors)\n\nGate: 3-input NAND\nF' = ABC\n\nTransistor count:\n  PDN (NMOS):  3\n  PUN (PMOS):  3\n  Inverters:   0 (no complemented inputs needed)\n  Total:       6\n\nStack height: PDN 3, PUN 1\n\nMinimality: proven minimal for complementary static CMOS: every declared variable (3) appears exactly once as a literal, so each must control at least one transistor in both the pull-down and pull-up networks — no complementary static CMOS realization (single- or multi-stage) could use fewer than 6 PDN+PUN transistors for this function. This bound is specific to complementary static CMOS; it makes no claim about pass-transistor logic, ratioed logic, dynamic logic, or any other circuit family.\n\nSchematic:\n      VDD       \n       |        \n PUN: A + B + C \n       |        \n       F        \n       |        \n   PDN: A·B·C   \n       |        \n      GND       \n\nVerification (D7, two independent checks):\n  vectors simulated: 8\n  functional equivalence: PASS\n  structural validity: PASS (no floating output, no VDD-GND short)"

_GOLDEN_Q2 = "Candidates considered (D1/D16: every literal-minimal AOI/OAI cover):\n  AOI: F' = A + B + C + D (8 core + 0 inverter = 8 transistors) <- chosen\n  OAI: F' = A + B + C + D (8 core + 0 inverter = 8 transistors)\n\nGate: 4-input NOR\nF' = A + B + C + D\n\nTransistor count:\n  PDN (NMOS):  4\n  PUN (PMOS):  4\n  Inverters:   0 (no complemented inputs needed)\n  Total:       8\n\nStack height: PDN 1, PUN 4\n\nMinimality: proven minimal for complementary static CMOS: every declared variable (4) appears exactly once as a literal, so each must control at least one transistor in both the pull-down and pull-up networks — no complementary static CMOS realization (single- or multi-stage) could use fewer than 8 PDN+PUN transistors for this function. This bound is specific to complementary static CMOS; it makes no claim about pass-transistor logic, ratioed logic, dynamic logic, or any other circuit family.\n\nSchematic:\n        VDD         \n         |          \n    PUN: A·B·C·D    \n         |          \n         F          \n         |          \n PDN: A + B + C + D \n         |          \n        GND         \n\nVerification (D7, two independent checks):\n  vectors simulated: 16\n  functional equivalence: PASS\n  structural validity: PASS (no floating output, no VDD-GND short)"

_GOLDEN_Q3 = "Candidates considered (D1/D16: every literal-minimal AOI/OAI cover):\n  AOI: F' = ABC + D (8 core + 0 inverter = 8 transistors) <- chosen\n  OAI: F' = (A + D)(B + D)(C + D) (12 core + 0 inverter = 12 transistors)\n\nGate: AOI31\nF' = ABC + D\n\nTransistor count:\n  PDN (NMOS):  4\n  PUN (PMOS):  4\n  Inverters:   0 (no complemented inputs needed)\n  Total:       8\n\nStack height: PDN 3, PUN 2\n\nMinimality: proven minimal for complementary static CMOS: every declared variable (4) appears exactly once as a literal, so each must control at least one transistor in both the pull-down and pull-up networks — no complementary static CMOS realization (single- or multi-stage) could use fewer than 8 PDN+PUN transistors for this function. This bound is specific to complementary static CMOS; it makes no claim about pass-transistor logic, ratioed logic, dynamic logic, or any other circuit family.\n\nSchematic:\n        VDD         \n         |          \n PUN: (A + B + C)·D \n         |          \n         F          \n         |          \n   PDN: A·B·C + D   \n         |          \n        GND         \n\nVerification (D7, two independent checks):\n  vectors simulated: 16\n  functional equivalence: PASS\n  structural validity: PASS (no floating output, no VDD-GND short)"

_GOLDEN_INVERTER = "Candidates considered (D1/D16: every literal-minimal AOI/OAI cover):\n  AOI: F' = a'b + c (6 core + 2 inverter = 8 transistors) <- chosen\n  OAI: F' = (a' + c)(b + c) (8 core + 2 inverter = 10 transistors)\n\nGate: AOI21\nF' = a'b + c\n\nTransistor count:\n  PDN (NMOS):  3\n  PUN (PMOS):  3\n  Inverters:   2 (shared, one each for a' — D12)\n  Total:       8\n\nStack height: PDN 2, PUN 2\n\nMinimality: proven minimal for complementary static CMOS: every declared variable (3) appears exactly once as a literal, so each must control at least one transistor in both the pull-down and pull-up networks — no complementary static CMOS realization (single- or multi-stage) could use fewer than 6 PDN+PUN transistors for this function. This bound is specific to complementary static CMOS; it makes no claim about pass-transistor logic, ratioed logic, dynamic logic, or any other circuit family.\n\nSchematic:\n       VDD       \n        |        \n PUN: (a' + b)·c \n        |        \n        F        \n        |        \n  PDN: a'·b + c  \n        |        \n       GND       \n\nVerification (D7, two independent checks):\n  vectors simulated: 8\n  functional equivalence: PASS\n  structural validity: PASS (no floating output, no VDD-GND short)"

_GOLDEN_DONTCARE = "Candidates considered (D1/D16: every literal-minimal AOI/OAI cover):\n  AOI: F' = a (2 core + 0 inverter = 2 transistors) <- chosen\n  OAI: F' = a (2 core + 0 inverter = 2 transistors)\n\nGate: inverter (1 input)\nF' = a\n\nTransistor count:\n  PDN (NMOS):  1\n  PUN (PMOS):  1\n  Inverters:   0 (no complemented inputs needed)\n  Total:       2\n\nStack height: PDN 1, PUN 1\n\nMinimality: not proven — search was limited to the flat AOI/OAI dual candidates (D1/D6); a different factoring might do better.\n\nSchematic:\n  VDD   \n   |    \n PUN: a \n   |    \n   F    \n   |    \n PDN: a \n   |    \n  GND   \n\nVerification (D7, two independent checks):\n  vectors simulated: 4\n  functional equivalence: PASS\n  structural validity: PASS (no floating output, no VDD-GND short)\n  don't-cares assigned (D4): 1->1"

_GOLDEN_DUALRAIL = "Candidates considered (D1/D16: every literal-minimal AOI/OAI cover):\n  AOI: F' = a'b + c (6 core + 0 inverter = 6 transistors) <- chosen\n  OAI: F' = (a' + c)(b + c) (8 core + 0 inverter = 8 transistors)\n\nGate: AOI21\nF' = a'b + c\n\nTransistor count:\n  PDN (NMOS):  3\n  PUN (PMOS):  3\n  Inverters:   0 (shared, one each for a' — D12)\n  Total:       6\n\nStack height: PDN 2, PUN 2\n\nMinimality: proven minimal for complementary static CMOS: every declared variable (3) appears exactly once as a literal, so each must control at least one transistor in both the pull-down and pull-up networks — no complementary static CMOS realization (single- or multi-stage) could use fewer than 6 PDN+PUN transistors for this function. This bound is specific to complementary static CMOS; it makes no claim about pass-transistor logic, ratioed logic, dynamic logic, or any other circuit family.\n\nSchematic:\n       VDD       \n        |        \n PUN: (a' + b)·c \n        |        \n        F        \n        |        \n  PDN: a'·b + c  \n        |        \n       GND       \n\nVerification (D7, two independent checks):\n  vectors simulated: 8\n  functional equivalence: PASS\n  structural validity: PASS (no floating output, no VDD-GND short)"

_GOLDEN_MAXSTACK = "Candidates considered (D1/D16: every literal-minimal AOI/OAI cover):\n  AOI: F' = a + b (4 core + 0 inverter = 4 transistors) <- chosen\n  OAI: F' = a + b (4 core + 0 inverter = 4 transistors)\n\nGate: 2-input NOR\nF' = a + b\n\nTransistor count:\n  PDN (NMOS):  2\n  PUN (PMOS):  2\n  Inverters:   0 (no complemented inputs needed)\n  Total:       4\n\nStack height: PDN 1, PUN 2\n\nMinimality: proven minimal for complementary static CMOS: every declared variable (2) appears exactly once as a literal, so each must control at least one transistor in both the pull-down and pull-up networks — no complementary static CMOS realization (single- or multi-stage) could use fewer than 4 PDN+PUN transistors for this function. This bound is specific to complementary static CMOS; it makes no claim about pass-transistor logic, ratioed logic, dynamic logic, or any other circuit family.\n\nSchematic:\n    VDD     \n     |      \n  PUN: a·b  \n     |      \n     F      \n     |      \n PDN: a + b \n     |      \n    GND     \n\nVerification (D7, two independent checks):\n  vectors simulated: 4\n  functional equivalence: PASS\n  structural validity: PASS (no floating output, no VDD-GND short)"

_GOLDEN_MAXSTACK_ERROR = "error: no AOI/OAI candidate fits within --max-stack 1 (AOI stack 3, OAI stack 3); a multi-stage NAND/NOR decomposition might, but that search isn't implemented yet — reporting nothing rather than guessing one (D6)"

_GOLDEN_BUFFER = "Candidates considered (D1/D16: every literal-minimal AOI/OAI cover):\n  AOI: F' = a (2 core + 0 inverter = 2 transistors) <- chosen\n  OAI: F' = a (2 core + 0 inverter = 2 transistors)\n\nGate: inverter (1 input)\nF' = a\n\nTransistor count:\n  PDN (NMOS):  1\n  PUN (PMOS):  1\n  Inverters:   0 (no complemented inputs needed)\n  Total:       2\n\nStack height: PDN 1, PUN 1\n\nMinimality: proven minimal for complementary static CMOS: every declared variable (1) appears exactly once as a literal, so each must control at least one transistor in both the pull-down and pull-up networks — no complementary static CMOS realization (single- or multi-stage) could use fewer than 2 PDN+PUN transistors for this function. This bound is specific to complementary static CMOS; it makes no claim about pass-transistor logic, ratioed logic, dynamic logic, or any other circuit family.\n\nSchematic:\n  VDD   \n   |    \n PUN: a \n   |    \n   F    \n   |    \n PDN: a \n   |    \n  GND   \n\nVerification (D7, two independent checks):\n  vectors simulated: 2\n  functional equivalence: PASS\n  structural validity: PASS (no floating output, no VDD-GND short)"

_GOLDEN_INVERTER_TRIVIAL = "Candidates considered (D1/D16: every literal-minimal AOI/OAI cover):\n  AOI: F' = a' (2 core + 2 inverter = 4 transistors) <- chosen\n  OAI: F' = a' (2 core + 2 inverter = 4 transistors)\n\nGate: buffer (degenerate: complemented input realized directly)\nF' = a'\n\nTransistor count:\n  PDN (NMOS):  1\n  PUN (PMOS):  1\n  Inverters:   2 (shared, one each for a' — D12)\n  Total:       4\n\nStack height: PDN 1, PUN 1\n\nMinimality: proven minimal for complementary static CMOS: every declared variable (1) appears exactly once as a literal, so each must control at least one transistor in both the pull-down and pull-up networks — no complementary static CMOS realization (single- or multi-stage) could use fewer than 2 PDN+PUN transistors for this function. This bound is specific to complementary static CMOS; it makes no claim about pass-transistor logic, ratioed logic, dynamic logic, or any other circuit family.\n\nSchematic:\n   VDD   \n    |    \n PUN: a' \n    |    \n    F    \n    |    \n PDN: a' \n    |    \n   GND   \n\nVerification (D7, two independent checks):\n  vectors simulated: 2\n  functional equivalence: PASS\n  structural validity: PASS (no floating output, no VDD-GND short)"

_GOLDEN_ERR_EXPR_VARS = 'error: --expr cannot be combined with --vars/--ones/--dc/--table'

_GOLDEN_ERR_NO_ONES = 'error: give --ones (or --table) alongside --vars'


@pytest.mark.parametrize(
    "args,golden,expect_error",
    [
        (['synth', '--expr', "(ABC)'"], _GOLDEN_Q1, False),
        (['synth', '--vars', 'A,B,C,D', '--table', '1000000000000000'], _GOLDEN_Q2, False),
        (['synth', '--expr', "(ABC+D)'"], _GOLDEN_Q3, False),
        (['synth', '--expr', "(a'b+c)'"], _GOLDEN_INVERTER, False),
        (['synth', '--vars', 'a,b', '--ones', '0', '--dc', '1'], _GOLDEN_DONTCARE, False),
        (['synth', '--expr', "(a'b+c)'", '--dual-rail'], _GOLDEN_DUALRAIL, False),
        (['synth', '--expr', "(a+b)'", '--max-stack', '2'], _GOLDEN_MAXSTACK, False),
        (['synth', '--expr', "(abc)'", '--max-stack', '1'], _GOLDEN_MAXSTACK_ERROR, True),
        (['synth', '--expr', "a'"], _GOLDEN_BUFFER, False),
        (['synth', '--expr', 'a'], _GOLDEN_INVERTER_TRIVIAL, False),
        (['synth', '--expr', 'ab', '--vars', 'a,b'], _GOLDEN_ERR_EXPR_VARS, True),
        (['synth', '--vars', 'a,b'], _GOLDEN_ERR_NO_ONES, True),
    ],
)
def test_golden_pre_m1_2_output(args, golden, expect_error):
    code, out, err = run(args)
    if expect_error:
        assert code != 0
        assert err == golden + "\n"
        assert out == ""
    else:
        assert code == 0
        assert err == ""
        assert out == golden + "\n"
