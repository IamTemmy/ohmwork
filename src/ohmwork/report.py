"""Formats a full M1b ``synth`` report: candidate comparison, transistor
breakdown, ASCII schematic, and the D7 verification result — one text block
that shows the work end to end (design principle 5.2), never just the
final number."""

from __future__ import annotations

from ohmwork.expr import render as render_expr
from ohmwork.network import render_network
from ohmwork.synth import SynthesisResult
from ohmwork.verify import VerificationResult


def _schematic(result: SynthesisResult) -> str:
    pun_line = f"PUN: {render_network(result.pun)}"
    pdn_line = f"PDN: {render_network(result.pdn)}"
    width = max(len(pun_line), len(pdn_line), 5) + 2
    return "\n".join(
        [
            "VDD".center(width),
            "|".center(width),
            pun_line.center(width),
            "|".center(width),
            "F".center(width),
            "|".center(width),
            pdn_line.center(width),
            "|".center(width),
            "GND".center(width),
        ]
    )


def format_synth_report(result: SynthesisResult, verification: VerificationResult) -> str:
    lines: list[str] = []

    lines.append("Candidates considered (D1/D16: every literal-minimal AOI/OAI cover):")
    for c in sorted(result.other_candidates, key=lambda c: (c.total_cost, render_expr(c.f_prime), c.label)):
        chosen = " <- chosen" if c is result.chosen else ""
        lines.append(
            f"  {c.label}: F' = {render_expr(c.f_prime)} "
            f"({c.core_cost} core + {c.inverter_cost} inverter = {c.total_cost} transistors){chosen}"
        )
    lines.append("")

    lines.append(f"Gate: {result.gate_name}")
    lines.append(f"F' = {render_expr(result.f_prime)}")
    lines.append("")

    lines.append("Transistor count:")
    lines.append(f"  PDN (NMOS):  {result.pdn_transistors}")
    lines.append(f"  PUN (PMOS):  {result.pun_transistors}")
    if result.inverter_literals:
        names = ", ".join(f"{n}'" for n in result.inverter_literals)
        lines.append(
            f"  Inverters:   {result.inverter_transistors} "
            f"(shared, one each for {names} — D12)"
        )
    else:
        lines.append("  Inverters:   0 (no complemented inputs needed)")
    lines.append(f"  Total:       {result.total_transistors}")
    lines.append("")

    lines.append(f"Stack height: PDN {result.pdn_stack_height}, PUN {result.pun_stack_height}")
    if result.stack_advisory:
        lines.append(f"  advisory: {result.stack_advisory}")
    lines.append("")

    if result.minimality_proof:
        lines.append(f"Minimality: {result.minimality_proof}")
    else:
        lines.append(
            "Minimality: not proven — search was limited to the flat AOI/OAI dual "
            "candidates (D1/D6); a different factoring might do better."
        )
    lines.append("")

    lines.append("Schematic:")
    lines.append(_schematic(result))
    lines.append("")

    lines.append("Verification (D7, two independent checks):")
    lines.append(f"  vectors simulated: {verification.vector_count}")
    if verification.functional_pass:
        lines.append("  functional equivalence: PASS")
    else:
        lines.append(f"  functional equivalence: FAIL — mismatches at {list(verification.mismatches)}")
    if verification.structural_pass:
        lines.append("  structural validity: PASS (no floating output, no VDD-GND short)")
    else:
        if verification.floating:
            lines.append(f"  structural validity: FAIL — floating at {list(verification.floating)}")
        if verification.shorted:
            lines.append(f"  structural validity: FAIL — shorted at {list(verification.shorted)}")
    if verification.dont_care_assignments:
        assigned = ", ".join(
            f"{i}->{'1' if v else '0'}" for i, v in sorted(verification.dont_care_assignments.items())
        )
        lines.append(f"  don't-cares assigned (D4): {assigned}")

    return "\n".join(lines)
