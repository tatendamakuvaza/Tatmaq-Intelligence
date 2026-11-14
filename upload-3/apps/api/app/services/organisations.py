"""Profiles, organisations and workspaces."""

from __future__ import annotations

import re
import unicodedata
import uuid
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.config import Settings
from ..core.database import system_session
from ..core.errors import Conflict, LimitExceeded
from ..models import Organisation, OrganisationMembership, Profile, Role, Workspace
from ..schemas.accounts import MemberOut, OrganisationOut, WorkspaceOut
from ..security.auth import AuthUser
from ..security.tenancy import TenantContext
from . import audit

DEFAULT_WORKSPACE_NAME = "Main workspace"


def upsert_profile(db: Session, user: AuthUser, full_name: str | None) -> Profile:
    """Create the caller's profile, or update their name. Safe to call repeatedly."""
    statement = (
        pg_insert(Profile)
        .values(id=user.id, full_name=full_name, email=user.email)
        .on_conflict_do_update(
            index_elements=[Profile.id],
            set_={
                "full_name": func.coalesce(full_name, Profile.full_name),
                "email": func.coalesce(user.email, Profile.email),
                "updated_at": func.now(),
            },
        )
    )
    db.execute(statement)
    db.commit()
    return db.get(Profile, user.id)


def _organisation_out(organisation: Organisation, role: str, permissions: dict | None) -> OrganisationOut:
    return OrganisationOut(
        id=organisation.id, name=organisation.name, slug=organisation.slug, role=role,
        permissions=sorted(name for name, allowed in (permissions or {}).items() if allowed),
        default_currency=organisation.default_currency, timezone=organisation.timezone,
        date_order=organisation.date_order,
    )  # fmt: skip


def list_organisations(db: Session, user: AuthUser) -> list[OrganisationOut]:
    rows = db.execute(
        select(Organisation, OrganisationMembership.role, Role.permissions)
        .join(OrganisationMembership, OrganisationMembership.organisation_id == Organisation.id)
        .join(Role, Role.name == OrganisationMembership.role)
        .where(OrganisationMembership.user_id == user.id, OrganisationMembership.status == "active")
        .order_by(Organisation.created_at)
    ).all()
    return [_organisation_out(organisation, role, permissions) for organisation, role, permissions in rows]


def slugify(name: str) -> str:
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_name.lower()).strip("-")[:60].strip("-") or "organisation"


def create_organisation(user: AuthUser, name: str, settings: Settings) -> tuple[OrganisationOut, WorkspaceOut]:
    """Create an organisation with the caller as its owner, plus a first workspace.

    Runs with system privileges: the caller is not yet a member of the organisation
    being created, so Row Level Security would (rightly) refuse them. Everything
    written here is derived from the verified user, never from request input.
    """
    base_slug = slugify(name)
    for attempt in range(6):
        slug = base_slug if attempt == 0 else f"{base_slug}-{uuid.uuid4().hex[:6]}"
        try:
            with system_session() as session:
                owned = session.scalar(
                    select(func.count())
                    .select_from(OrganisationMembership)
                    .where(OrganisationMembership.user_id == user.id, OrganisationMembership.role == "owner")
                )
                if owned >= settings.max_organisations_per_user:
                    raise LimitExceeded(
                        f"An account can own at most {settings.max_organisations_per_user} organisations."
                    )
                if session.get(Profile, user.id) is None:
                    session.add(Profile(id=user.id, email=user.email))
                    session.flush()
                organisation = Organisation(
                    name=name, slug=slug, default_currency=settings.default_currency,
                    timezone=settings.default_timezone, date_order=settings.default_date_order,
                )  # fmt: skip
                session.add(organisation)
                session.flush()
                session.add(OrganisationMembership(organisation_id=organisation.id, user_id=user.id, role="owner"))
                workspace = Workspace(organisation_id=organisation.id, name=DEFAULT_WORKSPACE_NAME, created_by=user.id)
                session.add(workspace)
                session.flush()
                audit.record(session, organisation_id=organisation.id, actor_id=user.id,
                             action="organisation.created", resource_type="organisation",
                             resource_id=organisation.id, details={"name": name})  # fmt: skip
                permissions = session.scalar(select(Role.permissions).where(Role.name == "owner"))
                return _organisation_out(organisation, "owner", permissions), WorkspaceOut.model_validate(workspace)
        except IntegrityError as error:
            if "organisations_slug_key" not in str(error.orig):
                raise
    raise Conflict("Could not reserve a unique address for this organisation. Try a different name.")


def list_members(db: Session, ctx: TenantContext) -> list[MemberOut]:
    rows = db.execute(
        select(OrganisationMembership, Profile)
        .join(Profile, Profile.id == OrganisationMembership.user_id)
        .where(OrganisationMembership.organisation_id == ctx.organisation_id)
        .order_by(OrganisationMembership.created_at)
    ).all()
    return [
        MemberOut(user_id=profile.id, full_name=profile.full_name, email=profile.email,
                  role=membership.role, status=membership.status)
        for membership, profile in rows
    ]  # fmt: skip


def list_workspaces(db: Session, ctx: TenantContext) -> list[WorkspaceOut]:
    rows = db.scalars(
        select(Workspace).where(Workspace.organisation_id == ctx.organisation_id).order_by(Workspace.created_at)
    ).all()
    return [WorkspaceOut.model_validate(row) for row in rows]


def create_workspace(db: Session, ctx: TenantContext, name: str) -> WorkspaceOut:
    ctx.require("workspaces:create")
    workspace = Workspace(organisation_id=ctx.organisation_id, name=name, created_by=ctx.user.id)
    db.add(workspace)
    try:
        db.flush()
    except IntegrityError as error:
        db.rollback()
        raise Conflict("A workspace with this name already exists.") from error
    audit.record(db, organisation_id=ctx.organisation_id, actor_id=ctx.user.id, action="workspace.created",
                 resource_type="workspace", resource_id=workspace.id, details={"name": name})  # fmt: skip
    db.commit()
    return WorkspaceOut.model_validate(workspace)


def get_workspace(db: Session, ctx: TenantContext, workspace_id: UUID) -> Workspace | None:
    return db.scalar(
        select(Workspace).where(Workspace.id == workspace_id, Workspace.organisation_id == ctx.organisation_id)
    )
