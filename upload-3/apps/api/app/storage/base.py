"""The storage interface every backend implements, and the object naming scheme.

Layout (every key starts with its organisation, which is what the worker checks
before touching a file):

    org/{organisation}/datasets/{dataset}/v{n}/original.xlsx   the upload, never modified
    org/{organisation}/datasets/{dataset}/v{n}/raw.parquet     table as imported
    org/{organisation}/datasets/{dataset}/v{n}/cleaned.parquet typed, standardised table
    org/{organisation}/jobs/{job}/report.pdf|xlsx|html         generated reports

Keys are built only from UUIDs and fixed names. A customer's filename is stored in the
database for display and never becomes part of a path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
from uuid import UUID

from ..security.signing import sign

UPLOAD_PURPOSE = "upload"
DOWNLOAD_PURPOSE = "download"
_SAFE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*$")


class StorageError(Exception):
    pass


class ObjectNotFound(StorageError):
    pass


class ObjectExists(StorageError):
    """Raised instead of overwriting: originals are write-once."""


class TenantBoundaryError(StorageError):
    """A storage key does not belong to the organisation being processed."""


@dataclass(frozen=True)
class UploadTarget:
    """Where and how the browser should send a file."""

    method: str
    url: str  # absolute, or starting with "/" when served by this API
    headers: dict[str, str] = field(default_factory=dict)


class Storage(Protocol):
    def exists(self, key: str) -> bool: ...
    def size(self, key: str) -> int: ...
    def download_to(self, key: str, destination: Path) -> None: ...
    def put_file(self, key: str, source: Path, *, content_type: str, overwrite: bool = False) -> None: ...
    def delete(self, key: str) -> None: ...
    def create_upload_target(
        self, key: str, *, content_type: str, max_bytes: int, ttl_seconds: int
    ) -> UploadTarget: ...
    def create_download_url(self, key: str, *, filename: str, content_type: str, ttl_seconds: int) -> str: ...


def validate_key(key: str) -> str:
    if not _SAFE_KEY.match(key) or ".." in key.split("/"):
        raise StorageError(f"unsafe storage key: {key!r}")
    return key


class ApiServedLinks:
    """For backends whose bytes travel through this API's own ``/v1/uploads`` and ``/v1/files`` routes.

    A link is a signed, expiring token that names one object and one purpose, so those
    two routes need no sign-in header and cannot be pointed at another file.
    """

    _secret: str

    def create_upload_target(self, key: str, *, content_type: str, max_bytes: int, ttl_seconds: int) -> UploadTarget:
        token = sign({"k": validate_key(key), "max": max_bytes, "ct": content_type}, purpose=UPLOAD_PURPOSE,
                     secret=self._secret, ttl_seconds=ttl_seconds)  # fmt: skip
        return UploadTarget(method="PUT", url=f"/v1/uploads/{token}", headers={"Content-Type": content_type})

    def create_download_url(self, key: str, *, filename: str, content_type: str, ttl_seconds: int) -> str:
        token = sign({"k": validate_key(key), "fn": filename, "ct": content_type}, purpose=DOWNLOAD_PURPOSE,
                     secret=self._secret, ttl_seconds=ttl_seconds)  # fmt: skip
        return f"/v1/files/{token}"


def org_prefix(organisation_id: UUID) -> str:
    return f"org/{organisation_id}/"


def assert_belongs_to(key: str, organisation_id: UUID) -> str:
    """Refuse a key outside the organisation's prefix. The worker calls this before every read."""
    validate_key(key)
    if not key.startswith(org_prefix(organisation_id)):
        raise TenantBoundaryError("storage object does not belong to this organisation")
    return key


def _version_folder(organisation_id: UUID, dataset_id: UUID, version_number: int) -> str:
    return f"{org_prefix(organisation_id)}datasets/{dataset_id}/v{version_number}"


def original_key(organisation_id: UUID, dataset_id: UUID, version_number: int, file_type: str) -> str:
    return f"{_version_folder(organisation_id, dataset_id, version_number)}/original.{file_type}"


def raw_key(organisation_id: UUID, dataset_id: UUID, version_number: int) -> str:
    return f"{_version_folder(organisation_id, dataset_id, version_number)}/raw.parquet"


def cleaned_key(organisation_id: UUID, dataset_id: UUID, version_number: int) -> str:
    return f"{_version_folder(organisation_id, dataset_id, version_number)}/cleaned.parquet"


def report_key(organisation_id: UUID, job_id: UUID, extension: str) -> str:
    return f"{org_prefix(organisation_id)}jobs/{job_id}/report.{extension}"
