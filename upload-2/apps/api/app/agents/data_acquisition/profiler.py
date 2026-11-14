"""Working out what each column is: its type, and its role in the business.

Type and role are decided together. A header reading "Invoice No" says the column is
an identifier, so its digits are kept as text; "Sales Amount" says the column is
money, so a few badly typed cells are flagged rather than the whole column being
treated as text. The header only ever *suggests*: a column called "Amount" that is
full of words does not become a number.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from analytics_core.cleaning import NUMERIC_NULL_TOKENS, TEXT_NULL_TOKENS, ColumnType, infer_column_type, tidy
from analytics_core.cleaning.dates import excel_serial_to_datetime, parse_date_column
from analytics_core.cleaning.numbers import parse_number

from .raw_table import RawTable

MEASURE_ROLES = frozenset({"revenue", "cost", "unit_cost", "unit_price", "quantity", "measure"})
CATEGORY_ROLES = frozenset({"product", "category", "customer", "region", "currency", "salesperson", "dimension"})
DIMENSION_ROLES = ("product", "category", "region", "customer", "salesperson")
MAX_DIMENSION_VALUES = 200


@dataclass(frozen=True)
class RoleRule:
    role: str
    kind: str  # the type a column must actually have to take this role
    synonyms: tuple[str, ...]  # most specific first: position is the preference between two candidates
    exclude: str | None = None

    def rank(self, normalised_name: str) -> int | None:
        if self.exclude and re.search(self.exclude, normalised_name):
            return None
        for position, synonym in enumerate(self.synonyms):
            if re.search(rf"\b{re.escape(synonym)}\b", normalised_name):
                return position
        return None


# Order matters: "Cost of Sales" must be claimed as a cost before "sales" can make it revenue.
RULES: tuple[RoleRule, ...] = (
    RoleRule("currency", "text", ("currency", "ccy", "curr")),
    RoleRule("date", "date", ("invoice date", "transaction date", "sale date", "sales date", "order date",
                              "posting date", "doc date", "date", "dated", "period", "month", "day",
                              "timestamp", "time")),
    RoleRule("unit_cost", "number", ("unit cost", "cost price", "cost per unit", "cost each", "buying price",
                                     "purchase price", "landed cost")),
    RoleRule("cost", "number", ("cost of sales", "cost of goods sold", "cost of goods", "cogs", "total cost",
                                "line cost", "cost amount", "cost"), exclude=r"\b(centre|center|code)\b"),
    RoleRule("unit_price", "number", ("unit price", "selling price", "sell price", "sales price", "price per unit",
                                      "price each", "price", "rate")),
    RoleRule("quantity", "number", ("quantity sold", "qty sold", "units sold", "quantity", "qty", "units",
                                    "volume", "pieces", "pcs")),
    RoleRule("revenue", "number", ("net sales", "sales amount", "sales value", "total sales", "revenue", "turnover",
                                   "line total", "invoice total", "invoice amount", "total amount", "net amount",
                                   "sales", "amount", "gross amount", "total", "value", "income"),
             exclude=r"\b(vat|tax|discount|cost|profit|margin|balance|paid|due|outstanding|qty|quantity|units|"
                     r"price|rate|budget|target|rep|person|agent|man|channel|region|type|date|id|no|number|code)\b"),
    RoleRule("identifier", "text", ("invoice no", "invoice number", "invoice num", "invoice id", "invoice",
                                    "receipt no", "receipt number", "receipt", "order no", "order number", "order id",
                                    "transaction id", "transaction no", "txn id", "document no", "doc no",
                                    "reference", "ref no", "ref", "voucher", "account number", "phone", "id",
                                    "no", "number")),
    RoleRule("product", "text", ("product name", "item name", "product description", "item description", "product",
                                 "item", "description", "stock item", "sku", "product code", "item code", "article")),
    RoleRule("category", "text", ("product category", "category", "product group", "department", "dept",
                                  "product type", "class", "group", "segment", "family", "type")),
    RoleRule("customer", "text", ("customer name", "client name", "customer", "client", "buyer", "debtor",
                                  "account name", "account")),
    RoleRule("region", "text", ("branch", "region", "store", "shop", "outlet", "location", "city", "town",
                                "province", "area", "territory", "depot", "site", "country")),
    RoleRule("salesperson", "text", ("sales rep", "salesperson", "sales person", "salesman", "sales agent", "rep",
                                     "cashier", "teller", "agent")),
)  # fmt: skip

#: Numbers that label a period rather than measure something: grouped by, never summed.
_PERIOD_PART = re.compile(r"\b(year|yr|quarter|qtr|week|wk)\b")


def normalise_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


@dataclass
class ColumnProfile:
    name: str
    position: int
    ctype: ColumnType
    role: str
    rank: int = 0
    non_null: int = 0
    null_count: int = 0
    distinct_count: int = 0
    examples: list[str] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def kind(self) -> str:
        return self.ctype.kind

    def to_json(self) -> dict[str, Any]:
        return {
            "name": self.name, "position": self.position, "kind": self.kind, "role": self.role,
            "non_null": self.non_null, "null_count": self.null_count, "distinct_count": self.distinct_count,
            "examples": self.examples, "stats": self.stats, "notes": self.notes,
        }  # fmt: skip


@dataclass
class TableProfile:
    columns: list[ColumnProfile]

    @property
    def roles(self) -> dict[str, str]:
        """role -> column name, for roles held by exactly one column."""
        return {column.role: column.name for column in self.columns
                if column.role not in ("measure", "dimension", "text", "empty", "date_other")}  # fmt: skip

    @property
    def types(self) -> dict[str, ColumnType]:
        return {column.name: column.ctype for column in self.columns}

    @property
    def category_columns(self) -> list[str]:
        return [c.name for c in self.columns if c.kind == "text" and c.role in CATEGORY_ROLES]

    @property
    def measure_columns(self) -> list[str]:
        return [c.name for c in self.columns if c.kind == "number" and c.role in MEASURE_ROLES]


def _role_and_type(name: str, values: list[object], default_day_first: bool) -> tuple[str | None, int, ColumnType]:
    normalised = normalise_name(name)
    for rule in RULES:
        rank = rule.rank(normalised)
        if rank is None:
            continue
        ctype = infer_column_type(values, expect=rule.kind, default_day_first=default_day_first)  # type: ignore[arg-type]
        if ctype.kind == "empty":
            return None, 0, ctype
        if ctype.kind == rule.kind:
            return rule.role, rank, ctype
    if _PERIOD_PART.search(normalised):
        return "dimension", 0, infer_column_type(values, expect="text")
    return None, 0, infer_column_type(values, default_day_first=default_day_first)


def _describe(column: ColumnProfile, values: list[object], default_day_first: bool) -> None:
    null_tokens = TEXT_NULL_TOKENS if column.kind == "text" else NUMERIC_NULL_TOKENS
    present = [tidy(v) for v in values if isinstance(v, str) and v.strip().casefold() not in null_tokens]
    counts = Counter(present)
    column.non_null, column.null_count = len(present), len(values) - len(present)
    column.distinct_count = len(counts)
    column.examples = [text[:60] for text in list(counts)[:5]]

    if column.kind == "number":
        parsed = {text: parse_number(text, column.ctype.decimal_separator) for text in counts}
        numbers = [(float(value), counts[text]) for text, value in parsed.items() if value is not None]
        if numbers:
            total = sum(count for _, count in numbers)
            column.stats = {
                "min": min(value for value, _ in numbers), "max": max(value for value, _ in numbers),
                "mean": sum(value * count for value, count in numbers) / total,
                "invalid": column.non_null - total,
            }  # fmt: skip
        if column.ctype.decimal_separator == ",":
            column.notes.append("Decimals are written with a comma (12,5).")
        if column.ctype.percent:
            column.notes.append("Values are percentages.")
    elif column.kind == "date":
        distinct = list(counts)
        if column.ctype.excel_serial_dates:
            stamps = [
                excel_serial_to_datetime(float(n)) if (n := parse_number(t)) is not None else None for t in distinct
            ]
            column.notes.append("Stored as spreadsheet day numbers; converted to dates.")
        else:
            stamps = parse_date_column(distinct, default_day_first=default_day_first).values
        valid = [stamp for stamp in stamps if stamp is not None]
        if valid:
            column.stats = {
                "min": min(valid).date().isoformat(), "max": max(valid).date().isoformat(),
                "invalid": sum(counts[t] for t, stamp in zip(distinct, stamps, strict=True) if stamp is None),
            }  # fmt: skip
    elif column.kind == "text":
        column.stats = {"top_values": [{"value": value[:60], "count": count} for value, count in counts.most_common(5)]}


def profile_table(table: RawTable, *, default_day_first: bool = True) -> TableProfile:
    columns: list[ColumnProfile] = []
    for position, name in enumerate(table.columns):
        values = table.frame[name].tolist()
        role, rank, ctype = _role_and_type(name, values, default_day_first)
        column = ColumnProfile(name=name, position=position, ctype=ctype, role=role or "", rank=rank)
        _describe(column, values, default_day_first)
        columns.append(column)

    # A role such as "revenue" belongs to one column: the best-named candidate keeps it.
    claimed: dict[str, ColumnProfile] = {}
    for column in columns:
        if not column.role or column.role == "dimension":
            continue
        holder = claimed.get(column.role)
        if holder is None or column.rank < holder.rank:
            if holder is not None:
                holder.role = ""
            claimed[column.role] = column
        else:
            column.role = ""

    has_date = "date" in claimed
    for column in columns:
        if column.role:
            continue
        if column.kind == "number":
            column.role = "measure"
        elif column.kind == "date":
            column.role, has_date = ("date_other", has_date) if has_date else ("date", True)
        elif column.kind == "text":
            few = column.distinct_count <= MAX_DIMENSION_VALUES
            repeats = column.non_null < 20 or column.distinct_count <= 0.5 * column.non_null
            column.role = "dimension" if few and repeats else "text"
        else:
            column.role = "empty"
    return TableProfile(columns)
