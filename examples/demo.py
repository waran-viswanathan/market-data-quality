"""Run the complete report pipeline from checked-in fixtures, without a network."""

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

from market_data_quality.config import Config
from market_data_quality.ingest import cache_path
from market_data_quality.pipeline import run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=Path("reports/demo"))
    args = parser.parse_args()
    fixtures = Path(__file__).resolve().parents[1] / "tests/fixtures"
    with TemporaryDirectory(prefix="dq-demo-") as temporary:
        cache = Path(temporary)
        for ticker, source, fixture in [
            ("SPKY", "yfinance", "spikes.csv"),
            ("SPKY", "stooq", "spikes_second_source.csv"),
            ("SOLO", "stooq", "stooq_sample.csv"),
        ]:
            date_column = "Date" if fixture == "stooq_sample.csv" else "date"
            df = pd.read_csv(fixtures / fixture, parse_dates=[date_column], index_col=date_column)
            df.columns = df.columns.str.lower()
            df.index.name = "date"
            df.to_parquet(cache_path(cache, ticker, source))
        result = run_pipeline(["SPKY", "SOLO"], None, None, Config(), cache, args.output_dir, offline=True)
        print(result.markdown_path)
        print(result.html_path)


if __name__ == "__main__":
    main()
