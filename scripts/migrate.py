#!/usr/bin/env python3
"""Apply the database schema: migrations, security policies and seed data.

    python scripts/migrate.py              # uses DATABASE_URL from the environment or .env
    python scripts/migrate.py --status     # show what has been applied, change nothing

How it works
------------
database/migrations/*.sql   applied once each, in filename order, and recorded in the
                            ``schema_migrations`` table with a checksum. An applied
                            migration must never be edited: add a new file instead.
database/policies/*.sql     Row Level Security. Idempotent; re-applied on every run.
database/seeds/*.sql        reference data (roles). Idempotent; re-applied on every run.
database/local/*.sql        the ``auth`` schema for a plain PostgreSQL database: a stand-in
                            for Supabase's, and where built-in sign-in keeps its accounts.
                            Applied once each, like migrations, but only when the database
                            has no ``auth`` schema or has this project's own. Never applied
                            to a Supabase project.

Each file runs in its own transaction, so a failing file leaves nothing half-applied.
The same script works against local PostgreSQL and against a Supabase project.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

import psycopg

REPO_ROOT = Path(__file__).resolve().parent.parent
DATABASE_DIR = REPO_ROOT / "database"
LOCK_KEY = 0x7A74A701  # arbitrary constant: one migrator at a time
OWN_AUTH_SCHEMA = "tatmaq-local-auth-shim"  # the comment database/local/000 puts on its auth schema

MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename TEXT PRIMARY KEY,
    checksum TEXT NOT NULL,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
)
"""


class MigrationError(RuntimeError):
    pass


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def resolve_database_url(explicit: str | None = None) -> str:
    url = explicit or os.environ.get("DATABASE_URL") or read_env_file(REPO_ROOT / ".env").get("DATABASE_URL")
    if not url:
        raise MigrationError("DATABASE_URL is not set (environment, .env, or --database-url).")
    return to_libpq_url(url)


def to_libpq_url(url: str) -> str:
    """Accept SQLAlchemy-style URLs (postgresql+psycopg://) as well as plain ones."""
    scheme, separator, rest = url.partition("://")
    return f"{scheme.split('+')[0]}{separator}{rest}"


def checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sql_files(folder: str) -> list[Path]:
    return sorted((DATABASE_DIR / folder).glob("*.sql"))


def migrate(database_url: str, *, log=print) -> list[str]:
    """Bring the database up to date. Returns the names of newly applied migrations."""
    applied_now: list[str] = []
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))
        try:
            connection.execute(MIGRATIONS_TABLE)
            applied = dict(connection.execute("SELECT filename, checksum FROM schema_migrations").fetchall())

            auth_schema = connection.execute(
                "SELECT obj_description(oid, 'pg_namespace') FROM pg_namespace WHERE nspname = 'auth'"
            ).fetchone()
            pending: list[tuple[str, Path]] = []
            if auth_schema is None:
                log("No 'auth' schema found: this is not Supabase, installing the project's own.")
            if auth_schema is None or auth_schema[0] == OWN_AUTH_SCHEMA:
                pending += [(f"local/{path.name}", path) for path in sql_files("local")]
            pending += [(f"migrations/{path.name}", path) for path in sql_files("migrations")]

            for name, path in pending:
                digest = checksum(path)
                if name in applied:
                    if applied[name] != digest:
                        raise MigrationError(
                            f"{name} was changed after it was applied. "
                            "Applied migrations are immutable: put the change in a new file."
                        )
                    continue
                log(f"applying {name}")
                with connection.transaction():
                    connection.execute(path.read_text(encoding="utf-8"))
                    connection.execute(
                        "INSERT INTO schema_migrations (filename, checksum) VALUES (%s, %s)", (name, digest)
                    )
                applied_now.append(name)

            for folder in ("policies", "seeds"):
                for path in sql_files(folder):
                    log(f"applying {folder}/{path.name}")
                    with connection.transaction():
                        connection.execute(path.read_text(encoding="utf-8"))
        finally:
            connection.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
    return applied_now


def status(database_url: str) -> None:
    with psycopg.connect(database_url) as connection:
        exists = connection.execute("SELECT to_regclass('public.schema_migrations')").fetchone()[0]
        applied = (
            dict(connection.execute("SELECT filename, applied_at FROM schema_migrations").fetchall()) if exists else {}
        )
    for path in sql_files("migrations"):
        name = f"migrations/{path.name}"
        print(f"{'applied ' + str(applied[name])[:19] if name in applied else 'PENDING':<28} {name}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--database-url", help="overrides DATABASE_URL")
    parser.add_argument("--status", action="store_true", help="list migrations without applying anything")
    arguments = parser.parse_args()
    try:
        url = resolve_database_url(arguments.database_url)
        if arguments.status:
            status(url)
        else:
            newly = migrate(url)
            print(f"Database is up to date ({len(newly)} new migration(s) applied).")
    except (MigrationError, psycopg.Error) as error:
        print(f"Migration failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
