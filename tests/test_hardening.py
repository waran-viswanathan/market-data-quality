"""Regression cases for unavailable evidence, malformed values and cache windows."""

import numpy as np
import pandas as pd
import pytest

from market_data_quality import ingest
from market_data_quality.checks.missing_days import check_missing_days
from market_data_quality.checks.schema import check_schema
from market_data_quality.checks.spikes import check_price_spikes
from market_data_quality.config import Config
from market_data_quality.pipeline import check_ticker, run_pipeline
from market_data_quality.report import summarize


def frame() -> pd.DataFrame:
    return pd.DataFrame({"open": 100., "high": 101., "low": 99., "close": 100., "adj_close": 100., "volume": 1000.}, index=pd.date_range("2025-01-13", periods=5, freq="B"))


def test_both_sources_down_does_not_report_pass(monkeypatch, tmp_path):
    def unavailable(*args, **kwargs):
        raise ingest.IngestError("source unavailable")
    monkeypatch.setattr(ingest, "get_data", unavailable)
    result = run_pipeline(["X"], "2025-01-13", "2025-01-17", Config(), tmp_path / "cache", tmp_path / "reports")
    summary = summarize(result.findings, ["X"], result.executions).set_index("check")
    assert summary.loc["ingestion", "status"] == "FAIL"
    assert set(summary.drop("ingestion")["status"]) == {"UNAVAILABLE"}
    assert "all checks passed" not in result.markdown_path.read_text()


def test_all_nan_rows_fail_schema_and_do_not_pass_price_checks():
    df = frame() * np.nan
    executions = {}
    findings = check_ticker("X", {"yfinance": df}, Config(), executions=executions)
    summary = summarize(findings, ["X"], executions).set_index("check")
    assert summary.loc["schema", "status"] == "FAIL"
    assert summary.loc["price_spikes", "status"] == "UNAVAILABLE"
    assert summary.loc["adjustment_consistency", "status"] == "SKIPPED"


@pytest.mark.parametrize(("column", "value"), [("close", np.inf), ("open", np.nan), ("close", 0), ("volume", -1), ("high", 98)])
def test_schema_catches_invalid_values_and_ohlc_ranges(column, value):
    df = frame()
    df.loc[df.index[0], column] = value
    assert check_schema(df, "X", "source")


def test_missing_adjusted_close_and_short_history_are_explicitly_skipped():
    df = frame().drop(columns="adj_close")
    executions = {}
    check_ticker("X", {"stooq": df}, Config(), executions=executions)
    assert executions[("X", "adjustment_consistency")].status == "SKIPPED"
    assert executions[("X", "price_spikes")].status == "SKIPPED"
    assert executions[("X", "cross_source")].status == "UNAVAILABLE"


def test_missing_requested_edges_and_singleton_weekend():
    df = frame().iloc[1:-1]
    findings = check_missing_days(df, "X", Config(), "2025-01-13", "2025-01-17")
    dates = {date.isoformat() for finding in findings for date in finding.dates}
    assert dates == {"2025-01-13", "2025-01-17"}
    weekend = frame().iloc[:1].copy()
    weekend.index = pd.DatetimeIndex(["2025-01-11"])
    assert "non-trading" in check_missing_days(weekend, "X", Config())[0].detail


def test_narrow_refresh_retains_outer_history_and_vendor_duplicates(monkeypatch, tmp_path):
    df = frame()
    monkeypatch.setattr(ingest, "fetch_yfinance", lambda ticker, start, end: ingest._slice(df, start, end))
    ingest.get_data("X", "yfinance", "2025-01-13", "2025-01-17", tmp_path)
    narrow = df.iloc[-2:].copy()
    narrow.loc[:, "close"] = 100.5
    # A duplicate is evidence, not something cache maintenance should repair.
    narrow = pd.concat([narrow, narrow.iloc[-1:]])
    monkeypatch.setattr(ingest, "fetch_yfinance", lambda *args: narrow)
    ingest.get_data("X", "yfinance", "2025-01-16", "2025-01-17", tmp_path)
    cached = ingest.get_data("X", "yfinance", "2025-01-13", "2025-01-17", tmp_path, offline=True)
    assert len(cached) == 6
    assert cached.loc["2025-01-13", "close"] == 100
    assert cached.loc["2025-01-16", "close"] == 100.5
    assert cached.index.duplicated().sum() == 1


