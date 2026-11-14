"""Calendar-month bucketing for dated transactions."""

from __future__ import annotations

import calendar
from collections.abc import Sequence
from datetime import date, datetime

import pandas as pd

#: A first month whose earliest record falls after this day is treated as incomplete.
FIRST_MONTH_LATEST_START_DAY = 5
#: A last month whose latest record is more than this many days before month end is incomplete.
LAST_MONTH_MAX_MISSING_DAYS = 4
#: Completeness is only judged when months typically hold at least this many distinct days.
MIN_TYPICAL_DAYS_FOR_COMPLETENESS = 8

BLANK_LABEL = "(blank)"


def month_key(value: object) -> str | None:
    """``YYYY-MM`` for a date-like value, ``None`` for a missing one."""
    if value is None or value is pd.NaT:
        return None
    if isinstance(value, (datetime, date)):
        return f"{value.year:04d}-{value.month:02d}"
    if pd.isna(value):
        return None
    stamp = pd.Timestamp(value)
    return f"{stamp.year:04d}-{stamp.month:02d}"


def month_keys(dates: pd.Series) -> list[str | None]:
    """Month key for every row of a datetime column, keeping row positions."""
    stamps = pd.to_datetime(dates)
    years = stamps.dt.year.tolist()
    months = stamps.dt.month.tolist()
    return [
        None if year != year else f"{int(year):04d}-{int(month):02d}"  # NaN != NaN
        for year, month in zip(years, months, strict=True)
    ]


def month_range(first: str, last: str) -> list[str]:
    """Every month from ``first`` to ``last`` inclusive, so gaps show up as zero months."""
    year, month = (int(part) for part in first.split("-"))
    last_year, last_month = (int(part) for part in last.split("-"))
    months: list[str] = []
    while (year, month) <= (last_year, last_month):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return months


def incomplete_months(dates: pd.Series) -> dict[str, str]:
    """Find a first or last month that the data only partly covers.

    A dataset exported on 11 October holds eleven days of October. Comparing that month
    with full months would wrongly make it the "worst month" and bend any trend line
    downwards, so callers exclude these months from comparisons and say so.

    Returns ``{month: reason}``. Nothing is flagged when the data is not daily enough to
    judge (for example one summary line per month).
    """
    stamps = pd.to_datetime(dates).dropna()
    if stamps.empty:
        return {}
    periods = stamps.dt.to_period("M")
    distinct_days = stamps.dt.day.groupby(periods).nunique()
    if float(distinct_days.median()) < MIN_TYPICAL_DAYS_FOR_COMPLETENESS:
        return {}

    flagged: dict[str, str] = {}
    earliest, latest = stamps.min(), stamps.max()
    if earliest.day > FIRST_MONTH_LATEST_START_DAY:
        flagged[month_key(earliest)] = f"data starts on {earliest.date().isoformat()}"
    days_in_last = calendar.monthrange(latest.year, latest.month)[1]
    if days_in_last - latest.day > LAST_MONTH_MAX_MISSING_DAYS:
        flagged[month_key(latest)] = f"data ends on {latest.date().isoformat()}"
    return flagged


def label_values(values: Sequence[object]) -> list[str]:
    """Text labels for a grouping column; missing values share one visible label."""
    labels: list[str] = []
    for value in values:
        if value is None or (not isinstance(value, str) and pd.isna(value)):
            labels.append(BLANK_LABEL)
            continue
        text = str(value).strip()
        labels.append(text if text else BLANK_LABEL)
    return labels
