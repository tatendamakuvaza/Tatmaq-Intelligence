"""How figures are written, in one place, so the PDF, the Excel file, the web page and
every sentence about a number all agree.

Currency amounts carry their ISO code (``USD 1,250.00``, ``ZWG 1,250.00``) rather than
a symbol: in a multi-currency market "$" does not say which dollar.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from analytics_core.financial import quantize, to_decimal

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
MONTHS_LONG = ("January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December")  # fmt: skip


def decimal_text(value: Decimal | None, places: int | None = None) -> str | None:
    """A decimal as plain text for JSON (never scientific notation), optionally rounded."""
    if value is None:
        return None
    return format(quantize(value, places) if places is not None else value, "f")


def money(value: Decimal | float | str | None, currency: str | None) -> str:
    amount = to_decimal(value)
    if amount is None:
        return "n/a"
    rounded = quantize(amount, 2)
    body = f"{abs(rounded):,.2f}"
    prefix = f"{currency} " if currency else ""
    return f"-{prefix}{body}" if rounded < 0 else f"{prefix}{body}"


def number(value: Any, places: int = 2) -> str:
    amount = to_decimal(value)
    return "n/a" if amount is None else f"{quantize(amount, places):,.{places}f}"


def integer(value: Any) -> str:
    amount = to_decimal(value)
    return "n/a" if amount is None else f"{int(quantize(amount, 0)):,}"


def percent(value: Any, places: int = 2) -> str:
    amount = to_decimal(value)
    return "n/a" if amount is None else f"{quantize(amount, places):,.{places}f}%"


def signed_percent(value: Any, places: int = 1) -> str:
    amount = to_decimal(value)
    if amount is None:
        return "n/a"
    rounded = quantize(amount, places)
    return f"{'+' if rounded > 0 else ''}{rounded:,.{places}f}%"


def points(value: Any, places: int = 2) -> str:
    """A change between two percentages, in percentage points."""
    amount = to_decimal(value)
    if amount is None:
        return "n/a"
    rounded = quantize(amount, places)
    return f"{'+' if rounded > 0 else ''}{rounded:,.{places}f} percentage points"


def p_value(value: float | None) -> str:
    if value is None:
        return "n/a"
    return "p < 0.001" if value < 0.001 else f"p = {value:.3f}"


def month_label(month: str, long: bool = False) -> str:
    """``2026-03`` -> ``Mar 2026`` (or ``March 2026``)."""
    year, number_ = month.split("-")
    names = MONTHS_LONG if long else MONTHS
    return f"{names[int(number_) - 1]} {year}"


def date_label(value: date | None) -> str:
    return "n/a" if value is None else f"{value.day} {MONTHS[value.month - 1]} {value.year}"


def format_cell(value: Any, kind: str, currency: str | None = None) -> str:
    """Render a table or KPI value according to its declared format."""
    if value is None or value == "":
        return "–"
    if kind == "money":
        return money(value, currency)
    if kind == "percent":
        return percent(value)
    if kind == "integer":
        return integer(value)
    if kind == "number":
        return number(value)
    if kind == "number4":
        return number(value, 4)
    if kind == "month":
        return month_label(str(value))
    return str(value)


def join_names(names: list[str]) -> str:
    """``A``, ``A and B``, ``A, B and C``."""
    if len(names) <= 1:
        return "".join(names)
    return f"{', '.join(names[:-1])} and {names[-1]}"


def count_of(count: int, singular: str, plural: str | None = None) -> str:
    """``1 row``, ``12 rows``."""
    return f"{count:,} {singular if count == 1 else (plural or singular + 's')}"


def compared_with(change_pct: Any, places: int = 1) -> str:
    """A percentage change as words: ``4.5% higher than``, ``12.0% lower than``, ``the same as``."""
    amount = to_decimal(change_pct)
    if amount is None:
        return "not comparable with"
    rounded = quantize(amount, places)
    if rounded == 0:
        return "the same as"
    return f"{abs(rounded):,.{places}f}% {'higher' if rounded > 0 else 'lower'} than"


def above_below(change_pct: Any, places: int = 1) -> str:
    """``36.0% above``, ``12.5% below``, ``level with``."""
    amount = to_decimal(change_pct)
    if amount is None:
        return "not comparable with"
    rounded = quantize(amount, places)
    if rounded == 0:
        return "level with"
    return f"{abs(rounded):,.{places}f}% {'above' if rounded > 0 else 'below'}"
