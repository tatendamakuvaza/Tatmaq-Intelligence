"""Agent 04 - Statistical Analysis.

Executes a validated :class:`AnalysisSpec` with deterministic code. The agent's
toolbox holds one thing, a read-only dataset loader: it has no AI model, so no figure
it reports can have been produced by one.

Datasets that mix currencies are split first, and every operation runs once per
currency. Adding US dollars to ZiG would produce a number that means nothing.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pandas as pd

from analytics_core.financial.periods import BLANK_LABEL, label_values

from ...analytics.spec import OPERATION_TITLES, AnalysisSpec, Profitability, SalesOverview
from ..base import AgentError, AgentResult, AgentTask, BaseAgent, Metrics
from ..base.permissions import TOOL_CLEANED_READ
from . import correlation, descriptive, outliers, profitability, quality, regression, sales, trends
from .builder import EvidenceCounter, OperationSkipped, SegmentBuilder

HANDLERS: dict[str, Callable[..., None]] = {
    "sales_overview": sales.run,
    "profitability": profitability.run,
    "descriptive_statistics": descriptive.run,
    "correlation": correlation.run,
    "regression": regression.run,
    "trend": trends.run,
    "outliers": outliers.run,
    "data_quality": quality.run,
}
MAX_SEGMENTS = 6
CURRENCY_ALIASES = {"US$": "USD", "$": "USD", "US DOLLAR": "USD", "US DOLLARS": "USD", "ZIG": "ZWG",
                    "RAND": "ZAR", "R": "ZAR"}  # fmt: skip

BASE_ASSUMPTIONS = (
    "Money is added in exact decimal arithmetic and rounded half-up to two decimals only for presentation.",
    "A row with a missing value is left out of any calculation that needs that value. "
    "Missing values are never treated as zero.",
)


@dataclass
class Segment:
    key: str
    label: str
    currency: str | None
    filters: tuple[str, ...]
    frame: pd.DataFrame


def currency_code(value: str) -> str:
    upper = value.strip().upper()
    return CURRENCY_ALIASES.get(upper, upper)


def split_by_currency(
    frame: pd.DataFrame, column: str | None, default_currency: str | None
) -> tuple[list[Segment], list[str]]:
    """One segment per currency. Returns the segments and any notes about how rows were assigned."""
    if not column or column not in frame.columns:
        return [Segment("all", "All records", default_currency, (), frame)], []

    labels = pd.Series([BLANK_LABEL if v == BLANK_LABEL else currency_code(v)
                        for v in label_values(frame[column].tolist())], index=frame.index)  # fmt: skip
    counts = labels.value_counts()
    named = [code for code in counts.index if code != BLANK_LABEL]
    blanks = int(counts.get(BLANK_LABEL, 0))
    notes: list[str] = []

    if len(named) <= 1:
        currency = named[0] if named else default_currency
        if blanks and named:
            notes.append(
                f"{blanks:,} row{'' if blanks == 1 else 's'} with nothing in '{column}' "
                f"{'is' if blanks == 1 else 'are'} treated as {currency}."
            )
        return [Segment("all", "All records", currency, (), frame)], notes

    segments = [Segment(code, code, code, (f"'{column}' = {code}",), frame[labels == code]) for code in named]
    if blanks:
        segments.append(Segment("unspecified", "No currency given", None, (f"'{column}' is blank",),
                                frame[labels == BLANK_LABEL]))  # fmt: skip
    if len(segments) > MAX_SEGMENTS:
        dropped = segments[MAX_SEGMENTS:]
        notes.append(f"{sum(len(s.frame) for s in dropped):,} rows in {len(dropped)} less-used currencies "
                     f"({', '.join(s.label for s in dropped)}) were not analysed.")  # fmt: skip
        segments = segments[:MAX_SEGMENTS]
    notes.append(f"The dataset holds {len(named)} currencies. They are analysed separately and never added together.")
    return segments, notes


class StatisticalAnalysisAgent(BaseAgent):
    agent_key = "statistical_analysis"

    async def execute(self, task: AgentTask) -> AgentResult:
        if task.action != "run_analysis":
            raise AgentError(f"The statistical analysis agent has no action called '{task.action}'.")
        started = time.monotonic()
        spec = AnalysisSpec.model_validate(task.inputs["analysis_spec"])
        frame: pd.DataFrame = self.tools.get(TOOL_CLEANED_READ)(task.dataset_refs["cleaned_path"])
        segments, notes = split_by_currency(frame, spec.currency_column, task.inputs.get("default_currency"))

        options = {
            "has_profitability": any(isinstance(op, Profitability) for op in spec.operations),
            "cleaning": task.inputs.get("cleaning"),
            "context_columns": task.inputs.get("context_columns", []),
        }
        counter = EvidenceCounter()
        builders: list[SegmentBuilder] = []
        operations_log: list[dict[str, Any]] = []
        warnings = list(notes)
        multiple = len(segments) > 1

        for segment in segments:
            builder = SegmentBuilder(
                key=segment.key, label=segment.label, currency=segment.currency, rows=len(segment.frame),
                filters=segment.filters, dataset_version_id=task.dataset_version_id,  # type: ignore[arg-type]
                dataset_sha256=task.dataset_refs["sha256"], counter=counter,
            )  # fmt: skip
            for operation in spec.operations:
                entry = {"type": operation.type, "segment": segment.key, "status": "completed", "reason": None}
                try:
                    HANDLERS[operation.type](operation, segment.frame, builder, options)
                except OperationSkipped as skipped:
                    entry.update(status="skipped", reason=str(skipped))
                    where = f" for {segment.label}" if multiple else ""
                    warnings.append(f"{OPERATION_TITLES[operation.type]} was not run{where}: {skipped}.")
                operations_log.append(entry)
            warnings += [f"{segment.label}: {note}" if multiple else note for note in builder.notes]
            builders.append(builder)

        completed = [entry for entry in operations_log if entry["status"] == "completed"]
        if not completed:
            reasons = "; ".join(sorted({entry["reason"] for entry in operations_log if entry["reason"]}))
            raise AgentError(f"None of the planned analyses could be run on this dataset ({reasons}).")

        findings = [finding for builder in builders
                    for finding in sorted(builder.findings, key=lambda f: -f.importance)]  # fmt: skip
        evidence = [record for builder in builders for record in builder.evidence]
        assumptions = list(BASE_ASSUMPTIONS)
        derived = [op for op in spec.operations
                   if isinstance(op, SalesOverview | Profitability) and op.revenue.multiply]  # fmt: skip
        if derived:
            assumptions.append(f"Sales were calculated as {derived[0].revenue.label} for each row, because the "
                               "dataset has no column holding the sales amount.")  # fmt: skip
        derived_cost = [op for op in spec.operations if isinstance(op, Profitability) and op.cost.multiply]
        if derived_cost:
            assumptions.append(f"Cost of sales was calculated as {derived_cost[0].cost.label} for each row.")

        titles = sorted({OPERATION_TITLES[entry["type"]].lower() for entry in completed})
        scope = f" across {len(segments)} currencies" if multiple else ""
        return AgentResult(
            agent_key="statistical_analysis",
            status="completed",
            summary=f"Computed {', '.join(titles)} from {len(frame):,} rows{scope}: {len(findings)} findings, "
                    f"each with its formula and source recorded.",
            findings=tuple(findings),
            evidence=tuple(evidence),
            evidence_refs=tuple(record.ref for record in evidence),
            assumptions=tuple(assumptions),
            warnings=tuple(warnings),
            metrics=Metrics(execution_time_ms=int((time.monotonic() - started) * 1000), records_processed=len(frame)),
            outputs={
                "segments": [builder.to_json() for builder in builders],
                "audit": {builder.key: builder.audit for builder in builders},
                "operations": operations_log,
                "headline": findings[0].statement if findings else None,
            },
        )  # fmt: skip
