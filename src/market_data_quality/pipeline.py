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

from market_data_quality import ingest
from market_data_quality.checks import (
    check_adjustment_consistency,
    check_cross_source,
    check_missing_days,
    check_price_spikes,
    check_stale_prices,
)
from market_data_quality.config import Config
from market_data_quality.findings import Finding, Severity
from market_data_quality.report import RunMeta, write_reports


@dataclass(frozen=True, slots=True)
class RunResult:
    """Everything a caller needs after one pipeline run."""

    findings: list[Finding]
    markdown_path: Path
    html_path: Path
    tickers: tuple[str, ...]


def _dedupe(df: pd.DataFrame) -> pd.DataFrame:
    """Unique, sorted index for checks that assume one row per session."""
    return df[~df.index.duplicated(keep="first")].sort_index()


def check_ticker(
    ticker: str,
    frames: dict[str, pd.DataFrame],
    config: Config,
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
    primary_name = "yfinance" if "yfinance" in frames else "stooq" if "stooq" in frames else None
    if primary_name is None:
        return findings
    primary = frames[primary_name]

    # Missing-days sees the raw index (it is the check that owns duplicates);
    # every other check requires a unique, sorted index.
    findings += check_missing_days(primary, ticker, config)
    deduped = _dedupe(primary)
    secondary_name = next((name for name in frames if name != primary_name), None)
    secondary = _dedupe(frames[secondary_name]) if secondary_name else None

    findings += check_price_spikes(deduped, ticker, config, other=secondary)
    findings += check_stale_prices(deduped, ticker, config)
    findings += check_adjustment_consistency(deduped, ticker, config)
    if secondary is not None and secondary_name is not None:
        findings += check_cross_source(
            deduped,
            secondary,
            ticker,
            config,
            primary_name=primary_name,
            secondary_name=secondary_name,
        )
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
    for ticker in tickers:
        frames: dict[str, pd.DataFrame] = {}
        for source in ingest.SOURCES:
            try:
                frames[source] = ingest.get_data(
                    ticker, source, start, end, cache_dir, offline=offline
                )
            except ingest.IngestError as exc:
                all_findings.append(
                    Finding(
                        check="ingestion",
                        severity=Severity.ERROR,
                        ticker=ticker,
                        dates=(),
                        detail=str(exc),
                    )
                )
        all_findings += check_ticker(ticker, frames, config)

    meta = RunMeta(
        tickers=tuple(tickers), start=start, end=end, offline=offline, config=config
    )
    markdown_path, html_path = write_reports(all_findings, meta, reports_dir)
    return RunResult(
        findings=all_findings,
        markdown_path=markdown_path,
        html_path=html_path,
        tickers=tuple(tickers),
    )
