"""Shared fixture loading for the offline test suite.

All tests run against small hand-crafted CSVs in ``tests/fixtures`` with
known planted defects — no network access anywhere.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from market_data_quality.config import Config

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> pd.DataFrame:
    """Load a fixture CSV into the pipeline's standard frame shape."""
    df = pd.read_csv(FIXTURES / name, parse_dates=["date"], index_col="date")
    df.index.name = "date"
    return df


@pytest.fixture()
def config() -> Config:
    """Default thresholds used across the suite."""
    return Config()
