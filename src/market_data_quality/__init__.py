"""market-data-quality: a data-quality pipeline for daily OHLCV market data.

Ingests the same tickers from two independent free sources (yfinance and
Stooq), runs a battery of vendor-defect checks, and renders Markdown and
self-contained HTML reports.  No trading logic — pure data validation.
"""

from market_data_quality.findings import Finding, Severity

__all__ = ["Finding", "Severity"]
__version__ = "0.1.0"
