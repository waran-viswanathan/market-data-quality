"""Orchestrate ingest -> checks -> report for a list of tickers.

The pipeline is deliberately forgiving about ingestion: a source that fails
to load becomes an ERROR *finding* (visible in the report) rather than a
crash, because "the vendor gave us nothing today" is itself a data-quality
event worth recording.  Single-source checks run on the primary source
(yfinance, falling back to Stooq); reconciliation runs whenever both
sources loaded.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import numpy as np

from market_data_quality import ingest
from market_data_quality.checks import (
    check_adjustment_consistency,
    check_cross_source,
    check_missing_days,
    check_price_spikes,
    check_stale_prices,
)
from market_data_quality.config import Config
from market_data_quality.checks import CHECK_ORDER
from market_data_quality.checks.schema import check_schema
from market_data_quality.findings import CheckExecution, Finding, Severity
from market_data_quality.report import RunMeta, write_reports


@dataclass(frozen=True, slots=True)
class RunResult:
    """Everything a caller needs after one pipeline run."""

    findings: list[Finding]
    markdown_path: Path
    html_path: Path
    tickers: tuple[str, ...]
    executions: dict[tuple[str, str], CheckExecution]


def _dedupe(df: pd.DataFrame) -> pd.DataFrame:
    """Unique, sorted index for checks that assume one row per session."""
    return df[~df.index.duplicated(keep="first")].sort_index()


def check_ticker(
    ticker: str,
    frames: dict[str, pd.DataFrame],
    config: Config,
    *,
    start: str | None = None,
    end: str | None = None,
    executions: dict[tuple[str, str], CheckExecution] | None = None,
) -> list[Finding]:
    """Run every applicable check for one ticker.

    Args:
        ticker: Ticker symbol.
        frames: Mapping of source name to standardized frame (either source
            may be absent if ingestion failed).
        config: Thresholds.

    Returns:
        Findings from all checks that could run.
    """
    findings: list[Finding] = []
    if executions is None:
        executions = {}
    for check in CHECK_ORDER:
        if check != "ingestion":
            executions[(ticker, check)] = CheckExecution("UNAVAILABLE", "no source data available")
    for source, frame in frames.items():
        findings += check_schema(frame, ticker, source)
    primary_name = "yfinance" if "yfinance" in frames else "stooq" if "stooq" in frames else None
    if primary_name is None:
        return findings
    primary = frames[primary_name]
    executions[(ticker, "schema")] = CheckExecution("COMPLETED")

    # Missing-days sees the raw index (it is the check that owns duplicates);
    # every other check requires a unique, sorted index.
    findings += check_missing_days(primary, ticker, config, start, end)
    executions[(ticker, "missing_days")] = (
        CheckExecution("COMPLETED") if primary.index.notna().any() or (start and end)
        else CheckExecution("UNAVAILABLE", "no valid dates or complete requested date range")
    )
    deduped = _dedupe(primary)
    secondary_name = next((name for name in frames if name != primary_name), None)
    secondary = _dedupe(frames[secondary_name]) if secondary_name else None

    def usable(frame: pd.DataFrame, columns: tuple[str, ...]) -> bool:
        if frame.empty or frame.index.isna().any() or any(column not in frame for column in columns):
            return False
        return all(pd.api.types.is_numeric_dtype(frame[column]) and np.isfinite(frame[column]).all() and (frame[column].ge(0) if column == "volume" else frame[column].gt(0)).all() for column in columns)

    prices_available = usable(deduped, ("close", "volume"))
    for check in ("price_spikes", "stale_prices", "adjustment_consistency"):
        executions[(ticker, check)] = CheckExecution("UNAVAILABLE", "required prices or volume are missing or invalid")
    if prices_available:
        if len(deduped) >= max(5, config.spike_window // 2) + 2:
            other = secondary if secondary is not None and usable(secondary, ("close",)) else None
            findings += check_price_spikes(deduped, ticker, config, other=other)
            executions[(ticker, "price_spikes")] = CheckExecution("COMPLETED")
        else:
            executions[(ticker, "price_spikes")] = CheckExecution("SKIPPED", "insufficient return history for trailing volatility")
        if len(deduped) >= config.stale_max_days + 2:
            findings += check_stale_prices(deduped, ticker, config)
            executions[(ticker, "stale_prices")] = CheckExecution("COMPLETED")
        else:
            executions[(ticker, "stale_prices")] = CheckExecution("SKIPPED", "insufficient history for a stale-price run")
    if usable(deduped, ("close", "adj_close")) and len(deduped) >= 2:
        findings += check_adjustment_consistency(deduped, ticker, config)
        executions[(ticker, "adjustment_consistency")] = CheckExecution("COMPLETED")
    else:
        executions[(ticker, "adjustment_consistency")] = CheckExecution("SKIPPED", "adjusted closes unavailable, incomplete, or too short")
    if secondary is not None and secondary_name is not None and prices_available and usable(secondary, ("close", "volume")):
        findings += check_cross_source(
            deduped,
            secondary,
            ticker,
            config,
            primary_name=primary_name,
            secondary_name=secondary_name,
        )
        executions[(ticker, "cross_source")] = CheckExecution("COMPLETED")
    else:
        executions[(ticker, "cross_source")] = CheckExecution("UNAVAILABLE", "two usable sources are required")
    return findings


def run_pipeline(
    tickers: list[str],
    start: str | None,
    end: str | None,
    config: Config,
    cache_dir: Path,
    reports_dir: Path,
    offline: bool = False,
) -> RunResult:
    """Ingest, validate, and report for every ticker.

    Args:
        tickers: Ticker symbols to process.
        start: Inclusive start date (ISO string) or ``None``.
        end: Inclusive end date or ``None``.
        config: Thresholds.
        cache_dir: Parquet cache directory.
        reports_dir: Root directory for dated report folders.
        offline: Use only cached data.

    Returns:
        A :class:`RunResult` with all findings and report paths.
    """
    all_findings: list[Finding] = []
    executions: dict[tuple[str, str], CheckExecution] = {}
    sources: list[dict[str, object]] = []
    for ticker in tickers:
        frames: dict[str, pd.DataFrame] = {}
        for source in ingest.SOURCES:
            try:
                frames[source] = ingest.get_data(
                    ticker, source, start, end, cache_dir, offline=offline
                )
                sources.append({"ticker": ticker, "source": source, **frames[source].attrs.get("provenance", {})})
            except ingest.IngestError as exc:
                sources.append({"ticker": ticker, "source": source, "origin": "unavailable", "detail": str(exc)})
                all_findings.append(
                    Finding(
                        check="ingestion",
                        severity=Severity.ERROR,
                        ticker=ticker,
                        dates=(),
                        detail=str(exc),
                    )
                )
        executions[(ticker, "ingestion")] = CheckExecution("COMPLETED")
        all_findings += check_ticker(ticker, frames, config, start=start, end=end, executions=executions)

    meta = RunMeta(
        tickers=tuple(tickers), start=start, end=end, offline=offline, config=config,
        executions=executions, sources=tuple(sources),
    )
    markdown_path, html_path = write_reports(all_findings, meta, reports_dir)
    return RunResult(
        findings=all_findings,
        markdown_path=markdown_path,
        html_path=html_path,
        tickers=tuple(tickers),
        executions=executions,
    )

