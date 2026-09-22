"""Required dedicated CI gate; optional locally when ngspice is absent.

Run OHMWORK_REQUIRE_NGSPICE=1 pytest tests/test_spice_ngspice.py -q.
Each case enumerates all inputs, including the chosen values on don't-care rows.
"""
import itertools
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

from ohmwork.api import synthesize_from_input, resolve_truth_table
from ohmwork.synth import _synthesize
from ohmwork.schematic import build_textbook_schematic
from ohmwork.spice import render_spice_example


def ngspice_executable():
    executable = shutil.which("ngspice")
    if executable:
        return executable
    if os.environ.get("OHMWORK_REQUIRE_NGSPICE") == "1":
        pytest.fail("Required ngspice binary is missing")
    pytest.skip("ngspice is optional locally; required in the dedicated CI job")


def read_output(completed, node):
    """Parse only the .op node-voltage table, never device/model diagnostics."""
    log = completed.stdout + "\n" + completed.stderr
    if completed.returncode or re.search(
        r"(?im)(^\s*(?:fatal|error)\b|failed|singular matrix|timestep too small|no convergence|"
        r"not converg|convergence problem|doanalyses:)", log
    ):
        raise AssertionError("ngspice failed or did not converge:\n" + log)
    match = re.search(r"Node\s+Voltage\s*\n(.*?)\n\s*Source\s+Current", log, re.S)
    if not match:
        raise AssertionError("Missing operating-point node table")
    values = re.findall(r"^\s*" + re.escape(node) + r"\s+(\S+)\s*$", match[1], re.M)
    if len(values) != 1:
        raise AssertionError("Missing or duplicate output value")
    try:
        voltage = float(values[0])
    except ValueError as exc:
        raise AssertionError("Invalid output value") from exc
    if not math.isfinite(voltage):
        raise AssertionError("Non-finite output value")
    if voltage <= 1.0:
        return False, voltage
    if voltage >= 4.0:
        return True, voltage
    raise AssertionError(f"Ambiguous output level: {voltage} V")


def check_harness(text, layout, values):
    """Independent check of actual exported top-level pin mapping and stimuli."""
    lines = [line.split() for line in text.splitlines() if line and not line.startswith("*")]
    mapping = {parts[2]: json.loads(parts[3]) for line in text.splitlines()
               if line.startswith("* node ") for parts in [line.split(" ", 3)]}
    ports = next(l[2:] for l in lines if l[0] == ".subckt")
    instance = next(l for l in lines if l[0] == "x0")
    assert instance[1:-1] == [ports[0], ports[1], "0", *ports[3:]]
    assert instance[-1] == "ohmwork_gate"
    sources = [l for l in lines if re.fullmatch(r"v\d+", l[0])]
    assert len(sources) == 1 + len(ports[3:])
    assert len({l[0] for l in sources}) == len(sources)
    assert len({l[1] for l in sources}) == len(sources)
    driven = {l[1]: float(l[4]) for l in sources}
    assert all(len(l) == 5 and l[2:4] == ["0", "DC"] for l in sources)
    assert driven[ports[1]] == 5
    for var, port in zip(layout.var_order, ports[3:]):
        assert driven[port] == 5 * values[var]
    complements = dict(layout.complement_nets)
    external = [v for v in layout.var_order if v in complements and v not in layout.inverter_driven_vars]
    for var, port in zip(external, ports[3 + len(layout.var_order):]):
        assert mapping[port][0] == complements[var]
        assert driven[port] == 5 * (not values[var])
    return ports[0]


CASES = [
    ('phase1-aoi32', {'expr': "(abc+de)'"}),
    ('phase1-nand5', {'expr': "(abcde)'"}),
    ('phase1-nor5', {'expr': "(a+b+c+d+e)'"}),
    ('phase1-oai', {'expr': "((a+b)(c+d)e)'"}),
    ('phase1-shared', {'expr': "a'b+c'd+e"}),
    ('phase1-unused-case', {'variables': 'a,A,a0,z,q', 'ones': ','.join(map(str,range(16,32)))}),
    ('phase1-dontcare', {'variables': 'a,b,c,d,e', 'ones': '16', 'dc': '0'}),
    ("nand3", {"expr": "(abc)'"}),
    ("nor4", {"expr": "(a+b+c+d)'"}),
    ("aoi31", {"expr": "(abc+d)'"}),
    ("shared", {"expr": "(a'b+c)'"}),
    ("and", {"expr": "ab"}),
    ("buffer", {"expr": "a"}),
    ("inverter", {"expr": "a'"}),
    ("oai22", {"expr": "((a+b)(c+d))'"}),
    ("asymmetric", {"expr": "((a+b)cd)'"}),
    ("nested", {"expr": "((ab+c)(a+d))'"}),
    ("nested2", {"expr": "((a+bc)(b+d))'"}),
    ("stress40", {"expr": "a'b'c'd + a'b'cd' + a'bc'd' + ab'c'd'"}),
    ("netcase", {"expr": "(aA)'"}),
    ("devicecase", {"expr": "aA"}),
    ("threecase", {"expr": "(a A a0)'"}),
    ("unused", {"variables": "a,b", "ones": "2,3"}),
    ("dontcare", {"variables": "a,b,c", "ones": "1,3", "dc": "0,2,5"}),
]