def test_refresh_does_not_hide_new_holes_with_old_cached_rows(monkeypatch, tmp_path):
    df = frame()
    df.to_parquet(ingest.cache_path(tmp_path, "X", "yfinance"))
    monkeypatch.setattr(ingest, "fetch_yfinance", lambda *args: df.iloc[1:-1])
    ingest.get_data("X", "yfinance", "2025-01-13", "2025-01-17", tmp_path)
    cached = ingest.get_data("X", "yfinance", None, None, tmp_path, offline=True)
    assert len(cached) == 3
    assert check_missing_days(cached, "X", Config(), "2025-01-13", "2025-01-17")


def test_cache_fallback_is_visible_in_the_report(monkeypatch, tmp_path):
    for source in ingest.SOURCES:
        frame().to_parquet(ingest.cache_path(tmp_path, "BRK.B", source))
    assert ingest.cached_tickers(tmp_path) == ["BRK.B"]
    def offline(*args):
        raise RuntimeError("vendor unavailable")
    monkeypatch.setattr(ingest, "fetch_yfinance", offline)
    monkeypatch.setattr(ingest, "fetch_stooq", offline)
    result = run_pipeline(["BRK.B"], None, None, Config(), tmp_path, tmp_path / "reports")
    report = result.markdown_path.read_text()
    assert "cache_fallback" in report and "vendor unavailable" in report
    assert "actual_start=2025-01-13" in report
    assert "unknown (legacy cache)" in report


def test_final_day_spike_does_not_invent_next_day_confirmation():
    df = pd.DataFrame({"close": 100 * np.exp(np.cumsum(np.random.default_rng(0).normal(0, .001, 40))), "volume": 100.}, index=pd.bdate_range("2025-01-02", periods=40))
    df.iloc[-1, 0] *= 1.2
    df.iloc[-1, 1] = 5000
    last = check_price_spikes(df, "X", Config())[-1]
    assert "persistence is unavailable" in last.detail
    assert "persisted next day" not in last.detail
    assert last.severity.value == "warning"


def test_inclusive_end_date_is_translated_for_yfinance(monkeypatch):
    import yfinance
    calls = []
    raw = frame().rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume", "adj_close": "Adj Close"})
    def download(ticker, **kwargs):
        calls.append(kwargs)
        return raw
    monkeypatch.setattr(yfinance, "download", download)
    ingest.fetch_yfinance("X", "2025-01-13", "2025-01-17")
    assert all(call["end"] == "2025-01-18" for call in calls)


def test_malformed_numeric_values_and_empty_history_do_not_crash_or_pass():
    df = frame().astype({"close": object})
    df.loc[df.index[0], "close"] = "bad"
    executions = {}
    findings = check_ticker("X", {"yfinance": df}, Config(), executions=executions)
    assert any(f.check == "schema" for f in findings)
    assert executions[("X", "price_spikes")].status == "UNAVAILABLE"
    check_ticker("X", {"yfinance": frame().iloc[:0]}, Config(), executions=executions)
    assert executions[("X", "missing_days")].status == "UNAVAILABLE"


def test_empty_unbounded_refresh_preserves_cache(monkeypatch, tmp_path):
    frame().to_parquet(ingest.cache_path(tmp_path, "X", "yfinance"))
    monkeypatch.setattr(ingest, "fetch_yfinance", lambda *args: frame().iloc[:0])
    result = ingest.get_data("X", "yfinance", None, None, tmp_path)
    assert len(result) == 5
    assert result.attrs["provenance"]["origin"] == "cache_fallback"
    assert len(ingest.load_cached(tmp_path, "X", "yfinance")) == 5
