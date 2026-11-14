"""Built-in sign-in: the application's own email-and-password accounts.

Used when no outside sign-in service is configured (``AUTH_MODE=builtin`` in
production, ``AUTH_MODE=dev`` on a laptop). The alternative is Supabase Auth, in which
case none of this is reachable: the routes are not registered.

What it does, and what it deliberately does not do:

* Passwords are stored only as salted scrypt hashes.
* Five wrong passwords in a row lock the account for fifteen minutes, so a password
  cannot be found by guessing over the network.
* A signed-in user can change their password. A forgotten password is reset by the
  administrator (``scripts/accounts.py reset-password``): this sign-in sends no email,
  so there is no confirmation message and no "forgot password" link.
* A session token lasts eight hours and is not revoked early by a password change.

Accounts live in the ``auth.users`` table that ``database/local`` creates. Before
touching it the code checks that schema's marker, so it can never write passwords into
a real Supabase ``auth.users`` table by mistake.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import time
from functools import lru_cache
from uuid import UUID

import jwt
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..core.config import Settings
from ..core.errors import (
    AppError,
    AuthenticationError,
    ConfigurationError,
    Conflict,
    LimitExceeded,
    PermissionDenied,
)
from .auth import BUILTIN_ISSUER, AuthUser

TOKEN_TTL_SECONDS = 8 * 3600
MIN_PASSWORD_LENGTH = 8
MAX_FAILED_SIGN_INS = 5
LOCKOUT_MINUTES = 15
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}
SHIM_MARKER = "tatmaq-local-auth-shim"


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return f"scrypt${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def _password_matches(password: str, stored: str) -> bool:
    try:
        _, salt, digest = stored.split("$")
        expected = base64.b64decode(digest)
        actual = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), **_SCRYPT)
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


def _require_builtin_accounts_schema(session: Session) -> None:
    marker = session.execute(
        text("SELECT obj_description(oid, 'pg_namespace') FROM pg_namespace WHERE nspname = 'auth'")
    ).scalar()
    if marker != SHIM_MARKER:
        raise ConfigurationError(
            "Built-in sign-in needs the accounts schema that scripts/migrate.py installs on a plain "
            "PostgreSQL database. This database has a real 'auth' schema: use AUTH_MODE=supabase."
        )


def normalise_email(email: str) -> str:
    cleaned = email.strip().lower()
    if not _EMAIL.match(cleaned) or len(cleaned) > 320:
        raise AuthenticationError("Enter a valid email address.", code="invalid_email")
    return cleaned


def check_new_password(password: str, email: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise AuthenticationError(
            f"Choose a password of at least {MIN_PASSWORD_LENGTH} characters.", code="weak_password"
        )
    if password.strip().lower() == email.strip().lower():
        raise AuthenticationError("Choose a password that is not your email address.", code="weak_password")
    return password


def create_account(session: Session, email: str, password: str) -> AuthUser:
    """Create an account. Used by sign-up and by the administrator's script."""
    _require_builtin_accounts_schema(session)
    email = normalise_email(email)
    check_new_password(password, email)
    row = session.execute(
        text(
            "INSERT INTO auth.users (email, encrypted_password) VALUES (:email, :password) "
            "ON CONFLICT (email) DO NOTHING RETURNING id"
        ),
        {"email": email, "password": hash_password(password)},
    ).one_or_none()
    if row is None:
        raise Conflict("An account with this email already exists.", code="email_taken")
    return AuthUser(id=row.id, email=email)


def register(session: Session, email: str, password: str, settings: Settings) -> AuthUser:
    if not settings.allow_signups:
        raise PermissionDenied(
            "Sign-ups are closed. Ask your administrator to create an account for you.", code="signups_closed"
        )
    return create_account(session, email, password)


