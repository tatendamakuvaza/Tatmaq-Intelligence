"""Uploaded datasets, their immutable versions and column dictionaries."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, created_timestamp, uuid_pk


class DatasetStatus:
    PENDING_UPLOAD = "pending_upload"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[uuid_pk]
    organisation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organisations.id"))
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workspaces.id"))
    name: Mapped[str] = mapped_column(String(255))
    source_filename: Mapped[str | None] = mapped_column(String(255))
    file_type: Mapped[str | None] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), default=DatasetStatus.PENDING_UPLOAD)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("profiles.id"))
    created_at: Mapped[created_timestamp]
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DatasetVersion(Base):
    """One upload of a dataset. The original file is never changed after this row exists."""

    __tablename__ = "dataset_versions"

    id: Mapped[uuid_pk]
    organisation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organisations.id"))
    dataset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("datasets.id"))
    version_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default=DatasetStatus.PROCESSING)
    storage_path: Mapped[str] = mapped_column(Text)  # the original upload
    canonical_path: Mapped[str | None] = mapped_column(Text)  # raw table as imported (Parquet)
    cleaned_path: Mapped[str | None] = mapped_column(Text)  # typed, standardised table (Parquet)
    sha256_hash: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    row_count: Mapped[int | None] = mapped_column(BigInteger)
    column_count: Mapped[int | None] = mapped_column(Integer)
    schema_json: Mapped[dict[str, Any] | None] = mapped_column()
    profile_json: Mapped[dict[str, Any] | None] = mapped_column()
    cleaning_json: Mapped[dict[str, Any] | None] = mapped_column()
    error_message: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("profiles.id"))
    created_at: Mapped[created_timestamp]


class DatasetColumn(Base):
    __tablename__ = "dataset_columns"

    id: Mapped[uuid_pk]
    organisation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organisations.id"))
    dataset_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("dataset_versions.id"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    column_name: Mapped[str] = mapped_column(String(255))
    data_type: Mapped[str | None] = mapped_column(String(50))
    inferred_role: Mapped[str | None] = mapped_column(String(50))
    null_count: Mapped[int | None] = mapped_column(BigInteger, default=0)
    distinct_count: Mapped[int | None] = mapped_column(BigInteger)
    metadata_: Mapped[dict[str, Any] | None] = mapped_column("metadata", default=dict)
