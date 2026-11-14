"""Acceptance: "Customer A cannot access Customer B's datasets" (and everything else of B's).

Checked at both layers: through the API, and directly in the database as the
restricted role the API runs as, where there is no application code to rely on.
"""

from __future__ import annotations

import json
import uuid

import psycopg
import pytest

from conftest import add_member

PROMPT = "Analyse my sales and identify my most profitable products."


@pytest.fixture
def two_tenants(make_account, small_csv):
    a, b = make_account("Company A"), make_account("Company B")
    upload = b.upload(small_csv, "b-sales.csv")
    job = b.analyse(upload["dataset_version_id"], PROMPT)
    assert job["status"] == "completed", job
    report = b.get("/reports").json()[0]
    return a, b, upload, job, report


def test_a_cannot_read_anything_of_bs_through_the_api(two_tenants):
    a, b, upload, job, report = two_tenants
    assert a.get("/datasets").json() == [] and a.get("/reports").json() == [] and a.get("/analysis-jobs").json() == []
    for path in (
        f"/datasets/{upload['dataset_id']}", f"/datasets/{upload['dataset_id']}/profile",
        f"/analysis-jobs/{job['id']}", f"/analysis-jobs/{job['id']}/results", f"/analysis-jobs/{job['id']}/agents",
        f"/reports/{report['id']}/download",
    ):  # fmt: skip
        response = a.get(path)
        assert response.status_code == 404, f"{path} -> {response.status_code}"
    # ...while B can
    assert b.get(f"/datasets/{upload['dataset_id']}").status_code == 200


def test_a_cannot_act_on_bs_resources(two_tenants):
    a, b, upload, job, _ = two_tenants
    assert a.post(f"/analysis-jobs/{job['id']}/cancel").status_code == 404
    assert a.post(f"/datasets/{upload['dataset_id']}/complete").status_code == 404
    # A names B's dataset while acting in A's own organisation
    stolen = a.post("/analysis-jobs", json={"workspace_id": a.workspace_id,
                                            "dataset_version_id": upload["dataset_version_id"], "prompt": PROMPT})  # fmt: skip
    assert stolen.status_code == 404
    # A names B's workspace
    assert a.post("/datasets/upload-url", json={"workspace_id": b.workspace_id, "filename": "x.csv",
                                                "size_bytes": 10}).status_code == 404  # fmt: skip


def test_a_cannot_select_bs_organisation_by_sending_its_id(two_tenants):
    a, b, *_ = two_tenants
    response = a.client.get("/v1/datasets", headers={**a.headers, "X-Organisation-Id": b.organisation_id})
    assert response.status_code == 404  # same answer as for an organisation that does not exist
    unknown = a.client.get("/v1/datasets", headers={**a.headers, "X-Organisation-Id": str(uuid.uuid4())})
    assert unknown.json() == response.json()


def test_a_download_link_cannot_be_retargeted(two_tenants, settings):
    from app.security.signing import sign

    _, b, _, _, report = two_tenants
    link = b.get(f"/reports/{report['id']}/download").json()["url"]
    assert b.client.get(link).status_code == 200
    tampered = link[:-4] + ("AAAA" if not link.endswith("AAAA") else "BBBB")
    assert b.client.get(tampered).status_code == 403
    # a link signed for another purpose is refused, even with a valid signature
    upload_token = sign(
        {"k": "org/x/y.pdf", "max": 10}, purpose="upload", secret=settings.app_secret_key, ttl_seconds=60
    )
    assert b.client.get(f"/v1/files/{upload_token}").status_code == 403


# --------------------------------------------------------------------------- database layer


def as_user(connection, user_id: str | None):
    """Start a transaction exactly as the API does for an end-user request."""
    connection.execute("SET LOCAL ROLE tatmaq_app_user")
    if user_id:
        connection.execute("SELECT set_config('request.jwt.claims', %s, true)", (json.dumps({"sub": user_id}),))


TENANT_TABLES = ["organisations", "workspaces", "datasets", "dataset_versions", "dataset_columns", "analysis_jobs",
                 "agent_tasks", "agent_runs", "analysis_results", "artifacts", "usage_records"]  # fmt: skip


