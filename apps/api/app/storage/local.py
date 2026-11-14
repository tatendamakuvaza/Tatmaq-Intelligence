"""Files on the local disk: development, tests, and single-server deployments with a volume."""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

from .base import ApiServedLinks, ObjectExists, ObjectNotFound, StorageError, validate_key


class UploadWriter:
    """Receives an upload chunk by chunk into a temporary file.

    The object only appears under its real name when :meth:`commit` is called, so an
    upload that is interrupted or exceeds the size limit leaves nothing behind. Uploads
    are write-once: an existing object is never replaced.
    """

    def __init__(self, final_path: Path, max_bytes: int) -> None:
        self._final = final_path
        self._temporary = final_path.with_name(f".{final_path.name}.{uuid.uuid4().hex}.part")
        self._max_bytes = max_bytes
        self._handle = self._temporary.open("wb")
        self.bytes_written = 0

    def write(self, chunk: bytes) -> bool:
        """Append a chunk. Returns False (and stops accepting data) once over the limit."""
        self.bytes_written += len(chunk)
        if self.bytes_written > self._max_bytes:
            return False
        self._handle.write(chunk)
        return True

    def commit(self) -> None:
        """Publish the object under its real name, refusing to replace an existing one."""
        self._handle.flush()
        os.fsync(self._handle.fileno())
        self._handle.close()
        try:
            os.link(self._temporary, self._final)  # atomic, and fails if the name is taken
        except FileExistsError as error:
            raise ObjectExists(self._final.name) from error
        finally:
            self._temporary.unlink(missing_ok=True)

    def abort(self) -> None:
        self._handle.close()
        self._temporary.unlink(missing_ok=True)


class LocalStorage(ApiServedLinks):
    def __init__(self, root: Path, signing_secret: str) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)
        self._secret = signing_secret

    def path(self, key: str) -> Path:
        candidate = (self._root / validate_key(key)).resolve()
        if not candidate.is_relative_to(self._root):
            raise StorageError(f"unsafe storage key: {key!r}")
        return candidate

    def exists(self, key: str) -> bool:
        return self.path(key).is_file()

    def size(self, key: str) -> int:
        try:
            return self.path(key).stat().st_size
        except FileNotFoundError as error:
            raise ObjectNotFound(key) from error

    def download_to(self, key: str, destination: Path) -> None:
        try:
            shutil.copyfile(self.path(key), destination)
        except FileNotFoundError as error:
            raise ObjectNotFound(key) from error

    def put_file(self, key: str, source: Path, *, content_type: str, overwrite: bool = False) -> None:
        target = self.path(key)
        if target.exists() and not overwrite:
            raise ObjectExists(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.part")
        shutil.copyfile(source, temporary)
        os.replace(temporary, target)

    def delete(self, key: str) -> None:
        self.path(key).unlink(missing_ok=True)

    def open_upload(self, key: str, max_bytes: int, content_type: str = "application/octet-stream") -> UploadWriter:
        target = self.path(key)
        target.parent.mkdir(parents=True, exist_ok=True)
        return UploadWriter(target, max_bytes)
