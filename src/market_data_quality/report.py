"""Render run results as Markdown and self-contained HTML.

The Markdown report is for diffs, PR comments, and terminals; the HTML
report is for humans triaging findings.  The HTML is deliberately
dependency-free — inline CSS, no CDN, no JavaScript — so it can be attached
to a ticket or opened on an air-gapped research box and look identical.
"""

from __future__ import annotations

import datetime as dt
import html
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from market_data_quality.checks import CHECK_ORDER
from market_data_quality.config import Config
from market_data_quality.findings import Finding, Severity

_SEVERITY_ORDER = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}


@dataclass(frozen=True, slots=True)
class RunMeta:
    """Metadata describing one pipeline run, shown in report headers."""

    tickers: tuple[str, ...]
    start: str | None
    end: str | None
    offline: bool
    config: Config
    generated_at: dt.datetime = field(default_factory=dt.datetime.now)


def summarize(findings: list[Finding], tickers: list[str]) -> pd.DataFrame:
    """Build the per-(ticker, check) summary table.

    Args:
        findings: All findings from a run.
        tickers: Tickers processed, so clean (ticker, check) cells still get
            a PASS row instead of vanishing.

    Returns:
        Frame with columns ``ticker, check, errors, warnings, info, status``
        where status is FAIL (any error), WARN (any warning), else PASS.
    """
    grid = pd.MultiIndex.from_product(
        [sorted(tickers), CHECK_ORDER], names=["ticker", "check"]
    )
    if findings:
        rows = pd.DataFrame(
            [(f.ticker, f.check, f.severity.value) for f in findings],
            columns=["ticker", "check", "severity"],
        )
        counts = (
            rows.pivot_table(
                index=["ticker", "check"], columns="severity", aggfunc="size", fill_value=0
            )
            .reindex(grid, fill_value=0)
            .reindex(columns=["error", "warning", "info"], fill_value=0)
        )
    else:
        counts = pd.DataFrame(0, index=grid, columns=["error", "warning", "info"])
    counts["status"] = np.select(
        [counts["error"] > 0, counts["warning"] > 0], ["FAIL", "WARN"], default="PASS"
    )
    return (
        counts.rename(columns={"error": "errors", "warning": "warnings"})
        .reset_index()
    )


def _sorted_findings(findings: list[Finding]) -> list[Finding]:
    return sorted(
        findings,
        key=lambda f: (f.ticker, _SEVERITY_ORDER[f.severity], f.check, f.dates),
    )


