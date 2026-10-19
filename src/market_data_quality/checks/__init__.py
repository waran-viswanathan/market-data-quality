"""Validation checks.

Every check is a pure function ``(DataFrame, ticker, Config, ...) ->
list[Finding]``: no I/O, no mutation of the input frame, no global state.
That makes each check independently testable against a small fixture CSV
and easy to reason about in isolation.
"""

from market_data_quality.checks.adjustment import check_adjustment_consistency
from market_data_quality.checks.missing_days import check_missing_days
from market_data_quality.checks.reconcile import check_cross_source
from market_data_quality.checks.spikes import check_price_spikes
from market_data_quality.checks.stale import check_stale_prices

#: Display order of checks in reports (ingestion failures are synthesized
#: by the pipeline rather than by a check function).
CHECK_ORDER = [
    "ingestion",
    "schema",
    "missing_days",
    "price_spikes",
    "stale_prices",
    "adjustment_consistency",
    "cross_source",
]

__all__ = [
    "CHECK_ORDER",
    "check_adjustment_consistency",
    "check_cross_source",
    "check_missing_days",
    "check_price_spikes",
    "check_stale_prices",
]

