#!/usr/bin/env python3
"""Manage the agent bridge account: the least-privilege sign-in an external AI assistant uses.

    python scripts/agent_account.py create --organisation acme-wholesale
    python scripts/agent_account.py list
    python scripts/agent_account.py rotate --email arena-agent@example.com
    python scripts/agent_account.py revoke --email arena-agent@example.com

The account is given the ``agent`` role: it may upload datasets, run and cancel analyses,
download reports and record lessons for the agents. It may not manage the organisation,
its members or its workspaces. Row Level Security keeps it inside its own organisation,
and everything it does is written to the audit log like any other user's actions.

``create`` prints the password once and a ready-to-paste prompt for a new Arena chat.
``revoke`` suspends the membership, which cuts off access immediately.

Uses DATABASE_URL from the environment or .env, like scripts/migrate.py.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from uuid import UUID

import psycopg

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(Path(__file__).resolve().parent), str(REPO_ROOT / "apps" / "api")]

from migrate import MigrationError, resolve_database_url  # noqa: E402

from app.security import builtin_auth  # noqa: E402

DEFAULT_EMAIL = "arena-agent@tatmaq.local"
AGENT_ROLE = "agent"


class BridgeError(RuntimeError):
    pass


def _connect(database_url: str) -> psycopg.Connection:
    connection = psycopg.connect(database_url)
    marker = connection.execute(
        "SELECT obj_description(oid, 'pg_namespace') FROM pg_namespace WHERE nspname = 'auth'"
    ).fetchone()
    if marker is None or marker[0] != builtin_auth.SHIM_MARKER:
        connection.close()
        raise BridgeError(
            "This database does not hold built-in accounts. The agent bridge needs AUTH_MODE=builtin "
            "(or dev). On a Supabase project, create the user in Supabase and add it to the "
            "organisation with the 'agent' role instead."
        )
    return connection


def _organisation(connection: psycopg.Connection, reference: str) -> tuple[UUID, str, str]:
    """Find an organisation by slug or by id."""
    reference = reference.strip()
    row = connection.execute(
        "SELECT id, name, slug FROM organisations WHERE slug = %s OR id::text = %s",
        (reference.lower(), reference.lower()),
    ).fetchone()
    if row is None:
        raise BridgeError(f"No organisation matches '{reference}'. Use its slug or its id.")
    return row[0], row[1], row[2]


def create(database_url: str, email: str, organisation: str, full_name: str) -> tuple[str, str, str]:
    """Create the account, attach it to one organisation as an agent, return (password, org id, org name)."""
    try:
        email = builtin_auth.normalise_email(email)
    except Exception as error:
        raise BridgeError(str(error)) from error
    password = builtin_auth.temporary_password()
    with _connect(database_url) as connection:
        organisation_id, name, _slug = _organisation(connection, organisation)
        created = connection.execute(
            "INSERT INTO auth.users (email, encrypted_password) VALUES (%s, %s) "
            "ON CONFLICT (email) DO NOTHING RETURNING id",
            (email, builtin_auth.hash_password(password)),
        ).fetchone()
        if created is None:
            raise BridgeError(f"An account for {email} already exists. Use rotate to give it a new password.")
        user_id = created[0]
        connection.execute(
            "INSERT INTO profiles (id, full_name, email) VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING",
            (user_id, full_name, email),
        )
        connection.execute(
            "INSERT INTO organisation_memberships (organisation_id, user_id, role, status) VALUES (%s, %s, %s, 'active')",
            (organisation_id, user_id, AGENT_ROLE),
        )
    return password, str(organisation_id), name


def rotate(database_url: str, email: str) -> str:
    password = builtin_auth.temporary_password()
    with _connect(database_url) as connection:
        updated = connection.execute(
            "UPDATE auth.users SET encrypted_password = %s, password_changed_at = NOW(), "
            "failed_sign_ins = 0, locked_until = NULL WHERE email = %s RETURNING id",
            (builtin_auth.hash_password(password), email.strip().lower()),
        ).fetchone()
    if updated is None:
        raise BridgeError(f"There is no account for {email.strip().lower()}.")
    return password


def revoke(database_url: str, email: str) -> int:
    """Suspend every membership of this account. It can no longer act in any organisation."""
    with _connect(database_url) as connection:
        updated = connection.execute(
            "UPDATE organisation_memberships SET status = 'suspended' "
            "WHERE user_id = (SELECT id FROM auth.users WHERE email = %s) AND status = 'active' RETURNING id",
            (email.strip().lower(),),
        ).fetchall()
    return len(updated)


def list_agents(database_url: str) -> list[tuple[str, str, str, str]]:
    with _connect(database_url) as connection:
        rows = connection.execute(
            "SELECT u.email, o.name, m.role, m.status FROM organisation_memberships m "
            "JOIN auth.users u ON u.id = m.user_id JOIN organisations o ON o.id = m.organisation_id "
            "WHERE m.role = 'agent' ORDER BY u.email, o.name"
        ).fetchall()
    return [(email, name, role, status) for email, name, role, status in rows]


def bridge_prompt(api_url: str, email: str, password: str, organisation_id: str) -> str:
    return (
        "You are working on my TATMAQ Intelligence system through its agent bridge.\n"
        f"Repository: https://github.com/tatendamakuvaza/Tatmaq-Intelligence\n"
        f"API: {api_url}\n"
        f"Agent sign-in: {email} / {password}\n"
        f"Organisation id: {organisation_id}\n\n"
        "Clone the repository, then read docs/agent-bridge/README.md and use\n"
        "scripts/tatmaq_agent.py (set TATMAQ_API_URL, TATMAQ_EMAIL, TATMAQ_PASSWORD,\n"
        "TATMAQ_ORGANISATION_ID) to inspect my datasets, run analyses and read the verified\n"
        "findings before proposing changes. Never invent figures: quote only what the API\n"
        "returns. Record what you learn with the 'lesson' command."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--database-url", help="overrides DATABASE_URL")
    commands = parser.add_subparsers(dest="command", required=True)
    create_parser = commands.add_parser("create", help="create the bridge account and attach it to an organisation")
    create_parser.add_argument("--organisation", required=True, help="organisation slug or id")
    create_parser.add_argument("--email", default=DEFAULT_EMAIL)
    create_parser.add_argument("--name", default="Arena Agent", help="display name shown under People")
    create_parser.add_argument(
        "--api-url", default="https://tatmaq-api.onrender.com", help="the API address, for the printed prompt"
    )
    create_parser.add_argument("--no-prompt", action="store_true", help="do not print the paste-ready Arena prompt")
    commands.add_parser("list", help="show every bridge account")
    for name, text in (("rotate", "give the account a new password"), ("revoke", "suspend the account's access")):
        commands.add_parser(name, help=text).add_argument("--email", default=DEFAULT_EMAIL)
    arguments = parser.parse_args()

    try:
        url = resolve_database_url(arguments.database_url)
        if arguments.command == "list":
            agents = list_agents(url)
            for email, organisation, role, status in agents:
                print(f"{email}  {organisation}  {role}  {status}")
            print(f"{len(agents)} bridge membership(s).")
            return 0
        if arguments.command == "create":
            password, organisation_id, name = create(url, arguments.email, arguments.organisation, arguments.name)
            print(f"Bridge account created: {arguments.email.strip().lower()}")
            print(f"Organisation: {name} ({organisation_id}), role: {AGENT_ROLE}")
            print(f"Password (shown once): {password}")
            if not arguments.no_prompt:
                print("\n--- Paste this into a new Arena chat " + "-" * 34)
                print(bridge_prompt(arguments.api_url, arguments.email.strip().lower(), password, organisation_id))
                print("-" * 72)
            print(
                "\nRevoke any time with: python scripts/agent_account.py revoke --email "
                + arguments.email.strip().lower()
            )
            return 0
        if arguments.command == "rotate":
            print(f"New password for {arguments.email.strip().lower()}: {rotate(url, arguments.email)}")
            return 0
        count = revoke(url, arguments.email)
        print(f"Suspended {count} membership(s) for {arguments.email.strip().lower()}. Access is cut off immediately.")
        return 0
    except (BridgeError, MigrationError, psycopg.Error) as error:
        print(f"Failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
