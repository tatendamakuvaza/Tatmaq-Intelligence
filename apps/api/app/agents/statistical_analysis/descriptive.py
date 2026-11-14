"""Descriptive statistics for numeric columns."""

from __future__ import annotations

from typing import Any

from analytics_core.statistics import describe

from ...analytics import formatting as fmt
from ...analytics.spec import DescriptiveStatistics
from .builder import OperationSkipped, SegmentBuilder

MAX_COLUMN_FINDINGS = 4
SKEW_THRESHOLD = 1.0


def _shape(stats: dict[str, Any]) -> str:
    skewness = stats.get("skewness")
    if skewness is None:
        return ""
    if skewness > SKEW_THRESHOLD:
        return (" The distribution is right-skewed: a small number of large values pull the mean above the "
                "median, so the median is the better guide to a typical value.")  # fmt: skip
    if skewness < -SKEW_THRESHOLD:
        return (" The distribution is left-skewed: a small number of low values pull the mean below the "
                "median, so the median is the better guide to a typical value.")  # fmt: skip
    return " The mean and median are close, so the values are spread fairly evenly around the centre."


def run(operation: DescriptiveStatistics, frame: Any, builder: SegmentBuilder, options: dict[str, Any]) -> None:
    described = {name: describe(frame[name].to_numpy(dtype="float64")) for name in operation.columns}
    described = {name: stats for name, stats in described.items() if stats["count"]}
    if not described:
        raise OperationSkipped("none of the selected columns has any values")

    ref = builder.add_evidence(
        operation="descriptive_statistics", columns=tuple(described),
        formula="sample statistics: variance and standard deviation use divisor n - 1; percentiles use linear "
                "interpolation; a mode is reported only when a value repeats",
        rows_total=len(frame), values=described,
    )  # fmt: skip
    builder.add_table(
        "descriptive_statistics", "Descriptive statistics",
        [("column", "Column", "text"), ("count", "Values", "integer"), ("mean", "Mean", "number"),
         ("median", "Median", "number"), ("std", "Std deviation", "number"), ("min", "Minimum", "number"),
         ("p25", "25th pct", "number"), ("p75", "75th pct", "number"), ("max", "Maximum", "number")],
        [{"column": name, **{key: stats.get(key) for key in ("count", "mean", "median", "std", "min", "p25", "p75", "max")}}
         for name, stats in described.items()],
        ref, note="Missing values are left out of each column's statistics.",
    )  # fmt: skip
    for name, stats in list(described.items())[:MAX_COLUMN_FINDINGS]:
        spread = f", standard deviation {fmt.number(stats['std'])}" if stats.get("std") is not None else ""
        builder.add_finding(
            f"descriptive.{name}", "statistic", f"{name}: summary",
            f"'{name}' has a mean of {fmt.number(stats['mean'])} and a median of {fmt.number(stats['median'])}"
            f"{spread}, across {stats['count']:,} values ranging from {fmt.number(stats['min'])} to "
            f"{fmt.number(stats['max'])}.{_shape(stats)}", ref, 48,
        )  # fmt: skip
