"""The common agent contract (specification Part E).

Every agent receives an :class:`AgentTask` and returns an :class:`AgentResult`. Both
are immutable and validated, so an agent cannot hand the orchestrator free-form text
in place of structured output. The same models are exported as JSON Schema to
``packages/contracts`` for other languages.
"""

from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

AgentKey = Literal[
    "chief_intelligence", "data_acquisition", "data_cleaning", "statistical_analysis", "report_generation"
]
ResultStatus = Literal["completed", "failed", "needs_clarification"]
FindingKind = Literal["kpi", "insight", "statistic", "quality", "limitation"]


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ExecutionLimits(_Frozen):
    max_rows: int
    max_columns: int
    max_file_bytes: int
    timeout_seconds: int


class AgentTask(_Frozen):
    """What an agent is asked to do, and the limits it must do it within."""

    job_id: UUID
    organisation_id: UUID
    agent_key: AgentKey
    action: str
    user_instruction: str
    dataset_version_id: UUID | None = None
    dataset_refs: dict[str, Any] = Field(default_factory=dict)
    permitted_tools: tuple[str, ...] = ()
    limits: ExecutionLimits
    inputs: dict[str, Any] = Field(default_factory=dict)
    output_format: str = "AgentResult/v1"


class Evidence(_Frozen):
    """Where a finding came from: enough to recompute it independently."""

    ref: str
    operation: str
    dataset_version_id: UUID
    dataset_sha256: str
    columns: tuple[str, ...] = ()
    formula: str = ""
    filters: tuple[str, ...] = ()
    parameters: dict[str, Any] = Field(default_factory=dict)
    rows_total: int | None = None
    rows_used: int | None = None
    rows_excluded: int | None = None
    exclusions: dict[str, int] = Field(default_factory=dict)
    values: dict[str, Any] = Field(default_factory=dict)


class Finding(_Frozen):
    key: str
    kind: FindingKind
    title: str
    statement: str
    evidence_ref: str
    importance: int = Field(default=50, ge=0, le=100)
    segment: str | None = None


class ArtifactRef(_Frozen):
    artifact_type: Literal["report_pdf", "report_xlsx", "report_html"]
    title: str
    filename: str
    content_type: str
    storage_path: str
    size_bytes: int
    sha256: str


class Metrics(_Frozen):
    execution_time_ms: int = 0
    records_processed: int = 0
    tokens_input: int = 0
    tokens_output: int = 0
    model_name: str | None = None


class AgentResult(_Frozen):
    agent_key: AgentKey
    status: ResultStatus
    summary: str
    findings: tuple[Finding, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    artifacts: tuple[ArtifactRef, ...] = ()
    metrics: Metrics = Metrics()
    # Agent-specific structured output (the plan, the profile, result tables...).
    outputs: dict[str, Any] = Field(default_factory=dict)
