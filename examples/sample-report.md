# Market data quality report

- Generated: 2026-10-19 11:38:03
- Tickers: SPKY, SOLO
- Date range: earliest to latest
- Mode: offline (cache only)
- Thresholds: spike sigma 4 over 21d, stale > 5 sessions, reconcile tolerance 20 bps

## Summary

| ticker | check | errors | warnings | info | status |
| --- | --- | --- | --- | --- | --- |
| SOLO | ingestion | 1 | 0 | 0 | FAIL |
| SOLO | schema | 0 | 0 | 0 | PASS |
| SOLO | missing_days | 0 | 0 | 0 | PASS |
| SOLO | price_spikes | 0 | 0 | 0 | SKIPPED |
| SOLO | stale_prices | 0 | 0 | 0 | SKIPPED |
| SOLO | adjustment_consistency | 0 | 0 | 0 | SKIPPED |
| SOLO | cross_source | 0 | 0 | 0 | UNAVAILABLE |
| SPKY | ingestion | 0 | 0 | 0 | PASS |
| SPKY | schema | 0 | 0 | 0 | PASS |
| SPKY | missing_days | 0 | 0 | 0 | PASS |
| SPKY | price_spikes | 1 | 0 | 1 | FAIL |
| SPKY | stale_prices | 0 | 0 | 0 | PASS |
| SPKY | adjustment_consistency | 0 | 0 | 0 | PASS |
| SPKY | cross_source | 1 | 0 | 0 | FAIL |

PASS means the check completed without warnings or errors; SKIPPED and UNAVAILABLE are not passes.

## Coverage and execution

- SOLO/adjustment_consistency: SKIPPED — adjusted closes unavailable, incomplete, or too short
- SOLO/cross_source: UNAVAILABLE — two usable sources are required
- SOLO/price_spikes: SKIPPED — insufficient return history for trailing volatility
- SOLO/stale_prices: SKIPPED — insufficient history for a stale-price run
- ticker=SPKY; source=yfinance; origin=cache; rows=80; actual_start=2024-01-02; actual_end=2024-04-25; cache_last_refresh=unknown (legacy cache); refreshed_window=unknown to unknown
- ticker=SPKY; source=stooq; origin=cache; rows=80; actual_start=2024-01-02; actual_end=2024-04-25; cache_last_refresh=unknown (legacy cache); refreshed_window=unknown to unknown
- ticker=SOLO; source=yfinance; origin=unavailable; detail=no cached data for SOLO/yfinance in [temporary fixture cache] — run `dq run` online first
- ticker=SOLO; source=stooq; origin=cache; rows=3; actual_start=2024-01-02; actual_end=2024-01-04; cache_last_refresh=unknown (legacy cache); refreshed_window=unknown to unknown

## Findings

### SOLO

- **ERROR** `ingestion` - — no cached data for SOLO/yfinance in [temporary fixture cache] — run `dq run` online first
### SPKY

- **ERROR** `cross_source` 2024-03-21 — closes disagree beyond 20 bps on 1 session(s) (max 1200 bps); sources genuinely disagree — at least one carries bad prices
- **ERROR** `price_spikes` 2024-03-21 — +13.0% close-to-close move (|z|=4.9 vs trailing 21d) — likely bad tick; second source does not show the move
- **INFO** `price_spikes` 2024-02-29 — +11.1% close-to-close move (|z|=14.3 vs trailing 21d) — likely real event; second source shows the same move