def _markdown_table(frame: pd.DataFrame) -> str:
    """Render a small DataFrame as a GitHub-flavoured Markdown table."""
    headers = [str(column) for column in frame.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in frame.itertuples(index=False):
        cells = [str(value).replace("|", r"\|") for value in row]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _meta_lines(meta: RunMeta) -> list[str]:
    date_range = f"{meta.start or 'earliest'} to {meta.end or 'latest'}"
    return [
        f"Generated: {meta.generated_at:%Y-%m-%d %H:%M:%S}",
        f"Tickers: {', '.join(meta.tickers)}",
        f"Date range: {date_range}",
        f"Mode: {'offline (cache only)' if meta.offline else 'online'}",
        (
            f"Thresholds: spike sigma {meta.config.spike_sigma:g} over "
            f"{meta.config.spike_window}d, stale > {meta.config.stale_max_days} sessions, "
            f"reconcile tolerance {meta.config.reconcile_close_bps:g} bps"
        ),
    ]


def render_markdown(findings: list[Finding], meta: RunMeta) -> str:
    """Render the full Markdown report."""
    summary = summarize(findings, list(meta.tickers))
    lines = ["# Market data quality report", ""]
    lines += [f"- {line}" for line in _meta_lines(meta)]
    lines += ["", "## Summary", "", _markdown_table(summary), "", "## Findings", ""]
    if not findings:
        lines.append("No findings — all checks passed.")
    current_ticker = None
    for finding in _sorted_findings(findings):
        if finding.ticker != current_ticker:
            current_ticker = finding.ticker
            lines += [f"### {current_ticker}", ""]
        lines.append(
            f"- **{finding.severity.value.upper()}** `{finding.check}` "
            f"{finding.date_span} — {finding.detail}"
        )
    lines.append("")
    return "\n".join(lines)


_HTML_STYLE = """
body { font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
       margin: 2rem auto; max-width: 60rem; padding: 0 1rem; color: #1a2233; }
h1 { border-bottom: 2px solid #d6dbe4; padding-bottom: .4rem; }
table { border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: .9rem; }
th, td { border: 1px solid #d6dbe4; padding: .35rem .6rem; text-align: left; }
th { background: #f2f4f8; }
ul.meta { color: #4a5568; font-size: .9rem; padding-left: 1.2rem; }
.badge { display: inline-block; padding: .1rem .5rem; border-radius: .6rem;
         font-size: .78rem; font-weight: 600; }
.badge.error, .status-FAIL { background: #fbe3e4; color: #8f1f1f; }
.badge.warning, .status-WARN { background: #fdf0d5; color: #7a5200; }
.badge.info { background: #e2ecf9; color: #1d4f91; }
.status-PASS { background: #e3f4e4; color: #1d6b28; }
li.finding { margin: .35rem 0; }
code { background: #f2f4f8; padding: .05rem .3rem; border-radius: .25rem; }
.dates { color: #4a5568; font-size: .85rem; }
"""


def _html_summary_table(summary: pd.DataFrame) -> str:
    header = "".join(f"<th>{html.escape(str(col))}</th>" for col in summary.columns)
    body_rows = []
    for row in summary.itertuples(index=False):
        cells = [f"<td>{html.escape(str(value))}</td>" for value in row[:-1]]
        status = html.escape(str(row[-1]))
        cells.append(f'<td><span class="badge status-{status}">{status}</span></td>')
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    return (
        f"<table><thead><tr>{header}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody></table>"
    )


def render_html(findings: list[Finding], meta: RunMeta) -> str:
    """Render the full self-contained HTML report (inline CSS, no CDN)."""
    summary = summarize(findings, list(meta.tickers))
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        "<title>Market data quality report</title>",
        f"<style>{_HTML_STYLE}</style></head><body>",
        "<h1>Market data quality report</h1>",
        '<ul class="meta">',
        *[f"<li>{html.escape(line)}</li>" for line in _meta_lines(meta)],
        "</ul>",
        "<h2>Summary</h2>",
        _html_summary_table(summary),
        "<h2>Findings</h2>",
    ]
    if not findings:
        parts.append("<p>No findings — all checks passed.</p>")
    current_ticker = None
    for finding in _sorted_findings(findings):
        if finding.ticker != current_ticker:
            if current_ticker is not None:
                parts.append("</ul>")
            current_ticker = finding.ticker
            parts.append(f"<h3>{html.escape(current_ticker)}</h3><ul>")
        parts.append(
            '<li class="finding">'
            f'<span class="badge {finding.severity.value}">'
            f"{finding.severity.value.upper()}</span> "
            f"<code>{html.escape(finding.check)}</code> "
            f'<span class="dates">{html.escape(finding.date_span)}</span> — '
            f"{html.escape(finding.detail)}</li>"
        )
    if current_ticker is not None:
        parts.append("</ul>")
    parts.append("</body></html>")
    return "\n".join(parts)


def write_reports(
    findings: list[Finding], meta: RunMeta, reports_dir: Path
) -> tuple[Path, Path]:
    """Write ``report.md`` and ``report.html`` under ``reports/YYYY-MM-DD/``.

    Returns:
        ``(markdown_path, html_path)``.
    """
    out_dir = Path(reports_dir) / meta.generated_at.date().isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = out_dir / "report.md"
    html_path = out_dir / "report.html"
    markdown_path.write_text(render_markdown(findings, meta), encoding="utf-8")
    html_path.write_text(render_html(findings, meta), encoding="utf-8")
    return markdown_path, html_path
