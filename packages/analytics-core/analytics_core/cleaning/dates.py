"""Reading dates written in mixed formats.

The hard case is ``01/09/2026``: 1 September in Zimbabwe, 9 January in the United
States. This module settles the question with evidence where it can:

* a value such as ``25/09/2026`` can only be day-first, and settles it for its column;
* if the column holds no such value, the configured default (day-first) is applied and
  the number of dates that rested on that assumption is reported, so the assumption
  is visible in the cleaning log instead of being silently baked into the results.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Literal

from .numbers import NUMERIC_NULL_TOKENS

OrderBasis = Literal["data", "default", "conflict", "not_applicable"]

MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}  # fmt: skip

_TIME = (
    r"(?:[ T]+(?P<hh>\d{1,2}):(?P<mi>\d{2})(?::(?P<ss>\d{2})(?:\.\d+)?)?\s*(?P<ap>[AaPp][Mm])?)?(?:Z|[+-]\d{2}:?\d{2})?"
)
_ISO = re.compile(rf"^(?P<y>\d{{4}})(?P<sep>[-/.])(?P<m>\d{{1,2}})(?P=sep)(?P<d>\d{{1,2}}){_TIME}$")
_NUMERIC = re.compile(rf"^(?P<a>\d{{1,2}})(?P<sep>[-/.])(?P<b>\d{{1,2}})(?P=sep)(?P<y>\d{{4}}|\d{{2}}){_TIME}$")
_DAY_MONTHNAME = re.compile(
    r"^(?P<d>\d{1,2})(?:st|nd|rd|th)?[ \-/.]*(?P<mon>[A-Za-z]{3,9})\.?,?[ \-/.]*(?P<y>\d{4}|\d{2})$"
)
_MONTHNAME_DAY = re.compile(r"^(?P<mon>[A-Za-z]{3,9})\.?\s+(?P<d>\d{1,2})(?:st|nd|rd|th)?,?\s+(?P<y>\d{4})$")
_MONTHNAME_YEAR = re.compile(r"^(?P<mon>[A-Za-z]{3,9})\.?[ \-/]*(?P<y>\d{4})$")
_YEAR_MONTH = re.compile(r"^(?P<y>\d{4})[-/](?P<m>\d{1,2})$")

#: Spreadsheet day counts accepted as dates (1 Jan 1955 to 31 Dec 2119).
EXCEL_SERIAL_MIN, EXCEL_SERIAL_MAX = 20090, 80353
_EXCEL_EPOCH = datetime(1899, 12, 30)


@dataclass
class DateColumnResult:
    values: list[datetime | None]
    format_counts: dict[str, int] = field(default_factory=dict)
    day_first: bool = True
    order_basis: OrderBasis = "not_applicable"
    ambiguous_rows: int = 0
    invalid_positions: list[int] = field(default_factory=list)
    two_digit_year_rows: int = 0
    has_time: bool = False

    @property
    def parsed_rows(self) -> int:
        return sum(1 for value in self.values if value is not None)


def excel_serial_to_datetime(serial: float) -> datetime | None:
    if not EXCEL_SERIAL_MIN <= serial <= EXCEL_SERIAL_MAX:
        return None
    return _EXCEL_EPOCH + timedelta(days=float(serial))


def _full_year(text: str, pivot_year: int) -> tuple[int, bool]:
    if len(text) == 4:
        return int(text), False
    year = 2000 + int(text)
    if year > pivot_year + 10:
        year -= 100
    return year, True


def _time_parts(match: re.Match[str]) -> tuple[int, int, int] | None:
    if match.groupdict().get("hh") is None:
        return 0, 0, 0
    hour, minute = int(match["hh"]), int(match["mi"])
    second = int(match["ss"]) if match["ss"] else 0
    meridiem = (match["ap"] or "").lower()
    if meridiem:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if meridiem == "pm" else 0)
    if hour > 23 or minute > 59 or second > 59:
        return None
    return hour, minute, second


def _build(year: int, month: int, day: int, clock: tuple[int, int, int] | None) -> datetime | None:
    if clock is None:
        return None
    try:
        return datetime(year, month, day, *clock)
    except ValueError:
        return None


@dataclass(frozen=True)
class _Candidate:
    """One distinct text value, classified but not yet resolved for day/month order."""

    kind: Literal["fixed", "numeric", "invalid"]
    value: datetime | None = None
    label: str = ""
    a: int = 0
    b: int = 0
    year: int = 0
    clock: tuple[int, int, int] | None = None
    separator: str = "/"
    short_year: bool = False
    has_time: bool = False


def _classify(text: str, pivot_year: int) -> _Candidate:
    match = _ISO.match(text)
    if match:
        clock = _time_parts(match)
        value = _build(int(match["y"]), int(match["m"]), int(match["d"]), clock)
        if value is None:
            return _Candidate("invalid")
        sep = match["sep"]
        return _Candidate("fixed", value, f"YYYY{sep}MM{sep}DD", has_time=match["hh"] is not None)

    match = _NUMERIC.match(text)
    if match:
        year, short = _full_year(match["y"], pivot_year)
        clock = _time_parts(match)
        if clock is None:
            return _Candidate("invalid")
        return _Candidate(
            "numeric", a=int(match["a"]), b=int(match["b"]), year=year, clock=clock,
            separator=match["sep"], short_year=short, has_time=match["hh"] is not None,
        )  # fmt: skip

    for pattern, label, day_group in (
        (_DAY_MONTHNAME, "D Mon YYYY", "d"),
        (_MONTHNAME_DAY, "Mon D, YYYY", "d"),
        (_MONTHNAME_YEAR, "Mon YYYY", None),
    ):
        match = pattern.match(text)
        if not match:
            continue
        month = MONTHS.get(match["mon"].lower())
        if month is None:
            return _Candidate("invalid")
        year, short = _full_year(match["y"], pivot_year)
        day = int(match[day_group]) if day_group else 1
        value = _build(year, month, day, (0, 0, 0))
        if value is None:
            return _Candidate("invalid")
        return _Candidate("fixed", value, label, short_year=short)

    match = _YEAR_MONTH.match(text)
    if match:
        value = _build(int(match["y"]), int(match["m"]), 1, (0, 0, 0))
        return _Candidate("fixed", value, "YYYY-MM") if value else _Candidate("invalid")

    return _Candidate("invalid")


def parse_date_column(
    values: Sequence[object],
    *,
    default_day_first: bool = True,
    pivot_year: int | None = None,
) -> DateColumnResult:
    """Parse a whole column of date text, deciding day/month order once for the column.

    Missing entries (``None``, NaN, empty text, ``N/A`` and similar) stay missing and are
    not counted as invalid.
    """
    pivot = pivot_year if pivot_year is not None else date.today().year
    texts: list[str | None] = []
    for value in values:
        if isinstance(value, str) and value.strip().casefold() not in NUMERIC_NULL_TOKENS:
            texts.append(value.strip())
        else:
            texts.append(None)

    counts = Counter(text for text in texts if text is not None)
    candidates = {text: _classify(text, pivot) for text in counts}

    day_first_votes = month_first_votes = 0
    for text, candidate in candidates.items():
        if candidate.kind != "numeric":
            continue
        if candidate.a > 12 >= candidate.b:
            day_first_votes += counts[text]
        elif candidate.b > 12 >= candidate.a:
            month_first_votes += counts[text]

    has_numeric = any(candidate.kind == "numeric" for candidate in candidates.values())
    if not has_numeric:
        day_first, basis = default_day_first, "not_applicable"
    elif day_first_votes and month_first_votes:
        day_first, basis = default_day_first, "conflict"
    elif day_first_votes:
        day_first, basis = True, "data"
    elif month_first_votes:
        day_first, basis = False, "data"
    else:
        day_first, basis = default_day_first, "default"

    resolved: dict[str, datetime | None] = {}
    labels: dict[str, str] = {}
    ambiguous: set[str] = set()
    for text, candidate in candidates.items():
        if candidate.kind == "fixed":
            resolved[text], labels[text] = candidate.value, candidate.label
            continue
        if candidate.kind == "invalid":
            resolved[text] = None
            continue
        a, b = candidate.a, candidate.b
        if a > 12 >= b:
            value_day_first = True
        elif b > 12 >= a:
            value_day_first = False
        else:
            value_day_first = day_first
            if a != b and basis in ("default", "conflict"):
                ambiguous.add(text)
        day, month = (a, b) if value_day_first else (b, a)
        resolved[text] = _build(candidate.year, month, day, candidate.clock)
        year_label = "YY" if candidate.short_year else "YYYY"
        order = ("DD", "MM") if value_day_first else ("MM", "DD")
        labels[text] = candidate.separator.join((*order, year_label))

    result = DateColumnResult(values=[], day_first=day_first, order_basis=basis)
    format_counts: Counter[str] = Counter()
    for position, text in enumerate(texts):
        if text is None:
            result.values.append(None)
            continue
        value = resolved[text]
        result.values.append(value)
        if value is None:
            result.invalid_positions.append(position)
            continue
        format_counts[labels[text]] += 1
        candidate = candidates[text]
        if candidate.short_year:
            result.two_digit_year_rows += 1
        if candidate.has_time:
            result.has_time = True
        if text in ambiguous:
            result.ambiguous_rows += 1
    result.format_counts = dict(format_counts.most_common())
    return result
