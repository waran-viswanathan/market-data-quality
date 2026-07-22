"""Report rendering: summary table, Markdown, and self-contained HTML."""

import datetime as dt

from market_data_quality.config import Config
from market_data_quality.findings import Finding, Severity
from market_data_quality.report import RunMeta, render_html, summarize, write_reports

FINDINGS = [
    Finding(
        check="price_spikes",
        severity=Severity.ERROR,
        ticker="AAPL",
        dates=(dt.date(2024, 3, 21),),
        detail="+12.0% move — likely bad tick <script>",
    ),
    Finding(
        check="cross_source",
        severity=Severity.WARNING,
        ticker="MSFT",
        dates=(dt.date(2024, 2, 7), dt.date(2024, 2, 9)),
        detail="closes disagree beyond 20 bps",
    ),
]


def _meta() -> RunMeta:
    return RunMeta(
        tickers=("AAPL", "MSFT"),
        start="2024-01-01",
        end=None,
        offline=True,
        config=Config(),
    )


def test_summarize_statuses_and_grid() -> None:
    summary = summarize(FINDINGS, ["AAPL", "MSFT"])
    indexed = summary.set_index(["ticker", "check"])
    assert indexed.loc[("AAPL", "price_spikes"), "status"] == "FAIL"
    assert indexed.loc[("MSFT", "cross_source"), "status"] == "WARN"
    # Clean cells still appear, as PASS with zero counts.
    assert indexed.loc[("AAPL", "stale_prices"), "status"] == "PASS"
    assert int(indexed["errors"].sum()) == 1


def test_write_reports_creates_dated_directory(tmp_path) -> None:
    markdown_path, html_path = write_reports(FINDINGS, _meta(), tmp_path)
    assert markdown_path.parent == tmp_path / dt.date.today().isoformat()
    markdown = markdown_path.read_text()
    assert "| AAPL | price_spikes | 1 | 0 | 0 | FAIL |" in markdown
    assert "2024-02-07 .. 2024-02-09" in markdown
    assert html_path.exists()


def test_html_is_self_contained_and_escaped(tmp_path) -> None:
    html_text = render_html(FINDINGS, _meta())
    assert "<script>" not in html_text  # finding text is escaped
    assert "&lt;script&gt;" in html_text
    for marker in ("http://", "https://", "@import", "<link", "src="):
        assert marker not in html_text  # no external resources, no CDN
    assert "<style>" in html_text


def test_empty_run_renders_pass_only(tmp_path) -> None:
    markdown_path, _ = write_reports([], _meta(), tmp_path)
    markdown = markdown_path.read_text()
    assert "No findings" in markdown
    assert "FAIL" not in markdown
