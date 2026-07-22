"""Spike detection and real-event vs bad-tick classification."""

import datetime as dt

import pandas as pd

from market_data_quality.checks import check_price_spikes
from market_data_quality.findings import Severity

from tests.conftest import load_fixture

REAL_EVENT = dt.date(2024, 2, 29)  # +12%, volume x5, persists
BAD_TICK = dt.date(2024, 3, 21)  # +12%, normal volume, fully reverts


def _by_date(findings, date):
    return [f for f in findings if f.dates == (date,)]


def test_clean_frame_has_no_findings(config) -> None:
    assert check_price_spikes(load_fixture("clean.csv"), "CLEAN", config) == []


def test_real_event_classified_by_volume_and_persistence(config) -> None:
    findings = check_price_spikes(load_fixture("spikes.csv"), "TEST", config)
    (real,) = _by_date(findings, REAL_EVENT)
    assert real.severity is Severity.INFO
    assert "likely real event" in real.detail
    assert "volume spiked" in real.detail


def test_bad_tick_classified_by_revert(config) -> None:
    findings = check_price_spikes(load_fixture("spikes.csv"), "TEST", config)
    (bad,) = _by_date(findings, BAD_TICK)
    assert bad.severity is Severity.ERROR
    assert "likely bad tick" in bad.detail
    assert "reverted" in bad.detail


def test_second_source_confirmation_beats_local_heuristics(config) -> None:
    primary = load_fixture("spikes.csv")
    secondary = load_fixture("spikes_second_source.csv")
    findings = check_price_spikes(primary, "TEST", config, other=secondary)
    (real,) = _by_date(findings, REAL_EVENT)
    (bad,) = _by_date(findings, BAD_TICK)
    assert "second source shows the same move" in real.detail
    assert real.severity is Severity.INFO
    assert "second source does not show the move" in bad.detail
    assert bad.severity is Severity.ERROR


def test_non_positive_prices_reported(config) -> None:
    df = load_fixture("clean.csv")
    df.iloc[5, df.columns.get_loc("close")] = -1.0
    findings = check_price_spikes(df, "TEST", config)
    assert any(
        f.severity is Severity.ERROR and "non-positive" in f.detail for f in findings
    )


def test_flags_are_never_deletions(config) -> None:
    df = load_fixture("spikes.csv")
    before = df.copy()
    check_price_spikes(df, "TEST", config)
    pd.testing.assert_frame_equal(df, before)  # input is never mutated
