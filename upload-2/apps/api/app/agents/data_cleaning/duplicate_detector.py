"""Sizing the duplicates that cleaning flagged, in business terms."""

from __future__ import annotations

from typing import Any

import pandas as pd

from analytics_core.cleaning import DUPLICATE_COLUMN, ROW_COLUMN
from analytics_core.financial import exact_sum, to_decimals

from ...analytics.formatting import decimal_text


def duplicate_summary(cleaned: pd.DataFrame, revenue_column: str | None) -> dict[str, Any]:
    """How many rows repeat an earlier row, and how much sales value sits in them.

    Duplicates stay in the data: only the business knows whether two identical lines
    are one sale entered twice or two real sales. Reporting the value at stake lets
    them judge whether it matters.
    """
    repeated = cleaned[cleaned[DUPLICATE_COLUMN]]
    summary: dict[str, Any] = {
        "rows": len(repeated),
        "sample_rows": [int(row) for row in repeated[ROW_COLUMN].head(10).tolist()],
        "revenue_column": None,
        "revenue": None,
    }
    if len(repeated) and revenue_column and revenue_column in cleaned.columns:
        summary["revenue_column"] = revenue_column
        summary["revenue"] = decimal_text(exact_sum(to_decimals(repeated[revenue_column].tolist())), 2)
    return summary
