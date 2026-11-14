"""Exact decimal arithmetic for monetary values.

Binary floating point cannot represent most decimal fractions (0.1 + 0.2 is not 0.3),
so totals built by adding floats drift by fractions of a cent. Money is therefore
added up here as :class:`decimal.Decimal`.

Datasets store numbers as 64-bit floats. A float is converted through its shortest
round-trip text form (``repr``), which recovers the decimal value that was typed into
the spreadsheet for any number of up to 15 significant digits. Beyond 15 digits the
source float itself is no longer exact; :func:`exceeds_float_precision` lets callers
warn about that instead of silently reporting a wrong cent.
"""

from __future__ import annotations

import math
import numbers
from collections.abc import Hashable, Iterable, Sequence
from decimal import ROUND_HALF_UP, Decimal, localcontext

ZERO = Decimal("0")
HUNDRED = Decimal("100")

#: Working precision for sums. Far more than a million 17-digit values can need.
_SUM_PRECISION = 60

#: Values with more significant digits than this cannot be held exactly in a float.
FLOAT_SAFE_DIGITS = 15


def to_decimal(value: object) -> Decimal | None:
    """Convert a number to ``Decimal``; missing or non-finite values become ``None``."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, bool):
        raise TypeError("booleans are not monetary values")
    if isinstance(value, numbers.Integral):
        return Decimal(int(value))
    if isinstance(value, numbers.Real):
        as_float = float(value)
        if not math.isfinite(as_float):
            return None
        return Decimal(repr(as_float))
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        parsed = Decimal(text)
        return parsed if parsed.is_finite() else None
    raise TypeError(f"cannot convert {type(value).__name__} to Decimal")


def to_decimals(values: Iterable[object]) -> list[Decimal | None]:
    """Convert a column of numbers to decimals, keeping row positions."""
    return [to_decimal(value) for value in values]


def exact_sum(values: Iterable[Decimal | None]) -> Decimal:
    """Add decimals exactly, ignoring missing values. An empty sum is zero."""
    with localcontext() as context:
        context.prec = _SUM_PRECISION
        total = ZERO
        for value in values:
            if value is not None:
                total += value
        return total


def exact_group_sums(keys: Sequence[Hashable], values: Sequence[Decimal | None]) -> dict[Hashable, tuple[Decimal, int]]:
    """Exact total and row count per key. Rows with a missing value are skipped."""
    if len(keys) != len(values):
        raise ValueError("keys and values must have the same length")
    totals: dict[Hashable, Decimal] = {}
    counts: dict[Hashable, int] = {}
    with localcontext() as context:
        context.prec = _SUM_PRECISION
        for key, value in zip(keys, values, strict=True):
            if value is None:
                continue
            totals[key] = totals.get(key, ZERO) + value
            counts[key] = counts.get(key, 0) + 1
    return {key: (totals[key], counts[key]) for key in totals}


def quantize(value: Decimal, places: int = 2) -> Decimal:
    """Round half-up to ``places`` decimals, the convention used on financial statements."""
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def divide(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    """Exact-as-possible division; ``None`` when the denominator is zero."""
    if denominator == 0:
        return None
    with localcontext() as context:
        context.prec = _SUM_PRECISION
        return numerator / denominator


def percent(numerator: Decimal, denominator: Decimal, places: int = 2) -> Decimal | None:
    """``numerator / denominator x 100`` rounded half-up; ``None`` if undefined."""
    result = divide(numerator, denominator)
    if result is None:
        return None
    return quantize(result * HUNDRED, places)


def percent_change(old: Decimal, new: Decimal, places: int = 2) -> Decimal | None:
    """Percentage change from ``old`` to ``new``; ``None`` when ``old`` is zero."""
    if old == 0:
        return None
    return percent(new - old, abs(old), places)


def exceeds_float_precision(value: Decimal) -> bool:
    """True when a value has more significant digits than a float holds exactly."""
    return len(value.normalize().as_tuple().digits) > FLOAT_SAFE_DIGITS
