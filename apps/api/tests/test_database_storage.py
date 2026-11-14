"""Files kept in the database (STORAGE_BACKEND=database), for hosts whose disk is wiped on restart."""

from __future__ import annotations

import os
import shutil
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from app.core.database import get_engine, system_session
from app.storage import DatabaseStorage, ObjectExists, ObjectNotFound, StorageError, get_storage
from app.storage.database import CHUNK_BYTES
from conftest import run_queued_jobs

PROMPT = "Analyse my sales records and identify my most profitable products."


@pytest.fixture
def storage(tmp_path) -> DatabaseStorage:
    return DatabaseStorage(get_engine, "secret", tmp_path / "spool")


@pytest.fixture
def files_in_database(settings, monkeypatch):
    """Switch the running application to database storage for one test."""
    monkeypatch.setattr(settings, "storage_backend", "database")
    get_storage.cache_clear()
    yield get_storage()
    monkeypatch.undo()
    get_storage.cache_clear()


def new_key(name: str = "file.bin") -> str:
    return f"org/{uuid.uuid4()}/tests/{name}"


def pieces_stored(key: str) -> int:
    with system_session() as session:
        return session.execute(text("SELECT COUNT(*) FROM stored_file_chunks WHERE key = :key"), {"key": key}).scalar()


def test_a_file_is_stored_in_pieces_and_comes_back_unchanged(storage, tmp_path):
    content = os.urandom(2 * CHUNK_BYTES + 12345)
    source, copy = tmp_path / "in.bin", tmp_path / "out.bin"
    source.write_bytes(content)
    key = new_key()

    assert not storage.exists(key)
    storage.put_file(key, source, content_type="application/octet-stream")
    assert storage.exists(key) and storage.size(key) == len(content)
    storage.download_to(key, copy)
    assert copy.read_bytes() == content
    assert [len(piece) for piece in storage.iter_chunks(key)] == [CHUNK_BYTES, CHUNK_BYTES, 12345]
    assert pieces_stored(key) == 3

    empty, empty_key = tmp_path / "empty.csv", new_key("empty.csv")
    empty.write_bytes(b"")
    storage.put_file(empty_key, empty, content_type="text/csv")  # an empty file is still a file
    storage.download_to(empty_key, copy)
    assert storage.exists(empty_key) and storage.size(empty_key) == 0 and copy.read_bytes() == b""


def test_files_are_write_once_unless_replaced_on_purpose_and_can_be_deleted(storage, tmp_path):
    long, short = tmp_path / "long", tmp_path / "short"
    long.write_bytes(b"A" * (CHUNK_BYTES + 10))
    short.write_bytes(b"short")
    key = new_key()

    storage.put_file(key, long, content_type="text/plain")
    with pytest.raises(ObjectExists):
        storage.put_file(key, short, content_type="text/plain")
    assert storage.size(key) == CHUNK_BYTES + 10  # the refused write changed nothing

    storage.put_file(key, short, content_type="text/plain", overwrite=True)
    assert b"".join(storage.iter_chunks(key)) == b"short" and pieces_stored(key) == 1  # nothing of the old file is left

    storage.delete(key)
    storage.delete(key)  # deleting twice is harmless
    assert not storage.exists(key) and pieces_stored(key) == 0
    for read in (
        lambda: storage.size(key),
        lambda: list(storage.iter_chunks(key)),
        lambda: storage.download_to(key, tmp_path / "never-created"),
    ):
        with pytest.raises(ObjectNotFound):
            read()
    assert not (tmp_path / "never-created").exists()
    with pytest.raises(StorageError):
        storage.exists("../etc/passwd")


def test_an_interrupted_or_oversized_upload_stores_nothing(storage, tmp_path):
    key, spool = new_key("partial.csv"), tmp_path / "spool"
    writer = storage.open_upload(key, max_bytes=1000, content_type="text/csv")
    assert writer.write(b"x" * 600) and not writer.write(b"x" * 600)  # the second chunk goes over the limit
    writer.abort()
    assert not storage.exists(key) and list(spool.iterdir()) == []

    writer = storage.open_upload(key, max_bytes=1000, content_type="text/csv")
    writer.write(b"hello")
    writer.commit()
    assert b"".join(storage.iter_chunks(key)) == b"hello" and list(spool.iterdir()) == []

    again = storage.open_upload(key, max_bytes=1000)
    again.write(b"other")
    with pytest.raises(ObjectExists):  # the same name cannot be uploaded twice
        again.commit()
    assert b"".join(storage.iter_chunks(key)) == b"hello" and list(spool.iterdir()) == []


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT * FROM stored_files",
        "SELECT * FROM stored_file_chunks",
        "DELETE FROM stored_files",
        "UPDATE stored_file_chunks SET data = ''",
        "INSERT INTO stored_files (key, size_bytes, content_type) VALUES ('org/x/y', 0, 'text/plain')",
    ],
)
def test_the_role_end_user_requests_run_as_cannot_touch_stored_files(storage, tmp_path, statement):
    source = tmp_path / "secret"
    source.write_bytes(b"another company's upload")
    storage.put_file(new_key(), source, content_type="text/plain")
    with get_engine().connect() as connection:
        connection.execute(text("SET LOCAL ROLE tatmaq_app_user"))
        with pytest.raises(ProgrammingError, match="permission denied"):
            connection.execute(text(statement))


