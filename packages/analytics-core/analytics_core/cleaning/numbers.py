"""Reading numbers the way people actually type them into spreadsheets.

Handles thousands separators (``10,000``), currency symbols and codes (``$45``,
``USD 45``, ``ZWG 45``), accounting negatives (``(30)`` and ``30-``), percentages and
the decimal-comma convention used by South African systems (``1 234,56``).

Parsing never guesses: text that is not unambiguously a number returns ``None`` so the
caller can flag it rather than analyse a wrong value.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from typing import Literal

DecimalSeparator = Literal[".", ","]

#: Text that means "no value" in a numeric or date column.
NUMERIC_NULL_TOKENS = frozenset({"", "na", "n/a", "#n/a", "null", "nan", "none", "nil", "-", "--", "?"})
#: Text that means "no value" in a text column (kept narrow: "none" can be a real answer).
TEXT_NULL_TOKENS = frozenset({"", "n/a", "#n/a", "null", "nan"})

_CODES = r"USD|US\$|ZWG|ZIG|ZWL|RTGS|ZAR|BWP|GBP|EUR"
_LEADING_CURRENCY = re.compile(rf"^(?:{_CODES}|R|\$|£|€)\s*(?=[\d.,(\-+])", re.IGNORECASE)
_TRAILING_CURRENCY = re.compile(rf"\s*(?:{_CODES}|\$|£|€)$", re.IGNORECASE)
_ANY_SPACE = re.compile(r"[\s\u00a0\u2007\u2009\u202f]+")
_SPACE_GROUPED = re.compile(r"^\d{1,3}( \d{3})+([.,]\d+)?$")
_PLAIN = re.compile(r"^(?:\d+(?:\.\d+)?|\.\d+)$")
_SCIENTIFIC = re.compile(r"^\d+(?:\.\d+)?[eE][+-]?\d+$")
_COMMA_GROUPED = re.compile(r"^\d{1,3}(?:,\d{3})+(?:\.\d+)?$")
_POINT_GROUPED = re.compile(r"^\d{1,3}(?:\.\d{3})+(?:,\d+)?$")
_COMMA_DECIMAL = re.compile(r"^\d+(?:,\d+)?$")
_ALREADY_CANONICAL = re.compile(r"^-?(?:\d+(?:\.\d+)?|\.\d+)$")
_LEADING_ZERO_CODE = re.compile(r"^0\d+$")


def is_null_token(text: str, tokens: frozenset[str] = NUMERIC_NULL_TOKENS) -> bool:
    return text.strip().casefold() in tokens


def is_canonical_number(text: str) -> bool:
    """True when the text is already a plain number needing no normalisation."""
    return bool(_ALREADY_CANONICAL.match(text.strip()))


def looks_like_code(text: str) -> bool:
    """Digits with a leading zero (``00123``) are account codes or phone numbers, not quantities."""
    return bool(_LEADING_ZERO_CODE.match(text.strip()))


def _strip_adornments(text: str) -> tuple[str, bool]:
    """Remove sign, brackets, currency and percent markers. Returns (digits text, negative)."""
    body = text.strip().replace("\u2212", "-")
    negative = False
    if body.startswith("(") and body.endswith(")"):
        negative, body = True, body[1:-1].strip()
    if body.startswith("-"):
        negative, body = not negative, body[1:].lstrip()
    elif body.startswith("+"):
        body = body[1:].lstrip()
    body = _LEADING_CURRENCY.sub("", body, count=1)
    body = _TRAILING_CURRENCY.sub("", body, count=1)
    if body.startswith("-"):
        negative, body = not negative, body[1:].lstrip()
    if body.endswith("-"):
        negative, body = not negative, body[:-1].rstrip()
    if body.endswith("%"):
        body = body[:-1].rstrip()
    return _ANY_SPACE.sub(" ", body).strip(), negative


def parse_number(text: str, decimal_separator: DecimalSeparator = ".") -> Decimal | None:
    """Parse one number, or return ``None`` if the text is not unambiguously numeric."""
    body, negative = _strip_adornments(text)
    if not body:
        return None
    if " " in body:
        if not _SPACE_GROUPED.match(body):
            return None
        body = body.replace(" ", "")

    if decimal_separator == ".":
        if _PLAIN.match(body) or _SCIENTIFIC.match(body):
            digits = body
        elif _COMMA_GROUPED.match(body):
            digits = body.replace(",", "")
        else:
            return None
    else:
        if _POINT_GROUPED.match(body):
            digits = body.replace(".", "").replace(",", ".")
        elif _COMMA_DECIMAL.match(body):
            digits = body.replace(",", ".")
        elif _PLAIN.match(body):
            digits = body
        else:
            return None

    try:
        value = Decimal(digits)
    except InvalidOperation:
        return None
    if not value.is_finite():
        return None
    return -value if negative else value


def detect_decimal_separator(values: Iterable[str]) -> DecimalSeparator:
    """Decide whether a column writes decimals with a comma (``12,5``) or a point (``12.5``).

    A comma is taken as the decimal mark only when some value can be nothing else (a
    comma followed by one, two, or four-plus digits at the end) and no value uses a
    point as its decimal mark. ``1,234`` on its own stays a thousands separator.
    """
    comma_votes = point_votes = 0
    for value in values:
        body, _ = _strip_adornments(value)
        if re.search(r"\d,(?:\d{1,2}|\d{4,})$", body):
            comma_votes += 1
        elif re.search(r"\d\.(?:\d{1,2}|\d{4,})$", body):
            point_votes += 1
    return "," if comma_votes and not point_votes else "."


def is_percent_text(text: str) -> bool:
    return text.strip().endswith("%")
