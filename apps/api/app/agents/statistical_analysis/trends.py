"""Trend analysis over complete calendar months."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Any

from analytics_core.financial import percent_change, summarise_sales, to_decimals
from analytics_core.statistics import ALPHA, MIN_POINTS_FOR_TEST, linear_trend

from ...analytics import formatting as fmt
from ...analytics.spec import Trend
from .builder import OperationSkipped, SegmentBuilder, series_floats

TREND_CAVEAT = (
    "The test fits a straight line and treats months as independent observations; it does not model "
    "seasonality, so a seasonal business can show a 'trend' or hide one."
)


def describe_trend(
    subject: str, months: Sequence[str], values: Sequence[Decimal], per_month: Callable[[float], str],
    *, plural: bool = False,
) -> tuple[str, dict[str, Any]]:  # fmt: skip
    """A sentence about the direction of a monthly series, plus the numbers behind it.

    ``per_month`` formats the size of the monthly change (a currency amount, or
    percentage points). The wording is driven entirely by the statistical result: a
    direction is only claimed when the slope is significant at the 5% level.
    """
    trend = linear_trend([float(value) for value in values])
    n = trend["n"]
    details = {**trend, "months": list(months), "caveat": TREND_CAVEAT}
    stats = ""
    if trend["r_squared"] is not None and trend["p_value"] is not None:
        stats = f"linear trend over {n} complete months, R\u00b2 = {trend['r_squared']:.2f}, {fmt.p_value(trend['p_value'])}"

    direction = trend["direction"]
    verb = "show" if plural else "shows"
    if direction in ("increasing", "decreasing"):
        word = "upward" if direction == "increasing" else "downward"
        change = per_month(abs(trend["slope"]))
        statement = (f"{subject} {verb} a statistically significant {word} trend: about {change} "
                     f"{'more' if direction == 'increasing' else 'less'} each month on average ({stats}).")  # fmt: skip
    elif direction == "no_significant_trend":
        statement = (f"{subject} {verb} no statistically significant upward or downward trend ({stats}): "
                     "the months do not rise or fall consistently.")  # fmt: skip
    elif direction == "flat":
        statement = f"{subject} {'were' if plural else 'was'} identical in each of the {n} complete months."
    elif n >= 2:
        statement = (f"There are only {n} complete months of data, fewer than the {MIN_POINTS_FOR_TEST} needed "
                     f"to test for a trend in {subject[0].lower()}{subject[1:]}.")  # fmt: skip
    else:
        statement = f"There is not enough dated history to assess a trend in {subject[0].lower()}{subject[1:]}."
    return statement, details


def first_to_last(first: Decimal, last: Decimal) -> Decimal | None:
    return percent_change(first, last, 1)


def run(operation: Trend, frame: Any, builder: SegmentBuilder, options: dict[str, Any]) -> None:
    """Monthly totals of any numeric column, with a tested trend."""
    values = to_decimals(frame[operation.measure].tolist())
    summary = summarise_sales(frame, amounts=values, date_column=operation.date)
    complete = summary.complete_months
    if len(complete) < 2:
        raise OperationSkipped(f"'{operation.date}' covers fewer than two complete months")

    months = [month.month for month in complete]
    totals = [month.revenue for month in complete]
    statement, details = describe_trend(f"Monthly {operation.measure}", months, totals, lambda v: fmt.number(v))
    ref = builder.add_evidence(
        operation="trend", columns=(operation.measure, operation.date),
        formula=f"monthly total = sum of '{operation.measure}' by calendar month of '{operation.date}'; "
                "trend = least-squares slope of monthly totals on month index",
        parameters={"alpha": ALPHA, "minimum_months_for_test": MIN_POINTS_FOR_TEST},
        rows_total=summary.rows_total, rows_used=summary.rows_used - summary.rows_missing_date,
        exclusions={"missing value": summary.rows_missing_amount, "missing date": summary.rows_missing_date},
        values={**details, "monthly": {m.month: fmt.decimal_text(m.revenue) for m in summary.monthly},
                "incomplete_months": {m.month: m.note for m in summary.monthly if not m.complete}},
    )  # fmt: skip
    builder.add_chart(
        f"trend_{len(builder.charts)}", f"{operation.measure} by month",
        [fmt.month_label(m.month) for m in summary.monthly],
        [{"name": operation.measure, "type": "line", "format": "number",
          "values": series_floats([m.revenue for m in summary.monthly])}],
        ref, note=_incomplete_note(summary.monthly),
    )  # fmt: skip
    builder.add_finding(f"trend.{operation.measure}", "statistic", f"Trend in {operation.measure}", statement, ref, 70)
    change = first_to_last(totals[0], totals[-1])
    if change is not None:
        builder.add_finding(
            f"trend.change.{operation.measure}", "insight", f"Change in {operation.measure}",
            f"{operation.measure} in {fmt.month_label(months[-1], long=True)} was {fmt.compared_with(change)} "
            f"in {fmt.month_label(months[0], long=True)} "
            f"({fmt.number(totals[-1])} against {fmt.number(totals[0])}).", ref, 55,
        )  # fmt: skip


def _incomplete_note(monthly: Sequence[Any]) -> str | None:
    partial = [
        f"{fmt.month_label(m.month if hasattr(m, 'month') else m.key)} ({m.note})" for m in monthly if not m.complete
    ]
    if not partial:
        return None
    noun = "Incomplete month" if len(partial) == 1 else "Incomplete months"
    return f"{noun}, left out of comparisons and the trend: {'; '.join(partial)}."


incomplete_note = _incomplete_note
