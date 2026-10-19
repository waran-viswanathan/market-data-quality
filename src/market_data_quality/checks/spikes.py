"""Price spikes: detection plus real-event vs bad-tick classification.

Why this failure mode exists at real vendors: a daily close is the last
print a vendor's handler saw, and handlers occasionally capture a
fat-finger trade, a misplaced decimal, or a print from the wrong venue or
currency.  A genuine 10% earnings move and a corrupted tick look identical
in isolation, so deleting outliers destroys real information.  We therefore
FLAG, never delete, and classify each flag with three heuristics:

* second-source confirmation — an independent vendor showing the same move
  is the strongest evidence it is real;
* volume confirmation — real repricings come with real turnover;
* next-day persistence — bad ticks fully revert the next session because
  the underlying market never actually moved.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from market_data_quality.config import Config
from market_data_quality.findings import Finding, Severity, to_dates

CHECK = "price_spikes"

_LABEL_SEVERITY = {
    "likely real event": Severity.INFO,
    "likely bad tick": Severity.ERROR,
    "ambiguous": Severity.WARNING,
}


def check_price_spikes(
    df: pd.DataFrame,
    ticker: str,
    config: Config,
    other: pd.DataFrame | None = None,
) -> list[Finding]:
    """Flag returns beyond ``spike_sigma`` trailing standard deviations.

    Args:
        df: OHLCV frame with unique, sorted date index and ``close`` /
            ``volume`` columns.
        ticker: Ticker symbol for the findings.
        config: Thresholds (``spike_sigma``, ``spike_window``,
            ``spike_volume_ratio``, ``spike_revert_fraction``).
        other: Optional second-source frame for the same ticker, used to
            confirm or deny flagged moves.

    Returns:
        One finding per non-positive-price incident and per flagged spike,
        each spike labeled ``likely real event`` / ``likely bad tick`` /
        ``ambiguous`` with the reasoning inline.
    """
    findings: list[Finding] = []
    close = df["close"]

    non_positive = close.le(0)
    if non_positive.any():
        findings.append(
            Finding(
                check=CHECK,
                severity=Severity.ERROR,
                ticker=ticker,
                dates=to_dates(df.index[non_positive]),
                detail=(
                    f"{int(non_positive.sum())} non-positive close price(s) — "
                    "impossible for listed equities; corrupt rows"
                ),
            )
        )

    log_ret = np.log(close.where(close > 0)).diff()
    window = config.spike_window
    min_periods = max(5, window // 2)
    # Trailing window excludes the current day so a spike cannot inflate the
    # very statistics used to judge it.
    trailing = log_ret.shift(1).rolling(window, min_periods=min_periods)
    z = (log_ret - trailing.mean()) / trailing.std()
    spike = z.abs().gt(config.spike_sigma)
    if not spike.any():
        return findings

    volume = df["volume"]
    trailing_vol = volume.shift(1).rolling(window, min_periods=min_periods).median()
    volume_spiked = volume.gt(config.spike_volume_ratio * trailing_vol)

    next_ret = log_ret.shift(-1)
    reverted = (np.sign(next_ret) == -np.sign(log_ret)) & next_ret.abs().ge(
        config.spike_revert_fraction * log_ret.abs()
    )

    if other is not None and not other.empty:
        other_close = other["close"]
        other_ret = np.log(other_close.where(other_close > 0)).diff().reindex(df.index)
    else:
        other_ret = pd.Series(np.nan, index=df.index)
    confirmed = (np.sign(other_ret) == np.sign(log_ret)) & other_ret.abs().ge(
        0.5 * log_ret.abs()
    )
    denied = other_ret.notna() & ~confirmed

    labels = pd.Series(
        np.select(
            [
                confirmed,
                denied,
                volume_spiked & next_ret.notna() & ~reverted,
                reverted & ~volume_spiked,
                volume_spiked & next_ret.isna(),
            ],
            [
                "likely real event; second source shows the same move",
                "likely bad tick; second source does not show the move",
                "likely real event; volume spiked and the move persisted next day",
                "likely bad tick; normal volume and the move fully reverted next day",
                "ambiguous; volume spiked but next-session persistence is unavailable",
            ],
            default="ambiguous; volume and persistence heuristics disagree — review manually",
        ),
        index=df.index,
    )

    for timestamp in df.index[spike.fillna(False)]:
        label = labels.loc[timestamp]
        severity = _LABEL_SEVERITY[label.split(";")[0]]
        move_pct = (np.exp(log_ret.loc[timestamp]) - 1.0) * 100.0
        findings.append(
            Finding(
                check=CHECK,
                severity=severity,
                ticker=ticker,
                dates=to_dates([timestamp]),
                detail=(
                    f"{move_pct:+.1f}% close-to-close move "
                    f"(|z|={abs(z.loc[timestamp]):.1f} vs trailing {window}d) — {label}"
                ),
            )
        )
    return findings

