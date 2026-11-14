"""Request and response shapes for datasets."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from .common import ApiModel


class UploadRequest(BaseModel):
    workspace_id: UUID
    filename: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0)
    name: str | None = Field(default=None, max_length=255)
    # Supply to add a new version to an existing dataset instead of creating one.
    dataset_id: UUID | None = None


class UploadInstructions(BaseModel):
    method: str
    url: str
    headers: dict[str, str]


class UploadResponse(BaseModel):
    dataset_id: UUID
    version_number: int
    upload: UploadInstructions
    max_bytes: int
    expires_in: int


class CompleteResponse(BaseModel):
    dataset_id: UUID
    dataset_version_id: UUID
    version_number: int
    job_id: UUID
    status: str


class VersionOut(ApiModel):
    id: UUID
    version_number: int
    status: str
    row_count: int | None
    column_count: int | None
    size_bytes: int | None
    sha256_hash: str | None
    error_message: str | None
    created_at: datetime


class DatasetOut(ApiModel):
    id: UUID
    workspace_id: UUID
    name: str
    source_filename: str | None
    file_type: str | None
    status: str
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    latest_version: VersionOut | None = None


class DatasetDetail(DatasetOut):
    versions: list[VersionOut] = []


class ColumnOut(BaseModel):
    name: str
    position: int
    data_type: str | None
    role: str | None
    null_count: int | None
    distinct_count: int | None
    details: dict[str, Any]


class DatasetProfile(BaseModel):
    dataset_id: UUID
    dataset_name: str
    version: VersionOut
    profile: dict[str, Any]
    columns: list[ColumnOut]
    cleaning: dict[str, Any]