def _locked_out(row) -> None:
    if row.locked_until is not None and row.locked_until > row.now:
        minutes = max(1, int((row.locked_until - row.now).total_seconds() // 60) + 1)
        raise LimitExceeded(
            f"Too many wrong passwords. This account is locked for another {minutes} minute(s).",
            code="too_many_attempts",
        )


def _verify_password(session: Session, row, password: str) -> None:
    """Check a password for an existing account, counting failures towards the lock.

    The count is committed before the error is raised: the caller's transaction is
    rolled back on an exception, and a failed attempt must not be forgotten with it.
    """
    _locked_out(row)
    if _password_matches(password, row.encrypted_password):
        if row.failed_sign_ins:
            session.execute(
                text("UPDATE auth.users SET failed_sign_ins = 0, locked_until = NULL WHERE id = :id"), {"id": row.id}
            )
        return
    failures = row.failed_sign_ins + 1
    if failures >= MAX_FAILED_SIGN_INS:
        session.execute(
            text(
                "UPDATE auth.users SET failed_sign_ins = 0, "
                "locked_until = NOW() + (:minutes * INTERVAL '1 minute') WHERE id = :id"
            ),
            {"id": row.id, "minutes": LOCKOUT_MINUTES},
        )
    else:
        session.execute(
            text("UPDATE auth.users SET failed_sign_ins = :failures WHERE id = :id"),
            {"id": row.id, "failures": failures},
        )
    session.commit()
    raise AuthenticationError("Incorrect email or password.", code="invalid_credentials")


@lru_cache
def _unknown_account_hash() -> str:
    return hash_password("unknown-account", b"\x00" * 16)


_ACCOUNT = (
    "SELECT id, email, encrypted_password, failed_sign_ins, locked_until, NOW() AS now "
    "FROM auth.users WHERE {column} = :value FOR UPDATE"
)


def login(session: Session, email: str, password: str) -> AuthUser:
    _require_builtin_accounts_schema(session)
    # FOR UPDATE: simultaneous attempts on one account are checked one at a time, so
    # guessing in parallel cannot get past the lock.
    row = session.execute(text(_ACCOUNT.format(column="email")), {"value": email.strip().lower()}).one_or_none()
    if row is None:
        # Do the same work as for a real account, so response time does not reveal
        # which emails are registered.
        _password_matches(password, _unknown_account_hash())
        raise AuthenticationError("Incorrect email or password.", code="invalid_credentials")
    _verify_password(session, row, password)
    return AuthUser(id=UUID(str(row.id)), email=row.email)


def change_password(session: Session, user: AuthUser, current_password: str, new_password: str) -> None:
    _require_builtin_accounts_schema(session)
    row = session.execute(text(_ACCOUNT.format(column="id")), {"value": user.id}).one_or_none()
    if row is None:
        raise AuthenticationError("This account no longer exists.")
    # The caller is signed in, so a mistake here is not "401 sign in again" (which would
    # make the web app sign them out): it is a refused or invalid request.
    try:
        _verify_password(session, row, current_password)
    except AuthenticationError as error:
        raise PermissionDenied("Your current password is incorrect.", code="invalid_credentials") from error
    try:
        check_new_password(new_password, row.email)
    except AuthenticationError as error:
        raise AppError(error.message, code="weak_password") from error
    if hmac.compare_digest(new_password, current_password):
        raise AppError("Choose a password different from your current one.", code="weak_password")
    set_password(session, row.id, new_password)


def set_password(session: Session, user_id: UUID, password: str) -> None:
    """Replace a password and clear any lock. The caller has already decided this is allowed."""
    session.execute(
        text(
            "UPDATE auth.users SET encrypted_password = :password, password_changed_at = NOW(), "
            "failed_sign_ins = 0, locked_until = NULL WHERE id = :id"
        ),
        {"id": user_id, "password": hash_password(password)},
    )


def temporary_password() -> str:
    """A random password for the administrator to hand over; the user should change it."""
    return secrets.token_urlsafe(12)


def issue_token(user: AuthUser, settings: Settings) -> tuple[str, int]:
    now = int(time.time())
    claims = {
        "sub": str(user.id), "email": user.email, "role": "authenticated",
        "aud": settings.jwt_audience, "iss": BUILTIN_ISSUER, "iat": now, "exp": now + TOKEN_TTL_SECONDS,
    }  # fmt: skip
    return jwt.encode(claims, settings.session_token_secret, algorithm="HS256"), TOKEN_TTL_SECONDS
