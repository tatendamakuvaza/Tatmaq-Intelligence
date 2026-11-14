"""Checking that the cleaned data can actually support a planned analysis.

A plan is written from column names and types. This is where it meets the data: an
operation is infeasible if, once rows with missing values are set aside, there is
nothing (or too little) left to compute from. Infeasible operations go back to the
Chief Intelligence Agent to re-plan rather than producing an empty or misleading
result.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from ...analytics.spec import (
    OPERATION_TITLES,
    AnalysisSpec,
    Correlation,
    DataQuality,
    DescriptiveStatistics,
    Operation,
    Outliers,
    Profitability,
    Regression,
    SalesOverview,
    Trend,
    required_columns,
)  # fmt: skip

MIN_ROWS = {"correlation": 3, "outliers": 8, "trend": 3}


def _dtype_matches(series: pd.Series, needed: str) -> bool:
    if needed == "number":
        return pd.api.types.is_numeric_dtype(series)
    if needed == "date":
        return pd.api.types.is_datetime64_any_dtype(series)
    return not pd.api.types.is_numeric_dtype(series) and not pd.api.types.is_datetime64_any_dtype(series)


def _complete_rows(frame: pd.DataFrame, columns: list[str]) -> int:
    return int(frame[columns].notna().all(axis=1).sum()) if columns else len(frame)


def check_operation(frame: pd.DataFrame, operation: Operation) -> dict[str, Any]:
    title = OPERATION_TITLES[operation.type]
    result: dict[str, Any] = {"type": operation.type, "title": title, "feasible": True, "usable_rows": len(frame),
                              "reason": None}  # fmt: skip
    if isinstance(operation, DataQuality):
        return result

    for name, needed in required_columns(operation).items():
        if name not in frame.columns:
            return {**result, "feasible": False, "usable_rows": 0, "reason": f"column '{name}' is not in the dataset"}
        if not _dtype_matches(frame[name], needed):
            return {**result, "feasible": False, "usable_rows": 0,
                    "reason": f"column '{name}' does not hold {needed} values"}  # fmt: skip

    if isinstance(operation, SalesOverview):
        usable, minimum = _complete_rows(frame, list(operation.revenue.columns)), 1
    elif isinstance(operation, Profitability):
        usable, minimum = _complete_rows(frame, [*operation.revenue.columns, *operation.cost.columns]), 1
    elif isinstance(operation, DescriptiveStatistics):
        usable, minimum = max(int(frame[name].notna().sum()) for name in operation.columns), 1
    elif isinstance(operation, Correlation):
        columns = list(operation.columns)
        usable = max(_complete_rows(frame, [a, b]) for i, a in enumerate(columns) for b in columns[i + 1 :])
        minimum = MIN_ROWS["correlation"]
    elif isinstance(operation, Regression):
        usable = _complete_rows(frame, [operation.target, *operation.predictors])
        minimum = len(operation.predictors) + 2
    elif isinstance(operation, Trend):
        usable, minimum = _complete_rows(frame, [operation.measure, operation.date]), MIN_ROWS["trend"]
    elif isinstance(operation, Outliers):
        usable, minimum = int(frame[operation.column].notna().sum()), MIN_ROWS["outliers"]
    else:  # pragma: no cover - the union above is exhaustive
        usable, minimum = len(frame), 1

    result["usable_rows"] = usable
    if usable < minimum:
        result.update(feasible=False, reason=(
            "no rows have the values this analysis needs" if usable == 0
            else f"only {usable} row{' has' if usable == 1 else 's have'} the values this analysis needs "
                 f"(at least {minimum} required)"
        ))  # fmt: skip
    return result


def check_spec(frame: pd.DataFrame, spec: AnalysisSpec) -> list[dict[str, Any]]:
    return [check_operation(frame, operation) for operation in spec.operations]


def columns_used(spec: AnalysisSpec) -> set[str]:
    used: set[str] = set()
    for operation in spec.operations:
        used.update(required_columns(operation))
    if spec.currency_column:
        used.add(spec.currency_column)
    return used
