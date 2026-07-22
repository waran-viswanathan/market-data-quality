"""Missing trading sessions and duplicated timestamps.

Why this failure mode exists at real vendors: daily files are assembled
from exchange feeds plus manual backfill jobs.  A failed backfill leaves
holes; a re-run that appends instead of upserting produces duplicate rows;
a timezone bug shifts rows onto weekends.  All of these silently corrupt
anything downstream that assumes exactly one row per session — return
calculations, rolling windows, calendar joins — so we compare the index
against an NYSE session calendar rather than trusting it.
"""

from __future__ import annotations

import pandas as pd

from market_data_quality.checks._runs import consecutive_runs
from market_data_quality.config import Config
from market_data_quality.findings import Finding, Severity, to_dates
from market_data_quality.trading_calendar import nyse_sessions

CHECK = "missing_days"


def check_missing_days(df: pd.DataFrame, ticker: str, config: Config) -> list[Finding]:
    """Report duplicated timestamps and gaps vs the NYSE session calendar.

    Args:
        df: OHLCV frame indexed by session date (duplicates allowed here —
            detecting them is part of the job).
        ticker: Ticker symbol for the findings.
        config: Thresholds (unused; kept for the uniform check signature).

    Returns:
        One finding per duplicate set, per contiguous gap, and per group of
        rows dated on non-sessions.
    """
    del config  # uniform signature; this check is threshold-free
    findings: list[Finding] = []
    index = pd.DatetimeIndex(df.index)

    duplicated = index[index.duplicated(keep="first")].unique()
    if len(duplicated):
        findings.append(
            Finding(
                check=CHECK,
                severity=Severity.ERROR,
                ticker=ticker,
                dates=to_dates(duplicated),
                detail=(
                    f"{len(duplicated)} session(s) appear more than once — "
                    "vendor re-run appended instead of upserting"
                ),
            )
        )

    unique = index.unique().sort_values()
    if len(unique) < 2:
        return findings
    expected = nyse_sessions(unique.min(), unique.max())

    missing = expected.difference(unique)
    for run in consecutive_runs(missing, within=expected):
        findings.append(
            Finding(
                check=CHECK,
                severity=Severity.WARNING,
                ticker=ticker,
                dates=to_dates(run),
                detail=(
                    f"gap of {len(run)} expected NYSE session(s) with no data "
                    "(not explained by weekends or holidays)"
                ),
            )
        )

    unexpected = unique.difference(expected)
    if len(unexpected):
        findings.append(
            Finding(
                check=CHECK,
                severity=Severity.WARNING,
                ticker=ticker,
                dates=to_dates(unexpected),
                detail=(
                    f"{len(unexpected)} row(s) dated on non-trading days "
                    "(weekend/holiday) — calendar bug or timezone shift at the vendor"
                ),
            )
        )
    return findings
