"""Built-in sign-in, profiles, organisations and workspaces."""

from __future__ import annotations

from fastapi import APIRouter, Response

from ...core.database import system_session
from ...schemas.accounts import (
    Credentials,
    MemberOut,
    OrganisationCreated,
    OrganisationIn,
    OrganisationOut,
    PasswordChange,
    ProfileIn,
    ProfileOut,
    TokenOut,
    UserOut,
    WorkspaceIn,
    WorkspaceOut,
)  # fmt: skip
from ...security import builtin_auth
from ...services import organisations
from ..deps import AppSettings, CurrentUser, Db, Tenant

router = APIRouter()
# Registered only when this API keeps the accounts itself (AUTH_MODE=builtin or dev).
# Under Supabase Auth these routes do not exist.
sign_in_router = APIRouter(prefix="/auth", tags=["sign-in"])


def _session_for(user, settings) -> TokenOut:
    token, expires_in = builtin_auth.issue_token(user, settings)
    return TokenOut(access_token=token, expires_in=expires_in, user=UserOut(id=user.id, email=user.email))


@sign_in_router.post("/register", response_model=TokenOut, status_code=201)
def register(credentials: Credentials, settings: AppSettings) -> TokenOut:
    """Create an account and sign in. Refused with ``signups_closed`` when sign-ups are switched off."""
    with system_session() as session:
        user = builtin_auth.register(session, credentials.email, credentials.password, settings)
    return _session_for(user, settings)


@sign_in_router.post("/login", response_model=TokenOut)
def login(credentials: Credentials, settings: AppSettings) -> TokenOut:
    """Sign in. Five wrong passwords in a row lock the account for fifteen minutes (``too_many_attempts``)."""
    with system_session() as session:
        user = builtin_auth.login(session, credentials.email, credentials.password)
    return _session_for(user, settings)


@sign_in_router.post("/password", status_code=204)
def change_password(body: PasswordChange, user: CurrentUser) -> Response:
    """Change the caller's own password. They stay signed in."""
    with system_session() as session:
        builtin_auth.change_password(session, user, body.current_password, body.new_password)
    return Response(status_code=204)


@router.post("/auth/profile", response_model=ProfileOut, tags=["accounts"])
def save_profile(body: ProfileIn, user: CurrentUser, db: Db) -> ProfileOut:
    """Create the caller's profile after sign-up, or update their name. Safe to repeat."""
    return ProfileOut.model_validate(organisations.upsert_profile(db, user, body.full_name))


@router.get("/organisations", response_model=list[OrganisationOut], tags=["accounts"])
def list_organisations(user: CurrentUser, db: Db) -> list[OrganisationOut]:
    return organisations.list_organisations(db, user)


@router.post("/organisations", response_model=OrganisationCreated, status_code=201, tags=["accounts"])
def create_organisation(body: OrganisationIn, user: CurrentUser, settings: AppSettings) -> OrganisationCreated:
    organisation, workspace = organisations.create_organisation(user, body.name, settings)
    return OrganisationCreated(organisation=organisation, workspace=workspace)


@router.get("/organisations/members", response_model=list[MemberOut], tags=["accounts"])
def list_members(ctx: Tenant, db: Db) -> list[MemberOut]:
    return organisations.list_members(db, ctx)


@router.get("/workspaces", response_model=list[WorkspaceOut], tags=["accounts"])
def list_workspaces(ctx: Tenant, db: Db) -> list[WorkspaceOut]:
    return organisations.list_workspaces(db, ctx)


@router.post("/workspaces", response_model=WorkspaceOut, status_code=201, tags=["accounts"])
def create_workspace(body: WorkspaceIn, ctx: Tenant, db: Db) -> WorkspaceOut:
    return organisations.create_workspace(db, ctx, body.name)
