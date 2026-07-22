"""Cross-source reconciliation of two vendors' series for one ticker.

Why this check exists: no vendor is ground truth, but two independently
built pipelines rarely make the *same* mistake, so disagreement localises
errors that no single-source check can see.  Two patterns recur in
practice: short disagreements (one vendor captured a bad print or missed a
correction) and long near-constant-ratio offsets, which almost always mean
the vendors apply different split/dividend adjustment conventions rather
than that either price is wrong — the finding says which pattern it sees.
"""

from __future__ import annotations

import pandas as pd

from market_data_quality.checks._runs import consecutive_runs
from market_data_quality.config import Config
from market_data_quality.findings import Finding, Severity, to_dates

CHECK = "cross_source"

#: Disagreement runs at least this long with a near-constant ratio are
#: reported as an adjustment-convention mismatch rather than bad prices.
_CONVENTION_MIN_DAYS = 5
_CONVENTION_RATIO_CV = 1e-3


def check_cross_source(
    primary: pd.DataFrame,
    secondary: pd.DataFrame,
    ticker: str,
    config: Config,
    primary_name: str = "yfinance",
    secondary_name: str = "stooq",
) -> list[Finding]:
    """Align two sources by date and report material disagreements.

    Args:
        primary: First source frame (unique, sorted date index).
        secondary: Second source frame (unique, sorted date index).
        ticker: Ticker symbol for the findings.
        config: Thresholds (``reconcile_close_bps``,
            ``reconcile_volume_rel_tol``).
        primary_name: Label for the first source in messages.
        secondary_name: Label for the second source in messages.

    Returns:
        Findings for dates present in only one source, close disagreements
        beyond the bps tolerance (grouped into consecutive runs), and
        volume disagreements beyond the relative tolerance.
    """
    merged = primary[["close", "volume"]].add_suffix("_a").join(
        secondary[["close", "volume"]].add_suffix("_b"), how="outer"
    )
    findings: list[Finding] = []

    for mask, present, absent in (
        (merged["close_a"].notna() & merged["close_b"].isna(), primary_name, secondary_name),
        (merged["close_b"].notna() & merged["close_a"].isna(), secondary_name, primary_name),
    ):
        if mask.any():
            findings.append(
                Finding(
                    check=CHECK,
                    severity=Severity.WARNING,
                    ticker=ticker,
                    dates=to_dates(merged.index[mask]),
                    detail=(
                        f"{int(mask.sum())} session(s) present in {present} "
                        f"but missing from {absent}"
                    ),
                )
            )

    both = merged.dropna(subset=["close_a", "close_b"])
    ratio = both["close_a"] / both["close_b"]
    bps = (ratio - 1.0).abs() * 1e4
    disagree = bps.gt(config.reconcile_close_bps)
    for run in consecutive_runs(both.index[disagree], within=both.index):
        run_ratio = ratio.loc[run]
        run_bps = bps.loc[run]
        convention_offset = (
            len(run) >= _CONVENTION_MIN_DAYS
            and (run_ratio.std() / run_ratio.mean()) < _CONVENTION_RATIO_CV
        )
        if convention_offset:
            severity = Severity.WARNING
            explanation = (
                f"near-constant {primary_name}/{secondary_name} ratio "
                f"{run_ratio.mean():.4f} — differing split/dividend adjustment "
                "conventions, not bad prices"
            )
        else:
            severity = Severity.ERROR
            explanation = "sources genuinely disagree — at least one carries bad prices"
        findings.append(
            Finding(
                check=CHECK,
                severity=severity,
                ticker=ticker,
                dates=to_dates(run),
                detail=(
                    f"closes disagree beyond {config.reconcile_close_bps:.0f} bps on "
                    f"{len(run)} session(s) (max {run_bps.max():.0f} bps); {explanation}"
                ),
            )
        )

    volumes = both[["volume_a", "volume_b"]].dropna()
    if not volumes.empty:
        denominator = volumes.max(axis=1)
        rel = (volumes["volume_a"] - volumes["volume_b"]).abs() / denominator.where(denominator > 0)
        vol_disagree = rel.gt(config.reconcile_volume_rel_tol)
        if vol_disagree.any():
            findings.append(
                Finding(
                    check=CHECK,
                    severity=Severity.WARNING,
                    ticker=ticker,
                    dates=to_dates(volumes.index[vol_disagree]),
                    detail=(
                        f"volumes disagree by more than "
                        f"{config.reconcile_volume_rel_tol:.0%} on "
                        f"{int(vol_disagree.sum())} session(s) (max {rel.max():.0%}) — "
                        "sources likely count consolidated vs primary-exchange volume "
                        "differently, or one is missing a correction"
                    ),
                )
            )
    return findings
