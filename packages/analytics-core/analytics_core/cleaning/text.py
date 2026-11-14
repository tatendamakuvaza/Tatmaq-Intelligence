"""Tidying text and reconciling different spellings of the same category."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping

_WHITESPACE = re.compile(r"\s+")


def tidy(text: str) -> str:
    """Trim, collapse runs of whitespace and normalise Unicode composition."""
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFC", text)).strip()


def category_key(text: str) -> str:
    """The form under which spellings are considered the same category."""
    return tidy(text).casefold()


def _is_mixed_case(text: str) -> bool:
    return text != text.lower() and text != text.upper()


def find_variants(counts: Mapping[str, int]) -> dict[str, str]:
    """Map each alternative spelling to the spelling that should be used instead.

    ``harare cbd``, ``HARARE CBD`` and ``Harare CBD`` are one branch. The most frequent
    spelling wins; ties go to a mixed-case spelling, then alphabetical order, so the
    outcome never depends on row order.
    """
    groups: dict[str, list[str]] = {}
    for spelling in counts:
        groups.setdefault(category_key(spelling), []).append(spelling)

    mapping: dict[str, str] = {}
    for spellings in groups.values():
        if len(spellings) < 2:
            continue
        canonical = max(spellings, key=lambda s: (counts[s], _is_mixed_case(s), [-ord(c) for c in s]))
        for spelling in spellings:
            if spelling != canonical:
                mapping[spelling] = canonical
    return mapping


def count_of(count: int, singular: str, plural: str | None = None) -> str:
    """``1 row``, ``12 rows``: a count with its noun, for messages people will read."""
    return f"{count:,} {singular if count == 1 else (plural or singular + 's')}"
