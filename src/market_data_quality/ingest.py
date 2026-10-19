"""Two-source ingestion with parquet caching.

Sources:

* **yfinance** — pulled twice per ticker, once with ``auto_adjust=False``
  (as-traded OHLCV) and once with ``auto_adjust=True`` (the adjusted close),
  merged into one frame.  Keeping raw and adjusted side by side is what
  makes the adjustment-consistency check possible.
* **Stooq** — a plain CSV endpoint with no API key.  Stooq maintains its
  own pipeline, which is exactly why it is useful: an independent vendor
  rarely makes the same mistake as Yahoo.

Every successful pull is cached to ``data/raw/*.parquet`` so repeated runs
(and ``dq report``) are offline-friendly and deterministic.
"""

from __future__ import annotations

import io
import datetime as dt
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import requests

STANDARD_COLUMNS = ["open", "high", "low", "close", "adj_close", "volume"]
SOURCES = ("yfinance", "stooq")
STOOQ_URL = "https://stooq.com/q/d/l/?s={symbol}&i=d"
_REQUEST_TIMEOUT_SECONDS = 30
_USER_AGENT = "market-data-quality/0.1 (+https://github.com/waran-viswanathan/market-data-quality)"


class IngestError(RuntimeError):
    """Raised when a source yields no usable data and no cache exists."""


