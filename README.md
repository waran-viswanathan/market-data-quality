# market-data-quality

[![CI](https://github.com/lalitheswaran11-stack/market-data-quality/actions/workflows/ci.yml/badge.svg)](https://github.com/lalitheswaran11-stack/market-data-quality/actions/workflows/ci.yml)

A command-line pipeline for checking daily OHLCV data before it reaches a
research notebook or backtest. It pulls Yahoo Finance and Stooq data, stores
the raw results as Parquet, and writes Markdown and HTML reports. Findings are
reported for review; the pipeline never edits the source data.

## Checks

| Check | Flags |
| --- | --- |
| `missing_days` | missing sessions, duplicate dates, and weekend or holiday rows |
| `price_spikes` | large returns, with volume, next-day reversion, and a second source used as context |
| `stale_prices` | repeated closes that may indicate a frozen feed |
| `adjustment_consistency` | one-day adjustment errors, drifting factors, and unanchored adjusted prices |
| `cross_source` | price, volume, and coverage differences between vendors |

The thresholds live in [`config.toml`](config.toml). The NYSE calendar is a
small pandas-based implementation with known ad-hoc closures included; it is
not intended to replace an exchange calendar for historical market operations.

## Run it

Python 3.11+ and [uv](https://docs.astral.sh/uv/) are required.

```sh
uv sync
uv run dq run --tickers AAPL,MSFT,SPY --start 2020-01-01
```

Each run writes a dated report under `reports/` and caches source data under
`data/raw/`. Once a cache exists, the same checks can be rerun without a
network request:

```sh
uv run dq report
uv run dq run --tickers AAPL,MSFT --start 2024-01-01 --offline
```

A report starts with a per-ticker summary and then lists the dates and evidence
for each finding:

```text
ticker  check                   errors  warnings  info  status
AAPL    price_spikes                  0         0     2  PASS
AAPL    adjustment_consistency       0         0    24  PASS
AAPL    cross_source                 0         1     0  WARN
```

Network failures fall back to cached data when possible. If neither a live
response nor a cache is available, ingestion records an error in the report so
the missing source remains visible.

## Code map

```text
src/market_data_quality/
  ingest.py             vendor adapters and Parquet cache
  checks/               one module per quality check
  pipeline.py           check orchestration
  report.py             Markdown and standalone HTML output
  cli.py                dq run / dq report
tests/fixtures/         small CSVs containing specific data defects
```

Tests use only the checked-in fixtures:

```sh
uv run pytest
```
