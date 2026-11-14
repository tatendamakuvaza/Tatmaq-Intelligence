"""Unusual values, flagged for review with the interquartile-range rule."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from analytics_core.cleaning import ROW_COLUMN
from analytics_core.statistics import STANDARD_K, iqr_bounds, outlier_mask

from ...analytics import formatting as fmt
from ...analytics.spec import Outliers
from .builder import TOP_N, OperationSkipped, SegmentBuilder

#: The platform never concludes wrongdoing from a number alone (specification, Agent 01 restriction).
NOT_A_VERDICT = ("An unusual value is a prompt to look at the record. On its own it is not evidence of an "
                 "error or of wrongdoing.")  # fmt: skip


def run(operation: Outliers, frame: Any, builder: SegmentBuilder, options: dict[str, Any]) -> None:
    column = operation.column
    values = frame[column].to_numpy(dtype="float64")
    bounds = iqr_bounds(values, STANDARD_K)
    if bounds is None:
        raise OperationSkipped(f"'{column}' has fewer than 8 values")
    if bounds.iqr == 0:
        raise OperationSkipped(f"the middle half of '{column}' is a single value, so the IQR rule cannot be applied")

    flagged = outlier_mask(values, bounds)
    count = int(flagged.sum())
    context = [name for name in options.get("context_columns", []) if name in frame.columns and name != column][:3]
    distance = np.where(values > bounds.upper, values - bounds.upper, bounds.lower - values)
    order = np.argsort(-np.where(flagged, distance, -np.inf))[: min(count, TOP_N)]
    examples = frame.iloc[order]

    ref = builder.add_evidence(
        operation="outliers", columns=(column,),
        formula="a value is flagged when it lies below Q1 - 1.5 x IQR or above Q3 + 1.5 x IQR (Tukey's rule)",
        parameters={"k": STANDARD_K, "q1": bounds.q1, "q3": bounds.q3, "iqr": bounds.iqr,
                    "lower_fence": bounds.lower, "upper_fence": bounds.upper},
        rows_total=len(frame), rows_used=bounds.n, exclusions={"missing value": len(frame) - bounds.n},
        values={"flagged": count, "source_rows": [int(row) for row in examples[ROW_COLUMN].tolist()]},
    )  # fmt: skip

    if count:
        rows = []
        for _, record in examples.iterrows():
            row: dict[str, Any] = {"row": int(record[ROW_COLUMN]), "value": float(record[column])}
            for name in context:
                cell = record[name]
                row[name] = None if pd.isna(cell) else (cell.date().isoformat() if hasattr(cell, "date") else str(cell))
            rows.append(row)
        builder.add_table(
            f"outliers_{len(builder.tables)}", f"Most unusual values of {column}",
            [("row", "Source row", "integer"), *[(name, name, "text") for name in context], ("value", column, "number")],
            rows, ref, note=NOT_A_VERDICT,
        )  # fmt: skip
        largest = (
            f" The most extreme is {fmt.number(float(examples[column].iloc[0]))} (source row "
            f"{int(examples[ROW_COLUMN].iloc[0]):,})."
        )
        statement = (f"{count:,} of {bounds.n:,} values of '{column}' ({count / bounds.n:.1%}) fall outside the "
                     f"usual range of {fmt.number(bounds.lower)} to {fmt.number(bounds.upper)} "
                     f"(1.5 x IQR rule).{largest} {NOT_A_VERDICT}")  # fmt: skip
    else:
        statement = (f"No values of '{column}' fall outside the usual range of {fmt.number(bounds.lower)} to "
                     f"{fmt.number(bounds.upper)} (1.5 x IQR rule, {bounds.n:,} values).")  # fmt: skip
    builder.add_finding(f"outliers.{column}", "statistic", f"Unusual values: {column}", statement, ref, 62)
