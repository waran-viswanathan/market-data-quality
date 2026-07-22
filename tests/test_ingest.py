"""Ingestion parsing, normalization, and cache behaviour — all offline."""

import numpy as np
import pandas as pd
import pytest

from market_data_quality import ingest

from tests.conftest import FIXTURES, load_fixture


def test_parse_stooq_csv() -> None:
    df = ingest.parse_stooq_csv((FIXTURES / "stooq_sample.csv").read_text())
    assert list(df.columns) == ingest.STANDARD_COLUMNS
    assert df.index.name == "date"
    assert len(df) == 3
    assert df.loc["2024-01-03", "close"] == pytest.approx(184.1)
    assert df["adj_close"].isna().all()  # Stooq has no adjusted close


def test_parse_stooq_no_data_raises() -> None:
    with pytest.raises(ingest.IngestError, match="No data"):
        ingest.parse_stooq_csv("No data\n")


def test_combine_yfinance_frames_multiindex_and_adjusted() -> None:
    dates = pd.DatetimeIndex(["2024-01-02", "2024-01-03"], name="Date")
    columns = pd.MultiIndex.from_product(
        [["Open", "High", "Low", "Close", "Adj Close", "Volume"], ["AAPL"]]
    )
    raw = pd.DataFrame(
        [[185.0, 186.0, 184.0, 185.5, 184.9, 1e6], [185.5, 187.0, 185.0, 186.5, 185.9, 2e6]],
        index=dates,
        columns=columns,
    )
    adjusted = pd.DataFrame(
        {"Open": [184.4, 184.9], "Close": [184.8, 185.8], "Volume": [1e6, 2e6]},
        index=dates,
    )
    df = ingest.combine_yfinance_frames(raw, adjusted)
    assert list(df.columns) == ingest.STANDARD_COLUMNS
    # OHLCV comes from the raw pull; adj_close from the adjusted pull's close.
    assert df["close"].tolist() == [185.5, 186.5]
    assert df["adj_close"].tolist() == [184.8, 185.8]


def test_combine_yfinance_empty_raises() -> None:
    with pytest.raises(ingest.IngestError):
        ingest.combine_yfinance_frames(pd.DataFrame(), pd.DataFrame())


def test_standardize_fills_missing_columns_and_sorts() -> None:
    frame = pd.DataFrame(
        {"close": [2.0, 1.0]},
        index=pd.DatetimeIndex(["2024-01-03", "2024-01-02"], tz="UTC"),
    )
    df = ingest._standardize(frame)
    assert df.index.tz is None
    assert df.index.is_monotonic_increasing
    assert np.isnan(df["open"]).all()


def test_cache_round_trip_and_offline(tmp_path) -> None:
    df = load_fixture("clean.csv")
    path = ingest.cache_path(tmp_path, "aapl", "stooq")
    assert path.name == "AAPL.stooq.parquet"
    df.to_parquet(path)

    loaded = ingest.get_data("AAPL", "stooq", None, None, tmp_path, offline=True)
    pd.testing.assert_frame_equal(loaded, df)

    sliced = ingest.get_data(
        "AAPL", "stooq", "2024-02-01", "2024-02-29", tmp_path, offline=True
    )
    assert sliced.index.min() >= pd.Timestamp("2024-02-01")
    assert sliced.index.max() <= pd.Timestamp("2024-02-29")

    assert ingest.cached_tickers(tmp_path) == ["AAPL"]


def test_offline_without_cache_raises(tmp_path) -> None:
    with pytest.raises(ingest.IngestError, match="no cached data"):
        ingest.get_data("MSFT", "stooq", None, None, tmp_path, offline=True)


def test_unknown_source_raises(tmp_path) -> None:
    with pytest.raises(ValueError, match="unknown source"):
        ingest.get_data("AAPL", "bloomberg", None, None, tmp_path, offline=True)
