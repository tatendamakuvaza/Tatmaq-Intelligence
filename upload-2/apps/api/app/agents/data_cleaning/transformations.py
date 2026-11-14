"""Applying the cleaning rules and describing the cleaned table."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from analytics_core.cleaning import DUPLICATE_COLUMN, ROW_COLUMN, CleaningOutcome, ColumnType, clean_table

INTERNAL_COLUMNS = (ROW_COLUMN, DUPLICATE_COLUMN)


def clean(
    raw: pd.DataFrame, column_types: dict[str, dict[str, Any]], *,
    category_columns: list[str], measure_columns: list[str], day_first: bool, today: date | None = None,
) -> CleaningOutcome:  # fmt: skip
    """Run the standard cleaning pass using the types the acquisition agent decided."""
    types = {name: ColumnType(**options) for name, options in column_types.items()}
    return clean_table(raw, types, category_columns=category_columns, measure_columns=measure_columns,
                       default_day_first=day_first, today=today)  # fmt: skip


def column_statistics(cleaned: pd.DataFrame) -> dict[str, dict[str, Any]]:
    """Per-column facts about the *cleaned* table: what analyses will actually see."""
    described: dict[str, dict[str, Any]] = {}
    for name in cleaned.columns:
        if name in INTERNAL_COLUMNS:
            continue
        series = cleaned[name]
        present = series.dropna()
        facts: dict[str, Any] = {
            "null_count": int(series.isna().sum()),
            "distinct_count": int(present.nunique()),
            "stats": {},
        }
        if pd.api.types.is_numeric_dtype(series) and len(present):
            values = present.to_numpy(dtype="float64")
            facts["stats"] = {"min": float(values.min()), "max": float(values.max()),
                              "mean": float(values.mean()), "median": float(np.median(values))}  # fmt: skip
        elif pd.api.types.is_datetime64_any_dtype(series) and len(present):
            facts["stats"] = {"min": present.min().date().isoformat(), "max": present.max().date().isoformat()}
        elif len(present):
            top = present.value_counts().head(5)
            facts["stats"] = {"top_values": [{"value": str(v)[:60], "count": int(n)} for v, n in top.items()]}
        described[name] = facts
    return described


def outcome_json(outcome: CleaningOutcome) -> dict[str, Any]:
    return {
        "rows_in": outcome.rows_in,
        "rows_out": outcome.rows_out,
        "log": [asdict(entry) for entry in outcome.log],
        "issues": [asdict(issue) for issue in outcome.issues],
    }
