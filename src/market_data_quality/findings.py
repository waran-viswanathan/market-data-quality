"""Structured findings emitted by every check.

Checks never mutate or "repair" data — they return `Finding` records that
carry enough context (check name, severity, ticker, affected dates, and a
human-readable detail string) for a reviewer to decide what to do.  Keeping
the schema flat and typed makes findings trivial to tabulate in reports and
to assert on in tests.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

import pandas as pd


class Severity(str, Enum):
    """How much a finding should worry a consumer of the data."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class Finding:
    """A single data-quality observation for one ticker.

    Attributes:
        check: Machine name of the check that produced the finding.
        severity: How serious the finding is.
        ticker: Ticker symbol the finding applies to.
        dates: Affected session dates, sorted ascending.
        detail: Human-readable explanation with the relevant numbers.
    """

    check: str
    severity: Severity
    ticker: str
    dates: tuple[dt.date, ...]
    detail: str

    @property
    def date_span(self) -> str:
        """Compact 'YYYY-MM-DD' or 'YYYY-MM-DD .. YYYY-MM-DD' label."""
        if not self.dates:
            return "-"
        first, last = self.dates[0], self.dates[-1]
        if first == last:
            return first.isoformat()
        return f"{first.isoformat()} .. {last.isoformat()}"


def to_dates(index: Iterable[object]) -> tuple[dt.date, ...]:
    """Convert an iterable of timestamps to a sorted tuple of dates."""
    return tuple(sorted(pd.Timestamp(value).date() for value in index))
