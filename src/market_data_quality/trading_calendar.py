"""NYSE trading calendar built from pandas' holiday machinery.

Vendors assemble daily files from exchange sessions, so "every weekday has a
row" is the wrong null hypothesis: NYSE closes for ten scheduled holidays a
year plus rare ad-hoc closures (presidential funerals, Hurricane Sandy).
A gap check that ignores those produces noise; one that models them catches
real dropped sessions.  We build the calendar with pandas' observance rules
rather than pulling in a heavyweight exchange-calendar dependency.
"""

from __future__ import annotations

import pandas as pd
from pandas.tseries.holiday import (
    AbstractHolidayCalendar,
    GoodFriday,
    Holiday,
    USLaborDay,
    USMartinLutherKingJr,
    USMemorialDay,
    USPresidentsDay,
    USThanksgivingDay,
    nearest_workday,
    sunday_to_monday,
)
from pandas.tseries.offsets import CustomBusinessDay


class NYSEHolidayCalendar(AbstractHolidayCalendar):
    """Regular full-day NYSE closures (post-2000 rule set).

    Note the asymmetric New Year's rule: when Jan 1 falls on a Saturday the
    NYSE does *not* close on Dec 31, so ``sunday_to_monday`` is correct
    where ``nearest_workday`` would not be.
    """

    rules = [
        Holiday("New Year's Day", month=1, day=1, observance=sunday_to_monday),
        USMartinLutherKingJr,
        USPresidentsDay,
        GoodFriday,
        USMemorialDay,
        Holiday(
            "Juneteenth",
            month=6,
            day=19,
            start_date=pd.Timestamp("2022-01-01"),
            observance=nearest_workday,
        ),
        Holiday("Independence Day", month=7, day=4, observance=nearest_workday),
        USLaborDay,
        USThanksgivingDay,
        Holiday("Christmas Day", month=12, day=25, observance=nearest_workday),
    ]


#: Ad-hoc full-day closures that no rule generates.
SPECIAL_CLOSURES = pd.DatetimeIndex(
    [
        "2001-09-11",  # September 11 attacks
        "2001-09-12",
        "2001-09-13",
        "2001-09-14",
        "2004-06-11",  # Reagan funeral
        "2007-01-02",  # Ford funeral
        "2012-10-29",  # Hurricane Sandy
        "2012-10-30",
        "2018-12-05",  # G. H. W. Bush funeral
        "2025-01-09",  # Carter funeral
    ]
)


def nyse_sessions(start: pd.Timestamp | str, end: pd.Timestamp | str) -> pd.DatetimeIndex:
    """Expected NYSE trading sessions between ``start`` and ``end``, inclusive.

    Args:
        start: First calendar date to consider.
        end: Last calendar date to consider.

    Returns:
        Normalized, ascending ``DatetimeIndex`` of expected sessions.
    """
    business_day = CustomBusinessDay(calendar=NYSEHolidayCalendar())
    sessions = pd.date_range(start=start, end=end, freq=business_day)
    return sessions.difference(SPECIAL_CLOSURES)
