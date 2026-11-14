"""Which organisation a request acts in, and what the caller may do there."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.errors import NotFound, PermissionDenied
from ..models import Organisation, OrganisationMembership, Role
from .auth import AuthUser


@dataclass(frozen=True)
class TenantContext:
    """The verified answer to "who is asking, for which organisation, with what rights".

    Service functions take this instead of a bare organisation id, so an id that
    arrives in a URL or request body can never choose the tenant.
    """

    user: AuthUser
    organisation_id: UUID
    role: str
    permissions: frozenset[str]

    def can(self, permission: str) -> bool:
        return permission in self.permissions

    def require(self, permission: str) -> None:
        if permission not in self.permissions:
            raise PermissionDenied(f"Your role ({self.role}) does not allow this action.")


def resolve_tenant(db: Session, user: AuthUser, organisation_id: UUID) -> TenantContext:
    row = db.execute(
        select(OrganisationMembership.role, Role.permissions, Organisation.status)
        .join(Role, Role.name == OrganisationMembership.role)
        .join(Organisation, Organisation.id == OrganisationMembership.organisation_id)
        .where(
            OrganisationMembership.organisation_id == organisation_id,
            OrganisationMembership.user_id == user.id,
            OrganisationMembership.status == "active",
        )
    ).one_or_none()
    # A non-member gets the same answer as for an organisation that does not exist.
    if row is None or row.status != "active":
        raise NotFound("Organisation not found.")
    granted = frozenset(name for name, allowed in (row.permissions or {}).items() if allowed)
    return TenantContext(user=user, organisation_id=organisation_id, role=row.role, permissions=granted)
