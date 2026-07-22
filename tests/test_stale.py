"""Stale-price run detection with the low-volume downgrade."""

import datetime as dt

from market_data_quality.checks import check_stale_prices
from market_data_quality.findings import Severity

from tests.conftest import load_fixture


def test_clean_frame_has_no_findings(config) -> None:
    assert check_stale_prices(load_fixture("clean.csv"), "CLEAN", config) == []


def test_normal_volume_freeze_is_warning(config) -> None:
    findings = check_stale_prices(load_fixture("stale.csv"), "TEST", config)
    warnings = [f for f in findings if f.severity is Severity.WARNING]
    assert len(warnings) == 1
    assert warnings[0].dates[0] == dt.date(2024, 1, 17)
    assert warnings[0].dates[-1] == dt.date(2024, 1, 29)
    assert "stale feed" in warnings[0].detail


def test_low_volume_flat_run_is_downgraded_to_info(config) -> None:
    findings = check_stale_prices(load_fixture("stale.csv"), "TEST", config)
    infos = [f for f in findings if f.severity is Severity.INFO]
    assert len(infos) == 1
    assert infos[0].dates[0] == dt.date(2024, 2, 22)
    assert infos[0].dates[-1] == dt.date(2024, 3, 8)
    assert "thinly-traded" in infos[0].detail


def test_threshold_is_respected(config) -> None:
    from dataclasses import replace

    lenient = replace(config, stale_max_days=20)
    assert check_stale_prices(load_fixture("stale.csv"), "TEST", lenient) == []
