"""Stale prices: implausibly long runs of an unchanged close.

Why this failure mode exists at real vendors: when an exchange feed handler
dies mid-session, many vendors forward-fill the last good price rather than
publish nothing — the series looks alive but is frozen, and every
downstream volatility or correlation estimate quietly collapses.  The
subtlety is that thinly-traded names legitimately print the same close for
days, so runs accompanied by abnormally low volume are downgraded to
informational instead of being treated as feed failures.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from market_data_quality.config import Config
from market_data_quality.findings import Finding, Severity, to_dates

CHECK = "stale_prices"


def check_stale_prices(df: pd.DataFrame, ticker: str, config: Config) -> list[Finding]:
    """Report runs where the close is unchanged beyond ``stale_max_days``.

    A run of ``n`` identical closes represents ``n - 1`` consecutive
    unchanged sessions; runs with ``n - 1 > stale_max_days`` are reported.

    Args:
        df: OHLCV frame with unique, sorted date index.
        ticker: Ticker symbol for the findings.
        config: Thresholds (``stale_max_days``, ``stale_low_volume_fraction``).

    Returns:
        One finding per offending flat run — WARNING at normal volume
        (likely frozen feed), INFO at low volume (plausibly thin trading).
    """
    close = df["close"]
    run_id = close.ne(close.shift()).cumsum()
    runs = (
        pd.DataFrame(
            {
                "session": df.index,
                "run": run_id.to_numpy(),
                "close": close.to_numpy(),
                "volume": df["volume"].to_numpy(),
            }
        )
        .groupby("run")
        .agg(
            n=("session", "size"),
            start=("session", "min"),
            end=("session", "max"),
            price=("close", "first"),
            median_volume=("volume", "median"),
        )
    )
    offending = runs[runs["n"] - 1 > config.stale_max_days]
    if offending.empty:
        return []

    overall_median_volume = df["volume"].median()
    low_volume_cutoff = config.stale_low_volume_fraction * overall_median_volume

    findings: list[Finding] = []
    for run_key, run in offending.iterrows():
        run_dates = df.index[run_id.to_numpy() == run_key]
        low_volume = bool(np.isfinite(run["median_volume"]) and run["median_volume"] <= low_volume_cutoff)
        explanation = (
            "volume also dried up — plausibly a thinly-traded name going flat"
            if low_volume
            else "volume stayed normal while the price froze — likely a stale feed"
        )
        findings.append(
            Finding(
                check=CHECK,
                severity=Severity.INFO if low_volume else Severity.WARNING,
                ticker=ticker,
                dates=to_dates(run_dates),
                detail=(
                    f"close pinned at {run['price']:.2f} for {int(run['n'])} sessions "
                    f"({int(run['n']) - 1} consecutive unchanged closes); run median volume "
                    f"{run['median_volume']:,.0f} vs ticker median {overall_median_volume:,.0f} — "
                    f"{explanation}"
                ),
            )
        )
    return findings
