"""Audit trail and usage accounting."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, created_timestamp, uuid_pk


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[uuid_pk]
    organisation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organisations.id"))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)  # NULL for system actions
    action: Mapped[str] = mapped_column(String(150))
    resource_type: Mapped[str | None] = mapped_column(String(100))
    resource_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    details: Mapped[dict[str, Any] | None] = mapped_column(default=dict)
    created_at: Mapped[created_timestamp]


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id: Mapped[uuid_pk]
    organisation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("organisations.id"))
    job_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("analysis_jobs.id"))
    metric: Mapped[str] = mapped_column(String(100))
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    unit: Mapped[str | None] = mapped_column(String(50))
    source_key: Mapped[str | None] = mapped_column(String(150))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
