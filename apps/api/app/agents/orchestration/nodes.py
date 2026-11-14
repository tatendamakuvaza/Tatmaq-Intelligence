"""The workflow steps. Each step runs one task and saves what the next step needs.

Agents never write to the database; these steps do it for them, with the worker's
privileges, after the agent's result has been validated.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ...analytics.spec import OPERATION_TITLES, AnalysisSpec
from ...core.database import system_session
from ...models import AnalysisResult, Artifact, Dataset, DatasetColumn, DatasetStatus, DatasetVersion, JobStatus
from ...services import usage
from ...storage.base import StorageError, report_key
from ...workers import queue
from ..base.permissions import TOOL_CLEANED_READ
from . import routing
from .context import ContextError, JobContext
from .state import AnalysisState, failed
from .tasks import ensure_tasks, run_task

logger = logging.getLogger(__name__)

INGESTION_PLAN = [
    {"sequence": 1, "agent": "data_acquisition", "action": "import_and_profile", "depends_on": []},
    {"sequence": 2, "agent": "data_cleaning", "action": "clean_and_validate", "depends_on": [1]},
]


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


class WorkflowNodes:
    def __init__(self, ctx: JobContext) -> None:
        self.ctx = ctx

    # ------------------------------------------------------------------ shared
    def _preflight(self, state: AnalysisState) -> dict[str, Any]:
        ctx = self.ctx
        ctx.checkpoint()
        try:
            dataset = ctx.load_dataset()
        except (ContextError, StorageError) as error:
            return failed(state, "validating_dataset", str(error))
        return {"dataset_id": str(dataset.dataset_id), "dataset_version_id": str(dataset.version_id)}

    # ---------------------------------------------------------------- analysis
    async def preflight(self, state: AnalysisState) -> dict[str, Any]:
        return self._preflight(state)

    async def planning(self, state: AnalysisState) -> dict[str, Any]:
        ctx = self.ctx
        ctx.set_status(JobStatus.PLANNING)
        outcome = await run_task(
            ctx, sequence=1, agent_key="chief_intelligence", action="plan_analysis",
            inputs={"columns": ctx.dataset.profile.get("columns_detail", []), "analysis_type": ctx.analysis_type,
                    "excluded_operations": sorted(state.get("excluded_operations", [])),
                    "learning_profile": ctx.organisation.get("learning_profile") or {}},
        )  # fmt: skip
        if not outcome.ok:
            return failed(state, "planning", outcome.error)
        plan = outcome.result["outputs"]["execution_plan"]
        ensure_tasks(ctx, plan)
        return {"planning_result": outcome.result, "execution_plan": plan,
                "analysis_spec": outcome.result["outputs"]["analysis_spec"]}  # fmt: skip

    async def acquisition(self, state: AnalysisState) -> dict[str, Any]:
        ctx, dataset = self.ctx, self.ctx.dataset
        ctx.set_status(JobStatus.EXECUTING)
        outcome = await run_task(
            ctx, sequence=2, agent_key="data_acquisition", action="verify_and_load", inputs={},
            dataset_refs={"original_path": dataset.original_path, "sha256": dataset.sha256,
                          "rows": dataset.rows, "columns": dataset.columns},
        )  # fmt: skip
        return (
            {"acquisition_result": outcome.result} if outcome.ok else failed(state, "data_acquisition", outcome.error)
        )

    async def cleaning(self, state: AnalysisState) -> dict[str, Any]:
        ctx, dataset = self.ctx, self.ctx.dataset
        outcome = await run_task(
            ctx, sequence=3, agent_key="data_cleaning", action="validate_for_analysis",
            inputs={"analysis_spec": state["analysis_spec"], "cleaning": dataset.cleaning,
                    "currency": ctx.organisation["currency"]},
            dataset_refs={"cleaned_path": dataset.cleaned_path, "rows": dataset.rows},
        )  # fmt: skip
        if not outcome.ok:
            return failed(state, "data_cleaning", outcome.error)
        update: dict[str, Any] = {"cleaning_result": outcome.result}
        infeasible = outcome.result["outputs"]["infeasible"]
        if infeasible:
            # "A failed validation should send the workflow back for correction" - once.
            if state.get("replans", 0) >= routing.MAX_REPLANS:
                reasons = "; ".join(f"{c['title']}: {c['reason']}" for c in outcome.result["outputs"]["operations"]
                                    if not c["feasible"])  # fmt: skip
                return {
                    **update,
                    **failed(state, "data_cleaning", f"The data cannot support this analysis ({reasons})."),
                }
            update["replans"] = state.get("replans", 0) + 1
            update["excluded_operations"] = _unique([*state.get("excluded_operations", []), *infeasible])
        return update

    async def statistics(self, state: AnalysisState) -> dict[str, Any]:
        ctx, dataset = self.ctx, self.ctx.dataset
        roles = dataset.profile.get("roles", {})
        outcome = await run_task(
            ctx, sequence=4, agent_key="statistical_analysis", action="run_analysis",
            inputs={"analysis_spec": state["analysis_spec"], "default_currency": ctx.organisation["currency"],
                    "cleaning": dataset.cleaning, "attempt": state.get("statistics_attempts", 0),
                    "context_columns": [roles[r] for r in ("identifier", "date", "product") if r in roles]},
            dataset_refs={"cleaned_path": dataset.cleaned_path, "sha256": dataset.sha256},
        )  # fmt: skip
        return (
            {"statistical_result": outcome.result}
            if outcome.ok
            else failed(state, "statistical_analysis", outcome.error)
        )

    async def verification(self, state: AnalysisState) -> dict[str, Any]:
        ctx, dataset = self.ctx, self.ctx.dataset
        ctx.set_status(JobStatus.VERIFYING)
        statistical = state["statistical_result"]

        async def verify() -> dict[str, Any]:
            from ...analytics.verification import verify_results  # deferred: imports the analytics stack

            frame = ctx.tools[TOOL_CLEANED_READ](dataset.cleaned_path)
            outcome = verify_results(
                frame, AnalysisSpec.model_validate(state["analysis_spec"]), statistical["outputs"],
                statistical["findings"], statistical["evidence"], default_currency=ctx.organisation["currency"],
                dataset_version_id=str(dataset.version_id), dataset_sha256=dataset.sha256,
            )  # fmt: skip
            passed = sum(1 for check in outcome["checks"] if check["passed"])
            failures = [check["name"] for check in outcome["checks"] if not check["passed"]]
            return {
                "agent_key": "quality_verification", "status": "completed",
                "summary": (f"All {passed} reconciliation checks passed: the parts add up to the totals and the "
                            "totals agree with an independent recalculation." if not failures else
                            f"{len(failures)} of {len(outcome['checks'])} reconciliation checks failed."),
                "warnings": failures,
                "outputs": {**outcome, "verified_at": datetime.now(UTC).isoformat(timespec="seconds")},
            }  # fmt: skip

        outcome = await run_task(
            ctx, sequence=5, agent_key="quality_verification", action="verify_results", executor=verify,
            inputs={"statistics_fingerprint": statistical["metrics"], "attempt": state.get("statistics_attempts", 0),
                    "findings": len(statistical["findings"])},
        )  # fmt: skip
        if not outcome.ok:
            return failed(state, "quality_verification", outcome.error)
        update: dict[str, Any] = {"verification_result": outcome.result}
        if outcome.result["outputs"]["passed"]:
            self._store_findings(statistical)
            return update
        attempts = state.get("statistics_attempts", 0) + 1
        if attempts >= routing.MAX_STATISTICS_ATTEMPTS:
            return {**update, **failed(
                state, "quality_verification",
                "The results did not pass verification, so they were not reported. Nothing has been published "
                "from this analysis; please try again or contact support.")}  # fmt: skip
        return {**update, "statistics_attempts": attempts}

    def _store_findings(self, statistical: dict[str, Any]) -> None:
        """Publish verified findings. Replaces any earlier set for the job, so a retry cannot duplicate them."""
        evidence = {record["ref"]: record for record in statistical["evidence"]}
        with system_session() as session:
            session.execute(delete(AnalysisResult).where(AnalysisResult.job_id == self.ctx.job_id))
            for sequence, finding in enumerate(statistical["findings"], start=1):
                session.add(AnalysisResult(
                    organisation_id=self.ctx.organisation_id, job_id=self.ctx.job_id, agent_key="statistical_analysis",
                    sequence=sequence, result_type=finding["kind"], result_key=finding["key"][:150],
                    title=finding["title"][:255], finding=finding["statement"], evidence_ref=finding["evidence_ref"],
                    evidence_json={**evidence.get(finding["evidence_ref"], {}), "segment": finding.get("segment"),
                                   "importance": finding["importance"]},
                    approved=True,
                ))  # fmt: skip

    def _notes(self, state: AnalysisState) -> tuple[list[str], list[str]]:
        results = [state.get(key) or {} for key in ("planning_result", "cleaning_result", "statistical_result")]
        warnings = _unique([w for result in results for w in result.get("warnings", [])])
        assumptions = _unique([a for result in results[1:] for a in result.get("assumptions", [])])
        return warnings, assumptions

    async def reporting(self, state: AnalysisState) -> dict[str, Any]:
        ctx, dataset = self.ctx, self.ctx.dataset
        ctx.set_status(JobStatus.REPORTING)
        spec, statistical = state["analysis_spec"], state["statistical_result"]
        verification = state["verification_result"]["outputs"]
        warnings, assumptions = self._notes(state)
        outcome = await run_task(
            ctx, sequence=6, agent_key="report_generation", action="generate_report",
            inputs={
                "title": spec["report_title"], "objective": spec["objective"], "request": ctx.prompt,
                "organisation": ctx.organisation["name"], "job_id": str(ctx.job_id),
                "generated_at": verification["verified_at"], "timezone": ctx.organisation["timezone"],
                "dataset": {"name": dataset.name, "version": dataset.version_number, "filename": dataset.filename,
                            "rows": dataset.rows, "sha256": dataset.sha256},
                "segments": statistical["outputs"]["segments"],
                # only findings that passed verification reach the report agent
                "findings": [{**finding, "approved": True} for finding in statistical["findings"]],
                "evidence": statistical["evidence"], "warnings": warnings, "assumptions": assumptions,
                "verification": {"passed": verification["passed"], "checks": verification["checks"]},
                "learning_profile": ctx.organisation.get("learning_profile") or {},
            },
            dataset_refs={"report_paths": {ext: report_key(ctx.organisation_id, ctx.job_id, ext)
                                           for ext in ("pdf", "xlsx", "html")}},
        )  # fmt: skip
        if not outcome.ok:
            # Verified results stand on their own; the job finishes as partially completed.
            return {"report_result": {"error": outcome.error}}
        with system_session() as session:
            for artifact in outcome.result["artifacts"]:
                values = {"title": artifact["title"], "filename": artifact["filename"],
                          "content_type": artifact["content_type"], "size_bytes": artifact["size_bytes"],
                          "sha256_hash": artifact["sha256"], "storage_path": artifact["storage_path"]}  # fmt: skip
                session.execute(
                    pg_insert(Artifact)
                    .values(organisation_id=ctx.organisation_id, job_id=ctx.job_id,
                            artifact_type=artifact["artifact_type"], **values)
                    .on_conflict_do_update(constraint="artifacts_job_type_key", set_=values)
                )  # fmt: skip
        return {"report_result": outcome.result}

    async def finalise(self, state: AnalysisState) -> dict[str, Any]:
        """The Chief's closing step: combine the agents' outputs and record the outcome."""
        ctx, dataset = self.ctx, self.ctx.dataset
        if state.get("status") == "failed":
            message = state["errors"][-1]["message"]
            if not queue.finish(ctx.job_id, ctx.lock_token, JobStatus.FAILED, error_message=message):
                raise queue.JobLockLost(str(ctx.job_id))
            return {"status": JobStatus.FAILED}

        planning, statistical = state["planning_result"], state["statistical_result"]
        report = state.get("report_result") or {}
        verification = state["verification_result"]["outputs"]
        spec = state["analysis_spec"]
        warnings, assumptions = self._notes(state)
        unmet = planning["outputs"].get("unmet_requests", [])
        report_failed = "error" in report
        if report_failed:
            warnings.append(
                f"The report files could not be produced ({report['error']}) The results below are verified."
            )

        ranked = sorted(statistical["findings"], key=lambda f: -f["importance"])
        summary = {
            "title": spec["report_title"],
            "objective": spec["objective"],
            "headline": statistical["outputs"].get("headline"),
            "executive_summary": report.get("outputs", {}).get("executive_summary")
                                 or [finding["statement"] for finding in ranked[:6]],
            "next_steps": report.get("outputs", {}).get("next_steps", []),
            "narrative_source": report.get("outputs", {}).get("narrative_source"),
            "segments": statistical["outputs"]["segments"],
            "warnings": warnings,
            "assumptions": assumptions,
            "unmet_requests": unmet,
            "verification": {"passed": verification["passed"], "checks": verification["checks"]},
            "plan": {"planner": planning["outputs"]["planner"],
                     "operations": [{"type": op["type"], "title": OPERATION_TITLES[op["type"]]} for op in spec["operations"]]},
            "dataset": {"name": dataset.name, "version": dataset.version_number, "rows": dataset.rows,
                        "sha256": dataset.sha256},
        }  # fmt: skip

        tokens = sum(
            (state.get(key) or {}).get("metrics", {}).get(field, 0)
            for key in ("planning_result", "report_result")
            for field in ("tokens_input", "tokens_output")
        )
        with system_session() as session:
            source = f"job:{ctx.job_id}"
            common = {"organisation_id": ctx.organisation_id, "job_id": ctx.job_id, "source_key": source}
            usage.record(session, metric="analyses", quantity=1, unit="job", **common)
            usage.record(session, metric="rows_analysed", quantity=dataset.rows or 0, unit="rows", **common)
            usage.record(session, metric="reports", quantity=len(report.get("artifacts", [])), unit="files", **common)
            if tokens:
                usage.record(session, metric="ai_tokens", quantity=tokens, unit="tokens", **common)

        status = JobStatus.PARTIAL if (unmet or report_failed) else JobStatus.COMPLETED
        if not queue.finish(ctx.job_id, ctx.lock_token, status, result_summary=summary):
            raise queue.JobLockLost(str(ctx.job_id))
        return {"status": status}

    # --------------------------------------------------------------- ingestion
    async def ingest_preflight(self, state: AnalysisState) -> dict[str, Any]:
        update = self._preflight(state)
        if update.get("status") != "failed":
            ensure_tasks(self.ctx, INGESTION_PLAN)
        return update

    async def ingest_acquire(self, state: AnalysisState) -> dict[str, Any]:
        ctx, dataset = self.ctx, self.ctx.dataset
        ctx.set_status(JobStatus.EXECUTING)
        outcome = await run_task(
            ctx, sequence=1, agent_key="data_acquisition", action="import_and_profile",
            inputs={"date_order": ctx.organisation["date_order"]},
            dataset_refs={"original_path": dataset.original_path, "raw_path": dataset.raw_path,
                          "file_type": dataset.file_type},
        )  # fmt: skip
        if not outcome.ok:
            return failed(state, "data_acquisition", outcome.error)
        outputs = outcome.result["outputs"]
        with system_session() as session:
            version = session.get(DatasetVersion, dataset.version_id)
            version.sha256_hash, version.canonical_path = outputs["sha256"], outputs["raw_path"]
            version.size_bytes, version.schema_json = outputs["size_bytes"], outputs["schema"]
        return {"acquisition_result": outcome.result}

    async def ingest_clean(self, state: AnalysisState) -> dict[str, Any]:
        ctx, dataset = self.ctx, self.ctx.dataset
        acquired = state["acquisition_result"]["outputs"]
        outcome = await run_task(
            ctx, sequence=2, agent_key="data_cleaning", action="clean_and_validate",
            inputs={"column_types": acquired["column_types"], "category_columns": acquired["category_columns"],
                    "measure_columns": acquired["measure_columns"], "roles": acquired["profile"]["roles"],
                    "date_order": ctx.organisation["date_order"]},
            dataset_refs={"raw_path": dataset.raw_path, "cleaned_path": dataset.cleaned_path},
        )  # fmt: skip
        return {"cleaning_result": outcome.result} if outcome.ok else failed(state, "data_cleaning", outcome.error)

    async def ingest_finalise(self, state: AnalysisState) -> dict[str, Any]:
        ctx, dataset = self.ctx, self.ctx.dataset
        if state.get("status") == "failed":
            message = state["errors"][-1]["message"]
            if not queue.finish(ctx.job_id, ctx.lock_token, JobStatus.FAILED, error_message=message):
                raise queue.JobLockLost(str(ctx.job_id))
            return {"status": JobStatus.FAILED}

        acquired, cleaned = state["acquisition_result"]["outputs"], state["cleaning_result"]["outputs"]
        profile = acquired["profile"]
        # The profile describes the data as it will be analysed, so take its counts from the cleaned table.
        profile["rows"] = cleaned["rows"]
        for column in profile["columns_detail"]:
            column.update(cleaned["column_stats"].get(column["name"], {}))
        profile["warnings"] = _unique([*state["acquisition_result"]["warnings"]])

        with system_session() as session:
            version = session.get(DatasetVersion, dataset.version_id)
            version.cleaned_path, version.cleaning_json = cleaned["cleaned_path"], cleaned["cleaning"]
            version.profile_json, version.row_count, version.column_count = profile, cleaned["rows"], profile["columns"]
            version.status, version.error_message = DatasetStatus.READY, None
            session.execute(delete(DatasetColumn).where(DatasetColumn.dataset_version_id == version.id))
            for column in profile["columns_detail"]:
                session.add(DatasetColumn(
                    organisation_id=ctx.organisation_id, dataset_version_id=version.id, position=column["position"],
                    column_name=column["name"][:255], data_type=column["kind"], inferred_role=column["role"],
                    null_count=column["null_count"], distinct_count=column["distinct_count"],
                    metadata_={"examples": column["examples"], "stats": column["stats"], "notes": column["notes"]},
                ))  # fmt: skip
            record = session.get(Dataset, dataset.dataset_id)
            record.status, record.error_message, record.updated_at = DatasetStatus.READY, None, datetime.now(UTC)
            source = f"version:{version.id}"
            common = {"organisation_id": ctx.organisation_id, "job_id": ctx.job_id, "source_key": source}
            usage.record(session, metric="rows_ingested", quantity=cleaned["rows"], unit="rows", **common)
            usage.record(session, metric="storage_bytes", quantity=acquired["size_bytes"], unit="bytes", **common)

        summary = {
            "headline": state["cleaning_result"]["summary"],
            "rows": cleaned["rows"],
            "columns": profile["columns"],
        }
        if not queue.finish(ctx.job_id, ctx.lock_token, JobStatus.COMPLETED, result_summary=summary):
            raise queue.JobLockLost(str(ctx.job_id))
        return {"status": JobStatus.COMPLETED}
