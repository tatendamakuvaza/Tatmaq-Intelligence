"""Checks a set of results must pass before anything is reported.

These are the arithmetic identities an auditor would test: the parts add up to the
whole, profit equals sales less cost, and no row has been lost or counted twice.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from ..financial.money import exact_sum


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str


def parts_equal_total(name: str, parts: Iterable[Decimal], total: Decimal) -> Check:
    """The breakdown adds back to the total, exactly."""
    summed = exact_sum(parts)
    return Check(name, summed == total, f"sum of parts {summed} vs total {total}")


def identity(name: str, left: Decimal | None, right: Decimal | None) -> Check:
    """Two independently obtained figures are identical."""
    return Check(name, left == right, f"{left} vs {right}")


def rows_balance(name: str, used: int, excluded: int, total: int) -> Check:
    """Every row is either used or accounted for as excluded."""
    return Check(name, used + excluded == total, f"{used} used + {excluded} excluded vs {total} rows")


def close_to_float(name: str, exact: Decimal, approximate: float, rel_tol: float = 1e-9) -> Check:
    """An exact decimal total agrees with the same total computed in floating point.

    The two use different code paths, so agreement guards against a gross error (a
    wrong column, a dropped filter) that exact arithmetic alone would not reveal.
    """
    passed = math.isclose(float(exact), approximate, rel_tol=rel_tol, abs_tol=0.005)
    return Check(name, passed, f"exact {exact} vs floating-point {approximate!r}")


def within(name: str, value: Decimal | None, low: Decimal | None, high: Decimal | None) -> Check:
    """A figure lies in its logically possible range."""
    if value is None:
        return Check(name, True, "not applicable")
    passed = (low is None or value >= low) and (high is None or value <= high)
    return Check(name, passed, f"{value} within [{low}, {high}]")
