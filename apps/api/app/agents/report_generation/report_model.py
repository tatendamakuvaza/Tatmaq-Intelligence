"""The content of a report, independent of file format.

The PDF, Excel and HTML generators all render this one model, so the three files
cannot disagree with each other. It is built only from findings the verification step
approved, plus the evidence records those findings point to.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ...analytics import formatting as fmt

KIND_LABELS = {"kpi": "Key figure", "insight": "Insight", "statistic": "Statistical result",
               "quality": "Data quality", "limitation": "Limitation"}  # fmt: skip


@dataclass
class ReportModel:
    title: str
    objective: str
    request: str
    organisation: str
    dataset_name: str
    dataset_version: int
    dataset_filename: str | None
    dataset_rows: int
    dataset_sha256: str
    job_id: str
    generated_at: datetime
    timezone: str
    period: str | None
    segments: list[dict[str, Any]]
    findings: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    warnings: list[str]
    assumptions: list[str]
    verification: dict[str, Any]
    summary: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    narrative_source: str = "Written from the verified findings using fixed templates."
    learning_profile: dict[str, Any] = field(default_factory=dict)

    @property
    def multi_segment(self) -> bool:
        return len(self.segments) > 1

    @property
    def generated_label(self) -> str:
        return f"{fmt.date_label(self.generated_at.date())}, {self.generated_at:%H:%M} ({self.timezone})"

    @property
    def dataset_label(self) -> str:
        return f"{self.dataset_name} (version {self.dataset_version}, {self.dataset_rows:,} records)"

    @property
    def file_stem(self) -> str:
        slug = "".join(c if c.isalnum() else "-" for c in self.title.lower())
        while "--" in slug:
            slug = slug.replace("--", "-")
        return f"{slug.strip('-')}-{self.generated_at:%Y-%m-%d}"

    def evidence_by_ref(self) -> dict[str, dict[str, Any]]:
        return {record["ref"]: record for record in self.evidence}

    def segment_label(self, key: str | None) -> str:
        for segment in self.segments:
            if segment["key"] == key:
                return segment["label"]
        return ""


def _local_time(iso: str, timezone: str) -> tuple[datetime, str]:
    moment = datetime.fromisoformat(iso)
    try:
        return moment.astimezone(ZoneInfo(timezone)), timezone
    except (ZoneInfoNotFoundError, ValueError):
        return moment, "UTC"


def _period(segments: list[dict[str, Any]]) -> str | None:
    periods = [segment["period"] for segment in segments if segment.get("period")]
    if not periods:
        return None
    start = min(date.fromisoformat(period["start"]) for period in periods)
    end = max(date.fromisoformat(period["end"]) for period in periods)
    return f"{fmt.date_label(start)} to {fmt.date_label(end)}"


def build_model(inputs: dict[str, Any]) -> ReportModel:
    """Assemble the model from the report task's inputs. Unapproved findings are dropped here."""
    generated_at, timezone = _local_time(inputs["generated_at"], inputs.get("timezone") or "UTC")
    dataset = inputs["dataset"]
    findings = [finding for finding in inputs["findings"] if finding.get("approved", False)]
    used_refs = {finding["evidence_ref"] for finding in findings}
    for segment in inputs["segments"]:
        for block in (*segment["kpis"], *segment["charts"], *segment["tables"]):
            used_refs.add(block["evidence_ref"])
    return ReportModel(
        title=inputs["title"],
        objective=inputs["objective"],
        request=inputs["request"],
        organisation=inputs["organisation"],
        dataset_name=dataset["name"],
        dataset_version=dataset["version"],
        dataset_filename=dataset.get("filename"),
        dataset_rows=dataset["rows"],
        dataset_sha256=dataset["sha256"],
        job_id=inputs["job_id"],
        generated_at=generated_at,
        timezone=timezone,
        period=_period(inputs["segments"]),
        segments=inputs["segments"],
        findings=findings,
        evidence=[record for record in inputs["evidence"] if record["ref"] in used_refs],
        warnings=list(dict.fromkeys(inputs.get("warnings", []))),
        assumptions=list(dict.fromkeys(inputs.get("assumptions", []))),
        verification=inputs.get("verification") or {"passed": True, "checks": []},
        learning_profile=inputs.get("learning_profile") or {},
    )


def evidence_line(record: dict[str, Any]) -> str:
    """One readable line describing how a figure was obtained."""
    parts = [record["formula"].rstrip(".") + "."]
    if record.get("columns"):
        parts.append("Columns: " + ", ".join(f"'{name}'" for name in record["columns"]) + ".")
    if record.get("filters"):
        parts.append("Filter: " + "; ".join(record["filters"]) + ".")
    if record.get("rows_total") is not None and record.get("rows_used") is not None:
        rows = f"Rows used: {record['rows_used']:,} of {record['rows_total']:,}"
        if record.get("exclusions"):
            rows += (
                " (left out: " + ", ".join(f"{n:,} with {reason}" for reason, n in record["exclusions"].items()) + ")"
            )
        parts.append(rows + ".")
    return " ".join(parts)
