"""The job queue, kept in PostgreSQL (specification section 9.2).

``analysis_jobs`` is both the record of each job and the queue of work. No Redis or
message broker is needed. What makes that safe:

**Claiming**   ``SELECT ... FOR UPDATE SKIP LOCKED`` lets any number of workers ask for
               the next job at once; each row is handed to exactly one of them.
**Fencing**    A claim issues a random ``lock_token``. Every later write names it. If
               a worker is presumed dead and its job is handed to another, the first
               worker's token no longer matches, so anything it writes is refused.
**Heartbeats** A worker stamps its jobs regularly. A job whose stamp goes stale
               belonged to a worker that died; it returns to the queue, up to
               ``max_attempts`` times, so an interrupted analysis is not lost.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select, text, update

from ..core.database import system_session
from ..models import AnalysisJob, Dataset, DatasetStatus, DatasetVersion, JobStatus, JobType

CLAIM = text(
    """
    UPDATE analysis_jobs
    SET status = :claimed,
        locked_by = :worker,
        lock_token = :token,
        heartbeat_at = NOW(),
        started_at = COALESCE(started_at, NOW()),
        attempts = attempts + 1,
        updated_at = NOW()
    WHERE id = (
        SELECT id FROM analysis_jobs
        WHERE status = 'queued'
        ORDER BY priority, created_at
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    RETURNING id
    """
)


class JobLockLost(Exception):
    """This worker no longer owns the job. It must stop without writing anything further."""


class JobCancelled(Exception):
    """The customer asked for the job to stop."""


@dataclass(frozen=True)
class Claim:
    job_id: UUID
    lock_token: UUID


def claim_next(worker_id: str) -> Claim | None:
    """Take the highest-priority queued job, or return ``None`` if the queue is empty."""
    token = uuid.uuid4()
    with system_session() as session:
        row = session.execute(
            CLAIM, {"claimed": JobStatus.VALIDATING, "worker": worker_id, "token": token}
        ).one_or_none()
    return Claim(job_id=row.id, lock_token=token) if row else None


def _owned(job_id: UUID, lock_token: UUID) -> tuple:
    return (AnalysisJob.id == job_id, AnalysisJob.lock_token == lock_token,
            AnalysisJob.status.in_(JobStatus.IN_PROGRESS))  # fmt: skip


def set_status(job_id: UUID, lock_token: UUID, status: str) -> None:
    now = datetime.now(UTC)
    with system_session() as session:
        changed = session.execute(
            update(AnalysisJob)
            .where(*_owned(job_id, lock_token))
            .values(status=status, updated_at=now, heartbeat_at=now)
        ).rowcount
    if not changed:
        raise JobLockLost(str(job_id))


def checkpoint(job_id: UUID, lock_token: UUID) -> None:
    """Called between steps: stop if the job was cancelled or handed to another worker."""
    with system_session() as session:
        row = session.execute(select(AnalysisJob.cancel_requested_at).where(*_owned(job_id, lock_token))).one_or_none()
    if row is None:
        raise JobLockLost(str(job_id))
    if row.cancel_requested_at is not None:
        raise JobCancelled(str(job_id))


def heartbeat(claims: list[Claim]) -> dict[UUID, str]:
    """Stamp the jobs this worker holds. Returns each job's state: ``ok``, ``cancel`` or ``lost``."""
    states: dict[UUID, str] = {}
    now = datetime.now(UTC)
    with system_session() as session:
        for claim in claims:
            row = session.execute(
                update(AnalysisJob)
                .where(*_owned(claim.job_id, claim.lock_token))
                .values(heartbeat_at=now)
                .returning(AnalysisJob.cancel_requested_at)
            ).one_or_none()
            states[claim.job_id] = "lost" if row is None else ("cancel" if row.cancel_requested_at else "ok")
    return states


def _close_dataset(session: Any, job: AnalysisJob, message: str) -> None:
    """An ingestion job that ends without success leaves its dataset marked failed, never half-usable."""
    if job.job_type != JobType.INGESTION or job.dataset_version_id is None:
        return
    version = session.get(DatasetVersion, job.dataset_version_id)
    if version is None or version.status == DatasetStatus.READY:
        return
    version.status, version.error_message = DatasetStatus.FAILED, message
    dataset = session.get(Dataset, version.dataset_id)
    if dataset is not None:
        dataset.status, dataset.error_message, dataset.updated_at = DatasetStatus.FAILED, message, datetime.now(UTC)


def finish(
    job_id: UUID, lock_token: UUID, status: str, *, error_message: str | None = None,
    result_summary: dict[str, Any] | None = None,
) -> bool:  # fmt: skip
    """Move a job to a final state. Returns False if this worker no longer owns it."""
    now = datetime.now(UTC)
    with system_session() as session:
        job = session.scalar(select(AnalysisJob).where(*_owned(job_id, lock_token)).with_for_update())
        if job is None:
            return False
        job.status, job.completed_at, job.updated_at = status, now, now
        job.error_message = error_message
        if result_summary is not None:
            job.result_summary = result_summary
        job.locked_by = None
        if status in (JobStatus.FAILED, JobStatus.CANCELLED):
            _close_dataset(session, job, error_message or "The upload was cancelled.")
    return True


def retry_or_fail(job_id: UUID, lock_token: UUID, message: str) -> str:
    """After a crash: put the job back in the queue, or fail it once its attempts are used up."""
    with system_session() as session:
        job = session.scalar(select(AnalysisJob).where(*_owned(job_id, lock_token)).with_for_update())
        if job is None:
            return "lost"
        return _requeue(session, job, message)


def _requeue(session: Any, job: AnalysisJob, message: str) -> str:
    now = datetime.now(UTC)
    job.locked_by, job.lock_token, job.heartbeat_at, job.updated_at = None, None, None, now
    if job.cancel_requested_at is not None:
        job.status, job.completed_at = JobStatus.CANCELLED, now
        _close_dataset(session, job, "The upload was cancelled.")
        return JobStatus.CANCELLED
    if job.attempts < job.max_attempts:
        job.status = JobStatus.QUEUED
        return JobStatus.QUEUED
    job.status, job.completed_at, job.error_message = JobStatus.FAILED, now, message
    _close_dataset(session, job, message)
    return JobStatus.FAILED


def recover_stale(stale_after_seconds: int) -> list[tuple[UUID, str]]:
    """Find jobs whose worker stopped sending heartbeats and requeue (or fail) them."""
    cutoff = datetime.now(UTC) - timedelta(seconds=stale_after_seconds)
    recovered: list[tuple[UUID, str]] = []
    with system_session() as session:
        jobs = session.scalars(
            select(AnalysisJob)
            .where(AnalysisJob.status.in_(JobStatus.IN_PROGRESS), AnalysisJob.heartbeat_at < cutoff)
            .with_for_update(skip_locked=True)
        ).all()
        for job in jobs:
            outcome = _requeue(
                session, job,
                "The analysis was interrupted each time it was attempted and has been stopped. Please try again.",
            )  # fmt: skip
            recovered.append((job.id, outcome))
    return recovered
