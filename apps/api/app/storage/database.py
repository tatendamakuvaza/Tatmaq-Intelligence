"""Files kept in PostgreSQL itself.

For hosts whose disk does not survive a restart (most free container hosts), when no
separate file store is wanted: the database is then the only thing that has to last.
Each file is one row in ``stored_files`` plus its content in 1 MB pieces in
``stored_file_chunks``, so no file is ever held in memory whole, here or in PostgreSQL.

The tables are reached only through the connection's own role. The role that end-user
requests run as has no privileges on them at all (see database/policies), so the usual
rule holds: a file is reachable only through a signed link, or by the worker, which
checks the organisation in the key before every read.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

from sqlalchemy import Engine, text

from .base import ApiServedLinks, ObjectExists, ObjectNotFound, validate_key

CHUNK_BYTES = 1024 * 1024

_FIND = text("SELECT size_bytes FROM stored_files WHERE key = :key")
_CHUNK = text("SELECT data FROM stored_file_chunks WHERE key = :key AND seq = :seq")
_DELETE = text("DELETE FROM stored_files WHERE key = :key")
_INSERT_FILE = text(
    "INSERT INTO stored_files (key, size_bytes, content_type) VALUES (:key, :size, :content_type) "
    "ON CONFLICT (key) DO NOTHING RETURNING key"
)
_INSERT_CHUNK = text("INSERT INTO stored_file_chunks (key, seq, data) VALUES (:key, :seq, :data)")


class SpooledUpload:
    """Receives an upload chunk by chunk into a temporary file, then stores it in one transaction.

    Nothing reaches the database until :meth:`commit`, so an upload that is interrupted
    or exceeds the size limit leaves nothing behind. Uploads are write-once.
    """

    def __init__(self, storage: DatabaseStorage, key: str, max_bytes: int, content_type: str, folder: Path) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        self._storage, self._key, self._content_type = storage, key, content_type
        self._temporary = folder / f"{uuid.uuid4().hex}.part"
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
        """Publish the object, refusing to replace an existing one."""
        self._handle.close()
        try:
            self._storage.put_file(self._key, self._temporary, content_type=self._content_type, overwrite=False)
        finally:
            self._temporary.unlink(missing_ok=True)

    def abort(self) -> None:
        self._handle.close()
        self._temporary.unlink(missing_ok=True)


class DatabaseStorage(ApiServedLinks):
    def __init__(self, engine: Callable[[], Engine], signing_secret: str, spool_dir: Path) -> None:
        self._engine = engine
        self._secret = signing_secret
        self._spool_dir = spool_dir

    def exists(self, key: str) -> bool:
        with self._engine().connect() as connection:
            return connection.execute(_FIND, {"key": validate_key(key)}).first() is not None

    def size(self, key: str) -> int:
        with self._engine().connect() as connection:
            row = connection.execute(_FIND, {"key": validate_key(key)}).first()
        if row is None:
            raise ObjectNotFound(key)
        return int(row.size_bytes)

    def iter_chunks(self, key: str) -> Iterator[bytes]:
        """The file's content, one piece at a time.

        Read inside one snapshot, so a file being replaced at the same moment is seen
        either entirely old or entirely new, never as a mixture.
        """
        validate_key(key)
        with self._engine().connect().execution_options(isolation_level="REPEATABLE READ") as connection:
            if connection.execute(_FIND, {"key": key}).first() is None:
                raise ObjectNotFound(key)
            sequence = 0
            while (row := connection.execute(_CHUNK, {"key": key, "seq": sequence}).first()) is not None:
                yield bytes(row.data)
                sequence += 1

    def download_to(self, key: str, destination: Path) -> None:
        chunks = self.iter_chunks(key)
        first = next(chunks, b"")  # raises ObjectNotFound before the destination is created
        with destination.open("wb") as handle:
            handle.write(first)
            for chunk in chunks:
                handle.write(chunk)

    def put_file(self, key: str, source: Path, *, content_type: str, overwrite: bool = False) -> None:
        validate_key(key)
        with self._engine().begin() as connection:
            if overwrite:
                connection.execute(_DELETE, {"key": key})
            created = connection.execute(
                _INSERT_FILE, {"key": key, "size": source.stat().st_size, "content_type": content_type}
            ).first()
            if created is None:
                raise ObjectExists(key)
            with source.open("rb") as handle:
                sequence = 0
                while chunk := handle.read(CHUNK_BYTES):
                    connection.execute(_INSERT_CHUNK, {"key": key, "seq": sequence, "data": chunk})
                    sequence += 1

    def delete(self, key: str) -> None:
        with self._engine().begin() as connection:
            connection.execute(_DELETE, {"key": validate_key(key)})

    def open_upload(self, key: str, max_bytes: int, content_type: str = "application/octet-stream") -> SpooledUpload:
        return SpooledUpload(self, validate_key(key), max_bytes, content_type, self._spool_dir)