def test_row_level_security_filters_every_table_without_any_where_clause(two_tenants, database_url):
    a, b, *_ = two_tenants
    with psycopg.connect(database_url) as connection:
        with connection.transaction():
            as_user(connection, b.user_id)
            for table in TENANT_TABLES:
                column = "id" if table == "organisations" else "organisation_id"
                owners = {str(row[0]) for row in connection.execute(f"SELECT DISTINCT {column} FROM {table}")}
                assert owners == {b.organisation_id}, f"{table}: {owners}"
        with connection.transaction():
            as_user(connection, a.user_id)
            for table in TENANT_TABLES[2:]:
                assert connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0, table


def test_with_no_user_set_the_restricted_role_sees_nothing(two_tenants, database_url):
    with psycopg.connect(database_url) as connection, connection.transaction():
        as_user(connection, None)
        for table in [*TENANT_TABLES, "profiles", "organisation_memberships", "audit_logs"]:
            assert connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0, table


def test_the_restricted_role_cannot_write_into_another_organisation(two_tenants, database_url):
    a, b, *_ = two_tenants
    statements = [
        ("INSERT INTO datasets (organisation_id, workspace_id, name) VALUES (%s, %s, 'planted')",
         (b.organisation_id, b.workspace_id)),
        ("INSERT INTO analysis_jobs (organisation_id, workspace_id, prompt) VALUES (%s, %s, 'planted')",
         (b.organisation_id, b.workspace_id)),
        ("INSERT INTO audit_logs (organisation_id, actor_id, action) VALUES (%s, %s, 'planted')",
         (b.organisation_id, a.user_id)),
        ("INSERT INTO workspaces (organisation_id, name) VALUES (%s, 'planted')", (b.organisation_id,)),
    ]  # fmt: skip
    for statement, parameters in statements:
        with (psycopg.connect(database_url) as connection,
              pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction()):  # fmt: skip
            as_user(connection, a.user_id)
            connection.execute(statement, parameters)
    # an UPDATE aimed at B's rows simply matches nothing
    with psycopg.connect(database_url) as connection, connection.transaction():
        as_user(connection, a.user_id)
        assert connection.execute("UPDATE datasets SET name = 'hijacked'").rowcount == 0
        assert connection.execute("UPDATE analysis_jobs SET status = 'cancelled'").rowcount == 0


@pytest.mark.parametrize("statement", [
    "DELETE FROM datasets", "DELETE FROM audit_logs", "UPDATE audit_logs SET action = 'x'",
    "UPDATE analysis_results SET finding = 'x'", "INSERT INTO usage_records (organisation_id, metric, quantity) "
    "SELECT id, 'free', 0 FROM organisations", "UPDATE analysis_jobs SET result_summary = '{}'",
    "UPDATE organisation_memberships SET role = 'owner'", "TRUNCATE datasets",
])  # fmt: skip
def test_end_users_cannot_delete_or_rewrite_records_even_in_their_own_organisation(
    two_tenants, database_url, statement
):
    _, b, *_ = two_tenants
    with (psycopg.connect(database_url) as connection,
          pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction()):  # fmt: skip
        as_user(connection, b.user_id)
        connection.execute(statement)


def test_supabase_browser_roles_get_nothing_even_if_granted_by_default(two_tenants, database_url):
    """Supabase has granted new tables to anon/authenticated by default. Re-applying the policies must undo that."""
    from conftest import REPO_ROOT

    _, b, *_ = two_tenants
    policies = (REPO_ROOT / "database" / "policies" / "001_row_level_security.sql").read_text()
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute("GRANT ALL ON ALL TABLES IN SCHEMA public TO anon, authenticated")
        connection.execute(policies)
        for role in ("anon", "authenticated"):
            for table in ("datasets", "analysis_results", "organisations", "profiles"):
                with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
                    connection.execute(f"SET LOCAL ROLE {role}")
                    connection.execute(
                        "SELECT set_config('request.jwt.claims', %s, true)", (json.dumps({"sub": b.user_id}),)
                    )
                    connection.execute(f"SELECT * FROM {table}")
            with pytest.raises(psycopg.errors.InsufficientPrivilege), connection.transaction():
                connection.execute(f"SET LOCAL ROLE {role}")
                connection.execute("SELECT is_org_member(%s)", (b.organisation_id,))


