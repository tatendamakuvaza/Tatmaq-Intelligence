"""Running one task and recording exactly what happened.

Every task gets a row in ``agent_tasks``; every attempt at it gets a row in
``agent_runs`` with its input fingerprint, output, duration and any AI token use.
That record is also what makes a job resumable: if a worker dies and the job is
picked up again, a task whose identical input already completed is not run again;
its stored output is reused (specification 4.3: "recoverable after worker
interruptions and protected against duplicate execution").
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import func, select

from ...core.database import system_session
from ...models import AgentRun, AgentTask, TaskStatus
from ...storage.base import ObjectExists, ObjectNotFound, StorageError, TenantBoundaryError
from ...workers.queue import JobCancelled, JobLockLost
from ..base import AgentError, AgentResult, RetryableAgentError
from ..base import AgentTask as TaskContract
from ..base.registry import AGENTS, agent_name, load_agent
from .context import JobContext

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
RETRY_DELAYS = (0.5, 2.0)
_AGENT_KEYS = {agent.key for agent in AGENTS}


@dataclass
class TaskOutcome:
    result: dict[str, Any] | None = None
    error: str | None = None
    reused: bool = False

    @property
    def ok(self) -> bool:
        return self.result is not None


def _fingerprint(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _is_temporary(error: BaseException) -> bool:
    """Failures worth another attempt: a network blip or a storage hiccup, not a bad file."""
    if isinstance(error, RetryableAgentError | httpx.TransportError):
        return True
    return isinstance(error, StorageError) and not isinstance(
        error, ObjectNotFound | ObjectExists | TenantBoundaryError
    )


def ensure_tasks(ctx: JobContext, plan: list[dict[str, Any]]) -> None:
    """Create a pending task row for each step of a plan, so the whole plan is visible from the start."""
    with system_session() as session:
        existing = set(session.scalars(select(AgentTask.sequence).where(AgentTask.job_id == ctx.job_id)))
        for step in plan:
            if step["sequence"] not in existing:
                session.add(AgentTask(
                    organisation_id=ctx.organisation_id, job_id=ctx.job_id, sequence=step["sequence"],
                    agent_key=step["agent"], action=step["action"], dependencies=step.get("depends_on", []),
                ))  # fmt: skip


async def run_task(
    ctx: JobContext, *, sequence: int, agent_key: str, action: str, inputs: dict[str, Any],
    dataset_refs: dict[str, Any] | None = None,
    executor: Callable[[], Awaitable[dict[str, Any]]] | None = None,
) -> TaskOutcome:  # fmt: skip
    """Run a task (or reuse its stored result) and record the attempt.

    ``executor`` supplies the work for steps that are not agents (quality verification).
    """
    ctx.checkpoint()
    fingerprint = _fingerprint({"action": action, "inputs": inputs, "dataset_refs": dataset_refs})

    with system_session() as session:
        task = session.scalar(select(AgentTask).where(AgentTask.job_id == ctx.job_id, AgentTask.sequence == sequence))
        if task is None:
            task = AgentTask(organisation_id=ctx.organisation_id, job_id=ctx.job_id, sequence=sequence,
                             agent_key=agent_key, action=action)  # fmt: skip
            session.add(task)
            session.flush()
        previous = session.scalar(
            select(AgentRun)
            .where(AgentRun.task_id == task.id, AgentRun.status == "completed",
                   AgentRun.input_json["fingerprint"].astext == fingerprint)
            .order_by(AgentRun.started_at.desc())
        )  # fmt: skip
        if previous is not None:
            task.status = TaskStatus.COMPLETED
            return TaskOutcome(result=previous.output_json, reused=True)
        task.status, task.started_at, task.completed_at = TaskStatus.RUNNING, task.started_at or datetime.now(UTC), None
        task.task_input = {"action": action, "fingerprint": fingerprint}
        task_id = task.id
        attempts_so_far = session.scalar(select(func.count()).select_from(AgentRun).where(AgentRun.task_id == task_id))

    def record(run_attempt: int, status: str, started: float, *, output: dict[str, Any] | None = None,
               error: str | None = None, task_status: str | None = None) -> None:  # fmt: skip
        metrics = (output or {}).get("metrics") or {}
        with system_session() as session:
            session.add(AgentRun(
                organisation_id=ctx.organisation_id, job_id=ctx.job_id, task_id=task_id, agent_key=agent_key,
                attempt=run_attempt, status=status, output_json=output, error_message=error,
                input_json={"fingerprint": fingerprint, "action": action, "dataset_refs": dataset_refs or {},
                            "input_keys": sorted(inputs)},
                model_name=metrics.get("model_name"), tokens_input=metrics.get("tokens_input", 0),
                tokens_output=metrics.get("tokens_output", 0), duration_ms=int((time.monotonic() - started) * 1000),
                completed_at=datetime.now(UTC),
            ))  # fmt: skip
            if task_status:
                row = session.get(AgentTask, task_id)
                row.status, row.completed_at = task_status, datetime.now(UTC)

    for attempt in range(1, MAX_ATTEMPTS + 1):
        number, started = attempts_so_far + attempt, time.monotonic()
        try:
            if executor is not None:
                output = await executor()
            else:
                output = await _run_agent(ctx, agent_key, action, inputs, dataset_refs or {})
        except (JobCancelled, JobLockLost):
            raise
        except AgentError as error:
            if _is_temporary(error) and attempt < MAX_ATTEMPTS:
                record(number, "failed", started, error=str(error))
                await asyncio.sleep(RETRY_DELAYS[attempt - 1])
                continue
            record(number, "failed", started, error=str(error), task_status=TaskStatus.FAILED)
            return TaskOutcome(error=str(error))
        except MemoryError:
            record(number, "failed", started, error="out of memory", task_status=TaskStatus.FAILED)
            raise
        except Exception as error:
            if _is_temporary(error) and attempt < MAX_ATTEMPTS:
                record(number, "failed", started, error=f"{type(error).__name__}: {error}"[:2000])
                await asyncio.sleep(RETRY_DELAYS[attempt - 1])
                continue
            logger.exception("task %s (%s) failed", sequence, agent_key, extra={"job_id": str(ctx.job_id)})
            record(number, "failed", started, error=f"{type(error).__name__}: {error}"[:2000],
                   task_status=TaskStatus.FAILED)  # fmt: skip
            # Internal detail stays in the run record and the logs; the customer gets a plain message.
            return TaskOutcome(error=f"An unexpected problem stopped the {agent_name(agent_key)}. "
                                     "It has been logged for investigation.")  # fmt: skip
        record(number, "completed", started, output=output, task_status=TaskStatus.COMPLETED)
        return TaskOutcome(result=output)
    raise AssertionError("unreachable")  # pragma: no cover


async def _run_agent(ctx: JobContext, agent_key: str, action: str, inputs: dict[str, Any],
                     dataset_refs: dict[str, Any]) -> dict[str, Any]:  # fmt: skip
    if agent_key not in _AGENT_KEYS:
        raise AgentError(f"There is no agent called '{agent_key}'.")
    toolbox = ctx.toolbox(agent_key)
    contract = TaskContract(
        job_id=ctx.job_id, organisation_id=ctx.organisation_id, agent_key=agent_key, action=action,  # type: ignore[arg-type]
        user_instruction=ctx.prompt, dataset_version_id=ctx.dataset_version_id, dataset_refs=dataset_refs,
        permitted_tools=toolbox.permitted, limits=ctx.limits(), inputs=inputs,
    )  # fmt: skip
    result = await load_agent(agent_key, toolbox).execute(contract)
    # Accept only a well-formed result from the agent that was asked (specification Part E).
    if not isinstance(result, AgentResult) or result.agent_key != agent_key:
        raise AgentError(f"The {agent_name(agent_key)} returned a result in the wrong form.")
    validated = AgentResult.model_validate(result.model_dump())
    if validated.status != "completed":
        raise AgentError(validated.summary)
    return validated.model_dump(mode="json")
