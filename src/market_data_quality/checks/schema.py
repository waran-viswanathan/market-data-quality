"""Validate required OHLCV values before interpreting statistical patterns."""

import numpy as np
import pandas as pd

from market_data_quality.findings import Finding, Severity, to_dates

REQUIRED = ("open", "high", "low", "close", "volume")


def check_schema(df: pd.DataFrame, ticker: str, source: str) -> list[Finding]:
    findings: list[Finding] = []

    def error(detail: str, mask: pd.Series | None = None) -> None:
        dates = () if mask is None else to_dates(df.index[mask & df.index.notna()])
        findings.append(Finding("schema", Severity.ERROR, ticker, dates, f"{source}: {detail}"))

    if df.empty:
        error("no OHLCV rows available")
        return findings
    if df.index.isna().any():
        error("invalid or missing session dates")
    for column in REQUIRED:
        if column not in df:
            error(f"required column {column} is missing")
            continue
        values = pd.to_numeric(df[column], errors="coerce")
        invalid = ~np.isfinite(values)
        if invalid.any():
            error(f"{int(invalid.sum())} missing or non-finite {column} value(s)", invalid)
        invalid_range = values.lt(0) if column == "volume" else values.le(0)
        if invalid_range.any():
            error(f"{column} must be {'nonnegative' if column == 'volume' else 'positive'}", invalid_range)
    prices = ["open", "high", "low", "close"]
    if all(column in df for column in prices):
        numeric = df[prices].apply(pd.to_numeric, errors="coerce")
        valid = np.isfinite(numeric).all(axis=1)
        inconsistent = valid & (
            numeric["high"].lt(numeric.max(axis=1))
            | numeric["low"].gt(numeric.min(axis=1))
        )
        if inconsistent.any():
            error("OHLC range is inconsistent (low <= open/close <= high required)", inconsistent)
    return findings
