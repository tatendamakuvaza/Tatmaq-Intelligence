from decimal import Decimal

import numpy as np
import pytest

from analytics_core.financial import (
    exact_group_sums,
    exact_sum,
    exceeds_float_precision,
    gross_margin_pct,
    gross_profit,
    percent,
    percent_change,
    quantize,
    to_decimal,
    to_decimals,
)  # fmt: skip


def test_float_addition_is_wrong_and_decimal_addition_is_right():
    assert 0.1 + 0.2 != 0.3  # the reason this module exists
    assert exact_sum(to_decimals([0.1, 0.2])) == Decimal("0.3")


def test_a_hundred_thousand_cents_add_up_exactly():
    cents = [0.01] * 100_000
    running = 0.0
    for cent in cents:
        running += cent
    assert running != 1000.0  # naive float accumulation drifts
    assert exact_sum(to_decimals(cents)) == Decimal("1000")


def test_specification_example_gross_profit_and_margin():
    sales, cost = Decimal("100000"), Decimal("65000")
    assert gross_profit(sales, cost) == Decimal("35000")
    assert gross_margin_pct(sales, cost) == Decimal("35.00")


@pytest.mark.parametrize(
    ("value", "expected"),
    [("2.675", "2.68"), ("0.125", "0.13"), ("-2.675", "-2.68"), ("1.005", "1.01"), ("2.674", "2.67")],
)
def test_rounding_is_half_up_not_bankers(value, expected):
    assert quantize(Decimal(value)) == Decimal(expected)


def test_missing_and_non_finite_values_become_none():
    assert to_decimal(None) is None
    assert to_decimal(float("nan")) is None
    assert to_decimal(float("inf")) is None
    assert to_decimal("  ") is None


def test_numpy_scalars_convert_by_shortest_repr():
    assert to_decimal(np.float64(19.99)) == Decimal("19.99")
    assert to_decimal(np.int64(7)) == Decimal(7)
    assert to_decimal(1250.1) == Decimal("1250.1")


def test_booleans_are_rejected():
    with pytest.raises(TypeError):
        to_decimal(True)


def test_group_sums_skip_missing_values_and_count_rows():
    sums = exact_group_sums(["a", "b", "a", "a"], to_decimals([0.1, 5, 0.2, None]))
    assert sums == {"a": (Decimal("0.3"), 2), "b": (Decimal(5), 1)}


def test_percent_is_undefined_for_zero_denominator():
    assert percent(Decimal(1), Decimal(0)) is None
    assert percent_change(Decimal(0), Decimal(5)) is None
    assert percent_change(Decimal(200), Decimal(150)) == Decimal("-25.00")
    assert percent_change(Decimal(-50), Decimal(-25)) == Decimal("50.00")


def test_precision_warning_threshold():
    assert not exceeds_float_precision(Decimal("9999999999999.99"))  # 15 digits
    assert exceeds_float_precision(Decimal("99999999999999.99"))  # 16 digits
