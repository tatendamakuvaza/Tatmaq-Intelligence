"""Acceptance: a failed upload never becomes a usable dataset; originals are never overwritten;
large files cannot exhaust the server."""

from __future__ import annotations

import hashlib
import io
import zipfile

import pytest

from app.core.database import system_session
from app.models import DatasetVersion
from app.storage import get_storage
from conftest import run_queued_jobs

PROMPT = "Analyse sales"


def request_upload(account, filename="sales.csv", size=100):
    return account.post("/datasets/upload-url", json={"workspace_id": account.workspace_id, "filename": filename,
                                                      "size_bytes": size})  # fmt: skip


def test_an_upload_that_never_arrives_leaves_nothing_usable(account):
    target = request_upload(account).json()
    dataset_id = target["dataset_id"]
    # the browser never sends the file: completing is refused...
    completed = account.post(f"/datasets/{dataset_id}/complete")
    assert completed.status_code == 409 and completed.json()["error"]["code"] == "upload_missing"
    # ...and the dataset has no version, so there is nothing an analysis could be pointed at
    detail = account.get(f"/datasets/{dataset_id}").json()
    assert detail["status"] == "pending_upload" and detail["versions"] == []
    assert account.get(f"/datasets/{dataset_id}/profile").status_code == 409


def test_an_interrupted_upload_leaves_no_partial_file(account, settings):
    storage = get_storage()
    writer = storage.open_upload("org/test/partial.csv", max_bytes=1000)
    writer.write(b"half a fi")
    writer.abort()  # what the upload endpoint does when the connection drops
    assert not storage.exists("org/test/partial.csv")
    assert not any(storage.path("org/test/partial.csv").parent.glob("*partial*"))


@pytest.mark.parametrize(("content", "filename", "fragment"), [
    (b"this is not a spreadsheet", "broken.xlsx", "not a valid Excel workbook"),
    (b"Name,Amount\n", "empty.csv", "no rows of data"),
    (b"\x00\x01\x02\x03binary", "binary.csv", "does not look like a text file"),
])  # fmt: skip
def test_a_file_that_cannot_be_read_fails_cleanly_and_cannot_be_analysed(account, content, filename, fragment):
    upload = account.upload(content, filename)
    detail = account.get(f"/datasets/{upload['dataset_id']}").json()
    assert detail["status"] == "failed" and fragment in detail["error_message"]
    assert detail["latest_version"]["status"] == "failed"
    refused = account.post("/analysis-jobs", json={"workspace_id": account.workspace_id,
                                                   "dataset_version_id": upload["dataset_version_id"], "prompt": PROMPT})  # fmt: skip
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "dataset_not_ready"


def test_a_dataset_cannot_be_analysed_while_it_is_still_processing(account, small_csv):
    upload = account.upload(small_csv, process=False)
    refused = account.post("/analysis-jobs", json={"workspace_id": account.workspace_id,
                                                   "dataset_version_id": upload["dataset_version_id"], "prompt": PROMPT})  # fmt: skip
    assert refused.status_code == 409
    run_queued_jobs()
    assert account.analyse(upload["dataset_version_id"], PROMPT)["status"] == "completed"


def test_unsupported_and_oversized_files_are_refused_before_any_upload(account, settings):
    assert request_upload(account, "ledger.xls").status_code == 415
    assert "Save As" in request_upload(account, "ledger.xls").json()["error"]["message"]
    assert request_upload(account, "macro.xlsm").status_code == 415
    assert request_upload(account, "notes.pdf").status_code == 415
    assert request_upload(account, "big.csv", size=settings.max_upload_bytes + 1).status_code == 413


def test_the_size_limit_is_enforced_on_bytes_received_not_on_what_the_client_claims(account, settings):
    target = request_upload(account, "liar.csv", size=10).json()  # claims 10 bytes
    too_big = b"x" * (settings.max_upload_bytes + 1024)

    def chunks():  # streamed, so no Content-Length is sent
        for start in range(0, len(too_big), 64 * 1024):
            yield too_big[start : start + 64 * 1024]

    response = account.client.put(target["upload"]["url"], content=chunks())
    assert response.status_code == 413
    assert account.post(f"/datasets/{target['dataset_id']}/complete").json()["error"]["code"] == "upload_missing"


