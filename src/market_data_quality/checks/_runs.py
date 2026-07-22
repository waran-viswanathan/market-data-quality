"""Shared helper for grouping dates into consecutive runs."""

from __future__ import annotations

import numpy as np
import pandas as pd


def consecutive_runs(dates: pd.DatetimeIndex, within: pd.DatetimeIndex) -> list[pd.DatetimeIndex]:
    """Split ``dates`` into runs occupying consecutive positions of ``within``.

    ``within`` supplies the notion of adjacency (e.g. the expected session
    calendar, or the merged index of two sources), so a "run" respects
    weekends and holidays instead of naive day arithmetic.

    Args:
        dates: Subset of ``within`` to group.
        within: Reference index defining adjacency.

    Returns:
        List of ascending ``DatetimeIndex`` runs, in order.
    """
    if len(dates) == 0:
        return []
    positions = within.get_indexer(dates)
    breaks = np.flatnonzero(np.diff(positions) != 1) + 1
    return [pd.DatetimeIndex(chunk) for chunk in np.split(dates.to_numpy(), breaks)]
