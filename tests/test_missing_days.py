"""Missing-session and duplicate-timestamp detection."""

import datetime as dt

import pandas as pd

from market_data_quality.checks import check_missing_days
from market_data_quality.findings import Severity

from tests.conftest import load_fixture


def test_clean_frame_has_no_findings(config) -> None:
    assert check_missing_days(load_fixture("clean.csv"), "CLEAN", config) == []


def test_gap_reported_as_single_run(config) -> None:
    findings = check_missing_days(load_fixture("missing_dup.csv"), "TEST", config)
    gaps = [f for f in findings if "gap" in f.detail]
    assert len(gaps) == 1
    assert gaps[0].severity is Severity.WARNING
    assert gaps[0].dates == (dt.date(2024, 2, 14), dt.date(2024, 2, 15))


def test_duplicate_timestamp_reported(config) -> None:
    findings = check_missing_days(load_fixture("missing_dup.csv"), "TEST", config)
    dups = [f for f in findings if "more than once" in f.detail]
    assert len(dups) == 1
    assert dups[0].severity is Severity.ERROR
    assert dups[0].dates == (dt.date(2024, 1, 17),)


def test_weekend_row_reported(config) -> None:
    df = load_fixture("clean.csv")
    df.loc[pd.Timestamp("2024-01-13")] = df.iloc[0]  # a Saturday
    findings = check_missing_days(df.sort_index(), "TEST", config)
    weekend = [f for f in findings if "non-trading" in f.detail]
    assert len(weekend) == 1
    assert weekend[0].dates == (dt.date(2024, 1, 13),)
