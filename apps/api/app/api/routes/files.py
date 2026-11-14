"""Upload and download endpoints for files this API stores itself.

Registered when STORAGE_BACKEND is ``local`` (files on disk) or ``database`` (files in
PostgreSQL). With Supabase Storage the browser talks to Supabase directly through
signed URLs and these routes do not exist.

Neither route takes an ``Authorization`` header: the signed token in the URL is the
permission, it names exactly one object, and it expires.
"""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from starlette.concurrency import run_in_threadpool

from ...core.errors import Conflict, NotFound, PayloadTooLarge, PermissionDenied
from ...security.signing import InvalidLink, unsign
from ...storage import DatabaseStorage, LocalStorage, ObjectExists, ObjectNotFound
from ...storage.base import DOWNLOAD_PURPOSE, UPLOAD_PURPOSE
from ..deps import AppSettings, FileStorage

router = APIRouter(tags=["files"])


def _claims(token: str, purpose: str, secret: str) -> dict:
    try:
        return unsign(token, purpose=purpose, secret=secret)
    except InvalidLink as error:
        raise PermissionDenied("This link is invalid or has expired.", code="invalid_link") from error


def _attachment(filename: str) -> str:
    """A Content-Disposition value that always downloads, so a report never renders on the API's origin."""
    encoded = quote(filename)
    return f"attachment; filename*=utf-8''{encoded}" if encoded != filename else f'attachment; filename="{filename}"'


@router.put("/uploads/{token}", status_code=204)
async def receive_upload(token: str, request: Request, settings: AppSettings, storage: FileStorage) -> Response:
    """Receive a file, streaming it to disk so memory use does not grow with file size."""
    assert isinstance(storage, (LocalStorage, DatabaseStorage))
    claims = _claims(token, UPLOAD_PURPOSE, settings.app_secret_key)
    key, max_bytes = claims["k"], int(claims["max"])
    too_large = PayloadTooLarge(f"This file is larger than the {settings.max_upload_mb} MB upload limit.")

    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > max_bytes:
        raise too_large
    if await run_in_threadpool(storage.exists, key):
        raise Conflict("This file has already been uploaded.", code="already_uploaded")

    writer = storage.open_upload(key, max_bytes, str(claims.get("ct") or "application/octet-stream"))
    try:
        # The declared length is only a hint; the limit is enforced on bytes actually received.
        async for chunk in request.stream():
            if not writer.write(chunk):
                raise too_large
        # Publishing may mean writing the file into the database: keep that off the event loop.
        await run_in_threadpool(writer.commit)
    except ObjectExists as error:
        raise Conflict("This file has already been uploaded.", code="already_uploaded") from error
    except BaseException:
        writer.abort()
        raise
    return Response(status_code=204)


@router.get("/files/{token}")
def download_file(token: str, settings: AppSettings, storage: FileStorage) -> Response:
    assert isinstance(storage, (LocalStorage, DatabaseStorage))
    claims = _claims(token, DOWNLOAD_PURPOSE, settings.app_secret_key)
    key, filename, media_type = claims["k"], claims["fn"], claims["ct"]
    headers = {"Cache-Control": "private, no-store"}
    if isinstance(storage, LocalStorage):
        path = storage.path(key)
        if not path.is_file():
            raise NotFound("File not found.")
        return FileResponse(path, media_type=media_type, filename=filename, headers=headers)  # sent as an attachment
    try:
        size = storage.size(key)
    except ObjectNotFound as error:
        raise NotFound("File not found.") from error
    headers |= {"Content-Disposition": _attachment(filename), "Content-Length": str(size)}
    return StreamingResponse(storage.iter_chunks(key), media_type=media_type, headers=headers)
