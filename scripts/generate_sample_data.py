#!/usr/bin/env python3
"""Generate the benchmark sales dataset and its independently calculated answers.

    python scripts/generate_sample_data.py

Writes
    apps/api/tests/benchmark/sales_benchmark.xlsx   the dataset as a messy Excel export
    apps/api/tests/benchmark/sales_benchmark.csv    the same records as CSV
    apps/api/tests/benchmark/expected.json          the known answers
    apps/web/public/samples/sample-sales.xlsx       copy offered in the app as sample data

The business is fictional ("Mopane Grocers", a wholesaler with five branches). The
records are generated from a fixed seed, so the files are the same on every run.

Why the answers can be trusted as a benchmark
---------------------------------------------
``expected.json`` is NOT produced by the analytics engine. Each figure is accumulated
here, row by row, in whole cents using plain integers: no pandas, no floats, no
Decimal, no shared code. The test-suite then requires the engine, which reads the
messy file through the full agent pipeline, to arrive at exactly these figures.

Deliberate data problems (so the cleaning agent has real work to do)
    * two title lines above the header, and a TOTAL line at the bottom
    * exact duplicate invoice lines
    * missing quantities and missing costs
    * dates stored as real dates, as dd/mm/yyyy text and as dd-mm-yyyy text
    * amounts typed as text: "1,950.00" and "$31.20"
    * the same branch spelt four ways
    * "N/A" and a word where a quantity should be
    * returns (negative lines) and two unusually large bulk orders
"""

from __future__ import annotations

import calendar
import csv
import json
import random
import shutil
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

REPO_ROOT = Path(__file__).resolve().parent.parent
BENCHMARK_DIR = REPO_ROOT / "apps" / "api" / "tests" / "benchmark"
SAMPLE_COPY = REPO_ROOT / "apps" / "web" / "public" / "samples" / "sample-sales.xlsx"
SEED = 20261111

HEADERS = [
    "Invoice No",
    "Date",
    "Branch",
    "Product",
    "Category",
    "Quantity",
    "Unit Price",
    "Sales Amount",
    "Cost of Sales",
]

# (year, month, seasonal weight): twelve complete months, November 2025 to October 2026
MONTHS = [
    (2025, 11, 1.00),
    (2025, 12, 1.36),
    (2026, 1, 0.80),
    (2026, 2, 0.84),
    (2026, 3, 0.95),
    (2026, 4, 1.04),
    (2026, 5, 0.98),
    (2026, 6, 0.90),
    (2026, 7, 0.95),
    (2026, 8, 1.03),
    (2026, 9, 1.01),
    (2026, 10, 1.07),
]
INVOICES_PER_MONTH = 150

BRANCHES = [("Harare CBD", 34), ("Bulawayo", 24), ("Mutare", 16), ("Gweru", 14), ("Masvingo", 12)]

# name, category, unit price (cents), unit cost (cents), popularity
PRODUCTS = [
    ("Mealie Meal 10kg", "Groceries", 650, 572, 16),
    ("Cooking Oil 2L", "Groceries", 420, 340, 13),
    ("Sugar 2kg", "Groceries", 260, 208, 11),
    ("Rice 2kg", "Groceries", 290, 220, 9),
    ("Bread Flour 2kg", "Groceries", 240, 192, 8),
    ("Sugar Beans 500g", "Groceries", 150, 105, 6),
    ("Kapenta 250g", "Groceries", 220, 150, 4),
    ("Salt 1kg", "Groceries", 60, 36, 5),
    ("Orange Cordial 2L", "Beverages", 310, 205, 7),
    ("Tea Leaves 250g", "Beverages", 180, 110, 5),
    ("Maheu 500ml", "Beverages", 80, 52, 6),
    ("Washing Powder 1kg", "Household", 340, 190, 7),
    ("Laundry Soap Bar", "Household", 120, 70, 8),
    ("Candles 6-pack", "Household", 100, 108, 4),  # sold below cost: a loss-maker to find
    ("Matches 10-pack", "Household", 50, 28, 4),
    ("Petroleum Jelly 250ml", "Personal Care", 190, 115, 5),
    ("Toothpaste 100ml", "Personal Care", 140, 90, 5),
    ("Bath Soap 150g", "Personal Care", 90, 55, 6),
]
# Supplier costs creep up during the year on four staples; only one selling price follows.
# (product: (index of the first month at the higher cost, monthly rise in tenths of a percent))
COST_CREEP = {"Cooking Oil 2L": (3, 22), "Sugar 2kg": (5, 14), "Mealie Meal 10kg": (4, 9), "Rice 2kg": (6, 12)}
PRICE_RISE_FROM = (2026, 8)  # mealie meal's selling price rises 3% from August 2026
PRICE_RISE_PRODUCTS = {"Mealie Meal 10kg"}


