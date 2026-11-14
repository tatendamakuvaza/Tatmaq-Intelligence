"""Acceptance: an interrupted worker does not lose an analysis; a failed agent can be retried safely;
no job runs twice."""

from __future__ import annotations

import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select, update

from app.core.database import system_session
from app.models import AgentRun, AgentTask, AnalysisJob, AnalysisResult, JobStatus
from app.workers import queue
from app.workers.runner import MEMORY_MESSAGE, execute_job
from app.workers.worker import Running, Worker
from conftest import run_queued_jobs

PROMPT = "Analyse my sales and identify my most profitable products."


@pytest.fixture(autouse=True)
def empty_queue():
    """Other tests leave jobs behind; these tests need to know exactly what is queued."""
    with system_session() as session:
        session.execute(update(AnalysisJob).where(AnalysisJob.status.in_(JobStatus.ACTIVE))
                        .values(status=JobStatus.CANCELLED, lock_token=None))  # fmt: skip


@pytest.fixture
def version(account, small_csv):
    return account.upload(small_csv)["dataset_version_id"]


def submit(account, version) -> str:
    return account.analyse(version, PROMPT, run=False)["id"]


def job_row(job_id) -> AnalysisJob:
    with system_session() as session:
        return session.get(AnalysisJob, job_id)


def runs_per_agent(job_id) -> dict[str, int]:
    with system_session() as session:
        return dict(session.execute(select(AgentRun.agent_key, func.count()).where(AgentRun.job_id == job_id)
                                    .group_by(AgentRun.agent_key)).all())  # fmt: skip


def test_each_queued_job_is_claimed_by_exactly_one_worker(account, version):
    job_ids = {submit(account, version) for _ in range(12)}

    def drain(worker: int) -> list:
        claimed = []
        while (claim := queue.claim_next(f"worker-{worker}")) is not None:
            claimed.append(str(claim.job_id))
        return claimed

    with ThreadPoolExecutor(6) as pool:
        claimed = [job for jobs in pool.map(drain, range(6)) for job in jobs]
    assert sorted(claimed) == sorted(job_ids)  # every job exactly once: none skipped, none doubled
    assert queue.claim_next("late-worker") is None


def test_jobs_are_claimed_by_priority_then_age(account, version):
    first, second, urgent = submit(account, version), submit(account, version), submit(account, version)
    with system_session() as session:
        session.execute(update(AnalysisJob).where(AnalysisJob.id == urgent).values(priority=1))
    order = [str(queue.claim_next("w").job_id) for _ in range(3)]
    assert order == [urgent, first, second]


def test_an_interrupted_worker_does_not_lose_the_analysis(account, version, settings, monkeypatch):
    from app.agents.orchestration.nodes import WorkflowNodes

    job_id = submit(account, version)
    genuine = WorkflowNodes.statistics

    async def power_cut(self, state):
        raise RuntimeError("the worker's machine lost power")

    monkeypatch.setattr(WorkflowNodes, "statistics", power_cut)
    with pytest.raises(RuntimeError):
        execute_job(queue.claim_next("worker-1"), settings)
    assert job_row(job_id).status == JobStatus.EXECUTING  # stranded mid-flight, exactly as after a real crash
    before = runs_per_agent(job_id)
    assert before == {"chief_intelligence": 1, "data_acquisition": 1, "data_cleaning": 1}

    monkeypatch.setattr(WorkflowNodes, "statistics", genuine)
    assert queue.recover_stale(stale_after_seconds=0) == [(job_row(job_id).id, JobStatus.QUEUED)]
    assert execute_job(queue.claim_next("worker-2"), settings) == JobStatus.COMPLETED

    job = account.get(f"/analysis-jobs/{job_id}").json()
    assert job["status"] == "completed" and job["attempts"] == 2
    after = runs_per_agent(job_id)
    # the three steps that had finished were not run again; only the remaining work was done
    assert {agent: after[agent] for agent in before} == before
    assert after["statistical_analysis"] == after["quality_verification"] == after["report_generation"] == 1
    assert len(account.get(f"/analysis-jobs/{job_id}/results").json()["reports"]) == 3


