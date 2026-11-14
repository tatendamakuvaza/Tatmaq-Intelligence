"""Shared test setup.

Tests run against a real PostgreSQL server, because the behaviour under test (Row
Level Security, ``FOR UPDATE SKIP LOCKED``, tenant-aware foreign keys) only exists
there. A throwaway database is created for the session and dropped afterwards.

Point ``TEST_DATABASE_URL`` at any server you may create databases on. With the
project's docker-compose database running, the default works as is.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
BENCHMARK_DIR = Path(__file__).parent / "benchmark"
ADMIN_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:5432/postgres")
DATABASE_NAME = f"tatmaq_test_{uuid.uuid4().hex[:10]}"
_SCRATCH = Path(tempfile.mkdtemp(prefix="tatmaq-tests-"))


def _database_url(name: str) -> str:
    parts = urlsplit(ADMIN_URL)
    return urlunsplit((parts.scheme, parts.netloc, f"/{name}", parts.query, parts.fragment))


def _load_migrator():
    spec = importlib.util.spec_from_file_location("tatmaq_migrate", REPO_ROOT / "scripts" / "migrate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# The application reads its settings once, at import. Everything it needs is therefore
# put in place here, before any test module imports it.
with psycopg.connect(ADMIN_URL, autocommit=True) as _admin:
    _admin.execute(f'CREATE DATABASE "{DATABASE_NAME}"')
_load_migrator().migrate(_database_url(DATABASE_NAME), log=lambda *_: None)
os.environ.update(
    APP_ENV="test",
    DATABASE_URL=_database_url(DATABASE_NAME),
    AUTH_MODE="dev",
    STORAGE_BACKEND="local",
    STORAGE_LOCAL_DIR=str(_SCRATCH / "storage"),
    WORK_DIR=str(_SCRATCH / "work"),
    AI_PROVIDER="none",
    MAX_UPLOAD_MB="2",
    PLAN_MONTHLY_ANALYSIS_JOBS="1000",
    MAX_ACTIVE_JOBS_PER_ORG="50",
    JOB_MAX_ATTEMPTS="3",
)

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.core.database import dispose_engine, system_session
from app.main import app
from app.workers import queue
from app.workers.runner import execute_job


@pytest.fixture(scope="session", autouse=True)
def _database():
    yield
    dispose_engine()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'DROP DATABASE IF EXISTS "{DATABASE_NAME}" WITH (FORCE)')
    shutil.rmtree(_SCRATCH, ignore_errors=True)


@pytest.fixture(scope="session")
def database_url() -> str:
    return _database_url(DATABASE_NAME)


@pytest.fixture(scope="session")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(scope="session")
def settings():
    return get_settings()


@pytest.fixture(scope="session")
def expected() -> dict:
    return json.loads((BENCHMARK_DIR / "expected.json").read_text())


@dataclass
class Account:
    """A signed-in user who owns an organisation."""

    client: TestClient
    email: str
    user_id: str
    token: str
    organisation_id: str
    workspace_id: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "X-Organisation-Id": self.organisation_id}

    def get(self, path: str, **kwargs):
        return self.client.get(f"/v1{path}", headers={**self.headers, **kwargs.pop("headers", {})}, **kwargs)

    def post(self, path: str, **kwargs):
        return self.client.post(f"/v1{path}", headers={**self.headers, **kwargs.pop("headers", {})}, **kwargs)

    def upload(self, content: bytes, filename: str | None = None, *, process: bool = True) -> dict:
        """The three-step upload handshake, then (optionally) the ingestion job."""
        filename = filename or ("sales.xlsx" if content.startswith(b"PK") else "sales.csv")
        target = self.post("/datasets/upload-url", json={
            "workspace_id": self.workspace_id, "filename": filename, "size_bytes": len(content)})  # fmt: skip
        assert target.status_code == 201, target.text
        instructions = target.json()["upload"]
        sent = self.client.put(instructions["url"], content=content, headers=instructions["headers"])
        assert sent.status_code == 204, sent.text
        completed = self.post(f"/datasets/{target.json()['dataset_id']}/complete")
        assert completed.status_code == 200, completed.text
        if process:
            run_queued_jobs()
        return completed.json()

    def analyse(self, version_id: str, prompt: str, *, run: bool = True, **body) -> dict:
        response = self.post("/analysis-jobs", json={
            "workspace_id": self.workspace_id, "dataset_version_id": version_id, "prompt": prompt, **body})  # fmt: skip
        assert response.status_code == 202, response.text
        if run:
            run_queued_jobs()
        return self.get(f"/analysis-jobs/{response.json()['job_id']}").json()


def run_queued_jobs(limit: int = 20) -> list[str]:
    """Process the queue in this process, the way a worker would. Returns the final statuses."""
    outcomes = []
    for _ in range(limit):
        claim = queue.claim_next("test-worker")
        if claim is None:
            break
        outcomes.append(execute_job(claim, get_settings()))
    return outcomes


def new_account(client: TestClient, name: str = "Test Trading") -> Account:
    email = f"user-{uuid.uuid4().hex[:10]}@example.com"
    registered = client.post("/v1/auth/register", json={"email": email, "password": "correct horse battery"})
    assert registered.status_code == 201, registered.text
    token = registered.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    client.post("/v1/auth/profile", json={"full_name": f"{name} Owner"}, headers=headers)
    created = client.post("/v1/organisations", json={"name": name}, headers=headers)
    assert created.status_code == 201, created.text
    return Account(client, email, registered.json()["user"]["id"], token,
                   created.json()["organisation"]["id"], created.json()["workspace"]["id"])  # fmt: skip


@pytest.fixture
def make_account(client):
    return lambda name="Test Trading": new_account(client, name)


@pytest.fixture
def account(make_account) -> Account:
    return make_account("Mopane Grocers")


@pytest.fixture(scope="session")
def benchmark_xlsx() -> bytes:
    return (BENCHMARK_DIR / "sales_benchmark.xlsx").read_bytes()


@pytest.fixture(scope="session")
def benchmark_csv() -> bytes:
    return (BENCHMARK_DIR / "sales_benchmark.csv").read_bytes()


SMALL_CSV = (
    b"Invoice No,Date,Branch,Product,Quantity,Sales Amount,Cost of Sales\n"
    b"A1,05/01/2026,Harare,Sugar 2kg,2,5.20,4.16\n"
    b"A2,17/01/2026,Harare,Rice 2kg,1,2.90,2.20\n"
    b"A3,03/02/2026,Mutare,Sugar 2kg,3,7.80,6.24\n"
    b"A4,21/02/2026,Mutare,Salt 1kg,10,6.00,3.60\n"
    b"A5,09/03/2026,Harare,Rice 2kg,4,11.60,8.80\n"
    b"A6,27/03/2026,Gweru,Salt 1kg,5,3.00,1.80\n"
)


@pytest.fixture
def small_csv() -> bytes:
    return SMALL_CSV


def add_member(organisation_id: str, user_id: str, role: str) -> None:
    """Attach an existing user to an organisation (there is no invitation endpoint yet)."""
    from app.models import OrganisationMembership

    with system_session() as session:
        session.add(OrganisationMembership(organisation_id=organisation_id, user_id=user_id, role=role))
