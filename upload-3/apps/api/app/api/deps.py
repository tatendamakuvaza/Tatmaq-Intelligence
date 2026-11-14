"""Request dependencies: who is calling, their database session and their organisation."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from ..core.config import Settings, get_settings
from ..core.database import user_session
from ..core.errors import AuthenticationError
from ..security.auth import AuthUser, get_verifier
from ..security.tenancy import TenantContext, resolve_tenant
from ..storage import Storage, get_storage


def current_user(authorization: Annotated[str | None, Header()] = None) -> AuthUser:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthenticationError("Sign in to continue.")
    return get_verifier().verify(token.strip())


CurrentUser = Annotated[AuthUser, Depends(current_user)]


def db_session(user: CurrentUser) -> Iterator[Session]:
    """A Row-Level-Security session for the caller.

    Handlers commit explicitly when they change something; anything left uncommitted
    is rolled back when the session closes.
    """
    session = user_session(user.id)
    try:
        yield session
    finally:
        session.close()


Db = Annotated[Session, Depends(db_session)]


def tenant(
    user: CurrentUser, db: Db, x_organisation_id: Annotated[UUID, Header(description="The organisation to act in.")]
) -> TenantContext:
    return resolve_tenant(db, user, x_organisation_id)


Tenant = Annotated[TenantContext, Depends(tenant)]
AppSettings = Annotated[Settings, Depends(get_settings)]
FileStorage = Annotated[Storage, Depends(get_storage)]
