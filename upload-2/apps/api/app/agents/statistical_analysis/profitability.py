"""Gross profit and gross margin: overall, by month, and by product or other dimension."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from analytics_core.financial import ZERO, exact_sum, gross_margin_pct, percent, summarise_profitability
from analytics_core.statistics import ALPHA, MIN_POINTS_FOR_TEST

from ...analytics import formatting as fmt
from ...analytics.spec import Profitability
from .builder import (
    CHART_TOP_N,
    TOP_N,
    OperationSkipped,
    SegmentBuilder,
    measure_formula,
    measure_values,
    series_floats,
)
from .trends import describe_trend, incomplete_note

#: Groups smaller than this share of sales are ignored when naming the best and worst margins.
MIN_SHARE_FOR_MARGIN_RANKING = Decimal("1")
MAX_LOSS_MAKERS_LISTED = 5

COLUMNS = [("sales", "Sales", "money"), ("cost", "Cost of sales", "money"), ("profit", "Gross profit", "money"),
           ("margin", "Gross margin", "percent")]  # fmt: skip


def _row(name_key: str, name: str, revenue: Decimal, cost: Decimal, **extra: Any) -> dict[str, Any]:
    return {name_key: name, "sales": revenue, "cost": cost, "profit": revenue - cost,
            "margin": gross_margin_pct(revenue, cost), **extra}  # fmt: skip


def run(operation: Profitability, frame: Any, builder: SegmentBuilder, options: dict[str, Any]) -> None:
    currency = builder.currency
    money = lambda value: fmt.money(value, currency)  # noqa: E731
    summary = summarise_profitability(
        frame, revenues=measure_values(frame, operation.revenue), costs=measure_values(frame, operation.cost),
        date_column=operation.date, dimensions=operation.dimensions,
    )  # fmt: skip
    if summary.rows_used == 0:
        raise OperationSkipped("no rows have both a sales value and a cost value")

    sales_source, cost_source = measure_formula(operation.revenue), measure_formula(operation.cost)
    columns = (*operation.revenue.columns, *operation.cost.columns)
    exclusions = {"no cost value": summary.rows_missing_cost, "no sales value": summary.rows_missing_revenue,
                  "neither value": summary.rows_missing_both}  # fmt: skip
    definition = (f"gross profit = sales ({sales_source}) - cost of sales ({cost_source}); "
                  "gross margin = gross profit / sales x 100, rounded half-up to 2 decimals")  # fmt: skip

    ref = builder.add_evidence(
        operation="profitability.total", columns=columns,
        formula=f"{definition}; over rows that have both values (exact decimal arithmetic)",
        rows_total=summary.rows_total, rows_used=summary.rows_used, exclusions=exclusions,
        values={"sales": fmt.decimal_text(summary.revenue), "cost_of_sales": fmt.decimal_text(summary.cost),
                "gross_profit": fmt.decimal_text(summary.gross_profit),
                "gross_margin_pct": fmt.decimal_text(summary.margin_pct),
                "sales_on_rows_without_cost": fmt.decimal_text(summary.excluded_revenue)},
    )  # fmt: skip
    builder.add_kpi("gross_profit", "Gross profit", summary.gross_profit, "money", ref)
    builder.add_kpi("gross_margin", "Gross margin", summary.margin_pct, "percent", ref)
    builder.add_kpi("cost_of_sales", "Cost of sales", summary.cost, "money", ref)
    margin_text = (
        f"a gross margin of {fmt.percent(summary.margin_pct)}"
        if summary.margin_pct is not None
        else "with no margin defined because sales are zero"
    )
    builder.add_finding(
        "profit.overall", "kpi", "Gross profit",
        f"Gross profit was {money(summary.gross_profit)} on sales of {money(summary.revenue)} "
        f"(cost of sales {money(summary.cost)}): {margin_text}.", ref, 96,
    )  # fmt: skip
    if summary.rows_missing_cost:
        builder.add_finding(
            "profit.rows_without_cost", "limitation", "Rows without a cost",
            f"{fmt.count_of(summary.rows_missing_cost, 'row')} {'has' if summary.rows_missing_cost == 1 else 'have'} "
            f"a sales value but no cost. Their sales of {money(summary.excluded_revenue)} are left out of the "
            "profit figures: treating a missing cost as zero would overstate profit.", ref, 54,
        )  # fmt: skip

    audit: dict[str, Any] = {
        "revenue_measure": operation.revenue.model_dump(), "cost_measure": operation.cost.model_dump(),
        "revenue": fmt.decimal_text(summary.revenue), "cost": fmt.decimal_text(summary.cost),
        "gross_profit": fmt.decimal_text(summary.gross_profit), "margin_pct": fmt.decimal_text(summary.margin_pct),
        "rows_total": summary.rows_total, "rows_used": summary.rows_used, "rows_excluded": summary.rows_excluded,
        "dimensions": {},
    }  # fmt: skip

    if operation.date and summary.monthly:
        _monthly(operation, summary, builder, money, definition, columns, exclusions, audit)

    for position, dimension in enumerate(operation.dimensions):
        groups = summary.by_dimension[dimension]
        audit["dimensions"][dimension] = [
            [g.key, fmt.decimal_text(g.revenue), fmt.decimal_text(g.cost)] for g in groups
        ]
        if len(groups) < 2:
            continue
        dim_ref = builder.add_evidence(
            operation="profitability.by_dimension", columns=(*columns, dimension),
            formula=f"{definition}; grouped by '{dimension}'. Ranked by gross profit.",
            rows_total=summary.rows_total, rows_used=summary.rows_used, exclusions=exclusions,
            values={"groups": len(groups),
                    "top": {g.key: {"gross_profit": fmt.decimal_text(g.gross_profit),
                                    "margin_pct": fmt.decimal_text(g.margin_pct)} for g in groups[:TOP_N]}},
        )  # fmt: skip

        shown, rest = list(groups[:TOP_N]), list(groups[TOP_N:])
        losses_in_rest = [g for g in rest if g.gross_profit < 0][:MAX_LOSS_MAKERS_LISTED]
        rest = [g for g in rest if g not in losses_in_rest]
        rows = [_row("name", g.key, g.revenue, g.cost, share=g.profit_share_pct) for g in shown]
        if rest:
            revenue, cost = exact_sum(g.revenue for g in rest), exact_sum(g.cost for g in rest)
            share = percent(revenue - cost, summary.gross_profit) if summary.gross_profit > 0 else None
            rows.append(_row("name", f"All other ({len(rest)})", revenue, cost, share=share))
        rows += [_row("name", g.key, g.revenue, g.cost, share=g.profit_share_pct) for g in losses_in_rest]
        builder.add_table(f"profit_by_{position}", f"Profitability by {dimension}",
                          [("name", dimension, "text"), *COLUMNS, ("share", "Share of profit", "percent")],
                          rows, dim_ref)  # fmt: skip

        leaders = groups[:3]
        named = fmt.join_names(
            [f"{g.key} ({money(g.gross_profit)}, margin {fmt.percent(g.margin_pct, 1)})" for g in leaders]
        )
        statement = f"By {dimension}, the most profitable (ranked by gross profit) are {named}."
        if summary.gross_profit > 0 and len(groups) > 3:
            combined = percent(exact_sum(g.gross_profit for g in leaders), summary.gross_profit, 1)
            statement += f" Together they generate {fmt.percent(combined, 1)} of gross profit."
        builder.add_finding(f"profit.by.{dimension}", "insight", f"Most profitable: {dimension}", statement,
                            dim_ref, 92 if position == 0 else 62)  # fmt: skip

        losses = sorted((g for g in groups if g.gross_profit < 0), key=lambda g: g.gross_profit)
        if losses:
            listed = fmt.join_names([f"{g.key} ({money(g.gross_profit)}, margin {fmt.percent(g.margin_pct, 1)})"
                                     for g in losses[:MAX_LOSS_MAKERS_LISTED]])  # fmt: skip
            more = f" and {len(losses) - MAX_LOSS_MAKERS_LISTED} more" if len(losses) > MAX_LOSS_MAKERS_LISTED else ""
            builder.add_finding(
                f"profit.losses.{dimension}", "insight", f"Sold at a loss: {dimension}",
                f"Under {dimension}, {len(losses)} of {len(groups)} made a gross loss (cost of sales exceeded "
                f"sales): {listed}{more}.", dim_ref, 90 if position == 0 else 64,
            )  # fmt: skip

        ranked = [g for g in groups if g.margin_pct is not None and g.revenue > 0
                  and (percent(g.revenue, summary.revenue) or ZERO) >= MIN_SHARE_FOR_MARGIN_RANKING]  # fmt: skip
        if position == 0 and len(ranked) >= 3:
            high = max(ranked, key=lambda g: (g.margin_pct, g.key))
            low = min(ranked, key=lambda g: (g.margin_pct, g.key))
            builder.add_finding(
                f"profit.margin_range.{dimension}", "insight", f"Margin range: {dimension}",
                f"Gross margin varies widely by {dimension}: from {fmt.percent(low.margin_pct, 1)} "
                f"({low.key}) to {fmt.percent(high.margin_pct, 1)} ({high.key}), against "
                f"{fmt.percent(summary.margin_pct, 1)} overall. (Values under 1% of sales are not ranked.)",
                dim_ref, 68,
            )  # fmt: skip
        if position == 0:
            top = groups[:CHART_TOP_N]
            builder.add_chart("profit_by_dimension", f"Top {len(top)} by gross profit: {dimension}",
                              [g.key for g in top],
                              [{"name": "Gross profit", "type": "bar", "format": "money",
                                "values": series_floats([g.gross_profit for g in top])}],
                              dim_ref, orientation="horizontal")  # fmt: skip

    builder.audit["profitability"] = audit


def _monthly(operation: Profitability, summary: Any, builder: SegmentBuilder, money: Any, definition: str,
             columns: tuple[str, ...], exclusions: dict[str, int], audit: dict[str, Any]) -> None:  # fmt: skip
    monthly = summary.monthly
    audit["monthly"] = [[m.key, fmt.decimal_text(m.revenue), fmt.decimal_text(m.cost)] for m in monthly]
    usable = [m for m in summary.complete_months if m.margin_pct is not None]
    months = [m.key for m in usable]
    margins = [m.margin_pct for m in usable]
    trend_statement, trend_details = (
        describe_trend("Monthly gross margin", months, margins, lambda v: f"{v:.2f} percentage points")
        if months else ("", {})
    )  # fmt: skip
    ref = builder.add_evidence(
        operation="profitability.by_month", columns=(*columns, operation.date),
        formula=f"{definition}; grouped by calendar month of '{operation.date}'. "
                "Trend = least-squares slope of complete months' margin on month index.",
        parameters={"alpha": ALPHA, "minimum_months_for_test": MIN_POINTS_FOR_TEST},
        rows_total=summary.rows_total, rows_used=summary.rows_used, exclusions=exclusions,
        values={"monthly_margin_pct": {m.key: fmt.decimal_text(m.margin_pct) for m in monthly},
                "monthly_gross_profit": {m.key: fmt.decimal_text(m.gross_profit) for m in monthly},
                "incomplete_months": {m.key: m.note for m in monthly if not m.complete}, "trend": trend_details},
    )  # fmt: skip
    builder.add_chart(
        "profit_by_month", "Gross profit and margin by month", [fmt.month_label(m.key) for m in monthly],
        [{"name": "Gross profit", "type": "bar", "format": "money",
          "values": series_floats([m.gross_profit for m in monthly])},
         {"name": "Gross margin %", "type": "line", "format": "percent", "axis": "right",
          "values": series_floats([m.margin_pct for m in monthly])}],
        ref, note=incomplete_note(monthly),
    )  # fmt: skip
    builder.add_table(
        "profit_by_month",
        "Profitability by month",
        [("month", "Month", "month"), *COLUMNS],
        [_row("month", m.key, m.revenue, m.cost) for m in monthly],
        ref,
    )
    if len(usable) < 2:
        return
    first, last = usable[0], usable[-1]
    high = max(usable, key=lambda m: (m.margin_pct, m.key))
    low = min(usable, key=lambda m: (m.margin_pct, m.key))
    delta = last.margin_pct - first.margin_pct
    movement = (
        f"was {fmt.percent(first.margin_pct)} in both {fmt.month_label(first.key, long=True)} and "
        f"{fmt.month_label(last.key, long=True)}"
        if delta == 0
        else f"moved from {fmt.percent(first.margin_pct)} in {fmt.month_label(first.key, long=True)} to "
        f"{fmt.percent(last.margin_pct)} in {fmt.month_label(last.key, long=True)} ({fmt.points(delta)})"
    )
    builder.add_finding(
        "profit.margin_change", "insight", "Margin over the period",
        f"Gross margin {movement}. The highest monthly margin was "
        f"{fmt.percent(high.margin_pct)} ({fmt.month_label(high.key, long=True)}) and the lowest "
        f"{fmt.percent(low.margin_pct)} ({fmt.month_label(low.key, long=True)}).", ref, 78,
    )  # fmt: skip
    significant = trend_details.get("direction") in ("increasing", "decreasing")
    builder.add_finding(
        "profit.margin_trend", "statistic", "Margin trend", trend_statement, ref, 89 if significant else 57
    )
