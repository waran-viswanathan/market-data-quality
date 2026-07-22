"""End-to-end pipeline through the CLI, entirely from a fixture cache.

This is the offline proof that ingestion (cache path), every check, and
report generation compose: we seed the parquet cache with fixture data
containing known defects, run ``dq report``, and assert the defects show
up in the rendered reports.
"""

import datetime as dt

from market_data_quality.cli import main
from market_data_quality.ingest import cache_path

from tests.conftest import load_fixture


def _seed_cache(cache_dir) -> None:
    cache_dir.mkdir(parents=True)
    load_fixture("spikes.csv").to_parquet(cache_path(cache_dir, "SPKY", "yfinance"))
    load_fixture("spikes_second_source.csv").to_parquet(
        cache_path(cache_dir, "SPKY", "stooq")
    )


def test_dq_report_from_cache(tmp_path, capsys) -> None:
    cache_dir = tmp_path / "cache"
    reports_dir = tmp_path / "reports"
    _seed_cache(cache_dir)

    exit_code = main(
        [
            "report",
            "--cache-dir",
            str(cache_dir),
            "--reports-dir",
            str(reports_dir),
        ]
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "1 ticker(s) checked" in out

    markdown = (reports_dir / dt.date.today().isoformat() / "report.md").read_text()
    assert "SPKY" in markdown
    assert "likely bad tick" in markdown  # planted defect surfaced end-to-end
    assert "likely real event" in markdown
    html = (reports_dir / dt.date.today().isoformat() / "report.html").read_text()
    assert "SPKY" in html


def test_dq_report_without_cache_fails_cleanly(tmp_path, capsys) -> None:
    exit_code = main(["report", "--cache-dir", str(tmp_path / "empty")])
    assert exit_code == 2
    assert "no tickers" in capsys.readouterr().err


def test_dq_run_offline_uses_cache(tmp_path) -> None:
    cache_dir = tmp_path / "cache"
    reports_dir = tmp_path / "reports"
    _seed_cache(cache_dir)

    exit_code = main(
        [
            "run",
            "--tickers",
            "spky",
            "--offline",
            "--start",
            "2024-01-01",
            "--cache-dir",
            str(cache_dir),
            "--reports-dir",
            str(reports_dir),
        ]
    )
    assert exit_code == 0
    assert (reports_dir / dt.date.today().isoformat() / "report.md").exists()
