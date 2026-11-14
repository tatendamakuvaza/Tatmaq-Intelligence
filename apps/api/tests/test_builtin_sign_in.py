"""The built-in sign-in as it runs in production (AUTH_MODE=builtin).

Guessing a password is stopped, passwords can be changed and reset, sign-ups can be
closed, and production accepts this mode with nothing but APP_SECRET_KEY configured.
"""

from __future__ import annotations

import importlib.util
import uuid

import psycopg
import pytest
from sqlalchemy import text

from app.core.config import Settings
from app.core.database import system_session
from app.core.errors import AuthenticationError
from app.security import builtin_auth
from app.security.auth import AuthUser, BuiltinTokenVerifier
from conftest import ADMIN_URL, REPO_ROOT, _database_url

PASSWORD = "a long enough password"
WRONG = "not the password"


def register(client, password: str = PASSWORD) -> tuple[str, dict[str, str]]:
    email = f"user-{uuid.uuid4().hex[:10]}@example.com"
    response = client.post("/v1/auth/register", json={"email": email, "password": password})
    assert response.status_code == 201, response.text
    return email, {"Authorization": f"Bearer {response.json()['access_token']}"}


def sign_in(client, email: str, password: str = PASSWORD):
    return client.post("/v1/auth/login", json={"email": email, "password": password})


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(f"tatmaq_{name}", REPO_ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_five_wrong_passwords_lock_the_account_until_the_lock_expires(client):
    email, _ = register(client)
    for _ in range(builtin_auth.MAX_FAILED_SIGN_INS):
        wrong = sign_in(client, email, WRONG)
        assert wrong.status_code == 401 and wrong.json()["error"]["code"] == "invalid_credentials"

    locked = sign_in(client, email)  # the right password, but the account is locked
    assert locked.status_code == 429 and locked.json()["error"]["code"] == "too_many_attempts"
    assert "15 minute" in locked.json()["error"]["message"]
    assert sign_in(client, email, WRONG).status_code == 429  # and further guesses are not even checked

    with system_session() as session:
        session.execute(
            text("UPDATE auth.users SET locked_until = NOW() - INTERVAL '1 second' WHERE email = :email"),
            {"email": email},
        )
    assert sign_in(client, email).status_code == 200


def test_a_successful_sign_in_forgets_earlier_mistakes(client):
    email, _ = register(client)
    for _ in range(2):  # four mistakes, a success, four more mistakes: never five in a row
        for _ in range(builtin_auth.MAX_FAILED_SIGN_INS - 1):
            assert sign_in(client, email, WRONG).status_code == 401
        assert sign_in(client, email).status_code == 200


def test_a_signed_in_user_can_change_their_password(client):
    email, headers = register(client)

    def change(current: str, new: str, headers: dict = headers):
        body = {"current_password": current, "new_password": new}
        return client.post("/v1/auth/password", json=body, headers=headers)

    assert change(PASSWORD, "a brand new password", headers={}).status_code == 401  # only when signed in
    # Mistakes are refused without a 401, which would tell the web app to sign the person out.
    wrong = change(WRONG, "a brand new password")
    assert wrong.status_code == 403 and wrong.json()["error"]["message"] == "Your current password is incorrect."
    for unacceptable in ("short", PASSWORD, email):  # too short, unchanged, and the email address itself
        refused = change(PASSWORD, unacceptable)
        assert refused.status_code == 400 and refused.json()["error"]["code"] == "weak_password", unacceptable

    assert change(PASSWORD, "a brand new password").status_code == 204
    assert sign_in(client, email).status_code == 401
    assert sign_in(client, email, "a brand new password").status_code == 200
    assert client.get("/v1/organisations", headers=headers).status_code == 200  # the session in use carries on


def test_guessing_the_current_password_through_the_change_form_also_locks_the_account(client):
    email, headers = register(client)
    for _ in range(builtin_auth.MAX_FAILED_SIGN_INS):
        body = {"current_password": WRONG, "new_password": "a brand new password"}
        assert client.post("/v1/auth/password", json=body, headers=headers).status_code == 403
    assert sign_in(client, email).status_code == 429


def test_sign_ups_can_be_closed(client, settings, monkeypatch):
    email, _ = register(client)
    assert client.get("/v1/config").json()["signups_open"] is True
    monkeypatch.setattr(settings, "allow_signups", False)

    refused = client.post("/v1/auth/register", json={"email": "new-person@example.com", "password": PASSWORD})
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "signups_closed"
    assert client.get("/v1/config").json()["signups_open"] is False
    assert sign_in(client, email).status_code == 200  # existing accounts are unaffected


def test_the_administrator_can_create_accounts_and_reset_passwords(client, database_url, settings, monkeypatch):
    accounts = load_script("accounts")
    monkeypatch.setattr(settings, "allow_signups", False)  # the case this is for
    email = f"invited-{uuid.uuid4().hex[:8]}@example.com"

    temporary = accounts.create(database_url, email.upper())  # stored in lower case, like sign-up does
    assert len(temporary) >= 12 and sign_in(client, email, temporary).status_code == 200
    with pytest.raises(accounts.AccountError, match="already exists"):
        accounts.create(database_url, email)
    with pytest.raises(accounts.AccountError, match="valid email"):
        accounts.create(database_url, "not-an-email")

    for _ in range(builtin_auth.MAX_FAILED_SIGN_INS):  # the person forgets it and locks themselves out
        sign_in(client, email, WRONG)
    assert (email, True) in [(address, locked) for address, _, locked in accounts.list_accounts(database_url)]

    replacement = accounts.reset_password(database_url, email)
    assert replacement != temporary
    assert sign_in(client, email, replacement).status_code == 200  # works at once: the lock is cleared too
    assert sign_in(client, email, temporary).status_code == 401
    with pytest.raises(accounts.AccountError, match="no account"):
        accounts.reset_password(database_url, "nobody@example.com")


def test_built_in_sign_in_is_accepted_in_production_and_signs_sessions_with_a_derived_key():
    production = {"app_env": "production", "app_secret_key": "k" * 40, "database_url": "postgresql://u@h/d",
                  "cors_allowed_origins": "https://app.example.com", "auth_mode": "builtin",
                  "storage_backend": "database"}  # fmt: skip
    settings = Settings(_env_file=None, **production)
    assert settings.builtin_sign_in and settings.dev_jwt_secret == ""
    key = settings.session_token_secret
    assert len(key) == 64 and key != settings.app_secret_key  # derived, not the link-signing secret itself
    assert Settings(_env_file=None, **production).session_token_secret == key  # the same after a restart
    assert Settings(_env_file=None, **{**production, "app_secret_key": "j" * 40}).session_token_secret != key

    token, lifetime = builtin_auth.issue_token(AuthUser(id=uuid.uuid4(), email="a@example.com"), settings)
    assert lifetime == 8 * 3600 and BuiltinTokenVerifier(key, settings.jwt_audience).verify(token).email
    with pytest.raises(AuthenticationError):
        BuiltinTokenVerifier(settings.app_secret_key, settings.jwt_audience).verify(token)
    with pytest.raises(ValueError, match="refused in production"):  # the published development secret never ships
        Settings(_env_file=None, **{**production, "auth_mode": "dev"})
    with pytest.raises(ValueError, match="DB_POOL_SIZE"):
        Settings(_env_file=None, **{**production, "db_pool_size": 0})


def scratch_database(prepare: str = "") -> tuple[str, str]:
    name = f"tatmaq_test_{uuid.uuid4().hex[:10]}"
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    url = _database_url(name)
    if prepare:
        with psycopg.connect(url, autocommit=True) as connection:
            connection.execute(prepare)
    return name, url


def drop_database(name: str) -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def applied_files(url: str) -> set[str]:
    with psycopg.connect(url) as connection:
        return {name for (name,) in connection.execute("SELECT filename FROM schema_migrations")}


def account_columns(url: str) -> set[str]:
    with psycopg.connect(url) as connection:
        rows = connection.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'auth' AND table_name = 'users'"
        )
        return {name for (name,) in rows}


