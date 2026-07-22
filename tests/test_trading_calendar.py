"""NYSE session calendar behaviour."""

import pandas as pd

from market_data_quality.trading_calendar import nyse_sessions


def test_excludes_weekends_and_holidays() -> None:
    sessions = nyse_sessions("2024-06-24", "2024-07-08")
    assert pd.Timestamp("2024-07-04") not in sessions  # Independence Day
    assert pd.Timestamp("2024-07-06") not in sessions  # Saturday
    assert pd.Timestamp("2024-07-05") in sessions
    assert pd.Timestamp("2024-06-19") not in nyse_sessions("2024-06-01", "2024-06-30")


def test_juneteenth_only_observed_from_2022() -> None:
    assert pd.Timestamp("2021-06-18") in nyse_sessions("2021-06-01", "2021-06-30")
    # 2021-06-19 was a Saturday anyway; check the 2021 observance did not
    # remove the Friday, while 2023-06-19 (a Monday) is removed.
    assert pd.Timestamp("2023-06-19") not in nyse_sessions("2023-06-01", "2023-06-30")


def test_special_closures_excluded() -> None:
    sessions = nyse_sessions("2018-12-01", "2018-12-10")
    assert pd.Timestamp("2018-12-05") not in sessions  # G. H. W. Bush funeral
    assert pd.Timestamp("2018-12-04") in sessions


def test_good_friday_excluded() -> None:
    assert pd.Timestamp("2024-03-29") not in nyse_sessions("2024-03-01", "2024-04-05")