def test_a_worker_that_lost_its_job_cannot_write_to_it(account, version):
    job_id = submit(account, version)
    stale = queue.claim_next("worker-1")
    queue.recover_stale(stale_after_seconds=0)  # worker-1 is presumed dead
    fresh = queue.claim_next("worker-2")
    assert fresh.job_id == stale.job_id and fresh.lock_token != stale.lock_token

    with pytest.raises(queue.JobLockLost):  # worker-1 wakes up and tries to carry on
        queue.set_status(stale.job_id, stale.lock_token, JobStatus.REPORTING)
    with pytest.raises(queue.JobLockLost):
        queue.checkpoint(stale.job_id, stale.lock_token)
    assert queue.finish(stale.job_id, stale.lock_token, JobStatus.COMPLETED, result_summary={"forged": True}) is False
    assert queue.heartbeat([stale]) == {stale.job_id: "lost"}
    row = job_row(job_id)
    assert row.status == JobStatus.VALIDATING and row.lock_token == fresh.lock_token and row.result_summary is None


def test_a_job_that_keeps_crashing_is_failed_not_retried_forever(account, version, settings):
    job_id = submit(account, version)
    for attempt in range(1, settings.job_max_attempts + 1):
        assert queue.claim_next("crashing-worker") is not None
        outcome = queue.recover_stale(stale_after_seconds=0)[0][1]
        assert outcome == (JobStatus.QUEUED if attempt < settings.job_max_attempts else JobStatus.FAILED)
    job = account.get(f"/analysis-jobs/{job_id}").json()
    assert job["status"] == "failed" and "interrupted" in job["error_message"] and job["attempts"] == 3
    assert queue.claim_next("anyone") is None


def test_an_upload_whose_processing_keeps_crashing_ends_as_a_failed_dataset(account, small_csv, settings):
    upload = account.upload(small_csv, process=False)
    for _ in range(settings.job_max_attempts):
        queue.claim_next("crashing-worker")
        queue.recover_stale(stale_after_seconds=0)
    detail = account.get(f"/datasets/{upload['dataset_id']}").json()
    assert detail["status"] == "failed" and detail["latest_version"]["status"] == "failed"


def test_an_agent_that_fails_temporarily_is_retried_and_every_attempt_is_recorded(
    account, version, settings, monkeypatch
):
    from app.agents.base import RetryableAgentError
    from app.agents.orchestration import tasks
    from app.agents.statistical_analysis.agent import StatisticalAnalysisAgent

    genuine, calls = StatisticalAnalysisAgent.execute, []

    async def flaky(self, task):
        calls.append(1)
        if len(calls) < 3:
            raise RetryableAgentError("storage was briefly unreachable")
        return await genuine(self, task)

    monkeypatch.setattr(StatisticalAnalysisAgent, "execute", flaky)
    monkeypatch.setattr(tasks, "RETRY_DELAYS", (0, 0))
    job_id = submit(account, version)
    assert run_queued_jobs() == [JobStatus.COMPLETED]
    with system_session() as session:
        runs = session.execute(select(AgentRun.attempt, AgentRun.status, AgentRun.error_message)
                               .where(AgentRun.job_id == job_id, AgentRun.agent_key == "statistical_analysis")
                               .order_by(AgentRun.attempt)).all()  # fmt: skip
        task_status = session.scalar(
            select(AgentTask.status).where(AgentTask.job_id == job_id, AgentTask.sequence == 4)
        )
    assert [(r.attempt, r.status) for r in runs] == [(1, "failed"), (2, "failed"), (3, "completed")]
    assert runs[0].error_message == "storage was briefly unreachable" and task_status == "completed"