def half_up_div(numerator: int, denominator: int) -> int:
    """Integer division rounding half away from zero, without floats."""
    sign = -1 if (numerator < 0) != (denominator < 0) else 1
    numerator, denominator = abs(numerator), abs(denominator)
    return sign * ((2 * numerator + denominator) // (2 * denominator))


def unit_price(name: str, base: int, year: int, month: int) -> int:
    if name in PRICE_RISE_PRODUCTS and (year, month) >= PRICE_RISE_FROM:
        return half_up_div(base * 103, 100)
    return base


def unit_cost(name: str, base: int, month_index: int) -> int:
    """Supplier cost per unit in a given month."""
    start, step = COST_CREEP.get(name, (None, 0))
    if start is None or month_index < start:
        return base
    return half_up_div(base * (1000 + step * (month_index - start + 1)), 1000)


def cents(value: int) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}{abs(value) // 100}.{abs(value) % 100:02d}"


@dataclass
class Line:
    invoice: str
    day: date
    branch: str  # the correct spelling
    product: str
    category: str
    quantity: int | None
    price: int
    amount: int
    cost: int | None
    branch_written: str = ""
    date_style: str = "native"  # native | slash | dash
    amount_style: str = "number"  # number | comma | dollar
    quantity_written: str | None = None  # overrides the quantity cell with text
    tags: set[str] = field(default_factory=set)

    def date_cell(self, native: bool) -> object:
        if self.date_style == "slash":
            return self.day.strftime("%d/%m/%Y")
        if self.date_style == "dash":
            return self.day.strftime("%d-%m-%Y")
        return self.day if native else self.day.isoformat()

    def amount_cell(self, native: bool) -> object:
        if self.amount_style == "comma":
            return f"{self.amount // 100:,}.{self.amount % 100:02d}"
        if self.amount_style == "dollar":
            return f"${cents(self.amount)}"
        return self.amount / 100 if native else cents(self.amount)

    def quantity_cell(self) -> object:
        return self.quantity_written if self.quantity_written is not None else self.quantity

    def cells(self, native: bool) -> list[object]:
        number = (lambda v: v / 100) if native else cents
        return [
            self.invoice, self.date_cell(native), self.branch_written or self.branch, self.product, self.category,
            self.quantity_cell(), number(self.price), self.amount_cell(native),
            None if self.cost is None else number(self.cost),
        ]  # fmt: skip


def build_lines() -> list[Line]:
    rng = random.Random(SEED)
    lines: list[Line] = []
    invoice_number = 100_000
    for month_index, (year, month, weight) in enumerate(MONTHS):
        days_in_month = calendar.monthrange(year, month)[1]
        count = round(INVOICES_PER_MONTH * weight)
        days = sorted([1, days_in_month] + [rng.randint(1, days_in_month) for _ in range(count - 2)])
        for day in days:
            invoice_number += 1
            branch = rng.choices([b for b, _ in BRANCHES], weights=[w for _, w in BRANCHES])[0]
            line_count = rng.choices([1, 2, 3, 4], weights=[35, 35, 20, 10])[0]
            chosen: list[tuple] = []
            while len(chosen) < line_count:  # distinct products per invoice: no accidental duplicates
                product = rng.choices(PRODUCTS, weights=[p[4] for p in PRODUCTS])[0]
                if product not in chosen:
                    chosen.append(product)
            for name, category, base_price, base_cost, _ in chosen:
                quantity = rng.choice([1, 2, 2, 3, 4, 5, 6, 6, 8, 10, 12, 12, 18, 24])
                price = unit_price(name, base_price, year, month)
                cost = unit_cost(name, base_cost, month_index)
                lines.append(Line(f"INV-{invoice_number}", date(year, month, day), branch, name, category,
                                  quantity, price, quantity * price, quantity * cost))  # fmt: skip

    # ---- deliberate problems, each on its own set of otherwise ordinary lines ----
    order = list(range(len(lines)))
    rng.shuffle(order)
    take = iter(order)

    def pick(n: int, condition=lambda line: True) -> list[Line]:
        chosen = []
        while len(chosen) < n:
            line = lines[next(take)]
            if not line.tags and condition(line):
                chosen.append(line)
        return chosen

    for line in pick(2, lambda line: line.product == "Mealie Meal 10kg"):  # bulk orders, typed with a thousands comma
        unit_cost_paid = line.cost // line.quantity
        line.quantity = 300
        line.amount, line.cost = line.quantity * line.price, line.quantity * unit_cost_paid
        line.amount_style = "comma"
        line.tags.update({"bulk", "text_amount"})

    for line in pick(6):  # returns / credit notes
        line.quantity, line.amount, line.cost = -line.quantity, -line.amount, -line.cost
        line.tags.add("return")
    for line in pick(9):
        line.quantity = None
        line.tags.add("missing_quantity")
    for line in pick(3):
        line.quantity, line.quantity_written = None, "N/A"
        line.tags.add("placeholder_quantity")
    for line in pick(1):
        line.quantity, line.quantity_written = None, "ten"
        line.tags.add("invalid_quantity")
    for line in pick(14):
        line.cost = None
        line.tags.add("missing_cost")
    for line in pick(60):
        line.date_style = "slash"
        line.tags.add("text_date")
    for line in pick(25):
        line.date_style = "dash"
        line.tags.add("text_date")
    for line in pick(20):
        line.amount_style = "dollar"
        line.tags.add("text_amount")
    for spelling, n, branch in (("harare cbd", 14, "Harare CBD"), ("HARARE CBD", 9, "Harare CBD"),
                                ("Harare CBD ", 11, "Harare CBD"), ("Bulawayo ", 6, "Bulawayo")):  # fmt: skip
        for line in pick(n, lambda line, b=branch: line.branch == b):
            line.branch_written = spelling
            line.tags.add("branch_spelling")

    for original in pick(12):  # exact duplicates, inserted straight after the line they repeat
        duplicate = Line(**{k: (set(v) if isinstance(v, set) else v) for k, v in original.__dict__.items()})
        duplicate.tags = {"duplicate"}
        original.tags.add("duplicated")
        lines.insert(lines.index(original) + 1, duplicate)
    return lines


def expected_answers(lines: list[Line]) -> dict:
    """The known answers, accumulated in integer cents."""

    def add(table: dict[str, int], key: str, value: int) -> None:
        table[key] = table.get(key, 0) + value

    total = units = 0
    by_month: dict[str, int] = {}
    by_product: dict[str, int] = {}
    by_branch: dict[str, int] = {}
    by_category: dict[str, int] = {}
    profit_rows = profit_revenue = profit_cost = excluded_revenue = 0
    product_revenue: dict[str, int] = {}
    product_cost: dict[str, int] = {}
    month_revenue: dict[str, int] = {}
    month_cost: dict[str, int] = {}
    for line in lines:
        month = f"{line.day.year:04d}-{line.day.month:02d}"
        total += line.amount
        units += line.quantity or 0
        add(by_month, month, line.amount)
        add(by_product, line.product, line.amount)
        add(by_branch, line.branch, line.amount)
        add(by_category, line.category, line.amount)
        if line.cost is None:
            excluded_revenue += line.amount
            continue
        profit_rows += 1
        profit_revenue += line.amount
        profit_cost += line.cost
        add(product_revenue, line.product, line.amount)
        add(product_cost, line.product, line.cost)
        add(month_revenue, month, line.amount)
        add(month_cost, month, line.cost)

    def margin(revenue: int, cost: int) -> str:
        return cents(half_up_div((revenue - cost) * 10_000, revenue))  # percent to two decimals

    def tagged(tag: str) -> int:
        return sum(1 for line in lines if tag in line.tags)

    return {
        "about": "Known answers for the benchmark dataset, calculated in integer cents by "
                 "scripts/generate_sample_data.py, independently of the analytics engine.",
        "rows": len(lines),
        "summary_rows": 1,
        "period": {"start": min(line.day for line in lines).isoformat(),
                   "end": max(line.day for line in lines).isoformat()},
        "sales": {
            "total": cents(total),
            "invoices": len({line.invoice for line in lines}),
            "units": units,
            "by_month": {k: cents(v) for k, v in sorted(by_month.items())},
            "by_product": {k: cents(v) for k, v in sorted(by_product.items())},
            "by_branch": {k: cents(v) for k, v in sorted(by_branch.items())},
            "by_category": {k: cents(v) for k, v in sorted(by_category.items())},
        },
        "profitability": {
            "rows_used": profit_rows,
            "rows_missing_cost": tagged("missing_cost"),
            "excluded_revenue": cents(excluded_revenue),
            "revenue": cents(profit_revenue),
            "cost": cents(profit_cost),
            "gross_profit": cents(profit_revenue - profit_cost),
            "margin_pct": margin(profit_revenue, profit_cost),
            "by_product": {
                name: {"revenue": cents(product_revenue[name]), "cost": cents(product_cost[name]),
                       "gross_profit": cents(product_revenue[name] - product_cost[name]),
                       "margin_pct": margin(product_revenue[name], product_cost[name])}
                for name in sorted(product_revenue)
            },
            "by_month": {
                month: {"gross_profit": cents(month_revenue[month] - month_cost[month]),
                        "margin_pct": margin(month_revenue[month], month_cost[month])}
                for month in sorted(month_revenue)
            },
        },
        "quality": {
            "duplicate_rows": tagged("duplicate"),
            "duplicate_sales": cents(sum(line.amount for line in lines if "duplicate" in line.tags)),
            "missing_quantity": tagged("missing_quantity") + tagged("placeholder_quantity") + tagged("invalid_quantity"),
            "invalid_quantity": tagged("invalid_quantity"),
            "missing_cost": tagged("missing_cost"),
            "text_dates": tagged("text_date"),
            "text_amounts": tagged("text_amount"),
            "branch_case_variants": sum(1 for line in lines if line.branch_written.strip() not in ("", line.branch)),
            "branch_stray_spaces": sum(1 for line in lines if line.branch_written.endswith(" ")),
            "negative_lines": tagged("return"),
            "bulk_orders": tagged("bulk"),
        },
    }  # fmt: skip


def write_xlsx(lines: list[Line], path: Path) -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sales"
    sheet["A1"] = "Mopane Grocers (Pvt) Ltd - Sales Register"
    sheet["A1"].font = Font(bold=True, size=14)
    sheet["A2"] = "Sample data for demonstration. All branches, November 2025 to October 2026. Amounts in USD."
    sheet.append([])
    sheet.append(HEADERS)
    for cell in sheet[4]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="0F5C43")
        cell.alignment = Alignment(horizontal="center")
    for line in lines:
        sheet.append(line.cells(native=True))
        row = sheet.max_row
        if line.date_style == "native":
            sheet.cell(row, 2).number_format = "dd/mm/yyyy"
        for column in (7, 8, 9):
            sheet.cell(row, column).number_format = "#,##0.00"
    total_row = ["TOTAL", None, None, None, None, None, None,
                 sum(line.amount for line in lines) / 100,
                 sum(line.cost for line in lines if line.cost is not None) / 100]  # fmt: skip
    sheet.append(total_row)
    for cell in sheet[sheet.max_row]:
        cell.font = Font(bold=True)
        cell.number_format = "#,##0.00"
    for letter, width in zip("ABCDEFGHI", (14, 12, 14, 24, 15, 10, 11, 14, 14), strict=True):
        sheet.column_dimensions[letter].width = width
    sheet.freeze_panes = "A5"

    notes = workbook.create_sheet("About")
    notes["A1"] = "This workbook is fictional sample data generated by TATMAQ Intelligence."
    notes["A2"] = (
        "It deliberately contains duplicates, gaps and inconsistent formatting for the cleaning agent to find."
    )
    workbook.save(path)


