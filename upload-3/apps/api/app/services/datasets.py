"""Dataset upload, listing and profiles.

Upload is a three-step handshake so that file bytes go straight to storage and a
half-finished upload can never be analysed:

1. ``request_upload``  creates the dataset as *pending* and returns a one-off upload link
2. the browser sends the file to that link
3. ``complete_upload`` confirms the file arrived, creates an immutable version and
   queues the ingestion job. Only when that job succeeds does the version become
   ``ready``; until then the API refuses to analyse it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import PurePosixPath, PureWindowsPath
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..core.config import Settings
from ..core.errors import Conflict, NotFound, PayloadTooLarge, UnsupportedFile
from ..models import AnalysisJob, Dataset, DatasetColumn, DatasetStatus, DatasetVersion, JobType
from ..schemas.datasets import (
    ColumnOut,
    CompleteResponse,
    DatasetDetail,
    DatasetOut,
    DatasetProfile,
    UploadInstructions,
    UploadResponse,
    VersionOut,
)  # fmt: skip
from ..security.tenancy import TenantContext
from ..storage import Storage
from ..storage.base import original_key
from . import audit
from .organisations import get_workspace

CONTENT_TYPES = {
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
}
INGESTION_PROMPT = "Import, profile and clean the uploaded dataset."
INGESTION_PRIORITY = 3  # ahead of analyses: people are waiting to see their upload


def _file_type(filename: str) -> str:
    extension = PurePosixPath(filename).suffix.lower().lstrip(".")
    if extension in CONTENT_TYPES:
        return extension
    if extension in ("xls", "xlsm", "xlsb", "ods"):
        raise UnsupportedFile(
            f"'.{extension}' files are not supported yet. In Excel choose File > Save As > "
            "Excel Workbook (.xlsx) or CSV, then upload that file."
        )
    raise UnsupportedFile("Upload an Excel workbook (.xlsx) or a CSV file (.csv).")


def _display_filename(filename: str) -> str:
    """The customer's filename, for display only. It never becomes part of a storage path."""
    name = PureWindowsPath(filename).name
    cleaned = "".join(character for character in name if character.isprintable()).strip()
    return cleaned[:255] or "upload"


def _get_dataset(db: Session, ctx: TenantContext, dataset_id: UUID) -> Dataset:
    dataset = db.scalar(select(Dataset).where(Dataset.id == dataset_id, Dataset.organisation_id == ctx.organisation_id))
    if dataset is None:
        raise NotFound("Dataset not found.")
    return dataset


def _latest_version_number(db: Session, dataset_id: UUID) -> int:
    return db.scalar(
        select(func.coalesce(func.max(DatasetVersion.version_number), 0)).where(DatasetVersion.dataset_id == dataset_id)
    )


