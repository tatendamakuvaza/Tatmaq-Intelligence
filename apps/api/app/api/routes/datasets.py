"""Dataset upload, listing and profiles."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from ...schemas.datasets import (
    CompleteResponse,
    DatasetDetail,
    DatasetOut,
    DatasetProfile,
    UploadRequest,
    UploadResponse,
)
from ...services import datasets
from ..deps import AppSettings, Db, FileStorage, Tenant

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.get("", response_model=list[DatasetOut])
def list_datasets(ctx: Tenant, db: Db, workspace_id: UUID | None = None) -> list[DatasetOut]:
    return datasets.list_datasets(db, ctx, workspace_id)


@router.post("/upload-url", response_model=UploadResponse, status_code=201)
def create_upload_url(
    body: UploadRequest, ctx: Tenant, db: Db, storage: FileStorage, settings: AppSettings
) -> UploadResponse:
    """Step 1 of an upload: register the dataset and get a one-off link to send the file to."""
    return datasets.request_upload(
        db, ctx, storage, settings, workspace_id=body.workspace_id, filename=body.filename,
        size_bytes=body.size_bytes, name=body.name, dataset_id=body.dataset_id,
    )  # fmt: skip


@router.post("/{dataset_id}/complete", response_model=CompleteResponse)
def complete_upload(
    dataset_id: UUID, ctx: Tenant, db: Db, storage: FileStorage, settings: AppSettings
) -> CompleteResponse:
    """Step 3 of an upload: confirm the file arrived and start importing it. Safe to repeat."""
    return datasets.complete_upload(db, ctx, storage, settings, dataset_id)


@router.get("/{dataset_id}", response_model=DatasetDetail)
def get_dataset(dataset_id: UUID, ctx: Tenant, db: Db) -> DatasetDetail:
    return datasets.get_dataset(db, ctx, dataset_id)


@router.get("/{dataset_id}/profile", response_model=DatasetProfile)
def get_profile(
    dataset_id: UUID, ctx: Tenant, db: Db, version: Annotated[int | None, Query(ge=1)] = None
) -> DatasetProfile:
    return datasets.get_profile(db, ctx, dataset_id, version)