def test_an_agent_failure_fails_the_job_with_a_plain_message_and_publishes_nothing(account, version, monkeypatch):
    from app.agents.statistical_analysis.agent import StatisticalAnalysisAgent

    async def broken(self, task):
        raise ZeroDivisionError("internal detail that customers should not see: /srv/app/secret.py line 12")

    monkeypatch.setattr(StatisticalAnalysisAgent, "execute", broken)
    job = account.analyse(version, PROMPT)
    assert job["status"] == "failed"
    assert job["error_message"] == ("An unexpected problem stopped the Statistical Analysis Agent. "
                                    "It has been logged for investigation.")  # fmt: skip
    with system_session() as session:
        assert (
            session.scalar(select(func.count()).select_from(AnalysisResult).where(AnalysisResult.job_id == job["id"]))
            == 0
        )
        recorded = session.scalar(
            select(AgentRun.error_message).where(AgentRun.job_id == job["id"], AgentRun.status == "failed")
        )
    assert "ZeroDivisionError" in recorded  # the detail is kept for engineers


# --------------------------------------------------------------------------- the supervising worker


def tick_until(worker: Worker, done, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while not done():
        assert time.monotonic() < deadline, "timed out waiting for the worker"
        worker.tick()
        time.sleep(0.1)


def supervise_fake_child(worker: Worker, command: list[str]) -> queue.Claim:
    """Give the worker a claimed job whose 'process' is a stand-in we control."""
    claim = queue.claim_next(worker.worker_id)
    worker.running[claim.job_id] = Running(claim=claim, process=subprocess.Popen(command), started=time.monotonic())
    return claim


def test_the_worker_runs_a_job_in_a_child_process(account, version, settings):
    job_id = submit(account, version)
    worker = Worker(settings)
    # the child records the outcome just before it exits, so wait for the worker to see it leave too
    tick_until(worker, lambda: job_row(job_id).status in JobStatus.TERMINAL and not worker.running)
    assert job_row(job_id).status == JobStatus.COMPLETED
    assert not any(settings.work_dir.glob("*")), "the job's temporary folder was not cleaned up"


def test_cancelling_a_running_job_stops_its_process(account, version, settings):
    job_id = submit(account, version)
    worker = Worker(settings)
    claim = supervise_fake_child(worker, ["sleep", "60"])
    process = worker.running[claim.job_id].process
    assert account.post(f"/analysis-jobs/{job_id}/cancel").json()["cancel_requested"] is True
    tick_until(worker, lambda: job_row(job_id).status == JobStatus.CANCELLED, timeout=15)
    assert process.poll() is not None and not worker.running


def test_a_job_over_its_time_limit_is_stopped(account, version, settings, monkeypatch):
    job_id = submit(account, version)
    worker = Worker(settings)
    supervise_fake_child(worker, ["sleep", "60"])
    monkeypatch.setattr(settings, "job_timeout_seconds", 0)
    tick_until(worker, lambda: job_row(job_id).status == JobStatus.FAILED, timeout=15)
    assert "longer than the 0-minute limit" in job_row(job_id).error_message


def test_a_job_killed_by_the_operating_system_fails_with_a_helpful_message(account, version, settings):
    job_id = submit(account, version)
    worker = Worker(settings)
    supervise_fake_child(worker, ["sh", "-c", "kill -9 $$"])  # what the kernel's out-of-memory killer does
    tick_until(worker, lambda: job_row(job_id).status == JobStatus.FAILED, timeout=15)
    assert job_row(job_id).error_message == MEMORY_MESSAGE


def test_a_worker_shutting_down_hands_its_jobs_back(account, version, settings):
    job_id = submit(account, version)
    worker = Worker(settings)
    supervise_fake_child(worker, ["sleep", "60"])
    worker.shutdown()
    row = job_row(job_id)
    assert row.status == JobStatus.QUEUED and row.lock_token is None
    assert run_queued_jobs() == [JobStatus.COMPLETED]  # another worker finishes it


def test_the_memory_limit_stops_a_runaway_allocation():
    script = (
        "from app.workers.limits import apply_resource_limits\n"
        "assert apply_resource_limits(300)\n"
        "try:\n    block = bytearray(1024 * 1024 * 1024)\n    print('allocated')\n"
        "except MemoryError:\n    print('refused')\n"
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30)
    assert result.stdout.strip() == "refused", result.stderr
