from datetime import datetime

import pytest

from analytics_core.cleaning.dates import excel_serial_to_datetime, parse_date_column


def test_specification_example_is_read_day_first_and_the_assumption_is_counted():
    result = parse_date_column(["01/09/2026", "01-09-2026"])
    assert result.values == [datetime(2026, 9, 1), datetime(2026, 9, 1)]
    assert result.order_basis == "default"
    assert result.ambiguous_rows == 2
    assert result.format_counts == {"DD/MM/YYYY": 1, "DD-MM-YYYY": 1}


def test_one_unambiguous_value_settles_the_whole_column():
    result = parse_date_column(["01/09/2026", "25/09/2026", "02/09/2026"])
    assert [v.month for v in result.values] == [9, 9, 9]
    assert (result.order_basis, result.ambiguous_rows) == ("data", 0)


def test_month_first_columns_are_recognised_from_the_data():
    result = parse_date_column(["01/09/2026", "09/25/2026"])
    assert result.values == [datetime(2026, 1, 9), datetime(2026, 9, 25)]
    assert result.day_first is False and result.order_basis == "data"


def test_conflicting_orders_are_reported_not_hidden():
    result = parse_date_column(["25/09/2026", "09/25/2026", "01/02/2026", "05/05/2026"])
    assert result.order_basis == "conflict"
    assert result.values[0] == datetime(2026, 9, 25) and result.values[1] == datetime(2026, 9, 25)
    assert result.values[2] == datetime(2026, 2, 1)  # falls back to the day-first default
    assert result.ambiguous_rows == 1  # 05/05 reads the same either way


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-09-01", datetime(2026, 9, 1)),
        ("2026/09/01", datetime(2026, 9, 1)),
        ("2026-09-01T14:30:05", datetime(2026, 9, 1, 14, 30, 5)),
        ("2026-09-01 00:00:00", datetime(2026, 9, 1)),
        ("01.09.2026", datetime(2026, 9, 1)),
        ("1 Sep 2026", datetime(2026, 9, 1)),
        ("01-Sep-26", datetime(2026, 9, 1)),
        ("1st September 2026", datetime(2026, 9, 1)),
        ("September 1, 2026", datetime(2026, 9, 1)),
        ("Sep 2026", datetime(2026, 9, 1)),
        ("2026-09", datetime(2026, 9, 1)),
        ("01/09/2026 2:30 PM", datetime(2026, 9, 1, 14, 30)),
        ("01/09/26", datetime(2026, 9, 1)),
        ("01/09/99", datetime(1999, 9, 1)),
    ],
)
def test_supported_formats(text, expected):
    assert parse_date_column([text], pivot_year=2026).values == [expected]


def test_impossible_dates_are_invalid_and_blanks_are_merely_missing():
    result = parse_date_column(["31/02/2026", "hello", None, "", "N/A", float("nan"), "13/13/2026", "2026-13-01"])
    assert result.values == [None] * 8
    assert result.invalid_positions == [0, 1, 6, 7]


def test_spreadsheet_serial_dates():
    assert excel_serial_to_datetime(45000) == datetime(2023, 3, 15)
    assert excel_serial_to_datetime(12) is None
