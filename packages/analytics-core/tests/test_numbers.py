from decimal import Decimal

import pytest

from analytics_core.cleaning.numbers import detect_decimal_separator, looks_like_code, parse_number


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("10,000", "10000"),
        ("1,250.50", "1250.50"),
        ("$45", "45"),
        ("US$ 1,200.00", "1200.00"),
        ("USD 1,200.00", "1200.00"),
        ("ZWG 350", "350"),
        ("R 150.00", "150.00"),
        ("1200 USD", "1200"),
        ("(30)", "-30"),
        ("($1,250.00)", "-1250.00"),
        ("30-", "-30"),
        ("-12.5", "-12.5"),
        ("\u221212.5", "-12.5"),
        ("+7", "7"),
        ("35%", "35"),
        ("1 234.56", "1234.56"),
        ("1\u00a0234.56", "1234.56"),
        ("1e3", "1000"),
        (".5", "0.5"),
        ("0.10", "0.10"),
    ],
)
def test_numbers_as_people_type_them(text, expected):
    assert parse_number(text) == Decimal(expected)


@pytest.mark.parametrize("text", ["", "   ", "abc", "12,34", "1,23,456", "77 123 4567", "12.34.56", "N/A", "1,2", "$"])
def test_anything_ambiguous_is_rejected_not_guessed(text):
    assert parse_number(text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [("1 234,56", "1234.56"), ("1.234,56", "1234.56"), ("12,5", "12.5"), ("1.234", "1234"), ("7", "7")],
)
def test_decimal_comma_convention(text, expected):
    assert parse_number(text, ",") == Decimal(expected)


def test_decimal_separator_is_decided_from_unambiguous_values():
    assert detect_decimal_separator(["1 234,56", "12,5", "300"]) == ","
    assert detect_decimal_separator(["1,234.56", "10,000"]) == "."
    assert detect_decimal_separator(["1,234", "5,678"]) == "."  # thousands, not decimals
    assert detect_decimal_separator(["12,5", "3.75"]) == "."  # conflicting evidence: keep the default


def test_leading_zero_digits_are_codes():
    assert looks_like_code("00123")
    assert not looks_like_code("0")
    assert not looks_like_code("0.5")
    assert not looks_like_code("120")
