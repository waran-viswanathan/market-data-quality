"""Split/dividend adjustment consistency between adjusted and raw closes.

Why this failure mode exists at real vendors: adjusted prices are
recomputed from a corporate-action database maintained separately from the
price feed.  When an action is entered late, entered twice, or backfilled
with the wrong factor, the entire adjusted history is silently rewritten.
The invariant we exploit: ``adj_close / close`` must be piecewise constant,
stepping only at ex-dates, and equal to 1.0 on the most recent bar.  Three
violations matter:

* a one-day-only discrepancy (the ratio jumps and immediately jumps back)
  — a bad adjusted tick or an action applied to the wrong date;
* a continuous drift (the ratio changes day after day) — factors applied
  incrementally instead of as a step;
* a terminal ratio away from 1.0 — the adjusted series is not anchored to
  the current price, i.e. adjustments are stale.
"""

from __future__ import annotations

import pandas as pd

from market_data_quality.checks._runs import consecutive_runs
from market_data_quality.config import Config
from market_data_quality.findings import Finding, Severity, to_dates

CHECK = "adjustment_consistency"

#: A change-run at least this long is treated as a drift, not discrete steps.
_DRIFT_MIN_DAYS = 3


def check_adjustment_consistency(df: pd.DataFrame, ticker: str, config: Config) -> list[Finding]:
    """Verify that ``adj_close / close`` is piecewise constant.

    Args:
        df: OHLCV frame with unique, sorted date index; needs ``close`` and
            ``adj_close`` columns (silently skipped if ``adj_close`` is
            absent or empty, e.g. for Stooq data).
        ticker: Ticker symbol for the findings.
        config: Thresholds (``adjustment_ratio_tol``).

    Returns:
        ERROR findings for one-day blips, WARNING for drifts and an
        unanchored terminal ratio, INFO for clean steps (inferred corporate
        actions worth cross-checking against an actions calendar).
    """
    if "adj_close" not in df.columns:
        return []
    valid = df["adj_close"].notna() & df["close"].notna() & df["close"].ne(0)
    if valid.sum() < 2:
        return []

    ratio = (df["adj_close"] / df["close"])[valid]
    tol = config.adjustment_ratio_tol
    change = ratio.pct_change().abs().gt(tol)

    # Blip: ratio changes at t, changes again at t+1, and lands back where it
    # started — the adjusted series disagrees with raw on exactly one day.
    returns_to_prior = ((ratio.shift(-1) / ratio.shift(1)) - 1).abs().le(tol)
    blip = change & change.shift(-1, fill_value=False) & returns_to_prior
    blip_tail = blip.shift(1, fill_value=False)

    # Drift: the ratio keeps moving for several consecutive days.
    change_run = change.ne(change.shift()).cumsum()
    run_length = change.groupby(change_run).transform("size")
    drift = change & run_length.ge(_DRIFT_MIN_DAYS) & ~blip & ~blip_tail

    step = change & ~blip & ~blip_tail & ~drift

    findings: list[Finding] = []
    for timestamp in ratio.index[blip]:
        position = ratio.index.get_loc(timestamp)
        findings.append(
            Finding(
                check=CHECK,
                severity=Severity.ERROR,
                ticker=ticker,
                dates=to_dates([timestamp]),
                detail=(
                    f"adjusted/raw ratio is {ratio.iloc[position]:.4f} on this day only "
                    f"(neighbours at {ratio.iloc[position - 1]:.4f}) — one-day adjustment "
                    "discrepancy: bad adjusted tick or action applied to the wrong date"
                ),
            )
        )
    for run in consecutive_runs(ratio.index[drift], within=ratio.index):
        first, last = ratio.loc[run[0]], ratio.loc[run[-1]]
        findings.append(
            Finding(
                check=CHECK,
                severity=Severity.WARNING,
                ticker=ticker,
                dates=to_dates(run),
                detail=(
                    f"adjusted/raw ratio drifts continuously over {len(run)} sessions "
                    f"({first:.4f} -> {last:.4f}) — adjustment factors applied "
                    "incrementally instead of stepping at an ex-date"
                ),
            )
        )
    for timestamp in ratio.index[step]:
        position = ratio.index.get_loc(timestamp)
        step_pct = (ratio.iloc[position] / ratio.iloc[position - 1] - 1) * 100
        findings.append(
            Finding(
                check=CHECK,
                severity=Severity.INFO,
                ticker=ticker,
                dates=to_dates([timestamp]),
                detail=(
                    f"adjusted/raw ratio steps {step_pct:+.2f}% "
                    f"({ratio.iloc[position - 1]:.4f} -> {ratio.iloc[position]:.4f}) — "
                    "consistent with a dividend/split ex-date; verify against the "
                    "corporate-actions calendar"
                ),
            )
        )

    terminal = ratio.iloc[-1]
    if abs(terminal - 1.0) > tol:
        findings.append(
            Finding(
                check=CHECK,
                severity=Severity.WARNING,
                ticker=ticker,
                dates=to_dates([ratio.index[-1]]),
                detail=(
                    f"adjusted/raw ratio on the latest bar is {terminal:.4f}, expected 1.0 — "
                    "adjusted series is not anchored to the current price (stale factors)"
                ),
            )
        )
    return findings
