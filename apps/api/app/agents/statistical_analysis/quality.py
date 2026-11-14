"""Data quality: what the cleaning agent found and changed, as an analysis in its own right."""

from __future__ import annotations

from typing import Any

from ...analytics import formatting as fmt
from ...analytics.spec import DataQuality
from .builder import OperationSkipped, SegmentBuilder

ISSUE_LABELS = {
    "missing_values": "Missing values", "duplicate_rows": "Duplicate rows", "invalid_numbers": "Unreadable numbers",
    "invalid_dates": "Unreadable dates", "inconsistent_date_formats": "Mixed date formats",
    "ambiguous_dates": "Ambiguous dates", "date_order_conflict": "Conflicting date order",
    "inconsistent_categories": "Inconsistent spellings", "outliers": "Unusual values",
    "negative_values": "Negative values", "future_dates": "Dates in the future", "summary_rows": "Total lines",
    "two_digit_years": "Two-digit years", "empty_column": "Empty column", "precision": "Very large numbers",
}  # fmt: skip
STEP_LABELS = {
    "exclude_summary_rows": "Set aside total lines", "standardise_dates": "Standardised dates",
    "convert_serial_dates": "Converted spreadsheet dates", "normalise_numbers": "Normalised numbers",
    "trim_whitespace": "Removed stray spaces", "standardise_categories": "Merged spellings",
    "null_tokens": "Read placeholders as missing",
}  # fmt: skip


def run(operation: DataQuality, frame: Any, builder: SegmentBuilder, options: dict[str, Any]) -> None:
    report = options.get("cleaning") or {}
    if not report:
        raise OperationSkipped("no cleaning report is stored for this dataset")
    issues, log = report.get("issues", []), report.get("log", [])
    rows_in, rows_out = report.get("rows_in", len(frame)), report.get("rows_out", len(frame))
    duplicates = report.get("duplicates") or {"rows": 0}

    ref = builder.add_evidence(
        operation="data_quality", columns=(),
        formula="counts from the cleaning rules: rows that exactly repeat an earlier row; cells that are blank "
                "or cannot be read as their column's type; values whose format was standardised",
        rows_total=rows_in, rows_used=rows_out, exclusions={"total lines set aside": rows_in - rows_out},
        values={"issues": {f"{issue['code']}:{issue.get('column') or 'all columns'}": issue["count"] for issue in issues},
                "changes": {f"{entry['step']}:{entry.get('column') or 'all columns'}": entry["rows_affected"] for entry in log},
                "duplicate_rows": duplicates.get("rows"), "duplicate_sales_value": duplicates.get("revenue")},
    )  # fmt: skip

    if issues:
        builder.add_table(
            "quality_issues", "Data quality findings",
            [("issue", "Finding", "text"), ("column", "Column", "text"), ("count", "Rows", "integer"),
             ("severity", "Level", "text"), ("detail", "Detail", "text")],
            [{"issue": ISSUE_LABELS.get(issue["code"], issue["code"]), "column": issue.get("column") or "All",
              "count": issue["count"], "severity": issue["severity"].title(), "detail": issue["message"]}
             for issue in sorted(issues, key=lambda i: ({"critical": 0, "warning": 1, "info": 2}[i["severity"]], -i["count"]))],
            ref,
        )  # fmt: skip
    if log:
        builder.add_table(
            "cleaning_log", "Changes made during cleaning",
            [("step", "Change", "text"), ("column", "Column", "text"), ("count", "Rows", "integer"),
             ("detail", "What was done", "text")],
            [{"step": STEP_LABELS.get(entry["step"], entry["step"]), "column": entry.get("column") or "All",
              "count": entry["rows_affected"], "detail": entry["description"]} for entry in log],
            ref, note="The uploaded file is never modified; these changes apply to the working copy used for analysis.",
        )  # fmt: skip

    def total(*codes: str) -> int:
        return sum(issue["count"] for issue in issues if issue["code"] in codes)

    missing, unreadable = total("missing_values"), total("invalid_numbers", "invalid_dates")
    changed = sum(entry["rows_affected"] for entry in log if entry["step"] != "exclude_summary_rows")
    builder.add_kpi("quality_rows", "Records", rows_out, "integer", ref)
    builder.add_kpi("quality_duplicates", "Duplicate rows", duplicates.get("rows", 0), "integer", ref)
    builder.add_kpi("quality_missing", "Missing values", missing, "integer", ref)
    builder.add_kpi("quality_standardised", "Values standardised", changed, "integer", ref)

    builder.add_finding(
        "quality.overview", "quality", "Data quality overview",
        f"The dataset holds {rows_out:,} records. Cleaning flagged "
        f"{fmt.count_of(duplicates.get('rows', 0), 'duplicate row')}, {fmt.count_of(missing, 'missing value')} and "
        f"{fmt.count_of(unreadable, 'unreadable value')}, and standardised the format of "
        f"{fmt.count_of(changed, 'value')}. No records were deleted and no missing values were filled in.", ref, 80,
    )  # fmt: skip
    if duplicates.get("rows"):
        value = duplicates.get("revenue")
        worth = f" They carry {fmt.money(value, builder.currency)} of sales." if value is not None else ""
        builder.add_finding(
            "quality.duplicates", "quality", "Duplicate rows",
            f"{fmt.count_of(duplicates['rows'], 'row')} exactly {'repeats' if duplicates['rows'] == 1 else 'repeat'} "
            f"an earlier row.{worth} They remain in all totals until someone confirms whether each is a genuine "
            "second transaction or an entry made twice.", ref, 74,
        )  # fmt: skip
    for issue in issues:
        if issue["code"] == "missing_values" and issue["severity"] != "info":
            builder.add_finding(f"quality.missing.{issue['column']}", "quality", f"Missing: {issue['column']}",
                                issue["message"], ref, 60)  # fmt: skip
        elif issue["code"] in ("ambiguous_dates", "date_order_conflict", "invalid_numbers", "invalid_dates"):
            builder.add_finding(f"quality.{issue['code']}.{issue['column']}", "quality",
                                ISSUE_LABELS[issue["code"]], issue["message"], ref, 66)  # fmt: skip
