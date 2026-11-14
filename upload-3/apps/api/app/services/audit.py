"""Append-only audit trail."""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

from sqlalchemy import insert
from sqlalchemy.orm import Session

from ..models import AuditLog


def record(
    db: Session,
    *,
    organisation_id: UUID,
    actor_id: UUID | None,
    action: str,
    resource_type: str | None = None,
    resource_id: UUID | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    """Write one audit entry in the caller's transaction.

    A plain INSERT is used on purpose: the ORM would ask the database to return the
    new row, and members who may write audit entries but not read them (analysts,
    viewers) would be refused by Row Level Security.
    """
    db.execute(
        insert(AuditLog).values(
            id=uuid.uuid4(),
            organisation_id=organisation_id,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details or {},
        )
    )