def request_upload(
    db: Session, ctx: TenantContext, storage: Storage, settings: Settings, *,
    workspace_id: UUID, filename: str, size_bytes: int, name: str | None, dataset_id: UUID | None,
) -> UploadResponse:  # fmt: skip
    ctx.require("datasets:upload")
    file_type = _file_type(filename)
    if size_bytes > settings.max_upload_bytes:
        raise PayloadTooLarge(f"This file is larger than the {settings.max_upload_mb} MB upload limit.")
    display_name = _display_filename(filename)

    if dataset_id is None:
        if get_workspace(db, ctx, workspace_id) is None:
            raise NotFound("Workspace not found.")
        dataset = Dataset(
            organisation_id=ctx.organisation_id, workspace_id=workspace_id,
            name=(name or PurePosixPath(display_name).stem).strip()[:255] or "Dataset",
            source_filename=display_name, file_type=file_type, created_by=ctx.user.id,
        )  # fmt: skip
        db.add(dataset)
        db.flush()
    else:
        dataset = _get_dataset(db, ctx, dataset_id)
        if dataset.status == DatasetStatus.PROCESSING:
            raise Conflict("This dataset is still being processed. Try again when it has finished.")
        dataset.status = DatasetStatus.PENDING_UPLOAD
        dataset.source_filename, dataset.file_type = display_name, file_type
        dataset.error_message, dataset.updated_at = None, datetime.now(UTC)

    version_number = _latest_version_number(db, dataset.id) + 1
    target = storage.create_upload_target(
        original_key(ctx.organisation_id, dataset.id, version_number, file_type),
        content_type=CONTENT_TYPES[file_type],
        max_bytes=settings.max_upload_bytes,
        ttl_seconds=settings.upload_url_ttl_seconds,
    )
    audit.record(db, organisation_id=ctx.organisation_id, actor_id=ctx.user.id, action="dataset.upload_requested",
                 resource_type="dataset", resource_id=dataset.id,
                 details={"filename": display_name, "size_bytes": size_bytes, "version": version_number})  # fmt: skip
    db.commit()
    return UploadResponse(
        dataset_id=dataset.id, version_number=version_number,
        upload=UploadInstructions(method=target.method, url=target.url, headers=target.headers),
        max_bytes=settings.max_upload_bytes, expires_in=settings.upload_url_ttl_seconds,
    )  # fmt: skip


def complete_upload(
    db: Session, ctx: TenantContext, storage: Storage, settings: Settings, dataset_id: UUID
) -> CompleteResponse:
    ctx.require("datasets:upload")
    dataset = _get_dataset(db, ctx, dataset_id)

    if dataset.status != DatasetStatus.PENDING_UPLOAD:
        # Called twice (a retry, a double click): answer with what the first call created.
        version = db.scalar(
            select(DatasetVersion)
            .where(DatasetVersion.dataset_id == dataset.id)
            .order_by(DatasetVersion.version_number.desc())
        )
        job = version and db.scalar(
            select(AnalysisJob)
            .where(AnalysisJob.dataset_version_id == version.id, AnalysisJob.job_type == JobType.INGESTION)
            .order_by(AnalysisJob.created_at.desc())
        )
        if version is None or job is None:
            raise Conflict("This dataset has no upload in progress.")
        return CompleteResponse(dataset_id=dataset.id, dataset_version_id=version.id,
                                version_number=version.version_number, job_id=job.id, status=dataset.status)  # fmt: skip

    version_number = _latest_version_number(db, dataset.id) + 1
    key = original_key(ctx.organisation_id, dataset.id, version_number, dataset.file_type)
    if not storage.exists(key):
        raise Conflict("The file has not finished uploading yet.", code="upload_missing")
    size = storage.size(key)
    if size == 0 or size > settings.max_upload_bytes:
        storage.delete(key)
        dataset.status = DatasetStatus.FAILED
        dataset.error_message = "The uploaded file was empty." if size == 0 else "The uploaded file is too large."
        dataset.updated_at = datetime.now(UTC)
        db.commit()
        if size == 0:
            raise UnsupportedFile("The uploaded file is empty.")
        raise PayloadTooLarge(f"This file is larger than the {settings.max_upload_mb} MB upload limit.")

    version = DatasetVersion(
        organisation_id=ctx.organisation_id, dataset_id=dataset.id, version_number=version_number,
        storage_path=key, size_bytes=size, created_by=ctx.user.id,
    )  # fmt: skip
    db.add(version)
    db.flush()
    job = AnalysisJob(
        organisation_id=ctx.organisation_id, workspace_id=dataset.workspace_id, dataset_version_id=version.id,
        requested_by=ctx.user.id, job_type=JobType.INGESTION, analysis_type="ingestion",
        prompt=INGESTION_PROMPT, priority=INGESTION_PRIORITY, max_attempts=settings.job_max_attempts,
    )  # fmt: skip
    db.add(job)
    dataset.status, dataset.updated_at = DatasetStatus.PROCESSING, datetime.now(UTC)
    db.flush()
    audit.record(db, organisation_id=ctx.organisation_id, actor_id=ctx.user.id, action="dataset.uploaded",
                 resource_type="dataset_version", resource_id=version.id,
                 details={"size_bytes": size, "version": version_number})  # fmt: skip
    db.commit()
    return CompleteResponse(dataset_id=dataset.id, dataset_version_id=version.id, version_number=version_number,
                            job_id=job.id, status=dataset.status)  # fmt: skip


