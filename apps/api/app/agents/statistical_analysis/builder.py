"""Collects what an analysis produces: figures, charts, tables, findings and evidence.

Every figure is registered together with an evidence record (source dataset and its
fingerprint, columns, formula, parameters, rows used and excluded), so "where did
this number come from?" always has an answer, and a finding cannot exist without one.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from itertools import count
from typing import Any
from uuid import UUID

from analytics_core.financial import to_decimals

from ...analytics.formatting import decimal_text
from ...analytics.spec import Measure
from ..base import Evidence, Finding

TOP_N = 10
CHART_TOP_N = 8


class OperationSkipped(Exception):
    """An operation cannot be computed on this data. The reason is reported, not hidden."""


class EvidenceCounter:
    """Hands out E1, E2, ... across every segment of a job."""

    def __init__(self) -> None:
        self._numbers = count(1)

    def next_ref(self) -> str:
        return f"E{next(self._numbers)}"


class SegmentBuilder:
    def __init__(
        self, *, key: str, label: str, currency: str | None, rows: int, filters: tuple[str, ...],
        dataset_version_id: UUID, dataset_sha256: str, counter: EvidenceCounter,
    ) -> None:  # fmt: skip
        self.key, self.label, self.currency, self.rows, self.filters = key, label, currency, rows, filters
        self._dataset_version_id, self._sha256, self._counter = dataset_version_id, dataset_sha256, counter
        self.kpis: list[dict[str, Any]] = []
        self.charts: list[dict[str, Any]] = []
        self.tables: list[dict[str, Any]] = []
        self.findings: list[Finding] = []
        self.evidence: list[Evidence] = []
        self.notes: list[str] = []
        self.audit: dict[str, Any] = {}
        self.period: dict[str, str] | None = None

    def add_evidence(
        self, *, operation: str, columns: Sequence[str], formula: str, parameters: dict[str, Any] | None = None,
        rows_total: int | None = None, rows_used: int | None = None, exclusions: dict[str, int] | None = None,
        values: dict[str, Any] | None = None,
    ) -> str:  # fmt: skip
        exclusions = {reason: n for reason, n in (exclusions or {}).items() if n}
        record = Evidence(
            ref=self._counter.next_ref(), operation=operation, dataset_version_id=self._dataset_version_id,
            dataset_sha256=self._sha256, columns=tuple(columns), formula=formula, filters=self.filters,
            parameters=parameters or {}, rows_total=rows_total, rows_used=rows_used,
            rows_excluded=sum(exclusions.values()) if rows_total is not None else None,
            exclusions=exclusions, values=values or {},
        )  # fmt: skip
        self.evidence.append(record)
        return record.ref

    def add_finding(self, key: str, kind: str, title: str, statement: str, evidence_ref: str, importance: int) -> None:
        self.findings.append(Finding(key=key, kind=kind, title=title, statement=statement,  # type: ignore[arg-type]
                                     evidence_ref=evidence_ref, importance=importance, segment=self.key))  # fmt: skip

    def add_kpi(self, key: str, label: str, value: Any, kind: str, evidence_ref: str, note: str | None = None) -> None:
        if isinstance(value, Decimal):
            value = decimal_text(value, 2)
        self.kpis.append({"key": key, "label": label, "value": value, "format": kind,
                          "evidence_ref": evidence_ref, "note": note})  # fmt: skip

    def add_chart(
        self, key: str, title: str, categories: Sequence[str], series: Sequence[dict[str, Any]], evidence_ref: str,
        *, orientation: str = "vertical", note: str | None = None,
    ) -> None:  # fmt: skip
        self.charts.append({"key": key, "title": title, "orientation": orientation, "categories": list(categories),
                            "series": list(series), "evidence_ref": evidence_ref, "note": note})  # fmt: skip

    def add_table(
        self, key: str, title: str, columns: Sequence[tuple[str, str, str]], rows: Sequence[dict[str, Any]],
        evidence_ref: str, note: str | None = None,
    ) -> None:  # fmt: skip
        self.tables.append({
            "key": key, "title": title, "evidence_ref": evidence_ref, "note": note,
            "columns": [{"key": k, "label": label, "format": kind} for k, label, kind in columns],
            "rows": [{k: (decimal_text(v, 2) if isinstance(v, Decimal) else v) for k, v in row.items()} for row in rows],
        })  # fmt: skip

    def to_json(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label, "currency": self.currency, "rows": self.rows,
                "filters": list(self.filters), "period": self.period, "kpis": self.kpis, "charts": self.charts,
                "tables": self.tables, "notes": self.notes}  # fmt: skip


def measure_values(frame: Any, measure: Measure) -> list[Decimal | None]:
    """One exact decimal per row for a measure; missing wherever any input is missing."""
    if measure.column is not None:
        return to_decimals(frame[measure.column].tolist())
    left, right = (to_decimals(frame[name].tolist()) for name in measure.multiply or ())
    return [a * b if a is not None and b is not None else None for a, b in zip(left, right, strict=True)]


def measure_formula(measure: Measure) -> str:
    return f"'{measure.column}'" if measure.column is not None else " x ".join(f"'{n}'" for n in measure.multiply or ())


def series_floats(values: Sequence[Decimal | None]) -> list[float | None]:
    """Chart coordinates only. Reported figures always come from the exact decimals."""
    return [None if value is None else float(value) for value in values]
