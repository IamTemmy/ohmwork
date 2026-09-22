"""Deterministic D20 work/storage limits for five-variable exact searches.

These are search limits, not promises about wall-clock latency. Exhaustion
raises before a result escapes; no truncated cover inventory is returned.
Four-variable policy and the independent derivation-table limit are unchanged.
"""
from dataclasses import dataclass


class SearchLimitExceeded(RuntimeError):
    """Exact search stopped; no minimum or partial answer is available."""


@dataclass
class SearchBudget:
    max_work: int = 2_000_000
    max_items: int = 20_000
    work: int = 0
    peak_items: int = 0

    def check(self, *, work: int = 1, items: int = 0) -> None:
        self.work += work
        self.peak_items = max(self.peak_items, items)
        if self.work > self.max_work or items > self.max_items:
            raise SearchLimitExceeded(
                'Five-variable exact search exceeded its work/storage limit; '
                'no complete minimum was established and no partial result is returned.'
            )
