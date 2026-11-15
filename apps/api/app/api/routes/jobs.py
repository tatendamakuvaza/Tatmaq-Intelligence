"""Analysis jobs, agent activity, results and reports."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Response

from ...agents.base.registry import AGENTS
from ...models import JobStatus
from ...schemas.jobs import AgentActivity, DownloadLink, JobAccepted, JobOut, JobRequest, JobResults, ReportOut
from ...schemas.learning import JobFeedbackIn
from ...services import audit, jobs, learning, usage
from ..deps import AppSettings, Db, FileStorage, Tenant

router = APIRouter(tags=["analysis"])

CONTENT_TYPES = {
    "report_pdf": "application/pdf",
    "report_xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "report_html": "text/html; charset=utf-8",
}


@router.post("/analysis-jobs", response_model=JobAccepted, status_code=202)
def submit_job(
    body: JobRequest, response: Response, ctx: Tenant, db: Db, settings: AppSettings,
    idempotency_key: Annotated[str | None, Header(max_length=150)] = None,
) -> JobAccepted:  # fmt: skip
    """Queue an analysis.

    Send an ``Idempotency-Key`` header (any unique string per click) and a repeated
    request returns the original job instead of starting, and counting, a second one.
    """
    job, created = jobs.submit(
        db, ctx, settings, workspace_id=body.workspace_id, dataset_version_id=body.dataset_version_id,
        prompt=body.prompt, analysis_type=body.analysis_type, idempotency_key=idempotency_key,
    )  # fmt: skip
    if not created:
        response.status_code = 200
    message = "Your analysis has been submitted." if created else "This analysis was already submitted."
    return JobAccepted(job_id=job.id, status=job.status if not created else JobStatus.QUEUED, message=message)


@router.get("/analysis-jobs", response_model=list[JobOut])
def list_jobs(
    ctx: Tenant, db: Db, workspace_id: UUID | None = None, limit: Annotated[int, Query(ge=1, le=100)] = 20
) -> list[JobOut]:
    return jobs.list_jobs(db, ctx, workspace_id, limit)


@router.get("/analysis-jobs/{job_id}", response_model=JobOut)
def get_job(job_id: UUID, ctx: Tenant, db: Db) -> JobOut:
    return jobs.get(db, ctx, job_id)


@router.get("/analysis-jobs/{job_id}/results", response_model=JobResults)
def get_results(job_id: UUID, ctx: Tenant, db: Db) -> JobResults:
    return jobs.results(db, ctx, job_id)


@router.get("/analysis-jobs/{job_id}/agents", response_model=AgentActivity)
def get_agent_activity(job_id: UUID, ctx: Tenant, db: Db) -> AgentActivity:
    return jobs.agent_activity(db, ctx, job_id)


@router.post("/analysis-jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: UUID, ctx: Tenant, db: Db) -> JobOut:
    return jobs.cancel(db, ctx, job_id)


@router.post("/analysis-jobs/{job_id}/feedback", tags=["analysis"])
def submit_feedback(job_id: UUID, body: JobFeedbackIn, ctx: Tenant, db: Db) -> dict:
    """Record executive feedback on a completed analysis. A lesson is saved only for roles with learning:write."""
    job = jobs.get(db, ctx, job_id)
    audit.record(
        db,
        organisation_id=ctx.organisation_id,
        actor_id=ctx.user.id,
        action="analysis.feedback",
        resource_type="analysis_job",
        resource_id=job.id,
        details={"rating": body.rating},
    )
    lesson_saved = False
    if body.lesson and ctx.can("learning:write"):
        learning.add_lesson(db, ctx, body.lesson, source=f"analysis {job.id}")
        lesson_saved = True
    else:
        db.commit()
    return {"recorded": True, "lesson_saved": lesson_saved}


@router.get("/reports", response_model=list[ReportOut], tags=["reports"])
def list_reports(ctx: Tenant, db: Db, limit: Annotated[int, Query(ge=1, le=200)] = 60) -> list[ReportOut]:
    return jobs.list_reports(db, ctx, limit)


@router.get("/reports/{report_id}/download", response_model=DownloadLink, tags=["reports"])
def download_report(report_id: UUID, ctx: Tenant, db: Db, storage: FileStorage, settings: AppSettings) -> DownloadLink:
    """Return a short-lived link to the report file. The download is recorded in the audit log."""
    ctx.require("reports:download")
    artifact = jobs.get_report(db, ctx, report_id)
    content_type = artifact.content_type or CONTENT_TYPES.get(artifact.artifact_type or "", "application/octet-stream")
    filename = artifact.filename or "report"
    url = storage.create_download_url(
        artifact.storage_path, filename=filename, content_type=content_type,
        ttl_seconds=settings.download_url_ttl_seconds,
    )  # fmt: skip
    audit.record(db, organisation_id=ctx.organisation_id, actor_id=ctx.user.id, action="report.downloaded",
                 resource_type="artifact", resource_id=artifact.id, details={"filename": filename})  # fmt: skip
    db.commit()
    return DownloadLink(url=url, filename=filename, content_type=content_type,
                        expires_in=settings.download_url_ttl_seconds)  # fmt: skip


@router.get("/usage", tags=["usage"])
def get_usage(ctx: Tenant, db: Db, settings: AppSettings) -> dict:
    return usage.summary(db, ctx, settings)


@router.get("/agents", tags=["agents"])
def list_agents(ctx: Tenant, db: Db, settings: AppSettings) -> dict:
    """The agent team, what each may use, and this organisation's recent agent activity."""
    return {
        "ai_model": {
            "enabled": settings.ai_enabled,
            "provider": settings.ai_provider,
            "model": settings.ai_model or None,
        },
        "agents": [
            {
                "key": agent.key, "number": agent.number, "name": agent.name, "role": agent.role,
                "summary": agent.summary, "responsibilities": agent.responsibilities,
                "restrictions": agent.restrictions, "tools": agent.tools,
                "uses_ai_model": agent.uses_ai_model,
            }
            for agent in AGENTS
        ],
        "recent_runs": jobs.recent_agent_runs(db, ctx, 25),
    }  # fmt: skip
