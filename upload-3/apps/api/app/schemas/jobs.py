"""Request and response shapes for analysis jobs, agent activity, results and reports."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

AnalysisType = Literal["automatic", "sales", "profitability", "statistical", "data_quality"]


class JobRequest(BaseModel):
    workspace_id: UUID
    dataset_version_id: UUID
    prompt: str = Field(min_length=1, max_length=4000)
    analysis_type: AnalysisType = "automatic"

    @field_validator("prompt")
    @classmethod
    def _tidy(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Describe the analysis you want.")
        return cleaned


class JobAccepted(BaseModel):
    job_id: UUID
    status: str
    message: str


class JobDataset(BaseModel):
    id: UUID
    name: str
    version_id: UUID
    version_number: int


class JobOut(BaseModel):
    id: UUID
    workspace_id: UUID
    job_type: str
    analysis_type: str
    prompt: str
    status: str
    is_finished: bool
    cancel_requested: bool
    error_message: str | None
    attempts: int
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    dataset: JobDataset | None
    headline: str | None = None


class AgentTaskOut(BaseModel):
    id: UUID
    sequence: int
    agent_key: str
    agent_name: str
    role: str
    action: str | None
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    duration_ms: int | None
    attempts: int
    summary: str | None
    warnings: list[str]
    model_name: str | None
    tokens_input: int
    tokens_output: int
    error_message: str | None


class AgentActivity(BaseModel):
    job: JobOut
    tasks: list[AgentTaskOut]


class FindingOut(BaseModel):
    id: UUID
    sequence: int
    key: str | None
    kind: str | None
    title: str | None
    statement: str | None
    agent_key: str | None
    evidence_ref: str | None
    evidence: dict[str, Any]
    approved: bool


class ReportOut(BaseModel):
    id: UUID
    job_id: UUID
    format: str
    title: str | None
    filename: str | None
    size_bytes: int | None
    created_at: datetime
    prompt: str | None = None
    dataset_name: str | None = None


class JobResults(BaseModel):
    job: JobOut
    summary: dict[str, Any] | None
    findings: list[FindingOut]
    reports: list[ReportOut]


class DownloadLink(BaseModel):
    url: str
    filename: str
    content_type: str
    expires_in: int


class AgentRunOut(BaseModel):
    agent_key: str
    agent_name: str
    job_id: UUID
    status: str
    started_at: datetime
    duration_ms: int | None
    model_name: str | None
    tokens_input: int
    tokens_output: int
