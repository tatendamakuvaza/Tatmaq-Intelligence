"""The concrete tools an agent's toolbox can hold.

Each tool is a narrow callable bound to one organisation and one kind of object. A
tool checks, on every call, that the object it is asked for lives under that
organisation's storage prefix: this is the worker "independently verifying the
organisation context" (specification 3.4) at the point where data is actually read.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

from ...storage import Storage, assert_belongs_to
from ...storage.base import StorageError
from . import permissions as p

if TYPE_CHECKING:
    import pandas as pd

PARQUET = "application/vnd.apache.parquet"


def sha256_of(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _checked(key: str, organisation_id: UUID, suffix: str | None = None, contains: str | None = None) -> str:
    assert_belongs_to(key, organisation_id)
    if suffix and not key.endswith(suffix):
        raise StorageError(f"this tool only handles objects ending in '{suffix}'")
    if contains and contains not in key:
        raise StorageError("this tool cannot write outside its own job")
    return key


def build_tools(
    *, storage: Storage, organisation_id: UUID, job_id: UUID, workdir: Path, llm: Any | None
) -> Mapping[str, Any]:
    """Every tool, bound to this job. A :class:`Toolbox` then exposes only the permitted ones."""
    downloads = workdir / "data"
    downloads.mkdir(parents=True, exist_ok=True)

    def fetch_original(key: str) -> Path:
        """Download an uploaded file for reading. Nothing can write to an original."""
        _checked(key, organisation_id)
        destination = downloads / f"original{Path(key).suffix}"
        storage.download_to(key, destination)
        destination.chmod(0o400)
        return destination

    def reader(suffix: str) -> Callable[[str], pd.DataFrame]:
        def read(key: str) -> pd.DataFrame:
            import pandas as pd

            _checked(key, organisation_id, suffix=suffix)
            destination = downloads / Path(key).name
            storage.download_to(key, destination)
            return pd.read_parquet(destination)

        return read

    def writer(suffix: str) -> Callable[[str, pd.DataFrame], int]:
        def write(key: str, frame: pd.DataFrame) -> int:
            _checked(key, organisation_id, suffix=suffix)
            source = downloads / f"out-{Path(key).name}"
            frame.to_parquet(source, index=False)
            # Derived tables are a pure function of the original, so a retry may replace them.
            storage.put_file(key, source, content_type=PARQUET, overwrite=True)
            return source.stat().st_size

        return write

    def store_artifact(key: str, source: Path, content_type: str) -> tuple[int, str]:
        _checked(key, organisation_id, contains=f"/jobs/{job_id}/")
        storage.put_file(key, source, content_type=content_type, overwrite=True)
        return source.stat().st_size, sha256_of(source)

    return {
        p.TOOL_ORIGINAL_READ: fetch_original,
        p.TOOL_RAW_READ: reader("/raw.parquet"),
        p.TOOL_RAW_WRITE: writer("/raw.parquet"),
        p.TOOL_CLEANED_READ: reader("/cleaned.parquet"),
        p.TOOL_CLEANED_WRITE: writer("/cleaned.parquet"),
        p.TOOL_ARTIFACT_WRITE: store_artifact,
        p.TOOL_LLM: llm,
    }