def _standardize(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize any source frame to the standard schema.

    Sorted tz-naive date index named ``date``; float64 columns
    ``open/high/low/close/adj_close/volume`` (missing ones filled with
    NaN).  Duplicate index entries are deliberately preserved — detecting
    them is the missing-days check's job, not ingestion's.
    """
    df = frame.copy()
    index = pd.DatetimeIndex(df.index)
    if index.tz is not None:
        index = index.tz_localize(None)
    df.index = index.normalize()
    df.index.name = "date"
    df = df.sort_index()
    for column in STANDARD_COLUMNS:
        if column not in df.columns:
            df[column] = np.nan
        df[column] = pd.to_numeric(df[column], errors="coerce")
    return df[STANDARD_COLUMNS]


def _flatten_yf_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Drop the ticker level yfinance adds to single-ticker downloads."""
    if isinstance(frame.columns, pd.MultiIndex):
        frame = frame.copy()
        frame.columns = frame.columns.get_level_values(0)
    return frame


def combine_yfinance_frames(raw: pd.DataFrame, adjusted: pd.DataFrame) -> pd.DataFrame:
    """Merge yfinance raw (``auto_adjust=False``) and adjusted pulls.

    As-traded OHLCV comes from the raw pull; ``adj_close`` comes from the
    adjusted pull's close (falling back to the raw pull's ``Adj Close``
    column when the adjusted pull is empty).

    Args:
        raw: ``yf.download(..., auto_adjust=False)`` result.
        adjusted: ``yf.download(..., auto_adjust=True)`` result.

    Returns:
        Standardized frame.

    Raises:
        IngestError: If the raw pull is empty.
    """
    raw = _flatten_yf_columns(raw)
    adjusted = _flatten_yf_columns(adjusted)
    if raw.empty:
        raise IngestError("yfinance returned no rows")
    out = raw.rename(columns=str.lower).rename(columns={"adj close": "adj_close"})
    if not adjusted.empty:
        adj_close = adjusted.rename(columns=str.lower)["close"]
        out["adj_close"] = adj_close.reindex(out.index)
    return _standardize(out)


def parse_stooq_csv(text: str) -> pd.DataFrame:
    """Parse the CSV body of Stooq's daily-history endpoint.

    Args:
        text: Raw response body.

    Returns:
        Standardized frame (Stooq carries no adjusted close, so
        ``adj_close`` is NaN).

    Raises:
        IngestError: If the body is not a Stooq daily CSV (e.g. the literal
            "No data" response for unknown symbols).
    """
    if not text.lstrip().lower().startswith("date"):
        raise IngestError(f"Stooq returned no data (body starts with {text.strip()[:40]!r})")
    df = pd.read_csv(io.StringIO(text), parse_dates=["Date"], index_col="Date")
    return _standardize(df.rename(columns=str.lower))


def fetch_yfinance(ticker: str, start: str | None, end: str | None) -> pd.DataFrame:
    """Download one ticker from yfinance (raw + adjusted) and merge."""
    import yfinance as yf  # local import: keeps `dq report` fully offline

    # The CLI's end date is inclusive; yfinance's end boundary is exclusive.
    exclusive_end = (pd.Timestamp(end) + pd.Timedelta(days=1)).date().isoformat() if end else None
    common = {"start": start, "end": exclusive_end, "progress": False, "actions": False}
    raw = yf.download(ticker, auto_adjust=False, **common)
    adjusted = yf.download(ticker, auto_adjust=True, **common)
    if raw is None or raw.empty:
        raise IngestError(f"yfinance returned no rows for {ticker}")
    return combine_yfinance_frames(raw, adjusted if adjusted is not None else pd.DataFrame())


def fetch_stooq(ticker: str, start: str | None, end: str | None) -> pd.DataFrame:
    """Download one US ticker's daily history from Stooq's CSV endpoint."""
    url = STOOQ_URL.format(symbol=f"{ticker.lower()}.us")
    response = requests.get(
        url, timeout=_REQUEST_TIMEOUT_SECONDS, headers={"User-Agent": _USER_AGENT}
    )
    response.raise_for_status()
    return _slice(parse_stooq_csv(response.text), start, end)


def _slice(df: pd.DataFrame, start: str | None, end: str | None) -> pd.DataFrame:
    """Restrict a standardized frame to [start, end], inclusive."""
    if start is not None:
        df = df[df.index >= pd.Timestamp(start)]
    if end is not None:
        df = df[df.index <= pd.Timestamp(end)]
    return df


def cache_path(cache_dir: Path, ticker: str, source: str) -> Path:
    """Parquet cache location for one (ticker, source) pair."""
    return Path(cache_dir) / f"{ticker.upper()}.{source}.parquet"


def load_cached(cache_dir: Path, ticker: str, source: str) -> pd.DataFrame | None:
    """Read a cached pull, or ``None`` if absent."""
    path = cache_path(cache_dir, ticker, source)
    if not path.exists():
        return None
    try:
        return pd.read_parquet(path)
    except Exception as exc:
        raise IngestError(f"unreadable cache for {ticker}/{source}: {exc}") from exc


def cached_tickers(cache_dir: Path) -> list[str]:
    """Ticker symbols that have at least one cached source."""
    cache_dir = Path(cache_dir)
    if not cache_dir.exists():
        return []
    return sorted({path.name.removesuffix(f".{source}.parquet") for source in SOURCES for path in cache_dir.glob(f"*.{source}.parquet")})


def _cache_refresh(path: Path, fresh: pd.DataFrame, start: str | None, end: str | None) -> None:
    """Replace the requested window while retaining history outside it.

    Do not deduplicate vendor rows or fill holes inside the refreshed window:
    both are evidence for the checks. Atomic replacement avoids partial files.
    """
    if fresh.empty and (start is None or end is None):
        raise IngestError("empty response without a complete refresh range")
    previous = pd.read_parquet(path) if path.exists() else None
    combined = fresh
    if previous is not None and not previous.empty:
        lower = pd.Timestamp(start) if start else fresh.index.min()
        upper = pd.Timestamp(end) if end else fresh.index.max()
        retained = previous[(previous.index < lower) | (previous.index > upper)]
        combined = pd.concat([retained, fresh]).sort_index()
    combined.attrs = {"last_refresh": {"fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(), "start": start, "end": end}}
    with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".parquet", delete=False) as temp:
        temporary = Path(temp.name)
    try:
        combined.to_parquet(temporary)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _with_provenance(df: pd.DataFrame, origin: str, detail: str | None = None) -> pd.DataFrame:
    result = df.copy()
    refresh = df.attrs.get("last_refresh", {})
    result.attrs["provenance"] = {
        "origin": origin,
        "rows": len(df),
        "actual_start": str(df.index.min().date()) if not df.empty else None,
        "actual_end": str(df.index.max().date()) if not df.empty else None,
        "cache_last_refresh": refresh.get("fetched_at", "unknown (legacy cache)"),
        "refreshed_window": f"{refresh.get('start', 'unknown')} to {refresh.get('end', 'unknown')}",
        "detail": detail,
    }
    return result


def get_data(
    ticker: str,
    source: str,
    start: str | None,
    end: str | None,
    cache_dir: Path,
    offline: bool = False,
) -> pd.DataFrame:
    """Fetch one (ticker, source) frame, refreshing or falling back to cache.

    Online: fetch, refresh only that cache window, return the fresh frame; on network
    failure, fall back to the cache with a warning.  Offline: cache only.

    Args:
        ticker: Ticker symbol (e.g. ``AAPL``).
        source: ``"yfinance"`` or ``"stooq"``.
        start: Inclusive start date (ISO string) or ``None``.
        end: Inclusive end date or ``None``.
        cache_dir: Directory of ``*.parquet`` caches.
        offline: Never touch the network.

    Returns:
        Standardized frame restricted to [start, end].

    Raises:
        IngestError: If nothing could be fetched and no cache exists.
        ValueError: For an unknown ``source``.
    """
    if source not in SOURCES:
        raise ValueError(f"unknown source {source!r}; expected one of {SOURCES}")
    cache_dir = Path(cache_dir)
    fallback_detail = None
    if not offline:
        try:
            df = (
                fetch_yfinance(ticker, start, end)
                if source == "yfinance"
                else fetch_stooq(ticker, start, end)
            )
            cache_dir.mkdir(parents=True, exist_ok=True)
            path = cache_path(cache_dir, ticker, source)
            _cache_refresh(path, df, start, end)
            df.attrs["last_refresh"] = {"fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(), "start": start, "end": end}
            return _with_provenance(df, "live")
        except Exception as exc:  # noqa: BLE001 — degrade to cache on any fetch failure
            if load_cached(cache_dir, ticker, source) is None:
                raise IngestError(f"{source} fetch failed for {ticker}: {exc}") from exc
            print(
                f"warning: {source} fetch failed for {ticker} ({exc}); using cached data",
                file=sys.stderr,
            )
            fallback_detail = str(exc)
    cached = load_cached(cache_dir, ticker, source)
    if cached is None:
        raise IngestError(
            f"no cached data for {ticker}/{source} in {cache_dir} — run `dq run` online first"
        )
    return _with_provenance(_slice(cached, start, end), "cache" if offline else "cache_fallback", fallback_detail)

