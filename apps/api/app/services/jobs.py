"""Submitting, tracking and cancelling analysis jobs."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..agents.base.registry import agent_name, agent_role
from ..core.config import Settings
from ..core.errors import Conflict, LimitExceeded, NotFound
from ..models import (
    AgentRun,
    AgentTask,
    AnalysisJob,
    AnalysisResult,
    Artifact,
    Dataset,
    DatasetStatus,
    DatasetVersion,
    JobStatus,
    JobType,
)  # fmt: skip
from ..schemas.jobs import (
    AgentActivity,
    AgentRunOut,
    AgentTaskOut,
    FindingOut,
    JobDataset,
    JobOut,
    JobResults,
    ReportOut,
)  # fmt: skip
from ..security.tenancy import TenantContext
from . import audit, usage

REPORT_FORMATS = {"report_pdf": "pdf", "report_xlsx": "xlsx", "report_html": "html"}


def _job_out(job: AnalysisJob, dataset: Dataset | None, version: DatasetVersion | None) -> JobOut:
    return JobOut(
        id=job.id, workspace_id=job.workspace_id, job_type=job.job_type, analysis_type=job.analysis_type,
        prompt=job.prompt, status=job.status, is_finished=job.status in JobStatus.TERMINAL,
        cancel_requested=job.cancel_requested_at is not None, error_message=job.error_message,
        attempts=job.attempts, created_at=job.created_at, started_at=job.started_at,
        completed_at=job.completed_at,
        dataset=JobDataset(id=dataset.id, name=dataset.name, version_id=version.id,
                           version_number=version.version_number) if dataset and version else None,
        headline=(job.result_summary or {}).get("headline"),
    )  # fmt: skip


def _load(db: Session, ctx: TenantContext, job_id: UUID) -> tuple[AnalysisJob, Dataset | None, DatasetVersion | None]:
    row = db.execute(
        select(AnalysisJob, Dataset, DatasetVersion)
        .outerjoin(DatasetVersion, DatasetVersion.id == AnalysisJob.dataset_version_id)
        .outerjoin(Dataset, Dataset.id == DatasetVersion.dataset_id)
        .where(AnalysisJob.id == job_id, AnalysisJob.organisation_id == ctx.organisation_id)
    ).one_or_none()
    if row is None:
        raise NotFound("Analysis not found.")
    return row[0], row[1], row[2]


def submit(
    db: Session, ctx: TenantContext, settings: Settings, *,
    workspace_id: UUID, dataset_version_id: UUID, prompt: str, analysis_type: str, idempotency_key: str | None,
) -> tuple[AnalysisJob, bool]:  # fmt: skip
    """Queue an analysis. Returns ``(job, created)``; ``created`` is False for a repeated request."""
    ctx.require("analysis:run")

    def existing_for_key() -> AnalysisJob | None:
        if not idempotency_key:
            return None
        job = db.scalar(
            select(AnalysisJob).where(
                AnalysisJob.organisation_id == ctx.organisation_id, AnalysisJob.idempotency_key == idempotency_key
            )
        )
        if job and (job.dataset_version_id, job.prompt, job.analysis_type) != (
            dataset_version_id,
            prompt,
            analysis_type,
        ):
            raise Conflict(
                "This Idempotency-Key was already used for a different request.", code="idempotency_conflict"
            )
        return job

    if (repeat := existing_for_key()) is not None:
        return repeat, False

    found = db.execute(
        select(DatasetVersion, Dataset)
        .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
        .where(DatasetVersion.id == dataset_version_id, DatasetVersion.organisation_id == ctx.organisation_id)
    ).one_or_none()
    if found is None or found[1].workspace_id != workspace_id:
        raise NotFound("Dataset not found in this workspace.")
    version = found[0]
    if version.status != DatasetStatus.READY:
        message = (
            "This dataset could not be processed, so it cannot be analysed."
            if version.status == DatasetStatus.FAILED
            else "This dataset is still being processed. Try again in a moment."
        )
        raise Conflict(message, code="dataset_not_ready")

    if usage.analyses_this_month(db, ctx.organisation_id) >= settings.plan_monthly_analysis_jobs:
        raise LimitExceeded(
            f"Your organisation has used its {settings.plan_monthly_analysis_jobs} analyses for this month.",
            code="allowance_exhausted",
        )
    active = db.scalar(
        select(func.count())
        .select_from(AnalysisJob)
        .where(
            AnalysisJob.organisation_id == ctx.organisation_id,
            AnalysisJob.job_type == JobType.ANALYSIS,
            AnalysisJob.status.in_(JobStatus.ACTIVE),
        )
    )
    if active >= settings.max_active_jobs_per_org:
        raise LimitExceeded(
            f"{active} analyses are already in progress. Wait for one to finish before starting another.",
            code="too_many_active_jobs",
        )

    job = AnalysisJob(
        organisation_id=ctx.organisation_id, workspace_id=workspace_id, dataset_version_id=dataset_version_id,
        requested_by=ctx.user.id, job_type=JobType.ANALYSIS, analysis_type=analysis_type, prompt=prompt,
        idempotency_key=idempotency_key, max_attempts=settings.job_max_attempts,
    )  # fmt: skip
    db.add(job)
    try:
        db.flush()
    except IntegrityError:
        # Two identical requests raced; the other one won. Return its job.
        db.rollback()
        if (repeat := existing_for_key()) is not None:
            return repeat, False
        raise
    audit.record(db, organisation_id=ctx.organisation_id, actor_id=ctx.user.id, action="analysis.submitted",
                 resource_type="analysis_job", resource_id=job.id,
                 details={"dataset_version_id": str(dataset_version_id), "analysis_type": analysis_type})  # fmt: skip
    db.commit()
    return job, True


def get(db: Session, ctx: TenantContext, job_id: UUID) -> JobOut:
    return _job_out(*_load(db, ctx, job_id))


def list_jobs(db: Session, ctx: TenantContext, workspace_id: UUID | None, limit: int) -> list[JobOut]:
    query = (
        select(AnalysisJob, Dataset, DatasetVersion)
        .outerjoin(DatasetVersion, DatasetVersion.id == AnalysisJob.dataset_version_id)
        .outerjoin(Dataset, Dataset.id == DatasetVersion.dataset_id)
        .where(AnalysisJob.organisation_id == ctx.organisation_id, AnalysisJob.job_type == JobType.ANALYSIS)
    )
    if workspace_id is not None:
        query = query.where(AnalysisJob.workspace_id == workspace_id)
    rows = db.execute(query.order_by(AnalysisJob.created_at.desc()).limit(limit)).all()
    return [_job_out(job, dataset, version) for job, dataset, version in rows]


def cancel(db: Session, ctx: TenantContext, job_id: UUID) -> JobOut:
    """Cancel a job. A queued job stops at once; a running one is stopped by its worker."""
    ctx.require("analysis:cancel")
    _load(db, ctx, job_id)  # 404 for unknown jobs and other organisations' jobs
    now = datetime.now(UTC)
    scope = (AnalysisJob.id == job_id, AnalysisJob.organisation_id == ctx.organisation_id)
    # Conditional updates, so a worker claiming the job at this very moment cannot be overwritten.
    dequeued = db.execute(
        update(AnalysisJob)
        .where(*scope, AnalysisJob.status == JobStatus.QUEUED)
        .values(status=JobStatus.CANCELLED, completed_at=now, updated_at=now, cancel_requested_at=now)
    ).rowcount
    if not dequeued:
        signalled = db.execute(
            update(AnalysisJob)
            .where(*scope, AnalysisJob.status.in_(JobStatus.IN_PROGRESS))
            .values(cancel_requested_at=now, updated_at=now)
        ).rowcount
        if not signalled:
            db.rollback()
            raise Conflict("This analysis has already finished and cannot be cancelled.", code="already_finished")
    audit.record(db, organisation_id=ctx.organisation_id, actor_id=ctx.user.id, action="analysis.cancel_requested",
                 resource_type="analysis_job", resource_id=job_id)  # fmt: skip
    db.commit()
    return get(db, ctx, job_id)


def agent_activity(db: Session, ctx: TenantContext, job_id: UUID) -> AgentActivity:
    job, dataset, version = _load(db, ctx, job_id)
    tasks = db.scalars(
        select(AgentTask)
        .where(AgentTask.job_id == job.id, AgentTask.organisation_id == ctx.organisation_id)
        .order_by(AgentTask.sequence)
    ).all()
    runs = db.scalars(
        select(AgentRun)
        .where(AgentRun.job_id == job.id, AgentRun.organisation_id == ctx.organisation_id)
        .order_by(AgentRun.started_at)
    ).all()
    runs_by_task: dict[UUID, list[AgentRun]] = {}
    for run in runs:
        runs_by_task.setdefault(run.task_id, []).append(run)

    out: list[AgentTaskOut] = []
    for task in tasks:
        attempts = runs_by_task.get(task.id, [])
        last = attempts[-1] if attempts else None
        output = (last.output_json or {}) if last else {}
        out.append(
            AgentTaskOut(
                id=task.id, sequence=task.sequence, agent_key=task.agent_key, agent_name=agent_name(task.agent_key),
                role=agent_role(task.agent_key),
                action=task.action, status=task.status, started_at=task.started_at, completed_at=task.completed_at,
                duration_ms=sum(run.duration_ms or 0 for run in attempts) if attempts else None,
                attempts=len(attempts), summary=output.get("summary"), warnings=list(output.get("warnings") or []),
                model_name=last.model_name if last else None,
                tokens_input=sum(run.tokens_input or 0 for run in attempts),
                tokens_output=sum(run.tokens_output or 0 for run in attempts),
                error_message=last.error_message if last and task.status == "failed" else None,
            )
        )  # fmt: skip
    return AgentActivity(job=_job_out(job, dataset, version), tasks=out)


def _report_out(artifact: Artifact, prompt: str | None = None, dataset_name: str | None = None) -> ReportOut:
    return ReportOut(
        id=artifact.id, job_id=artifact.job_id, format=REPORT_FORMATS.get(artifact.artifact_type or "", "file"),
        title=artifact.title, filename=artifact.filename, size_bytes=artifact.size_bytes,
        created_at=artifact.created_at, prompt=prompt, dataset_name=dataset_name,
    )  # fmt: skip


def results(db: Session, ctx: TenantContext, job_id: UUID) -> JobResults:
    job, dataset, version = _load(db, ctx, job_id)
    findings = db.scalars(
        select(AnalysisResult)
        .where(AnalysisResult.job_id == job.id, AnalysisResult.organisation_id == ctx.organisation_id)
        .order_by(AnalysisResult.sequence)
    ).all()
    artifacts = db.scalars(
        select(Artifact)
        .where(Artifact.job_id == job.id, Artifact.organisation_id == ctx.organisation_id)
        .order_by(Artifact.artifact_type)
    ).all()
    return JobResults(
        job=_job_out(job, dataset, version),
        summary=job.result_summary if job.status in JobStatus.HAS_RESULTS else None,
        findings=[
            FindingOut(id=f.id, sequence=f.sequence, key=f.result_key, kind=f.result_type, title=f.title,
                       statement=f.finding, agent_key=f.agent_key, evidence_ref=f.evidence_ref,
                       evidence=f.evidence_json or {}, approved=f.approved)
            for f in findings
        ],
        reports=[_report_out(artifact, job.prompt, dataset.name if dataset else None) for artifact in artifacts],
    )  # fmt: skip


def list_reports(db: Session, ctx: TenantContext, limit: int) -> list[ReportOut]:
    rows = db.execute(
        select(Artifact, AnalysisJob.prompt, Dataset.name)
        .join(AnalysisJob, AnalysisJob.id == Artifact.job_id)
        .outerjoin(DatasetVersion, DatasetVersion.id == AnalysisJob.dataset_version_id)
        .outerjoin(Dataset, Dataset.id == DatasetVersion.dataset_id)
        .where(Artifact.organisation_id == ctx.organisation_id)
        .order_by(Artifact.created_at.desc(), Artifact.artifact_type)
        .limit(limit)
    ).all()
    return [_report_out(artifact, prompt, dataset_name) for artifact, prompt, dataset_name in rows]


def get_report(db: Session, ctx: TenantContext, report_id: UUID) -> Artifact:
    artifact = db.scalar(
        select(Artifact).where(Artifact.id == report_id, Artifact.organisation_id == ctx.organisation_id)
    )
    if artifact is None:
        raise NotFound("Report not found.")
    return artifact


def recent_agent_runs(db: Session, ctx: TenantContext, limit: int) -> list[AgentRunOut]:
    runs = db.scalars(
        select(AgentRun)
        .where(AgentRun.organisation_id == ctx.organisation_id)
        .order_by(AgentRun.started_at.desc())
        .limit(limit)
    ).all()
    return [
        AgentRunOut(agent_key=run.agent_key, agent_name=agent_name(run.agent_key), job_id=run.job_id,
                    status=run.status, started_at=run.started_at, duration_ms=run.duration_ms,
                    model_name=run.model_name, tokens_input=run.tokens_input or 0,
                    tokens_output=run.tokens_output or 0)
        for run in runs
    ]  # fmt: skip
