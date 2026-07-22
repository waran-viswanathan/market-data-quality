"""Command-line interface.

Two subcommands::

    dq run --tickers AAPL,MSFT,SPY --start 2020-01-01   # fetch + validate + report
    dq report                                           # re-validate cached data only

``dq report`` never touches the network, so a morning re-run against
yesterday's cache is cheap and deterministic.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from market_data_quality import ingest
from market_data_quality.config import load_config
from market_data_quality.pipeline import run_pipeline

DEFAULT_CACHE_DIR = Path("data/raw")
DEFAULT_REPORTS_DIR = Path("reports")


def build_parser() -> argparse.ArgumentParser:
    """Build the ``dq`` argument parser."""
    parser = argparse.ArgumentParser(
        prog="dq", description="Data-quality checks for daily OHLCV market data."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("--start", help="inclusive start date, e.g. 2020-01-01")
        sub.add_argument("--end", help="inclusive end date (default: latest)")
        sub.add_argument("--config", type=Path, help="path to config.toml (default: ./config.toml)")
        sub.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
        sub.add_argument("--reports-dir", type=Path, default=DEFAULT_REPORTS_DIR)

    run = subparsers.add_parser("run", help="fetch data, run checks, write reports")
    run.add_argument("--tickers", required=True, help="comma-separated, e.g. AAPL,MSFT,SPY")
    add_common(run)
    run.add_argument(
        "--offline", action="store_true", help="use cached parquet only; no network"
    )

    report = subparsers.add_parser(
        "report", help="re-run checks and reports from cached data only"
    )
    report.add_argument(
        "--tickers", help="comma-separated; default: every ticker in the cache"
    )
    add_common(report)
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.  Returns a process exit code."""
    args = build_parser().parse_args(argv)
    config = load_config(args.config)

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = ingest.cached_tickers(args.cache_dir)
    if not tickers:
        print(
            f"error: no tickers given and no cache found in {args.cache_dir}",
            file=sys.stderr,
        )
        return 2

    offline = args.command == "report" or getattr(args, "offline", False)
    result = run_pipeline(
        tickers=tickers,
        start=args.start,
        end=args.end,
        config=config,
        cache_dir=args.cache_dir,
        reports_dir=args.reports_dir,
        offline=offline,
    )
    counts = Counter(f.severity.value for f in result.findings)
    print(
        f"{len(result.tickers)} ticker(s) checked: "
        f"{counts.get('error', 0)} error(s), {counts.get('warning', 0)} warning(s), "
        f"{counts.get('info', 0)} info finding(s)"
    )
    print(f"markdown report: {result.markdown_path}")
    print(f"html report:     {result.html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