@pytest.mark.parametrize("case,kwargs", CASES, ids=[c[0] for c in CASES])
@pytest.mark.parametrize("dual", [False, True], ids=["single-rail", "dual-rail"])
def test_all_vectors_in_ngspice(case, kwargs, dual, tmp_path):
    executable = ngspice_executable()
    result = (_synthesize(*resolve_truth_table(**kwargs), dual_rail=dual)
              if case.startswith('phase1-') else synthesize_from_input(**kwargs, dual_rail=dual))
    layout = build_textbook_schematic(result, "Y")
    if case == "stress40" and not dual:
        assert result.total_transistors == 40
    artifact = Path("test-artifacts/spice") / f"{case}-{'dual' if dual else 'single'}"
    artifact.mkdir(parents=True, exist_ok=True)
    measurements = []
    for index, bits in enumerate(itertools.product([False, True], repeat=len(result.var_order))):
        values = dict(zip(result.var_order, bits))
        text = render_spice_example(layout, values)
        output = check_harness(text, layout, values)
        deck = tmp_path / "example.cir"
        deck.write_text(text)
        (artifact / f"vector-{index}.cir").write_text(text)
        # No shell, no user startup scripts, bounded runtime; timeout fails.
        completed = subprocess.run([executable, "-n", "-b", str(deck)],
                                   capture_output=True, text=True, timeout=15, cwd=tmp_path)
        (artifact / f"vector-{index}.log").write_text(completed.stdout + completed.stderr)
        actual, voltage = read_output(completed, output)
        expected = (result.verification.dont_care_assignments[index]
                    if index in result.dont_cares else index in result.minterms)
        assert actual == expected, (case, dual, index, values, voltage, expected)
        measurements.append({"minterm": index, "inputs": values, "expected": expected,
                             "voltage": voltage, "dont_care": index in result.dont_cares})
    (artifact / "results.json").write_text(json.dumps(measurements, indent=2) + "\n")


@pytest.mark.parametrize("value", ["NaN", "Inf", "-Inf", "bad", "2.5", ""])
def test_bad_output_rejected(value):
    log = f"Node  Voltage\n----\n n2 {value}\n\nSource Current\n"
    with pytest.raises(AssertionError):
        read_output(subprocess.CompletedProcess([], 0, log, ""), "n2")


@pytest.mark.parametrize("diagnostic,code", [("", 1), ("no convergence", 0),
    ("singular matrix", 0), ("Error: invalid model", 0), ("timestep too small", 0)])
def test_solver_failure_not_masked_by_valid_voltage(diagnostic, code):
    log = "Node Voltage\n----\nn2 5\n\nSource Current\n"
    with pytest.raises(AssertionError):
        read_output(subprocess.CompletedProcess([], code, log, diagnostic), "n2")


def test_missing_binary_fails_required_job(monkeypatch):
    monkeypatch.setenv("OHMWORK_REQUIRE_NGSPICE", "1")
    monkeypatch.setattr(shutil, "which", lambda _: None)
    with pytest.raises(pytest.fail.Exception, match="Required ngspice"):
        ngspice_executable()


def test_complement_stimulus_mutation_detected():
    layout = build_textbook_schematic(synthesize_from_input(expr="a", dual_rail=True), "Y")
    text = render_spice_example(layout, {"a": False})
    # Complement-only a: final source must be high, even though primary is unused.
    assert "v2 " in text
    corrupt = re.sub(r"(v2 \S+ 0 DC )5", r"\g<1>0", text)
    assert corrupt != text
    with pytest.raises(AssertionError):
        check_harness(corrupt, layout, {"a": False})


def test_model_diagnostic_is_not_misread_as_output():
    # ngspice 42 prints unset noise fields as "<<NAN, error = 7>>".
    # Output validation must read the node table, not unrelated model fields.
    log = "Node Voltage\n----\nn2 5\n\nSource Current\n model kf <<NAN, error = 7>>\n"
    assert read_output(subprocess.CompletedProcess([], 0, log, ""), "n2") == (True, 5)


@pytest.mark.parametrize("voltage,expected", [(1, False), (4, True), (0, False), (5, True)])
def test_pinned_voltage_thresholds(voltage, expected):
    log = f"Node Voltage\n----\nn2 {voltage}\n\nSource Current\n"
    assert read_output(subprocess.CompletedProcess([], 0, log, ""), "n2")[0] is expected


def test_no_node_table_is_not_treated_as_logic_zero():
    with pytest.raises(AssertionError, match="Missing operating-point"):
        read_output(subprocess.CompletedProcess([], 0, "No. of Data Rows : 1", ""), "n2")
