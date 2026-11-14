"""Everything one job needs, gathered once and checked against the job's organisation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

from ...core.config import Settings
from ...core.database import system_session
from ...models import AnalysisJob, Dataset, DatasetStatus, DatasetVersion, JobType, Organisation
from ...storage import Storage, assert_belongs_to
from ...storage.base import cleaned_key, raw_key
from ...workers import queue
from ..base import ExecutionLimits, Toolbox
from ..base.tools import build_tools


class ContextError(Exception):
    """The job's data does not check out. The message is safe to show the customer."""


@dataclass
class DatasetInfo:
    dataset_id: UUID
    name: str
    filename: str | None
    file_type: str
    version_id: UUID
    version_number: int
    original_path: str
    raw_path: str
    cleaned_path: str
    sha256: str | None
    rows: int | None
    columns: int | None
    profile: dict[str, Any]
    cleaning: dict[str, Any]


@dataclass
class JobContext:
    settings: Settings
    storage: Storage
    llm: Any | None
    workdir: Path
    job_id: UUID
    lock_token: UUID
    organisation_id: UUID
    workspace_id: UUID
    job_type: str
    prompt: str
    analysis_type: str
    requested_by: UUID | None
    dataset_version_id: UUID | None
    organisation: dict[str, Any] = field(default_factory=dict)
    dataset: DatasetInfo | None = None
    tools: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def for_claim(cls, claim: queue.Claim, settings: Settings, storage: Storage, llm: Any | None,
                  workdir: Path) -> JobContext:  # fmt: skip
        with system_session() as session:
            job = session.get(AnalysisJob, claim.job_id)
            if job is None or job.lock_token != claim.lock_token:
                raise queue.JobLockLost(str(claim.job_id))
            context = cls(
                settings=settings, storage=storage, llm=llm, workdir=workdir, job_id=job.id,
                lock_token=claim.lock_token, organisation_id=job.organisation_id, workspace_id=job.workspace_id,
                job_type=job.job_type, prompt=job.prompt, analysis_type=job.analysis_type,
                requested_by=job.requested_by, dataset_version_id=job.dataset_version_id,
            )  # fmt: skip
        context.tools = build_tools(storage=storage, organisation_id=context.organisation_id, job_id=context.job_id,
                                    workdir=workdir, llm=llm)  # fmt: skip
        return context

    def toolbox(self, agent_key: str) -> Toolbox:
        return Toolbox(agent_key, self.tools)

    def limits(self) -> ExecutionLimits:
        return ExecutionLimits(
            max_rows=self.settings.max_analysis_rows, max_columns=self.settings.max_analysis_columns,
            max_file_bytes=self.settings.max_upload_bytes, timeout_seconds=self.settings.job_timeout_seconds,
        )  # fmt: skip

    def set_status(self, status: str) -> None:
        queue.set_status(self.job_id, self.lock_token, status)

    def checkpoint(self) -> None:
        queue.checkpoint(self.job_id, self.lock_token)

    def load_dataset(self) -> DatasetInfo:
        """Load the job's dataset and verify that every part of it belongs to the job's organisation.

        The database's tenant-aware foreign keys already make a cross-organisation job
        impossible to create. The worker runs with privileges that bypass Row Level
        Security, so it checks again here rather than trusting that nothing upstream
        went wrong (specification 3.4).
        """
        if self.dataset_version_id is None:
            raise ContextError("This job has no dataset attached.")
        with system_session() as session:
            organisation = session.get(Organisation, self.organisation_id)
            version = session.get(DatasetVersion, self.dataset_version_id)
            dataset = session.get(Dataset, version.dataset_id) if version else None
            if organisation is None or version is None or dataset is None:
                raise ContextError("The dataset for this job no longer exists.")
            if organisation.status != "active":
                raise ContextError("This organisation's account is not active.")
            owners = {version.organisation_id, dataset.organisation_id}
            if owners != {self.organisation_id} or dataset.workspace_id != self.workspace_id:
                raise ContextError("The dataset does not belong to the organisation that submitted this job.")

            is_analysis = self.job_type == JobType.ANALYSIS
            if is_analysis and (
                version.status != DatasetStatus.READY or not version.cleaned_path or not version.sha256_hash
            ):
                raise ContextError("This dataset has not finished processing, so it cannot be analysed yet.")

            raw_path = version.canonical_path or raw_key(self.organisation_id, dataset.id, version.version_number)
            cleaned_path = version.cleaned_path or cleaned_key(self.organisation_id, dataset.id, version.version_number)
            for path in (version.storage_path, raw_path, cleaned_path):
                assert_belongs_to(path, self.organisation_id)

            self.organisation = {"name": organisation.name, "currency": organisation.default_currency,
                                 "timezone": organisation.timezone, "date_order": organisation.date_order,
                                 "learning_profile": organisation.learning_profile or {}}  # fmt: skip
            self.dataset = DatasetInfo(
                dataset_id=dataset.id, name=dataset.name, filename=dataset.source_filename,
                file_type=dataset.file_type or "", version_id=version.id, version_number=version.version_number,
                original_path=version.storage_path, raw_path=raw_path, cleaned_path=cleaned_path,
                sha256=version.sha256_hash, rows=version.row_count, columns=version.column_count,
                profile=version.profile_json or {}, cleaning=version.cleaning_json or {},
            )  # fmt: skip

        if not self.storage.exists(self.dataset.original_path):
            raise ContextError("The uploaded file could not be found in storage. Please upload it again.")
        if is_analysis and not self.storage.exists(self.dataset.cleaned_path):
            raise ContextError("The prepared copy of this dataset is missing. Please upload it again.")
        return self.dataset
