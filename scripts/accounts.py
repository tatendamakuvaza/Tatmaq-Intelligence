#!/usr/bin/env python3
"""Manage built-in sign-in accounts from the command line (AUTH_MODE=builtin).

    python scripts/accounts.py list
    python scripts/accounts.py create alice@example.com            # prints a temporary password
    python scripts/accounts.py reset-password alice@example.com    # new temporary password, lock cleared

Built-in sign-in sends no email, so there is no "forgot password" link: a forgotten
password is reset here, and the person changes it under Settings after signing in.
``create`` is for when sign-ups are closed (ALLOW_SIGNUPS=false).

Uses DATABASE_URL from the environment or .env, like scripts/migrate.py.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import psycopg

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(Path(__file__).resolve().parent), str(REPO_ROOT / "apps" / "api")]

from migrate import MigrationError, resolve_database_url  # noqa: E402

from app.security import builtin_auth  # noqa: E402


class AccountError(RuntimeError):
    pass


def _connect(database_url: str) -> psycopg.Connection:
    connection = psycopg.connect(database_url)
    marker = connection.execute(
        "SELECT obj_description(oid, 'pg_namespace') FROM pg_namespace WHERE nspname = 'auth'"
    ).fetchone()
    if marker is None or marker[0] != builtin_auth.SHIM_MARKER:
        connection.close()
        raise AccountError(
            "This database does not hold built-in accounts. Run scripts/migrate.py first; "
            "on a Supabase project, manage users in the Supabase dashboard instead."
        )
    return connection


def create(database_url: str, email: str) -> str:
    """Create an account and return its temporary password."""
    try:
        email = builtin_auth.normalise_email(email)
    except Exception as error:
        raise AccountError(str(error)) from error
    password = builtin_auth.temporary_password()
    with _connect(database_url) as connection:
        created = connection.execute(
            "INSERT INTO auth.users (email, encrypted_password) VALUES (%s, %s) "
            "ON CONFLICT (email) DO NOTHING RETURNING id",
            (email, builtin_auth.hash_password(password)),
        ).fetchone()
    if created is None:
        raise AccountError(f"An account for {email} already exists. Use reset-password to give it a new password.")
    return password


def reset_password(database_url: str, email: str) -> str:
    """Give an account a new temporary password, clear any lock, and return the password."""
    password = builtin_auth.temporary_password()
    with _connect(database_url) as connection:
        updated = connection.execute(
            "UPDATE auth.users SET encrypted_password = %s, password_changed_at = NOW(), "
            "failed_sign_ins = 0, locked_until = NULL WHERE email = %s RETURNING id",
            (builtin_auth.hash_password(password), email.strip().lower()),
        ).fetchone()
    if updated is None:
        raise AccountError(f"There is no account for {email.strip().lower()}.")
    return password


def list_accounts(database_url: str) -> list[tuple[str, str, bool]]:
    """(email, created on, locked right now) for every account, oldest first."""
    with _connect(database_url) as connection:
        rows = connection.execute(
            "SELECT email, created_at::date::text, COALESCE(locked_until > NOW(), FALSE) "
            "FROM auth.users ORDER BY created_at"
        ).fetchall()
    return [(email, created, bool(locked)) for email, created, locked in rows]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--database-url", help="overrides DATABASE_URL")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="show every account")
    for name, text in (("create", "create an account"), ("reset-password", "give an account a new password")):
        commands.add_parser(name, help=text).add_argument("email")
    arguments = parser.parse_args()
    try:
        url = resolve_database_url(arguments.database_url)
        if arguments.command == "list":
            accounts = list_accounts(url)
            for email, created, locked in accounts:
                print(f"{created}  {email}{'  (locked)' if locked else ''}")
            print(f"{len(accounts)} account(s).")
            return 0
        action = create if arguments.command == "create" else reset_password
        password = action(url, arguments.email)
    except (AccountError, MigrationError, psycopg.Error) as error:
        print(f"Failed: {error}", file=sys.stderr)
        return 1
    print(f"Temporary password for {arguments.email.strip().lower()}: {password}")
    print("Pass it on privately. They should change it under Settings after signing in.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
