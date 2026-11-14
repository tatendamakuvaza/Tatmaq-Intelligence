"""Runs one claimed job from start to finish.

Normally this is the entry point of a short-lived child process started by the worker:

    python -m app.workers.runner <job_id> <lock_token>

so that a job which exhausts memory or hangs can be stopped without affecting the
worker or other jobs. ``execute_job`` can also be called in-process (tests do).
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys
import tempfile
from uuid import UUID

from ..agents.orchestration.context import JobContext
from ..agents.orchestration.graph import RECURSION_LIMIT, build_analysis_graph, build_ingestion_graph
from ..agents.orchestration.nodes import WorkflowNodes
from ..core.config import Settings, get_settings
from ..core.logging import configure_logging
from ..llm import build_llm
from ..models import JobStatus, JobType
from ..storage import get_storage
from . import queue
from .limits import apply_resource_limits

logger = logging.getLogger(__name__)

#: Exit status telling the worker "temporary failure: put the job back in the queue".
EXIT_RETRY = 75
MEMORY_MESSAGE = ("This dataset is too large to process within the memory available. Try a smaller file, "
                  "for example one year of data at a time.")  # fmt: skip


def execute_job(claim: queue.Claim, settings: Settings) -> str:
    """Run the job's workflow. Returns the status the job ended in."""
    workdir = settings.work_dir / str(claim.job_id)
    workdir.mkdir(parents=True, exist_ok=True)
    previous_tempdir = tempfile.tempdir
    tempfile.tempdir = str(workdir)  # every temporary file an agent creates lands in the job's own folder
    extra = {"job_id": str(claim.job_id)}
    try:
        ctx = JobContext.for_claim(claim, settings, get_storage(), build_llm(settings), workdir)
        nodes = WorkflowNodes(ctx)
        graph = build_ingestion_graph(nodes) if ctx.job_type == JobType.INGESTION else build_analysis_graph(nodes)
        initial = {"job_id": str(ctx.job_id), "organisation_id": str(ctx.organisation_id), "user_prompt": ctx.prompt,
                   "analysis_type": ctx.analysis_type, "errors": [], "status": "running"}  # fmt: skip
        logger.info("job started", extra={**extra, "job_type": ctx.job_type})
        final = asyncio.run(graph.ainvoke(initial, {"recursion_limit": RECURSION_LIMIT}))
        logger.info("job finished", extra={**extra, "status": final.get("status")})
        return final.get("status", JobStatus.FAILED)
    except queue.JobCancelled:
        queue.finish(claim.job_id, claim.lock_token, JobStatus.CANCELLED, error_message="Cancelled at your request.")
        logger.info("job cancelled", extra=extra)
        return JobStatus.CANCELLED
    except queue.JobLockLost:
        logger.warning("job is no longer owned by this worker; stopping without writing", extra=extra)
        return "lost"
    except MemoryError:
        queue.finish(claim.job_id, claim.lock_token, JobStatus.FAILED, error_message=MEMORY_MESSAGE)
        logger.error("job exceeded its memory limit", extra=extra)
        return JobStatus.FAILED
    finally:
        tempfile.tempdir = previous_tempdir
        shutil.rmtree(workdir, ignore_errors=True)


def main(argv: list[str]) -> int:
    settings = get_settings()
    apply_resource_limits(settings.job_max_memory_mb)
    configure_logging()
    claim = queue.Claim(job_id=UUID(argv[1]), lock_token=UUID(argv[2]))
    try:
        execute_job(claim, settings)
    except Exception:
        logger.exception("job crashed", extra={"job_id": str(claim.job_id)})
        return EXIT_RETRY
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
