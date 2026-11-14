"""Sales performance: totals, months, and breakdowns by product, branch and so on."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from analytics_core.financial import ZERO, divide, exact_sum, percent, percent_change, summarise_sales, to_decimals
from analytics_core.statistics import ALPHA, MIN_POINTS_FOR_TEST

from ...analytics import formatting as fmt
from ...analytics.spec import SalesOverview
from .builder import (
    CHART_TOP_N,
    TOP_N,
    OperationSkipped,
    SegmentBuilder,
    measure_formula,
    measure_values,
    series_floats,
)
from .trends import describe_trend, first_to_last, incomplete_note


def run(operation: SalesOverview, frame: Any, builder: SegmentBuilder, options: dict[str, Any]) -> None:
    currency = builder.currency
    amounts = measure_values(frame, operation.revenue)
    quantities = to_decimals(frame[operation.quantity].tolist()) if operation.quantity else None
    summary = summarise_sales(
        frame, amounts=amounts, date_column=operation.date, dimensions=operation.dimensions,
        quantities=quantities, document_column=operation.document,
    )  # fmt: skip
    if summary.rows_used == 0:
        raise OperationSkipped("no rows have a sales value")

    source = measure_formula(operation.revenue)
    money = lambda value: fmt.money(value, currency)  # noqa: E731

    # ---- totals ---------------------------------------------------------------------
    total_ref = builder.add_evidence(
        operation="sales_overview.total", columns=operation.revenue.columns,
        formula=f"total sales = sum of {source} over every row that has a value (exact decimal arithmetic)",
        rows_total=summary.rows_total, rows_used=summary.rows_used,
        exclusions={"no sales value": summary.rows_missing_amount},
        values={"total_sales": fmt.decimal_text(summary.total_revenue), "records": summary.rows_used,
                "invoices": summary.documents, "units": fmt.decimal_text(summary.units),
                "negative_rows": summary.negative_rows, "negative_total": fmt.decimal_text(summary.negative_total)},
    )  # fmt: skip
    builder.add_kpi("total_sales", "Total sales", summary.total_revenue, "money", total_ref)
    if summary.documents:
        builder.add_kpi("invoices", "Invoices", summary.documents, "integer", total_ref,
                        note=f"{summary.rows_used:,} lines")  # fmt: skip
        builder.add_kpi("average_invoice", "Average invoice value",
                        divide(summary.total_revenue, Decimal(summary.documents)), "money", total_ref)  # fmt: skip
    else:
        builder.add_kpi("records", "Records", summary.rows_used, "integer", total_ref)
        builder.add_kpi("average_record", "Average per record", summary.average_per_row, "money", total_ref)
    if summary.units is not None:
        builder.add_kpi("units", "Units sold", summary.units, "integer", total_ref)

    volume = f"{summary.rows_used:,} records"
    if summary.documents:
        volume = f"{summary.documents:,} invoices ({summary.rows_used:,} lines)"
    period = ""
    if summary.period_start and summary.period_end:
        period = f" between {fmt.date_label(summary.period_start)} and {fmt.date_label(summary.period_end)}"
        builder.period = {"start": summary.period_start.isoformat(), "end": summary.period_end.isoformat()}
    left_out = (f" {fmt.count_of(summary.rows_missing_amount, 'row')} with no sales value "
                f"{'was' if summary.rows_missing_amount == 1 else 'were'} left out."
                if summary.rows_missing_amount else "")  # fmt: skip
    builder.add_finding("sales.total", "kpi", "Total sales",
                        f"Total sales were {money(summary.total_revenue)} from {volume}{period}.{left_out}",
                        total_ref, 100)  # fmt: skip
    if summary.negative_rows:
        builder.add_finding(
            "sales.negative_lines", "insight", "Returns and credits",
            f"The total includes {fmt.count_of(summary.negative_rows, 'negative line')} worth "
            f"{money(summary.negative_total)}: returns, credit notes or corrections.", total_ref, 35,
        )  # fmt: skip

    audit: dict[str, Any] = {
        "measure": operation.revenue.model_dump(), "total": fmt.decimal_text(summary.total_revenue),
        "rows_total": summary.rows_total, "rows_used": summary.rows_used,
        "rows_missing": summary.rows_missing_amount, "dimensions": {},
    }  # fmt: skip

    # ---- by month -------------------------------------------------------------------
    if operation.date and summary.monthly:
        _monthly(operation, summary, builder, money, source, audit)

    # ---- by dimension ---------------------------------------------------------------
    for position, dimension in enumerate(operation.dimensions):
        groups = summary.by_dimension[dimension]
        audit["dimensions"][dimension] = [[group.key, fmt.decimal_text(group.revenue)] for group in groups]
        if len(groups) < 2:
            continue
        ref = builder.add_evidence(
            operation="sales_overview.by_dimension", columns=(*operation.revenue.columns, dimension),
            formula=f"sales by {dimension} = sum of {source} grouped by '{dimension}'; "
                    "share = group sales / total sales x 100",
            rows_total=summary.rows_total, rows_used=summary.rows_used,
            exclusions={"no sales value": summary.rows_missing_amount},
            values={"groups": len(groups),
                    "top": {group.key: fmt.decimal_text(group.revenue) for group in groups[:TOP_N]}},
        )  # fmt: skip
        rows = [{"name": g.key, "sales": g.revenue, "share": g.share_pct, "records": g.rows} for g in groups[:TOP_N]]
        rest = groups[TOP_N:]
        if rest:
            rest_total = exact_sum(group.revenue for group in rest)
            rows.append({"name": f"All other ({len(rest)})", "sales": rest_total,
                         "share": percent(rest_total, summary.total_revenue), "records": sum(g.rows for g in rest)})  # fmt: skip
        builder.add_table(f"sales_by_{position}", f"Sales by {dimension}",
                          [("name", dimension, "text"), ("sales", "Sales", "money"),
                           ("share", "Share of sales", "percent"), ("records", "Records", "integer")], rows, ref)  # fmt: skip
        if position == 0 and not options.get("has_profitability"):
            top = groups[:CHART_TOP_N]
            builder.add_chart("sales_by_dimension", f"Top {len(top)} by sales: {dimension}", [g.key for g in top],
                              [{"name": "Sales", "type": "bar", "format": "money",
                                "values": series_floats([g.revenue for g in top])}], ref, orientation="horizontal")  # fmt: skip

        leaders = groups[:3]
        named = fmt.join_names([f"{g.key} ({money(g.revenue)}, {fmt.percent(g.share_pct, 1)})" for g in leaders])
        combined = percent(exact_sum(g.revenue for g in leaders), summary.total_revenue, 1)
        if len(groups) > 3:
            statement = (f"By {dimension}, the largest contributors to sales are {named}. Together they account "
                         f"for {fmt.percent(combined, 1)} of sales ({len(groups)} in total).")  # fmt: skip
        else:
            statement = f"By {dimension}, sales were {named}."
        builder.add_finding(f"sales.by.{dimension}", "insight", f"Sales by {dimension}", statement, ref,
                            72 if position == 0 else 58)  # fmt: skip
        if groups[0].share_pct is not None and groups[0].share_pct >= 50 and len(groups) > 2:
            builder.add_finding(
                f"sales.concentration.{dimension}", "insight", f"Concentration by {dimension}",
                f"Sales are concentrated: {groups[0].key} alone accounts for "
                f"{fmt.percent(groups[0].share_pct, 1)} of the total.", ref, 66,
            )  # fmt: skip

    builder.audit["sales"] = audit


def _monthly(operation: SalesOverview, summary: Any, builder: SegmentBuilder, money: Any, source: str,
             audit: dict[str, Any]) -> None:  # fmt: skip
    monthly, complete = summary.monthly, summary.complete_months
    audit["monthly"] = [[m.month, fmt.decimal_text(m.revenue)] for m in monthly]
    audit["undated"] = fmt.decimal_text(summary.undated_revenue)
    note = incomplete_note(monthly)
    if note:
        builder.notes.append(note)
    if summary.rows_missing_date:
        builder.notes.append(
            f"{fmt.count_of(summary.rows_missing_date, 'row')} worth {money(summary.undated_revenue)} "
            f"{'has' if summary.rows_missing_date == 1 else 'have'} no valid date: included in total sales, "
            "but not in any month."
        )

    months = [m.month for m in complete]
    totals = [m.revenue for m in complete]
    trend_statement, trend_details = (
        describe_trend("Monthly sales", months, totals, lambda v: money(v), plural=True) if months else ("", {})
    )
    ref = builder.add_evidence(
        operation="sales_overview.by_month", columns=(*operation.revenue.columns, operation.date),
        formula=f"monthly sales = sum of {source} grouped by calendar month of '{operation.date}'; "
                "trend = least-squares slope of complete months' sales on month index",
        parameters={"alpha": ALPHA, "minimum_months_for_test": MIN_POINTS_FOR_TEST},
        rows_total=summary.rows_total, rows_used=summary.rows_used - summary.rows_missing_date,
        exclusions={"no sales value": summary.rows_missing_amount, "no valid date": summary.rows_missing_date},
        values={"monthly": {m.month: fmt.decimal_text(m.revenue) for m in monthly},
                "incomplete_months": {m.month: m.note for m in monthly if not m.complete}, "trend": trend_details},
    )  # fmt: skip

    builder.add_chart("sales_by_month", "Sales by month", [fmt.month_label(m.month) for m in monthly],
                      [{"name": "Sales", "type": "bar", "format": "money",
                        "values": series_floats([m.revenue for m in monthly])}], ref, note=note)  # fmt: skip
    rows, previous = [], None
    for month in monthly:
        change = percent_change(previous, month.revenue, 2) if previous is not None and previous != ZERO else None
        rows.append({"month": month.month, "sales": month.revenue, "records": month.rows, "change": change,
                     "status": "Complete" if month.complete else f"Incomplete: {month.note}"})  # fmt: skip
        previous = month.revenue
    builder.add_table("sales_by_month", "Sales by month",
                      [("month", "Month", "month"), ("sales", "Sales", "money"), ("records", "Records", "integer"),
                       ("change", "Change on previous month", "percent"), ("status", "Coverage", "text")], rows, ref)  # fmt: skip

    if not complete:
        return
    average = divide(exact_sum(totals), Decimal(len(totals)))
    builder.add_kpi("average_monthly_sales", "Average monthly sales", average, "money", ref,
                    note=f"{len(complete)} complete month{'s' if len(complete) != 1 else ''}")  # fmt: skip
    if len(complete) >= 2:
        best = max(complete, key=lambda m: (m.revenue, m.month))
        worst = min(complete, key=lambda m: (m.revenue, m.month))
        above = first_to_last(average, best.revenue)
        builder.add_finding(
            "sales.best_worst_month", "insight", "Strongest and weakest months",
            f"The strongest month was {fmt.month_label(best.month, long=True)} with {money(best.revenue)}, "
            f"{fmt.above_below(above)} the monthly average of {money(average)}. The weakest was "
            f"{fmt.month_label(worst.month, long=True)} with {money(worst.revenue)}.", ref, 82,
        )  # fmt: skip
        significant = trend_details.get("direction") in ("increasing", "decreasing")
        builder.add_finding("sales.trend", "statistic", "Sales trend", trend_statement, ref, 88 if significant else 58)
        change = first_to_last(totals[0], totals[-1])
        if change is not None:
            builder.add_finding(
                "sales.change", "insight", "First month to last month",
                f"Sales in {fmt.month_label(months[-1], long=True)} were {fmt.compared_with(change)} in "
                f"{fmt.month_label(months[0], long=True)} ({money(totals[-1])} against {money(totals[0])}).", ref, 60,
            )  # fmt: skip
