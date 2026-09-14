"""D7's independent verification: simulate the actual constructed PDN/PUN
switch networks (not the abstract Boolean formula that produced them)
across every input vector, and check two things separately, never
collapsed into one pass/fail:

  (a) *Functional equivalence*: the simulated output matches the source
      truth table on every row that isn't a don't-care.
  (b) *Static CMOS structural validity*: no input leaves the output
      floating (neither network conducts) or shorted (both do).

For a PUN built as ``network.dual`` of a PDN, (b) is a mathematical
invariant of the construction — but this module simulates it anyway rather
than assuming it, per the project's verification-over-trust stance (charter
§4). That also means it doubles as a real check on any network that *isn't*
a clean dual (e.g. if synthesis is later extended to hand-tuned or
multi-stage networks where the invariant no longer holds by construction)."""

from __future__ import annotations

from dataclasses import dataclass

from ohmwork.derivation import all_assignments
from ohmwork.network import Network, conducts


@dataclass(frozen=True)
class VerificationResult:
    vector_count: int
    functional_pass: bool
    structural_pass: bool
    mismatches: tuple[int, ...]  # minterm indices where output != expected
    floating: tuple[int, ...]  # minterm indices where neither network conducts
    shorted: tuple[int, ...]  # minterm indices where both networks conduct
    dont_care_assignments: dict[int, bool]  # D4: what each don't-care resolved to

    @property
    def passed(self) -> bool:
        return self.functional_pass and self.structural_pass


def verify(
    pdn: Network,
    pun: Network,
    var_order: list[str],
    minterms: set[int],
    dont_cares: set[int] = frozenset(),
) -> VerificationResult:
    """Simulate ``pdn``/``pun`` across every assignment of ``var_order``
    (same row order as :func:`ohmwork.derivation.all_assignments`, so row
    index == minterm number) and check both D7 criteria independently."""
    rows = all_assignments(var_order)
    mismatches: list[int] = []
    floating: list[int] = []
    shorted: list[int] = []
    dont_care_assignments: dict[int, bool] = {}

    for i, row in enumerate(rows):
        pdn_on = conducts(pdn, row)
        pun_on = conducts(pun, row)
        if pdn_on and pun_on:
            shorted.append(i)
            continue
        if not pdn_on and not pun_on:
            floating.append(i)
            continue
        output = pun_on  # PUN conducting pulls the output to VDD (1)
        if i in dont_cares:
            dont_care_assignments[i] = output
        elif output != (i in minterms):
            mismatches.append(i)

    return VerificationResult(
        vector_count=len(rows),
        functional_pass=not mismatches,
        structural_pass=not floating and not shorted,
        mismatches=tuple(mismatches),
        floating=tuple(floating),
        shorted=tuple(shorted),
        dont_care_assignments=dont_care_assignments,
    )
