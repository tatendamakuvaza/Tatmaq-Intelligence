"""Usage accounting and the plan allowance."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..core.config import Settings
from ..models import AnalysisJob, Artifact, Dataset, DatasetVersion, JobStatus, JobType, UsageRecord
from ..security.tenancy import TenantContext

#: Jobs in these states count against the monthly allowance. Failed and cancelled jobs do not.
COUNTED_STATUSES = (*JobStatus.ACTIVE, JobStatus.COMPLETED, JobStatus.PARTIAL)


def month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def record(
    session: Session, *, organisation_id: UUID, metric: str, quantity: int | float | Decimal, unit: str,
    source_key: str, job_id: UUID | None = None,
) -> None:  # fmt: skip
    """Record usage once per (metric, source).

    A job that is retried, or a worker that crashes after recording, reaches this
    again with the same ``source_key``; the second write is ignored, so nothing is
    ever counted (or charged) twice.
    """
    session.execute(
        pg_insert(UsageRecord)
        .values(id=uuid.uuid4(), organisation_id=organisation_id, job_id=job_id, metric=metric,
                quantity=Decimal(str(quantity)), unit=unit, source_key=source_key)
        .on_conflict_do_nothing(constraint="usage_records_source_key")
    )  # fmt: skip


def analyses_this_month(db: Session, organisation_id: UUID) -> int:
    return db.scalar(
        select(func.count())
        .select_from(AnalysisJob)
        .where(
            AnalysisJob.organisation_id == organisation_id,
            AnalysisJob.job_type == JobType.ANALYSIS,
            AnalysisJob.status.in_(COUNTED_STATUSES),
            AnalysisJob.created_at >= month_start(),
        )
    )


def summary(db: Session, ctx: TenantContext, settings: Settings) -> dict[str, Any]:
    start = month_start()
    organisation_id = ctx.organisation_id
    metrics = dict(
        db.execute(
            select(UsageRecord.metric, func.sum(UsageRecord.quantity))
            .where(UsageRecord.organisation_id == organisation_id, UsageRecord.recorded_at >= start)
            .group_by(UsageRecord.metric)
        ).all()
    )
    return {
        "period_start": start,
        "analyses": {"used": analyses_this_month(db, organisation_id), "limit": settings.plan_monthly_analysis_jobs},
        "this_month": {name: float(total) for name, total in sorted(metrics.items())},
        "totals": {
            "datasets": db.scalar(
                select(func.count()).select_from(Dataset).where(Dataset.organisation_id == organisation_id)
            ),
            "reports": db.scalar(
                select(func.count()).select_from(Artifact).where(Artifact.organisation_id == organisation_id)
            ),
            "storage_bytes": int(
                db.scalar(
                    select(func.coalesce(func.sum(DatasetVersion.size_bytes), 0)).where(
                        DatasetVersion.organisation_id == organisation_id
                    )
                )
            ),
        },
        "limits": {
            "max_upload_mb": settings.max_upload_mb,
            "max_analysis_rows": settings.max_analysis_rows,
            "max_active_jobs": settings.max_active_jobs_per_org,
        },
    }
