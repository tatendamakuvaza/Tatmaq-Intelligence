"""The Excel report: every table as real numbers a reader can re-add, plus native charts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from ...analytics.formatting import month_label
from .report_model import KIND_LABELS, ReportModel, evidence_line

BRAND, PANEL, MUTED = "1D40B8", "F4F2FD", "5D6685"
HEAD_FONT = Font(bold=True, color="FFFFFF")
HEAD_FILL = PatternFill("solid", fgColor=BRAND)
THIN = Side(style="thin", color="E6E3F4")
NUMBER_FORMATS = {"money": "#,##0.00", "percent": '0.00"%"', "integer": "#,##0", "number": "#,##0.00",
                  "number4": "0.0000"}  # fmt: skip
_BAD_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")


def write(cell: Any, value: Any) -> None:
    """Write a value so that customer text is always stored as text.

    A product named ``=HYPERLINK(...)`` would otherwise become a live formula in the
    reader's spreadsheet (formula injection). Forcing the string type prevents that.
    """
    if isinstance(value, str):
        cell.value = ILLEGAL_CHARACTERS_RE.sub("", value)
        cell.data_type = "s"
    else:
        cell.value = value


def typed(value: Any, kind: str) -> Any:
    """A table value as the type Excel should hold: numbers as numbers, the rest as text."""
    if value is None or value == "":
        return None
    if kind in NUMBER_FORMATS:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value)
        return int(number) if kind == "integer" and number.is_integer() else number
    if kind == "month":
        return month_label(str(value))
    return str(value)


def _sheet(workbook: Workbook, title: str) -> Worksheet:
    base = _BAD_SHEET_CHARS.sub("", title).strip()[:31] or "Sheet"
    name, suffix = base, 2
    while name in workbook.sheetnames:
        name = f"{base[: 31 - len(str(suffix)) - 1]} {suffix}"
        suffix += 1
    return workbook.create_sheet(name)


def _header(sheet: Worksheet, row: int, labels: list[str]) -> None:
    for column, label in enumerate(labels, start=1):
        cell = sheet.cell(row, column)
        write(cell, label)
        cell.font, cell.fill = HEAD_FONT, HEAD_FILL
        cell.alignment = Alignment(vertical="center", wrap_text=True)
        cell.border = Border(bottom=THIN)


def _fit(sheet: Worksheet, widths: dict[int, float] | None = None, maximum: float = 60) -> None:
    measured: dict[int, float] = {}
    for row in sheet.iter_rows():
        for cell in row:
            if cell.value is not None:
                length = len(f"{cell.value:,.2f}") if isinstance(cell.value, float) else len(str(cell.value))
                measured[cell.column] = max(measured.get(cell.column, 0), length)
    for column, length in measured.items():
        sheet.column_dimensions[get_column_letter(column)].width = (widths or {}).get(
            column, min(max(length + 2, 9), maximum)
        )


def _text_block(sheet: Worksheet, row: int, heading: str, items: list[str]) -> int:
    sheet.cell(row, 1).font = Font(bold=True, size=12, color=BRAND)
    write(sheet.cell(row, 1), heading)
    for number, item in enumerate(items, start=1):
        row += 1
        write(sheet.cell(row, 1), number)
        write(sheet.cell(row, 2), item)
        sheet.cell(row, 2).alignment = Alignment(wrap_text=True, vertical="top")
        sheet.cell(row, 1).alignment = Alignment(vertical="top", horizontal="right")
    return row + 2


def _summary_sheet(sheet: Worksheet, model: ReportModel) -> None:
    sheet.title = "Summary"
    write(sheet["A1"], model.title)
    sheet["A1"].font = Font(bold=True, size=16, color=BRAND)
    write(sheet["A2"], model.objective)
    sheet["A2"].font = Font(color=MUTED)
    meta = [("Organisation", model.organisation), ("Dataset", model.dataset_label),
            ("Period covered", model.period or "Not applicable"), ("Request", model.request),
            ("Prepared", model.generated_label), ("Dataset fingerprint (SHA-256)", model.dataset_sha256),
            ("Analysis reference", model.job_id)]  # fmt: skip
    row = 4
    for key, value in meta:
        write(sheet.cell(row, 1), key)
        sheet.cell(row, 1).font = Font(bold=True, color=MUTED)
        write(sheet.cell(row, 2), value)
        sheet.cell(row, 2).alignment = Alignment(wrap_text=True, vertical="top")
        row += 1
    row = _text_block(sheet, row + 1, "Executive summary", model.summary)

    for segment in model.segments:
        if not segment["kpis"]:
            continue
        heading = "Key figures" + (f": {segment['label']}" if model.multi_segment else "")
        write(sheet.cell(row, 1), heading)
        sheet.cell(row, 1).font = Font(bold=True, size=12, color=BRAND)
        row += 1
        for kpi in segment["kpis"]:
            write(sheet.cell(row, 1), kpi["label"])
            cell = sheet.cell(row, 2)
            write(cell, typed(kpi["value"], kpi["format"]))
            cell.number_format = NUMBER_FORMATS.get(kpi["format"], "General")
            cell.alignment = Alignment(horizontal="left")
            cell.font = Font(bold=True)
            if kpi["format"] == "money" and segment.get("currency"):
                write(sheet.cell(row, 3), segment["currency"])
            row += 1
        row += 1
    if model.next_steps:
        row = _text_block(sheet, row, "Suggested next steps", model.next_steps)
    write(sheet.cell(row, 1), model.narrative_source)
    sheet.cell(row, 1).font = Font(italic=True, color=MUTED, size=9)
    sheet.column_dimensions["A"].width = 30
    sheet.column_dimensions["B"].width = 110
    sheet.column_dimensions["C"].width = 8


def _add_chart(sheet: Worksheet, table: dict[str, Any], rows: int) -> None:
    """Native Excel charts for the tables that have an obvious picture."""
    keys = [column["key"] for column in table["columns"]]
    anchor = f"{get_column_letter(len(keys) + 2)}2"
    categories = Reference(sheet, min_col=1, min_row=2, max_row=rows + 1)

    def bars(column_key: str, horizontal: bool = False) -> BarChart:
        chart = BarChart()
        chart.type = "bar" if horizontal else "col"
        column = keys.index(column_key) + 1
        chart.add_data(Reference(sheet, min_col=column, min_row=1, max_row=rows + 1), titles_from_data=True)
        chart.set_categories(categories)
        chart.title, chart.height, chart.width = table["title"], 8.5, 18
        chart.x_axis.delete = chart.y_axis.delete = False
        if horizontal:
            chart.x_axis.scaling.orientation = "maxMin"  # largest at the top, as in the table
            chart.legend = None
        return chart

    if table["key"] == "sales_by_month":
        chart = bars("sales")
        chart.legend = None
    elif table["key"] == "profit_by_month":
        chart = bars("profit")
        line = LineChart()
        column = keys.index("margin") + 1
        line.add_data(Reference(sheet, min_col=column, min_row=1, max_row=rows + 1), titles_from_data=True)
        line.y_axis.axId = 200
        line.y_axis.title = "Gross margin %"
        line.y_axis.crosses = "max"
        line.y_axis.delete = False
        chart += line
    elif table["key"] == "sales_by_0":
        chart = bars("sales", horizontal=True)
    elif table["key"] == "profit_by_0":
        chart = bars("profit", horizontal=True)
    else:
        return
    sheet.add_chart(chart, anchor)


def _table_sheet(workbook: Workbook, table: dict[str, Any], segment: dict[str, Any], multi: bool) -> None:
    sheet = _sheet(workbook, table["title"] + (f" {segment['label']}" if multi else ""))
    columns = table["columns"]
    _header(sheet, 1, [column["label"] for column in columns])
    for row_number, row in enumerate(table["rows"], start=2):
        for column_number, column in enumerate(columns, start=1):
            cell = sheet.cell(row_number, column_number)
            write(cell, typed(row.get(column["key"]), column["format"]))
            if column["format"] in NUMBER_FORMATS:
                cell.number_format = NUMBER_FORMATS[column["format"]]
            else:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
    footer = len(table["rows"]) + 3
    notes = [note for note in (table.get("note"), f"Evidence: {table['evidence_ref']}",
                               f"Currency: {segment['currency']}" if segment.get("currency") else None) if note]  # fmt: skip
    for offset, note in enumerate(notes):
        write(sheet.cell(footer + offset, 1), note)
        sheet.cell(footer + offset, 1).font = Font(italic=True, color=MUTED, size=9)
    sheet.freeze_panes = "A2"
    _fit(sheet)
    if table["rows"]:
        _add_chart(sheet, table, len(table["rows"]))


def render_xlsx(model: ReportModel, path: Path) -> None:
    workbook = Workbook()
    _summary_sheet(workbook.active, model)

    for segment in model.segments:
        for table in segment["tables"]:
            _table_sheet(workbook, table, segment, model.multi_segment)

    findings = _sheet(workbook, "Findings")
    _header(findings, 1, ["Evidence", "Type", "Scope", "Finding", "Statement"])
    for row, finding in enumerate(model.findings, start=2):
        values = [finding["evidence_ref"], KIND_LABELS.get(finding["kind"], "Finding"),
                  model.segment_label(finding.get("segment")), finding["title"], finding["statement"]]  # fmt: skip
        for column, value in enumerate(values, start=1):
            write(findings.cell(row, column), value)
            findings.cell(row, column).alignment = Alignment(wrap_text=True, vertical="top")
    findings.freeze_panes = "A2"
    _fit(findings, {4: 34, 5: 110})

    notes = _sheet(workbook, "Notes")
    row = 1
    for heading, items in (("Data notes and limitations", model.warnings), ("Assumptions", model.assumptions)):
        if items:
            row = _text_block(notes, row, heading, items)
    notes.column_dimensions["A"].width = 6
    notes.column_dimensions["B"].width = 120

    checks = model.verification.get("checks", [])
    if checks:
        verification = _sheet(workbook, "Verification")
        _header(verification, 1, ["Check", "Result", "Detail"])
        for row, check in enumerate(checks, start=2):
            for column, value in enumerate(
                (check["name"], "Passed" if check["passed"] else "FAILED", check["detail"]), start=1
            ):
                write(verification.cell(row, column), value)
        _fit(verification, maximum=90)

    evidence = _sheet(workbook, "Evidence")
    _header(evidence, 1, ["Ref", "Operation", "How it was calculated", "Rows in dataset", "Rows used",
                          "Rows left out", "Parameters", "Values"])  # fmt: skip
    for row, record in enumerate(model.evidence, start=2):
        values = [record["ref"], record["operation"], evidence_line(record), record.get("rows_total"),
                  record.get("rows_used"), record.get("rows_excluded"),
                  json.dumps(record.get("parameters") or {}, default=str)[:2000],
                  json.dumps(record.get("values") or {}, default=str)[:4000]]  # fmt: skip
        for column, value in enumerate(values, start=1):
            write(evidence.cell(row, column), value)
            evidence.cell(row, column).alignment = Alignment(wrap_text=True, vertical="top")
    evidence.freeze_panes = "A2"
    _fit(evidence, {3: 90, 7: 50, 8: 70})

    workbook.save(path)
