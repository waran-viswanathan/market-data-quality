"""Threshold configuration for all checks.

Thresholds live in one frozen dataclass so every check shares a single,
explicit source of truth.  Values are loaded from the `[thresholds]` table
of a `config.toml`; unknown keys raise instead of being ignored, because a
silently misspelled threshold is itself a data-quality bug.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

DEFAULT_CONFIG_FILENAME = "config.toml"


@dataclass(frozen=True, slots=True)
class Config:
    """Tunable thresholds for the validation checks."""

    # Price spikes.
    spike_sigma: float = 4.0
    spike_window: int = 21
    spike_volume_ratio: float = 3.0
    spike_revert_fraction: float = 0.5

    # Stale prices.
    stale_max_days: int = 5
    stale_low_volume_fraction: float = 0.25

    # Adjustment consistency.
    adjustment_ratio_tol: float = 1e-3

    # Cross-source reconciliation.
    reconcile_close_bps: float = 20.0
    reconcile_volume_rel_tol: float = 0.5


def load_config(path: Path | None = None) -> Config:
    """Load thresholds from a TOML file, falling back to defaults.

    Args:
        path: Explicit config file.  When ``None``, ``./config.toml`` is used
            if it exists, otherwise built-in defaults are returned.

    Returns:
        A frozen :class:`Config`.

    Raises:
        FileNotFoundError: If an explicit ``path`` does not exist.
        ValueError: If the ``[thresholds]`` table contains unknown keys.
    """
    if path is None:
        candidate = Path(DEFAULT_CONFIG_FILENAME)
        if not candidate.exists():
            return Config()
        path = candidate
    path = Path(path)
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    table = data.get("thresholds", {})
    valid = {field.name for field in fields(Config)}
    unknown = sorted(set(table) - valid)
    if unknown:
        raise ValueError(f"unknown threshold keys in {path}: {', '.join(unknown)}")
    return Config(**table)