def test_the_whole_journey_works_from_the_database_and_survives_losing_the_disk(
    account, files_in_database, settings, benchmark_xlsx, expected
):
    assert isinstance(files_in_database, DatabaseStorage)
    upload = account.upload(benchmark_xlsx, "sales_benchmark.xlsx")  # upload, then the import job
    job = account.analyse(upload["dataset_version_id"], PROMPT)
    assert job["status"] == "completed", job
    results = account.get(f"/analysis-jobs/{job['id']}/results").json()
    figures = {kpi["key"]: kpi["value"] for kpi in results["summary"]["segments"][0]["kpis"]}
    assert figures["total_sales"] == expected["sales"]["total"]
    assert figures["gross_profit"] == expected["profitability"]["gross_profit"]

    # Nothing of this organisation's was written to the storage folder, and the server's
    # disk can vanish (as it does when a free host puts the service to sleep) without loss.
    assert not (settings.storage_local_dir / "org" / account.organisation_id).exists()
    shutil.rmtree(settings.work_dir, ignore_errors=True)
    with system_session() as session:
        stored = session.execute(
            text("SELECT COUNT(*) FROM stored_files WHERE key LIKE :prefix"),
            {"prefix": f"org/{account.organisation_id}/%"},
        ).scalar()
    assert stored == 6  # the original, the imported table, the cleaned table, and three reports

    assert {report["format"] for report in results["reports"]} == {"pdf", "xlsx", "html"}
    for report in results["reports"]:
        link = account.get(f"/reports/{report['id']}/download").json()
        response = account.client.get(link["url"])
        assert response.status_code == 200 and len(response.content) == report["size_bytes"]
        assert response.headers["content-length"] == str(report["size_bytes"])
        assert response.headers["content-disposition"] == f'attachment; filename="{link["filename"]}"'
        assert response.headers["cache-control"] == "private, no-store"
        if report["format"] == "pdf":
            assert response.content.startswith(b"%PDF")

    another = account.analyse(upload["dataset_version_id"], "Which branches sell the most?")  # still analysable
    assert another["status"] == "completed", another


def test_upload_rules_hold_when_files_go_to_the_database(account, files_in_database, settings, small_csv):
    def request_upload(name: str, size: int):
        body = {"workspace_id": account.workspace_id, "filename": name, "size_bytes": size}
        return account.post("/datasets/upload-url", json=body).json()

    # the size limit is enforced on the bytes received, not on what the client claimed
    liar = request_upload("liar.csv", 10)
    too_big = b"x" * (settings.max_upload_bytes + 1024)
    streamed = (too_big[start : start + 64 * 1024] for start in range(0, len(too_big), 64 * 1024))
    assert account.client.put(liar["upload"]["url"], content=streamed).status_code == 413
    assert account.post(f"/datasets/{liar['dataset_id']}/complete").json()["error"]["code"] == "upload_missing"

    # an upload is write-once, before and after it is imported
    target = request_upload("sales.csv", len(small_csv))
    url = target["upload"]["url"]
    assert account.client.put(url, content=small_csv, headers=target["upload"]["headers"]).status_code == 204
    assert account.client.put(url, content=b"tampered").status_code == 409
    assert account.post(f"/datasets/{target['dataset_id']}/complete").status_code == 200
    run_queued_jobs()
    assert account.client.put(url, content=b"tampered").status_code == 409
    assert account.get(f"/datasets/{target['dataset_id']}").json()["status"] == "ready"

    # a link that was tampered with, or that names nothing, is refused
    assert account.client.put(url[:-3] + "abc", content=small_csv).status_code == 403
    assert account.client.get("/v1/files/not-a-real-link").status_code == 403
