"""Gross profit and gross margin, in exact decimal arithmetic.

Definitions used throughout
---------------------------
Gross profit        = sales - cost of sales
Gross profit margin = gross profit / sales x 100

Only rows that carry *both* a sales value and a cost value take part. A row with a
missing cost is left out and reported; treating it as zero cost would overstate profit.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

import pandas as pd

from .money import ZERO, exact_group_sums, exact_sum, percent
from .periods import incomplete_months, label_values, month_keys, month_range


@dataclass(frozen=True)
class ProfitRow:
    key: str
    revenue: Decimal
    cost: Decimal
    gross_profit: Decimal
    margin_pct: Decimal | None
    rows: int
    profit_share_pct: Decimal | None = None
    complete: bool = True
    note: str | None = None


@dataclass(frozen=True)
class ProfitabilitySummary:
    rows_total: int
    rows_used: int
    rows_missing_cost: int
    rows_missing_revenue: int
    rows_missing_both: int
    excluded_revenue: Decimal
    revenue: Decimal
    cost: Decimal
    gross_profit: Decimal
    margin_pct: Decimal | None
    monthly: list[ProfitRow] = field(default_factory=list)
    by_dimension: dict[str, list[ProfitRow]] = field(default_factory=dict)

    @property
    def rows_excluded(self) -> int:
        return self.rows_missing_cost + self.rows_missing_revenue + self.rows_missing_both

    @property
    def complete_months(self) -> list[ProfitRow]:
        return [month for month in self.monthly if month.complete]


def gross_profit(revenue: Decimal, cost: Decimal) -> Decimal:
    return revenue - cost


def gross_margin_pct(revenue: Decimal, cost: Decimal, places: int = 2) -> Decimal | None:
    """Gross margin as a percentage of sales; ``None`` when sales are zero."""
    return percent(revenue - cost, revenue, places)


def _profit_rows(
    keys: Sequence[object],
    revenues: Sequence[Decimal | None],
    costs: Sequence[Decimal | None],
) -> dict[object, tuple[Decimal, Decimal, int]]:
    revenue_sums = exact_group_sums(keys, revenues)
    cost_sums = exact_group_sums(keys, costs)
    return {key: (revenue_sums[key][0], cost_sums[key][0], revenue_sums[key][1]) for key in revenue_sums}


def summarise_profitability(
    frame: pd.DataFrame,
    *,
    revenues: Sequence[Decimal | None],
    costs: Sequence[Decimal | None],
    date_column: str | None = None,
    dimensions: Sequence[str] = (),
) -> ProfitabilitySummary:
    if len(revenues) != len(frame) or len(costs) != len(frame):
        raise ValueError("revenues and costs must have one entry per row")

    missing_cost = missing_revenue = missing_both = 0
    used_revenues: list[Decimal | None] = []
    used_costs: list[Decimal | None] = []
    excluded: list[Decimal] = []
    for revenue, cost in zip(revenues, costs, strict=True):
        if revenue is not None and cost is not None:
            used_revenues.append(revenue)
            used_costs.append(cost)
            continue
        used_revenues.append(None)
        used_costs.append(None)
        if revenue is None and cost is None:
            missing_both += 1
        elif cost is None:
            missing_cost += 1
            excluded.append(revenue)
        else:
            missing_revenue += 1

    total_revenue = exact_sum(used_revenues)
    total_cost = exact_sum(used_costs)
    total_profit = total_revenue - total_cost
    used_mask = pd.Series([value is not None for value in used_revenues], index=frame.index)

    monthly: list[ProfitRow] = []
    if date_column is not None:
        keys = month_keys(frame[date_column])
        groups = _profit_rows(keys, used_revenues, used_costs)
        groups.pop(None, None)
        partial = incomplete_months(frame[date_column][used_mask])
        if groups:
            for month in month_range(min(groups), max(groups)):
                revenue, cost, rows = groups.get(month, (ZERO, ZERO, 0))
                note = partial.get(month)
                if rows == 0:
                    note = "no records in this month"
                monthly.append(
                    ProfitRow(
                        key=month,
                        revenue=revenue,
                        cost=cost,
                        gross_profit=revenue - cost,
                        margin_pct=gross_margin_pct(revenue, cost),
                        rows=rows,
                        complete=month not in partial,
                        note=note,
                    )
                )

    by_dimension: dict[str, list[ProfitRow]] = {}
    for dimension in dimensions:
        labels = label_values(frame[dimension].tolist())
        rows = [
            ProfitRow(
                key=str(key),
                revenue=revenue,
                cost=cost,
                gross_profit=revenue - cost,
                margin_pct=gross_margin_pct(revenue, cost),
                rows=count,
                profit_share_pct=percent(revenue - cost, total_profit) if total_profit > 0 else None,
            )
            for key, (revenue, cost, count) in _profit_rows(labels, used_revenues, used_costs).items()
        ]
        rows.sort(key=lambda row: (-row.gross_profit, row.key))
        by_dimension[dimension] = rows

    return ProfitabilitySummary(
        rows_total=len(frame),
        rows_used=int(used_mask.sum()),
        rows_missing_cost=missing_cost,
        rows_missing_revenue=missing_revenue,
        rows_missing_both=missing_both,
        excluded_revenue=exact_sum(excluded),
        revenue=total_revenue,
        cost=total_cost,
        gross_profit=total_profit,
        margin_pct=gross_margin_pct(total_revenue, total_cost),
        monthly=monthly,
        by_dimension=by_dimension,
    )
