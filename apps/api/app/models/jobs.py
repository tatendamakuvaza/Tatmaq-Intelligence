"""Analysis jobs (which are also the work queue), agent activity, findings and reports."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, created_timestamp, uuid_pk


class JobStatus:
    """Job lifecycle (specification section 4.3)."""

    QUEUED = "queued"
    VALIDATING = "validating_dataset"
    PLANNING = "planning"
    EXECUTING = "executing_agents"
    VERIFYING = "quality_verification"
    REPORTING = "generating_report"
    COMPLETED = "completed"
    PARTIAL = "partially_completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    IN_PROGRESS = (VALIDATING, PLANNING, EXECUTING, VERIFYING, REPORTING)
    ACTIVE = (QUEUED, *IN_PROGRESS)
    TERMINAL = (COMPLETED, PARTIAL, FAILED, CANCELLED)
    HAS_RESULTS = (COMPLETED, PARTIAL)


class JobType:
    INGESTION = "ingestion"
    ANALYSIS = "analysis"


class TaskStatus:
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"

    id: Mapped[uuid_pk]
    organisation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organisations.id"))
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    dataset_version_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("dataset_versions.id"))
    requested_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("profiles.id"))
    job_type: Mapped[str] = mapped_column(String(30), default=JobType.ANALYSIS)
    analysis_type: Mapped[str] = mapped_column(String(50), default="automatic")
    prompt: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default=JobStatus.QUEUED)
    priority: Mapped[int] = mapped_column(Integer, default=5)
    idempotency_key: Mapped[str | None] = mapped_column(String(150))
    result_summary: Mapped[dict[str, Any] | None] = mapped_column()
    error_message: Mapped[str | None] = mapped_column(Text)
    # queue bookkeeping
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    locked_by: Mapped[str | None] = mapped_column(String(100))
    lock_token: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[created_timestamp]
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AgentTask(Base):
    """One assignment in a job's plan."""

    __tablename__ = "agent_tasks"

    id: Mapped[uuid_pk]
    organisation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organisations.id"))
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_jobs.id"))
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    agent_key: Mapped[str] = mapped_column(String(100))
    action: Mapped[str | None] = mapped_column(String(100))
    task_input: Mapped[dict[str, Any]] = mapped_column(default=dict)
    dependencies: Mapped[list[Any] | None] = mapped_column(default=list)
    status: Mapped[str] = mapped_column(String(30), default=TaskStatus.PENDING)
    created_at: Mapped[created_timestamp]
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentRun(Base):
    """One attempt at a task. A retried task has several runs."""

    __tablename__ = "agent_runs"

    id: Mapped[uuid_pk]
    organisation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organisations.id"))
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_jobs.id"))
    task_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent_tasks.id"))
    agent_key: Mapped[str] = mapped_column(String(100))
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    model_name: Mapped[str | None] = mapped_column(String(150))
    input_json: Mapped[dict[str, Any] | None] = mapped_column()
    output_json: Mapped[dict[str, Any] | None] = mapped_column()
    status: Mapped[str] = mapped_column(String(30), default="running")
    tokens_input: Mapped[int | None] = mapped_column(BigInteger, default=0)
    tokens_output: Mapped[int | None] = mapped_column(BigInteger, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AnalysisResult(Base):
    """One finding, with the evidence it rests on."""

    __tablename__ = "analysis_results"

    id: Mapped[uuid_pk]
    organisation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organisations.id"))
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_jobs.id"))
    agent_key: Mapped[str | None] = mapped_column(String(100))
    sequence: Mapped[int] = mapped_column(Integer, default=0)
    result_type: Mapped[str | None] = mapped_column(String(100))
    result_key: Mapped[str | None] = mapped_column(String(150))
    title: Mapped[str | None] = mapped_column(String(255))
    finding: Mapped[str | None] = mapped_column(Text)
    evidence_ref: Mapped[str | None] = mapped_column(String(50))
    evidence_json: Mapped[dict[str, Any] | None] = mapped_column(default=dict)
    # Reserved for estimated findings. Deterministic calculations leave it empty:
    # they are exact for the rows used, and row coverage is recorded in the evidence.
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    approved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[created_timestamp]


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[uuid_pk]
    organisation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organisations.id"))
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_jobs.id"))
    artifact_type: Mapped[str | None] = mapped_column(String(50))
    title: Mapped[str | None] = mapped_column(String(255))
    filename: Mapped[str | None] = mapped_column(String(255))
    content_type: Mapped[str | None] = mapped_column(String(100))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    sha256_hash: Mapped[str | None] = mapped_column(String(64))
    storage_path: Mapped[str] = mapped_column(Text)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", default=dict)
    created_at: Mapped[created_timestamp]