def test_an_existing_installation_gains_the_account_protections_on_its_next_migrate():
    migrate = load_script("migrate").migrate
    name, url = scratch_database()
    try:
        migrate(url, log=lambda *_: None)
        # Put the database back to how an installation made before this change looks.
        with psycopg.connect(url, autocommit=True) as connection:
            connection.execute(
                "ALTER TABLE auth.users DROP COLUMN failed_sign_ins, DROP COLUMN locked_until, "
                "DROP COLUMN password_changed_at"
            )
            connection.execute("DELETE FROM schema_migrations WHERE filename = 'local/001_builtin_accounts.sql'")
        assert migrate(url, log=lambda *_: None) == ["local/001_builtin_accounts.sql"]
        assert {"failed_sign_ins", "locked_until", "password_changed_at"} <= account_columns(url)
        assert migrate(url, log=lambda *_: None) == []  # and then there is nothing left to do
    finally:
        drop_database(name)


def test_a_database_with_its_own_auth_schema_is_never_given_ours():
    """As on Supabase: accounts belong to the platform, and our account tables must stay out."""
    migrate = load_script("migrate").migrate
    name, url = scratch_database(
        "CREATE SCHEMA auth; CREATE TABLE auth.users (id UUID PRIMARY KEY); "
        "CREATE FUNCTION auth.uid() RETURNS UUID LANGUAGE SQL STABLE AS "
        "$$ SELECT (NULLIF(current_setting('request.jwt.claims', TRUE), '')::JSONB ->> 'sub')::UUID $$;"
    )
    try:
        migrate(url, log=lambda *_: None)
        files = applied_files(url)
        assert not any(file.startswith("local/") for file in files)
        assert "migrations/0003_file_storage.sql" in files
        assert account_columns(url) == {"id"}
    finally:
        drop_database(name)


def test_this_installation_has_both_account_files_and_the_file_tables(database_url):
    assert {"local/000_supabase_auth_shim.sql", "local/001_builtin_accounts.sql",
            "migrations/0003_file_storage.sql"} <= applied_files(database_url)  # fmt: skip
