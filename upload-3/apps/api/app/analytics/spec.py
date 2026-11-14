"""The analysis specification: *what* to compute, never *how* and never the answer.

This is the boundary between understanding and calculating (specification Part H). A
planner, whether an AI model or the built-in rules, may only produce an
:class:`AnalysisSpec`. It is a closed vocabulary of operations over named columns, so
there is no way to express arbitrary code, a database query or a figure in it. The
spec is validated against the dataset's real columns before anything runs.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ColumnKind = Literal["number", "date", "text", "empty"]

MAX_DIMENSIONS = 4
MAX_STAT_COLUMNS = 12
MAX_PREDICTORS = 8
MAX_OPERATIONS = 8


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Measure(_Strict):
    """An amount per row: one column, or the product of two (quantity x unit price)."""

    column: str | None = None
    multiply: tuple[str, str] | None = None

    @model_validator(mode="after")
    def _one_source(self) -> Measure:
        if (self.column is None) == (self.multiply is None):
            raise ValueError("give either 'column' or 'multiply', not both")
        return self

    @property
    def columns(self) -> tuple[str, ...]:
        return (self.column,) if self.column is not None else tuple(self.multiply or ())

    @property
    def label(self) -> str:
        return self.column if self.column is not None else " x ".join(self.multiply or ())


class SalesOverview(_Strict):
    type: Literal["sales_overview"] = "sales_overview"
    revenue: Measure
    date: str | None = None
    dimensions: tuple[str, ...] = Field(default=(), max_length=MAX_DIMENSIONS)
    quantity: str | None = None
    document: str | None = None


class Profitability(_Strict):
    type: Literal["profitability"] = "profitability"
    revenue: Measure
    cost: Measure
    date: str | None = None
    dimensions: tuple[str, ...] = Field(default=(), max_length=MAX_DIMENSIONS)


class DescriptiveStatistics(_Strict):
    type: Literal["descriptive_statistics"] = "descriptive_statistics"
    columns: tuple[str, ...] = Field(min_length=1, max_length=MAX_STAT_COLUMNS)


class Correlation(_Strict):
    type: Literal["correlation"] = "correlation"
    columns: tuple[str, ...] = Field(min_length=2, max_length=MAX_STAT_COLUMNS)
    method: Literal["pearson", "spearman"] = "pearson"


class Regression(_Strict):
    type: Literal["regression"] = "regression"
    target: str
    predictors: tuple[str, ...] = Field(min_length=1, max_length=MAX_PREDICTORS)


class Trend(_Strict):
    type: Literal["trend"] = "trend"
    measure: str
    date: str


class Outliers(_Strict):
    type: Literal["outliers"] = "outliers"
    column: str


class DataQuality(_Strict):
    type: Literal["data_quality"] = "data_quality"


Operation = Annotated[
    SalesOverview | Profitability | DescriptiveStatistics | Correlation | Regression | Trend | Outliers | DataQuality,
    Field(discriminator="type"),
]

OPERATION_TITLES = {
    "sales_overview": "Sales performance",
    "profitability": "Profitability",
    "descriptive_statistics": "Descriptive statistics",
    "correlation": "Correlation",
    "regression": "Regression",
    "trend": "Trend",
    "outliers": "Outliers",
    "data_quality": "Data quality",
}


class AnalysisSpec(_Strict):
    objective: str = Field(min_length=1, max_length=300)
    report_title: str = Field(min_length=1, max_length=120)
    operations: tuple[Operation, ...] = Field(min_length=1, max_length=MAX_OPERATIONS)
    currency_column: str | None = None

    @model_validator(mode="after")
    def _no_repeats(self) -> AnalysisSpec:
        kinds = [operation.type for operation in self.operations]
        repeated = {
            kind
            for kind in kinds
            if kinds.count(kind) > 1 and kind in ("sales_overview", "profitability", "data_quality")
        }
        if repeated:
            raise ValueError(f"operation(s) listed more than once: {', '.join(sorted(repeated))}")
        return self


def required_columns(operation: Operation) -> dict[str, ColumnKind]:
    """Every column an operation reads, with the type it must have."""
    needs: dict[str, ColumnKind] = {}
    if isinstance(operation, SalesOverview | Profitability):
        for name in operation.revenue.columns:
            needs[name] = "number"
        if isinstance(operation, Profitability):
            for name in operation.cost.columns:
                needs[name] = "number"
        if operation.date:
            needs[operation.date] = "date"
        for name in operation.dimensions:
            needs[name] = "text"
        if isinstance(operation, SalesOverview) and operation.quantity:
            needs[operation.quantity] = "number"
    elif isinstance(operation, DescriptiveStatistics | Correlation):
        needs.update(dict.fromkeys(operation.columns, "number"))
    elif isinstance(operation, Regression):
        needs.update(dict.fromkeys((operation.target, *operation.predictors), "number"))
    elif isinstance(operation, Trend):
        needs[operation.measure] = "number"
        needs[operation.date] = "date"
    elif isinstance(operation, Outliers):
        needs[operation.column] = "number"
    return needs


def spec_problems(spec: AnalysisSpec, column_kinds: Mapping[str, ColumnKind]) -> list[str]:
    """Reasons the spec cannot run on a dataset with these columns. Empty means it can."""
    problems: list[str] = []
    for operation in spec.operations:
        title = OPERATION_TITLES[operation.type]
        for name, needed in required_columns(operation).items():
            actual = column_kinds.get(name)
            if actual is None:
                problems.append(f"{title}: there is no column named '{name}'.")
            elif actual != needed:
                problems.append(f"{title}: '{name}' holds {actual} values but {needed} values are needed.")
        if isinstance(operation, SalesOverview) and operation.document and operation.document not in column_kinds:
            problems.append(f"{title}: there is no column named '{operation.document}'.")
        if isinstance(operation, Regression) and operation.target in operation.predictors:
            problems.append(f"{title}: '{operation.target}' cannot predict itself.")
    if spec.currency_column and spec.currency_column not in column_kinds:
        problems.append(f"There is no column named '{spec.currency_column}'.")
    return problems
