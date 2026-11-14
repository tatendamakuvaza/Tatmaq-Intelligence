"""Acceptance: duplicate requests create no duplicate work, charges or reports; jobs can be cancelled;
allowances are enforced."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import func, select

from app.core.database import system_session
from app.models import AgentRun, AnalysisJob, AnalysisResult, Artifact, AuditLog, UsageRecord
from conftest import run_queued_jobs

PROMPT = "Analyse my sales and identify my most profitable products."


def submit(account, version_id, key=None, prompt=PROMPT):
    headers = {"Idempotency-Key": key} if key else {}
    return account.post("/analysis-jobs", headers=headers, json={
        "workspace_id": account.workspace_id, "dataset_version_id": version_id, "prompt": prompt})  # fmt: skip


def count(model, **filters) -> int:
    with system_session() as session:
        return session.scalar(select(func.count()).select_from(model).filter_by(**filters))


def test_a_repeated_request_returns_the_same_job_and_charges_once(account, small_csv):
    version = account.upload(small_csv)["dataset_version_id"]
    key = str(uuid.uuid4())
    first, second = submit(account, version, key), submit(account, version, key)
    assert (first.status_code, second.status_code) == (202, 200)
    assert first.json()["job_id"] == second.json()["job_id"]
    run_queued_jobs()
    third = submit(account, version, key)  # the user clicks again after it has finished
    job_id = first.json()["job_id"]
    assert third.status_code == 200 and third.json() == {
        "job_id": job_id, "status": "completed", "message": "This analysis was already submitted."}  # fmt: skip
    assert run_queued_jobs() == []  # nothing new was queued

    assert count(AnalysisJob, organisation_id=account.organisation_id, job_type="analysis") == 1
    assert count(Artifact, job_id=job_id) == 3  # one PDF, one Excel, one HTML
    assert count(UsageRecord, job_id=job_id, metric="analyses") == 1
    assert account.get("/usage").json()["analyses"]["used"] == 1


def test_simultaneous_identical_requests_still_create_one_job(account, small_csv):
    version = account.upload(small_csv)["dataset_version_id"]
    key = str(uuid.uuid4())
    with ThreadPoolExecutor(8) as pool:
        responses = list(pool.map(lambda _: submit(account, version, key), range(8)))
    assert {response.status_code for response in responses} <= {200, 202}
    assert len({response.json()["job_id"] for response in responses}) == 1
    assert count(AnalysisJob, organisation_id=account.organisation_id, job_type="analysis") == 1


def test_an_idempotency_key_cannot_be_reused_for_a_different_request(account, small_csv):
    version = account.upload(small_csv)["dataset_version_id"]
    key = str(uuid.uuid4())
    assert submit(account, version, key).status_code == 202
    conflict = submit(account, version, key, prompt="Something else entirely")
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "idempotency_conflict"


def test_recording_usage_twice_for_the_same_job_counts_once(account, small_csv):
    from app.services import usage

    version = account.upload(small_csv)["dataset_version_id"]
    job = account.analyse(version, PROMPT)
    with system_session() as session:
        for _ in range(3):  # as a retried or crashed-and-resumed job would
            usage.record(session, organisation_id=account.organisation_id, job_id=job["id"], metric="analyses",
                         quantity=1, unit="job", source_key=f"job:{job['id']}")  # fmt: skip
    assert count(UsageRecord, job_id=job["id"], metric="analyses") == 1


def test_a_queued_job_is_cancelled_immediately_and_never_runs(account, small_csv):
    version = account.upload(small_csv)["dataset_version_id"]
    job_id = submit(account, version).json()["job_id"]
    cancelled = account.post(f"/analysis-jobs/{job_id}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert run_queued_jobs() == []
    assert count(AgentRun, job_id=job_id) == 0 and count(AnalysisResult, job_id=job_id) == 0
    assert account.post(f"/analysis-jobs/{job_id}/cancel").status_code == 409  # already finished
    assert account.get("/usage").json()["analyses"]["used"] == 0  # a cancelled job uses no allowance


def test_a_running_job_stops_at_the_next_step_when_cancelled(account, small_csv):
    from app.workers import queue
    from app.workers.runner import execute_job
    from conftest import get_settings

    version = account.upload(small_csv)["dataset_version_id"]
    job_id = submit(account, version).json()["job_id"]
    claim = queue.claim_next("test-worker")  # a worker has picked it up
    response = account.post(f"/analysis-jobs/{job_id}/cancel")
    assert response.json()["status"] == "validating_dataset" and response.json()["cancel_requested"] is True
    assert execute_job(claim, get_settings()) == "cancelled"
    job = account.get(f"/analysis-jobs/{job_id}").json()
    assert job["status"] == "cancelled" and count(AnalysisResult, job_id=job_id) == 0


def test_the_monthly_allowance_and_the_concurrency_limit_are_enforced(account, small_csv, settings, monkeypatch):
    version = account.upload(small_csv)["dataset_version_id"]
    monkeypatch.setattr(settings, "max_active_jobs_per_org", 2)
    assert submit(account, version).status_code == 202 and submit(account, version).status_code == 202
    busy = submit(account, version)
    assert busy.status_code == 429 and busy.json()["error"]["code"] == "too_many_active_jobs"
    run_queued_jobs()

    monkeypatch.setattr(settings, "plan_monthly_analysis_jobs", 2)
    exhausted = submit(account, version)
    assert exhausted.status_code == 429 and exhausted.json()["error"]["code"] == "allowance_exhausted"


def test_requests_are_validated(account, small_csv):
    version = account.upload(small_csv)["dataset_version_id"]
    assert submit(account, version, prompt="   ").status_code == 422
    assert submit(account, version, prompt="x" * 4001).status_code == 422
    assert submit(account, str(uuid.uuid4())).status_code == 404
    bad_type = account.post("/analysis-jobs", json={"workspace_id": account.workspace_id, "dataset_version_id": version,
                                                    "prompt": PROMPT, "analysis_type": "run_python"})  # fmt: skip
    assert bad_type.status_code == 422 and "error" in bad_type.json()


def test_sensitive_actions_are_written_to_the_audit_log(account, small_csv):
    version = account.upload(small_csv)["dataset_version_id"]
    job = account.analyse(version, PROMPT)
    report = account.get("/reports").json()[0]
    account.get(f"/reports/{report['id']}/download")
    with system_session() as session:
        entries = session.execute(
            select(AuditLog.action, AuditLog.actor_id).where(AuditLog.organisation_id == account.organisation_id)
        ).all()
    actions = [action for action, _ in entries]
    for expected in ("organisation.created", "dataset.upload_requested", "dataset.uploaded", "analysis.submitted",
                     "report.downloaded"):  # fmt: skip
        assert expected in actions
    assert {str(actor) for _, actor in entries} == {account.user_id}
    assert job["status"] == "completed"
