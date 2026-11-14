from datetime import date
from decimal import Decimal as D

import numpy as np
import pandas as pd

from analytics_core.financial import summarise_profitability, summarise_sales, to_decimals


def frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2026-01-05", "2026-01-20", "2026-02-10", "2026-04-02", "2026-04-15", None, "2026-04-28"]
            ),
            "product": ["Sugar", "Oil", "Sugar", "Oil", "Soap", "Sugar", None],
            "amount": [100.10, 200.20, 50.05, 300.30, 19.99, 10.00, np.nan],
            "cost": [80.00, 150.15, np.nan, 310.30, 9.99, 8.00, 5.00],
            "qty": [1, 2, 1, 3, 1, 1, 1],
            "invoice": ["A1", "A2", "A3", "A4", "A4", "A5", "A6"],
        }
    )


def test_sales_totals_are_exact_and_missing_amounts_are_not_zero_sales():
    data = frame()
    summary = summarise_sales(
        data, amounts=to_decimals(data["amount"]), date_column="date", dimensions=["product"],
        quantities=to_decimals(data["qty"]), document_column="invoice",
    )  # fmt: skip
    assert summary.total_revenue == D("680.64")  # 100.10 + 200.20 + 50.05 + 300.30 + 19.99 + 10.00
    assert (summary.rows_total, summary.rows_used, summary.rows_missing_amount) == (7, 6, 1)
    assert summary.average_per_row == D("680.64") / 6
    assert summary.units == D(9)  # the row with no amount contributes no units
    assert summary.documents == 5  # A4 appears twice; A6 has no amount
    assert (summary.period_start, summary.period_end) == (date(2026, 1, 5), date(2026, 4, 15))
    assert (summary.rows_missing_date, summary.undated_revenue) == (1, D("10.00"))


def test_months_without_sales_appear_as_zero_and_everything_reconciles():
    data = frame()
    summary = summarise_sales(data, amounts=to_decimals(data["amount"]), date_column="date", dimensions=["product"])
    assert [(m.month, m.revenue, m.rows) for m in summary.monthly] == [
        ("2026-01", D("300.30"), 2),
        ("2026-02", D("50.05"), 1),
        ("2026-03", D("0"), 0),
        ("2026-04", D("320.29"), 2),
    ]
    assert summary.monthly[2].note == "no records in this month"
    assert sum(m.revenue for m in summary.monthly) + summary.undated_revenue == summary.total_revenue

    products = summary.by_dimension["product"]
    assert [(g.key, g.revenue) for g in products] == [
        ("Oil", D("500.50")),
        ("Sugar", D("160.15")),
        ("Soap", D("19.99")),
    ]
    assert sum(g.revenue for g in products) == summary.total_revenue
    assert products[0].share_pct == D("73.53")  # 500.50 / 680.64


def test_profit_excludes_rows_without_cost_instead_of_assuming_zero_cost():
    data = frame()
    summary = summarise_profitability(
        data, revenues=to_decimals(data["amount"]), costs=to_decimals(data["cost"]),
        date_column="date", dimensions=["product"],
    )  # fmt: skip
    # rows used: 100.10/80.00, 200.20/150.15, 300.30/310.30, 19.99/9.99, 10.00/8.00
    assert summary.revenue == D("630.59") and summary.cost == D("558.44")
    assert summary.gross_profit == D("72.15")
    assert summary.margin_pct == D("11.44")  # 72.15 / 630.59 = 11.4417...%
    assert (summary.rows_used, summary.rows_missing_cost, summary.rows_missing_revenue) == (5, 1, 1)
    assert summary.excluded_revenue == D("50.05")
    assert summary.rows_used + summary.rows_excluded == summary.rows_total

    by_product = {row.key: row for row in summary.by_dimension["product"]}
    assert by_product["Oil"].gross_profit == D("40.05")  # 50.05 profit and a 10.00 loss
    assert by_product["Soap"].margin_pct == D("50.03")
    assert by_product["Sugar"].gross_profit == D("22.10")
    assert sum(row.gross_profit for row in by_product.values()) == summary.gross_profit
    assert [row.key for row in summary.by_dimension["product"]] == ["Oil", "Sugar", "Soap"]  # by profit


def test_loss_making_month_has_negative_margin():
    data = frame()
    summary = summarise_profitability(
        data, revenues=to_decimals(data["amount"]), costs=to_decimals(data["cost"]), date_column="date"
    )
    april = next(row for row in summary.monthly if row.key == "2026-04")
    assert april.gross_profit == D("0.00") and april.margin_pct == D("0.00")  # 320.29 - 320.29
    january = summary.monthly[0]
    assert (january.revenue, january.cost, january.margin_pct) == (D("300.30"), D("230.15"), D("23.36"))


def daily(start: str, end: str) -> pd.DataFrame:
    days = pd.date_range(start, end, freq="D")
    return pd.DataFrame({"date": days, "amount": [10.0] * len(days)})


def test_a_month_the_data_only_partly_covers_is_marked_incomplete():
    data = daily("2026-08-01", "2026-10-11")  # export taken on 11 October
    summary = summarise_sales(data, amounts=to_decimals(data["amount"]), date_column="date")
    assert [(m.month, m.complete) for m in summary.monthly] == [
        ("2026-08", True),
        ("2026-09", True),
        ("2026-10", False),
    ]
    assert summary.monthly[-1].note == "data ends on 2026-10-11"
    assert [m.month for m in summary.complete_months] == ["2026-08", "2026-09"]

    late_start = daily("2026-08-19", "2026-10-31")
    flags = [
        m.complete
        for m in summarise_sales(late_start, amounts=to_decimals(late_start["amount"]), date_column="date").monthly
    ]
    assert flags == [False, True, True]


def test_month_level_data_is_not_judged_for_completeness():
    data = pd.DataFrame({"date": pd.to_datetime(["2026-01-15", "2026-02-15", "2026-03-15"]), "amount": [1.0, 2.0, 3.0]})
    summary = summarise_sales(data, amounts=to_decimals(data["amount"]), date_column="date")
    assert all(m.complete for m in summary.monthly)


def test_zero_sales_give_undefined_margin_not_a_crash():
    data = pd.DataFrame({"amount": [0.0], "cost": [5.0]})
    summary = summarise_profitability(data, revenues=to_decimals(data["amount"]), costs=to_decimals(data["cost"]))
    assert summary.gross_profit == D("-5") and summary.margin_pct is None
