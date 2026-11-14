"""Sales totals by period and by business dimension, in exact decimal arithmetic."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import pandas as pd

from .money import ZERO, divide, exact_group_sums, exact_sum, percent
from .periods import incomplete_months, label_values, month_keys, month_range


@dataclass(frozen=True)
class MonthlySales:
    month: str  # YYYY-MM
    revenue: Decimal
    rows: int
    complete: bool
    note: str | None = None


@dataclass(frozen=True)
class GroupSales:
    key: str
    revenue: Decimal
    rows: int
    share_pct: Decimal | None


@dataclass(frozen=True)
class SalesSummary:
    rows_total: int
    rows_used: int
    rows_missing_amount: int
    total_revenue: Decimal
    average_per_row: Decimal | None
    negative_rows: int
    negative_total: Decimal
    period_start: date | None
    period_end: date | None
    rows_missing_date: int
    undated_revenue: Decimal
    monthly: list[MonthlySales] = field(default_factory=list)
    by_dimension: dict[str, list[GroupSales]] = field(default_factory=dict)
    units: Decimal | None = None
    documents: int | None = None

    @property
    def complete_months(self) -> list[MonthlySales]:
        return [month for month in self.monthly if month.complete]


def summarise_sales(
    frame: pd.DataFrame,
    *,
    amounts: Sequence[Decimal | None],
    date_column: str | None = None,
    dimensions: Sequence[str] = (),
    quantities: Sequence[Decimal | None] | None = None,
    document_column: str | None = None,
) -> SalesSummary:
    """Summarise sales.

    ``amounts`` holds one sales value per row of ``frame`` (``None`` where the value is
    missing). Rows without an amount are counted and left out; they are never treated
    as zero-value sales.
    """
    if len(amounts) != len(frame):
        raise ValueError("amounts must have one entry per row")

    rows_total = len(frame)
    used = [amount is not None for amount in amounts]
    rows_used = sum(used)
    total = exact_sum(amounts)
    negatives = [amount for amount in amounts if amount is not None and amount < 0]

    monthly: list[MonthlySales] = []
    period_start = period_end = None
    rows_missing_date = 0
    undated = ZERO
    if date_column is not None:
        keys = month_keys(frame[date_column])
        rows_missing_date = sum(1 for key, has in zip(keys, used, strict=True) if has and key is None)
        undated = exact_sum(a for a, key in zip(amounts, keys, strict=True) if key is None)
        sums = exact_group_sums(keys, amounts)
        sums.pop(None, None)
        dated = frame[date_column][pd.Series(used, index=frame.index)]
        partial = incomplete_months(dated)
        if sums:
            for month in month_range(min(sums), max(sums)):
                revenue, rows = sums.get(month, (ZERO, 0))
                note = partial.get(month)
                if rows == 0:
                    note = "no records in this month"
                monthly.append(
                    MonthlySales(month=month, revenue=revenue, rows=rows, complete=month not in partial, note=note)
                )
            stamps = pd.to_datetime(dated).dropna()
            if not stamps.empty:
                period_start, period_end = stamps.min().date(), stamps.max().date()

    by_dimension: dict[str, list[GroupSales]] = {}
    for dimension in dimensions:
        labels = label_values(frame[dimension].tolist())
        groups = exact_group_sums(labels, amounts)
        rows = [
            GroupSales(key=str(key), revenue=revenue, rows=count, share_pct=percent(revenue, total))
            for key, (revenue, count) in groups.items()
        ]
        rows.sort(key=lambda row: (-row.revenue, row.key))
        by_dimension[dimension] = rows

    units = None
    if quantities is not None:
        units = exact_sum(q for q, has in zip(quantities, used, strict=True) if has)

    documents = None
    if document_column is not None:
        documents = int(frame[document_column][pd.Series(used, index=frame.index)].nunique(dropna=True))

    return SalesSummary(
        rows_total=rows_total,
        rows_used=rows_used,
        rows_missing_amount=rows_total - rows_used,
        total_revenue=total,
        average_per_row=divide(total, Decimal(rows_used)) if rows_used else None,
        negative_rows=len(negatives),
        negative_total=exact_sum(negatives),
        period_start=period_start,
        period_end=period_end,
        rows_missing_date=rows_missing_date,
        undated_revenue=undated,
        monthly=monthly,
        by_dimension=by_dimension,
        units=units,
        documents=documents,
    )