def write_csv(lines: list[Line], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(HEADERS)
        for line in lines:
            writer.writerow(["" if cell is None else cell for cell in line.cells(native=False)])
        writer.writerow(["TOTAL", "", "", "", "", "", "", cents(sum(line.amount for line in lines)),
                         cents(sum(line.cost for line in lines if line.cost is not None))])  # fmt: skip


def main() -> None:
    lines = build_lines()
    BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
    SAMPLE_COPY.parent.mkdir(parents=True, exist_ok=True)
    write_xlsx(lines, BENCHMARK_DIR / "sales_benchmark.xlsx")
    write_csv(lines, BENCHMARK_DIR / "sales_benchmark.csv")
    answers = expected_answers(lines)
    (BENCHMARK_DIR / "expected.json").write_text(json.dumps(answers, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(BENCHMARK_DIR / "sales_benchmark.xlsx", SAMPLE_COPY)
    print(f"{answers['rows']:,} invoice lines, {answers['sales']['invoices']:,} invoices")
    print(f"total sales  USD {answers['sales']['total']}")
    print(
        f"gross profit USD {answers['profitability']['gross_profit']}  (margin {answers['profitability']['margin_pct']}%)"
    )
    print("quality:", answers["quality"])


if __name__ == "__main__":
    main()
