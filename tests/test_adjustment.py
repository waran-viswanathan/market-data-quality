"""Adjustment-ratio consistency: steps, blips, drifts, anchoring."""

import datetime as dt

import numpy as np

from market_data_quality.checks import check_adjustment_consistency
from market_data_quality.findings import Severity

from tests.conftest import load_fixture


def test_clean_frame_has_no_findings(config) -> None:
    # clean.csv has adj_close == close (ratio 1.0 everywhere).
    assert check_adjustment_consistency(load_fixture("clean.csv"), "CLEAN", config) == []


def test_dividend_like_step_is_info(config) -> None:
    findings = check_adjustment_consistency(load_fixture("adjustment.csv"), "TEST", config)
    steps = [f for f in findings if f.severity is Severity.INFO]
    assert len(steps) == 1
    assert steps[0].dates == (dt.date(2024, 1, 31),)
    assert "ex-date" in steps[0].detail


def test_one_day_blip_is_error(config) -> None:
    findings = check_adjustment_consistency(load_fixture("adjustment.csv"), "TEST", config)
    blips = [f for f in findings if f.severity is Severity.ERROR]
    assert len(blips) == 1
    assert blips[0].dates == (dt.date(2024, 2, 22),)
    assert "one-day adjustment discrepancy" in blips[0].detail


def test_drift_is_warning(config) -> None:
    findings = check_adjustment_consistency(load_fixture("adjustment.csv"), "TEST", config)
    drifts = [f for f in findings if "drifts continuously" in f.detail]
    assert len(drifts) == 1
    assert drifts[0].severity is Severity.WARNING
    assert drifts[0].dates[0] == dt.date(2024, 3, 7)
    assert drifts[0].dates[-1] == dt.date(2024, 3, 18)


def test_unanchored_terminal_ratio_is_warning(config) -> None:
    df = load_fixture("clean.csv")
    df["adj_close"] = df["close"] * 0.97  # constant ratio but != 1.0 today
    findings = check_adjustment_consistency(df, "TEST", config)
    assert len(findings) == 1
    assert findings[0].severity is Severity.WARNING
    assert "not anchored" in findings[0].detail


def test_missing_adj_close_is_skipped(config) -> None:
    df = load_fixture("clean.csv")
    df["adj_close"] = np.nan  # e.g. Stooq carries no adjusted close
    assert check_adjustment_consistency(df, "TEST", config) == []