def test_the_original_file_is_write_once(account, small_csv):
    target = request_upload(account, size=len(small_csv)).json()
    url = target["upload"]["url"]
    assert account.client.put(url, content=small_csv).status_code == 204
    # the same link cannot be used to replace the file, before or after it is imported
    assert account.client.put(url, content=b"tampered").status_code == 409
    account.post(f"/datasets/{target['dataset_id']}/complete")
    run_queued_jobs()
    assert account.client.put(url, content=b"tampered").status_code == 409

    with system_session() as session:
        version = session.query(DatasetVersion).filter_by(dataset_id=target["dataset_id"]).one()
        stored = get_storage().path(version.storage_path).read_bytes()
        assert stored == small_csv and version.sha256_hash == hashlib.sha256(small_csv).hexdigest()


def test_completing_twice_is_harmless(account, small_csv):
    upload = account.upload(small_csv)
    again = account.post(f"/datasets/{upload['dataset_id']}/complete").json()
    assert (again["dataset_version_id"], again["job_id"]) == (upload["dataset_version_id"], upload["job_id"])
    assert len(account.get(f"/datasets/{upload['dataset_id']}").json()["versions"]) == 1


def test_a_file_changed_after_upload_is_detected_and_not_analysed(account, small_csv):
    upload = account.upload(small_csv)
    with system_session() as session:
        path = get_storage().path(session.get(DatasetVersion, upload["dataset_version_id"]).storage_path)
    path.chmod(0o600)
    path.write_bytes(small_csv.replace(b"5.20", b"9999.99"))  # someone edits the stored file behind our back
    job = account.analyse(upload["dataset_version_id"], PROMPT)
    assert job["status"] == "failed" and "Integrity check failed" in job["error_message"]
    assert account.get(f"/analysis-jobs/{job['id']}/results").json()["findings"] == []


def test_a_new_version_keeps_the_old_one_intact(account, small_csv):
    first = account.upload(small_csv)
    second_content = small_csv + b"A7,02/04/2026,Gweru,Salt 1kg,2,1.20,0.72\n"
    target = account.post("/datasets/upload-url", json={
        "workspace_id": account.workspace_id, "filename": "sales.csv", "size_bytes": len(second_content),
        "dataset_id": first["dataset_id"]}).json()  # fmt: skip
    assert target["version_number"] == 2
    account.client.put(target["upload"]["url"], content=second_content)
    second = account.post(f"/datasets/{first['dataset_id']}/complete").json()
    run_queued_jobs()
    versions = {v["version_number"]: v for v in account.get(f"/datasets/{first['dataset_id']}").json()["versions"]}
    assert (versions[1]["row_count"], versions[2]["row_count"]) == (6, 7)
    assert versions[1]["sha256_hash"] != versions[2]["sha256_hash"]
    # both remain analysable, each against its own data
    old = account.analyse(first["dataset_version_id"], PROMPT)
    new = account.analyse(second["dataset_version_id"], PROMPT)
    assert "USD 36.50" in old["headline"] and "USD 37.70" in new["headline"]


def test_a_decompression_bomb_is_refused_before_it_is_opened(account):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/workbook.xml", "<workbook/>")
        archive.writestr("xl/worksheets/sheet1.xml", "0" * 60_000_000)  # 60 MB of zeros in a few kilobytes
    assert len(buffer.getvalue()) < 100_000
    upload = account.upload(buffer.getvalue(), "bomb.xlsx")
    detail = account.get(f"/datasets/{upload['dataset_id']}").json()
    assert detail["status"] == "failed" and "too large to process safely" in detail["error_message"]


def test_row_and_column_limits_stop_oversized_tables(tmp_path):
    from app.agents.base import AgentError
    from app.agents.data_acquisition.csv_reader import read_csv

    path = tmp_path / "long.csv"
    path.write_text("a,b\n" + "1,2\n" * 50)
    assert len(read_csv(path, max_rows=50, max_columns=5).frame) == 50
    with pytest.raises(AgentError, match="more than 49 rows"):
        read_csv(path, max_rows=49, max_columns=5)
    with pytest.raises(AgentError, match="2 columns; the limit is 1"):
        read_csv(path, max_rows=100, max_columns=1)
