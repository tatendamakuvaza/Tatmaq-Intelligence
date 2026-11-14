"""Agent 03 - Data Cleaning.

``clean_and_validate``     once per upload: standardise formats, flag problems, store
                           the cleaned table and a log of every change.
``validate_for_analysis``  at the start of every analysis: confirm the cleaned data
                           can support each planned operation, and surface the data
                           problems that affect the columns this analysis uses.
"""

from __future__ import annotations

import time
from datetime import date
from typing import Any

from analytics_core.cleaning import CleaningOutcome

from ...analytics.formatting import count_of, money
from ...analytics.spec import AnalysisSpec
from ..base import AgentError, AgentResult, AgentTask, BaseAgent, Metrics
from ..base.permissions import TOOL_CLEANED_READ, TOOL_CLEANED_WRITE, TOOL_RAW_READ
from .duplicate_detector import duplicate_summary
from .transformations import clean, column_statistics, outcome_json
from .validator import check_spec, columns_used

#: Issue codes worth repeating in an analysis when they touch a column it uses.
ANALYSIS_RELEVANT = {"missing_values", "invalid_numbers", "invalid_dates", "ambiguous_dates", "date_order_conflict",
                     "precision", "negative_values", "outliers"}  # fmt: skip


def _count(outcome: CleaningOutcome, *steps: str) -> int:
    return sum(entry.rows_affected for entry in outcome.log if entry.step in steps)


def _summary(outcome: CleaningOutcome, duplicates: dict[str, Any]) -> str:
    changes = [
        (_count(outcome, "standardise_dates", "convert_serial_dates"), "date"),
        (_count(outcome, "normalise_numbers"), "number"),
        (_count(outcome, "standardise_categories", "trim_whitespace"), "text value"),
    ]
    standardised = ", ".join(count_of(n, label) for n, label in changes if n)
    flags = []
    if duplicates["rows"]:
        flags.append(count_of(duplicates["rows"], "duplicate row"))
    missing = sum(issue.count for issue in outcome.issues if issue.code == "missing_values")
    if missing:
        flags.append(count_of(missing, "missing value"))
    invalid = sum(issue.count for issue in outcome.issues if issue.code in ("invalid_numbers", "invalid_dates"))
    if invalid:
        flags.append(count_of(invalid, "unreadable value"))
    parts = [f"Checked {outcome.rows_in:,} rows."]
    if standardised:
        parts.append(f"Standardised {standardised}.")
    if outcome.summary_rows:
        parts.append(f"Set aside {count_of(len(outcome.summary_rows), 'TOTAL line')}.")
    parts.append(f"Flagged {', '.join(flags)}." if flags else "No problems were found.")
    parts.append("No records were deleted and no missing values were filled in.")
    return " ".join(parts)


class DataCleaningAgent(BaseAgent):
    agent_key = "data_cleaning"

    async def execute(self, task: AgentTask) -> AgentResult:
        if task.action == "clean_and_validate":
            return self._clean_and_validate(task)
        if task.action == "validate_for_analysis":
            return self._validate_for_analysis(task)
        raise AgentError(f"The data cleaning agent has no action called '{task.action}'.")

    def _clean_and_validate(self, task: AgentTask) -> AgentResult:
        started = time.monotonic()
        raw = self.tools.get(TOOL_RAW_READ)(task.dataset_refs["raw_path"])
        today = date.fromisoformat(task.inputs["today"]) if task.inputs.get("today") else None
        outcome = clean(
            raw, task.inputs["column_types"],
            category_columns=task.inputs.get("category_columns", []),
            measure_columns=task.inputs.get("measure_columns", []),
            day_first=task.inputs.get("date_order", "DMY") == "DMY", today=today,
        )  # fmt: skip
        if outcome.rows_out == 0:
            raise AgentError("After setting aside summary lines, the dataset has no rows of data.")
        self.tools.get(TOOL_CLEANED_WRITE)(task.dataset_refs["cleaned_path"], outcome.cleaned)

        duplicates = duplicate_summary(outcome.cleaned, task.inputs.get("roles", {}).get("revenue"))
        report = {**outcome_json(outcome), "duplicates": duplicates, "summary_rows": outcome.summary_rows}
        warnings = [issue.message for issue in outcome.issues if issue.severity != "info"]
        return AgentResult(
            agent_key="data_cleaning",
            status="completed",
            summary=_summary(outcome, duplicates),
            warnings=tuple(warnings),
            assumptions=tuple(issue.message for issue in outcome.issues if issue.code == "ambiguous_dates"),
            metrics=Metrics(execution_time_ms=int((time.monotonic() - started) * 1000),
                            records_processed=outcome.rows_in),
            outputs={
                "cleaned_path": task.dataset_refs["cleaned_path"],
                "rows": outcome.rows_out,
                "column_stats": column_statistics(outcome.cleaned),
                "cleaning": report,
            },
        )  # fmt: skip

    def _validate_for_analysis(self, task: AgentTask) -> AgentResult:
        started = time.monotonic()
        spec = AnalysisSpec.model_validate(task.inputs["analysis_spec"])
        frame = self.tools.get(TOOL_CLEANED_READ)(task.dataset_refs["cleaned_path"])
        expected_rows = task.dataset_refs.get("rows")
        if expected_rows is not None and len(frame) != int(expected_rows):
            raise AgentError("The cleaned dataset does not match its recorded row count. Upload the dataset again.")

        checks = check_spec(frame, spec)
        infeasible = [check for check in checks if not check["feasible"]]
        used = columns_used(spec)
        stored = task.inputs.get("cleaning") or {}
        relevant = [issue for issue in stored.get("issues", [])
                    if issue["code"] in ANALYSIS_RELEVANT and issue.get("column") in used]  # fmt: skip
        warnings = [issue["message"] for issue in relevant if issue["severity"] != "info"]

        duplicates = stored.get("duplicates") or {"rows": 0}
        if duplicates.get("rows"):
            value = duplicates.get("revenue")
            at_stake = f" worth {money(value, task.inputs.get('currency'))}" if value is not None else ""
            rows = count_of(duplicates["rows"], "row")
            warnings.append(
                f"{rows} exactly {'repeats' if duplicates['rows'] == 1 else 'repeat'} an earlier row and "
                f"{'is' if duplicates['rows'] == 1 else 'are'} included in the figures. If they are true duplicates, "
                f"the figures are overstated by those {rows}{at_stake}."
            )
        for check in infeasible:
            warnings.append(f"{check['title']} cannot be run: {check['reason']}.")

        feasible = len(checks) - len(infeasible)
        summary = (
            f"Confirmed the cleaned data ({len(frame):,} rows) supports {feasible} of {len(checks)} planned "
            f"analys{'is' if len(checks) == 1 else 'es'}."
        )
        if warnings:
            summary += f" {count_of(len(warnings), 'point')} to note."
        return AgentResult(
            agent_key="data_cleaning",
            status="completed",
            summary=summary,
            warnings=tuple(warnings),
            assumptions=tuple(issue["message"] for issue in relevant if issue["code"] == "ambiguous_dates"),
            metrics=Metrics(execution_time_ms=int((time.monotonic() - started) * 1000),
                            records_processed=len(frame)),
            outputs={
                "rows": len(frame),
                "operations": checks,
                "infeasible": [check["type"] for check in infeasible],
                "relevant_issues": relevant,
                "duplicates": duplicates,
            },
        )  # fmt: skip
