"""Database sessions.

There are exactly two ways to talk to the database, and choosing between them is a
security decision:

``user_session(user_id)``
    For anything done on behalf of a signed-in user. Every transaction first switches
    to the restricted role ``tatmaq_app_user`` and records who the user is, so
    PostgreSQL's Row Level Security filters every statement. A query that forgets to
    filter by organisation returns nothing from other tenants.

``system_session()``
    For the background worker, migrations and the few operations a user cannot do as
    themselves (creating the organisation they are about to own). Bypasses Row Level
    Security, so callers must establish the organisation themselves.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from uuid import UUID

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import Session

from .config import get_settings

APP_ROLE = "tatmaq_app_user"


@lru_cache
def get_engine() -> Engine:
    settings = get_settings()
    return create_engine(
        settings.sqlalchemy_url,
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        # Server-side prepared statements break behind transaction-mode connection
        # poolers such as Supabase's, so they are switched off.
        connect_args={"prepare_threshold": None},
    )


def user_session(user_id: UUID) -> Session:
    """A session in which every transaction is subject to Row Level Security for ``user_id``."""
    session = Session(get_engine(), expire_on_commit=False)
    claims = json.dumps({"sub": str(user_id), "role": "authenticated"})

    # Fires at the start of *every* transaction, so the restriction also holds after
    # a commit or rollback in the middle of a request: there is no window in which
    # the session runs with the connection's own, more powerful, role.
    @event.listens_for(session, "after_begin")
    def _restrict(_session, _transaction, connection) -> None:
        connection.execute(text(f"SET LOCAL ROLE {APP_ROLE}"))
        connection.execute(text("SELECT set_config('request.jwt.claims', :claims, true)"), {"claims": claims})

    return session


@contextmanager
def system_session() -> Iterator[Session]:
    """A privileged session. Commits on success, rolls back on error."""
    session = Session(get_engine(), expire_on_commit=False)
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()


def dispose_engine() -> None:
    if get_engine.cache_info().currsize:
        get_engine().dispose()
        get_engine.cache_clear()