def _with_latest(dataset: Dataset, versions: list[DatasetVersion]) -> DatasetOut:
    out = DatasetOut.model_validate(dataset)
    if versions:
        out.latest_version = VersionOut.model_validate(max(versions, key=lambda v: v.version_number))
    return out


def list_datasets(db: Session, ctx: TenantContext, workspace_id: UUID | None) -> list[DatasetOut]:
    query = select(Dataset).where(Dataset.organisation_id == ctx.organisation_id)
    if workspace_id is not None:
        query = query.where(Dataset.workspace_id == workspace_id)
    datasets = db.scalars(query.order_by(Dataset.created_at.desc())).all()
    if not datasets:
        return []
    versions = db.scalars(
        select(DatasetVersion).where(
            DatasetVersion.organisation_id == ctx.organisation_id,
            DatasetVersion.dataset_id.in_([dataset.id for dataset in datasets]),
        )
    ).all()
    by_dataset: dict[UUID, list[DatasetVersion]] = {}
    for version in versions:
        by_dataset.setdefault(version.dataset_id, []).append(version)
    return [_with_latest(dataset, by_dataset.get(dataset.id, [])) for dataset in datasets]


def _versions(db: Session, ctx: TenantContext, dataset_id: UUID) -> list[DatasetVersion]:
    return list(
        db.scalars(
            select(DatasetVersion)
            .where(DatasetVersion.dataset_id == dataset_id, DatasetVersion.organisation_id == ctx.organisation_id)
            .order_by(DatasetVersion.version_number.desc())
        )
    )


def get_dataset(db: Session, ctx: TenantContext, dataset_id: UUID) -> DatasetDetail:
    dataset = _get_dataset(db, ctx, dataset_id)
    versions = _versions(db, ctx, dataset.id)
    detail = DatasetDetail.model_validate(dataset)
    detail.versions = [VersionOut.model_validate(version) for version in versions]
    detail.latest_version = detail.versions[0] if versions else None
    return detail


def get_profile(db: Session, ctx: TenantContext, dataset_id: UUID, version_number: int | None) -> DatasetProfile:
    dataset = _get_dataset(db, ctx, dataset_id)
    versions = _versions(db, ctx, dataset.id)
    if version_number is not None:
        versions = [version for version in versions if version.version_number == version_number]
    ready = next((version for version in versions if version.status == DatasetStatus.READY), None)
    if ready is None:
        if versions and versions[0].status == DatasetStatus.FAILED:
            raise Conflict(versions[0].error_message or "This dataset could not be processed.", code="dataset_failed")
        raise Conflict("The profile is not ready yet: the dataset is still being processed.", code="dataset_not_ready")
    columns = db.scalars(
        select(DatasetColumn)
        .where(DatasetColumn.dataset_version_id == ready.id, DatasetColumn.organisation_id == ctx.organisation_id)
        .order_by(DatasetColumn.position)
    ).all()
    return DatasetProfile(
        dataset_id=dataset.id, dataset_name=dataset.name, version=VersionOut.model_validate(ready),
        profile=ready.profile_json or {}, cleaning=ready.cleaning_json or {},
        columns=[
            ColumnOut(name=column.column_name, position=column.position, data_type=column.data_type,
                      role=column.inferred_role, null_count=column.null_count,
                      distinct_count=column.distinct_count, details=column.metadata_ or {})
            for column in columns
        ],
    )  # fmt: skip
