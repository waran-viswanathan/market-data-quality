"""Cross-source reconciliation of two fixture vendors."""

import datetime as dt
from dataclasses import replace

from market_data_quality.checks import check_cross_source
from market_data_quality.findings import Severity

from tests.conftest import load_fixture


def _findings(config):
    return check_cross_source(
        load_fixture("reconcile_a.csv"),
        load_fixture("reconcile_b.csv"),
        "TEST",
        config,
        primary_name="alpha",
        secondary_name="beta",
    )


def test_sessions_present_in_only_one_source(config) -> None:
    findings = _findings(config)
    only_a = [f for f in findings if "present in alpha" in f.detail]
    only_b = [f for f in findings if "present in beta" in f.detail]
    assert len(only_a) == 1 and len(only_b) == 1
    assert only_a[0].dates == (dt.date(2024, 1, 9), dt.date(2024, 1, 10))
    assert only_b[0].dates == (dt.date(2024, 1, 31),)


def test_close_disagreement_grouped_into_one_run(config) -> None:
    findings = _findings(config)
    closes = [f for f in findings if "closes disagree" in f.detail]
    assert len(closes) == 1
    assert closes[0].severity is Severity.ERROR
    assert closes[0].dates == (
        dt.date(2024, 2, 7),
        dt.date(2024, 2, 8),
        dt.date(2024, 2, 9),
    )


def test_volume_disagreement_reported(config) -> None:
    findings = _findings(config)
    volumes = [f for f in findings if "volumes disagree" in f.detail]
    assert len(volumes) == 1
    assert volumes[0].severity is Severity.WARNING
    assert volumes[0].dates == (dt.date(2024, 2, 14),)


def test_tolerance_suppresses_close_findings(config) -> None:
    tolerant = replace(config, reconcile_close_bps=100.0)
    closes = [f for f in _findings(tolerant) if "closes disagree" in f.detail]
    assert closes == []


def test_constant_ratio_offset_labeled_as_convention_mismatch(config) -> None:
    a = load_fixture("reconcile_a.csv")
    b = a.copy()
    b["close"] = a["close"] * 1.02  # constant 2% offset on every session
    findings = check_cross_source(a, b, "TEST", config)
    closes = [f for f in findings if "closes disagree" in f.detail]
    assert len(closes) == 1
    assert closes[0].severity is Severity.WARNING
    assert "adjustment conventions" in closes[0].detail


def test_identical_sources_have_no_findings(config) -> None:
    a = load_fixture("reconcile_a.csv")
    assert check_cross_source(a, a.copy(), "TEST", config) == []