def test_the_database_refuses_cross_tenant_references_even_from_privileged_code(two_tenants, database_url):
    """Tenant-aware foreign keys: a row in A cannot point at a parent in B, whoever writes it."""
    a, b, upload, job, _ = two_tenants
    attempts = [
        ("INSERT INTO datasets (organisation_id, workspace_id, name) VALUES (%s, %s, 'x')", (a.organisation_id, b.workspace_id)),
        ("INSERT INTO analysis_jobs (organisation_id, workspace_id, dataset_version_id, prompt) VALUES (%s, %s, %s, 'x')",
         (a.organisation_id, a.workspace_id, upload["dataset_version_id"])),
        ("INSERT INTO analysis_results (organisation_id, job_id, sequence) VALUES (%s, %s, 999)", (a.organisation_id, job["id"])),
        ("INSERT INTO agent_tasks (organisation_id, job_id, agent_key, sequence) VALUES (%s, %s, 'planted', 999)",
         (a.organisation_id, job["id"])),
    ]  # fmt: skip
    for statement, parameters in attempts:
        with psycopg.connect(database_url) as connection, pytest.raises(psycopg.errors.ForeignKeyViolation):
            connection.execute(statement, parameters)


def test_the_worker_refuses_a_storage_path_outside_the_jobs_organisation(two_tenants):
    from app.storage import TenantBoundaryError, assert_belongs_to
    from app.storage.base import StorageError

    a, b, *_ = two_tenants
    key = f"org/{b.organisation_id}/datasets/x/v1/original.csv"
    assert assert_belongs_to(key, uuid.UUID(b.organisation_id)) == key
    with pytest.raises(TenantBoundaryError):
        assert_belongs_to(key, uuid.UUID(a.organisation_id))
    with pytest.raises(StorageError):
        assert_belongs_to(f"org/{a.organisation_id}/../{b.organisation_id}/x.csv", uuid.UUID(a.organisation_id))


def test_roles_limit_what_a_member_can_do(make_account, small_csv):
    owner, outsider = make_account("Roles Ltd"), make_account("Someone Else")
    upload = owner.upload(small_csv)
    add_member(owner.organisation_id, outsider.user_id, "viewer")
    viewer = type(owner)(owner.client, outsider.email, outsider.user_id, outsider.token,
                         owner.organisation_id, owner.workspace_id)  # fmt: skip
    assert viewer.get(f"/datasets/{upload['dataset_id']}").status_code == 200  # can read
    for response in (
        viewer.post("/analysis-jobs", json={"workspace_id": owner.workspace_id,
                                            "dataset_version_id": upload["dataset_version_id"], "prompt": PROMPT}),
        viewer.post("/datasets/upload-url", json={"workspace_id": owner.workspace_id, "filename": "x.csv", "size_bytes": 5}),
        viewer.post("/workspaces", json={"name": "Mine"}),
    ):  # fmt: skip
        assert response.status_code == 403, response.text
    assert {org["role"] for org in viewer.client.get("/v1/organisations", headers=viewer.headers).json()} == {
        "owner",
        "viewer",
    }


def test_suspending_an_organisation_cuts_off_access_at_the_database(make_account, small_csv, database_url):
    tenant = make_account("Soon Suspended")
    tenant.upload(small_csv)
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute("UPDATE organisations SET status = 'suspended' WHERE id = %s", (tenant.organisation_id,))
        with connection.transaction():
            as_user(connection, tenant.user_id)
            assert connection.execute("SELECT count(*) FROM datasets").fetchone()[0] == 0
    assert tenant.get("/datasets").status_code == 404


def test_the_restriction_survives_a_commit_or_rollback_in_the_middle_of_a_request(two_tenants):
    """SET LOCAL lasts one transaction. The session must re-apply it for the next one, or the rest of
    the request would run with the connection's own, unrestricted, role."""
    import uuid as _uuid

    from sqlalchemy import text

    from app.core.database import user_session

    a, *_ = two_tenants
    session = user_session(_uuid.UUID(a.user_id))
    try:
        for end_transaction in (session.commit, session.rollback, session.commit):
            assert session.execute(text("SELECT current_user")).scalar() == "tatmaq_app_user"
            visible = {str(row[0]) for row in session.execute(text("SELECT id FROM organisations"))}
            assert visible == {a.organisation_id}
            end_transaction()
    finally:
        session.close()
