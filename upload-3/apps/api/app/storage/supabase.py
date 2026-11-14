"""Supabase Storage (private bucket) over its REST API.

Browsers upload straight to Supabase through a signed URL and download through a
signed URL, so file bytes never pass through the API container. Only the worker
streams objects, using the project's secret key.

Create the bucket as *private*, with a file-size limit equal to MAX_UPLOAD_MB: signed
upload URLs cannot carry a per-upload size limit, so the bucket enforces it.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

import httpx

from .base import ObjectExists, ObjectNotFound, StorageError, UploadTarget, validate_key


class SupabaseStorage:
    def __init__(self, *, url: str, secret_key: str, bucket: str, client: httpx.Client | None = None) -> None:
        self._base = f"{url.rstrip('/')}/storage/v1"
        self._bucket = bucket
        self._headers = {"apikey": secret_key, "Authorization": f"Bearer {secret_key}"}
        self._client = client or httpx.Client(timeout=httpx.Timeout(30.0, read=300.0, write=300.0))

    def _object(self, key: str, prefix: str = "object") -> str:
        return f"{self._base}/{prefix}/{self._bucket}/{quote(validate_key(key))}"

    @staticmethod
    def _missing(response: httpx.Response) -> bool:
        # Supabase Storage reports a missing object as 404, or as 400 with a not-found body.
        return response.status_code == 404 or (response.status_code == 400 and "not" in response.text.lower())

    def _fail(self, action: str, response: httpx.Response) -> StorageError:
        return StorageError(f"storage {action} failed ({response.status_code}): {response.text[:200]}")

    def exists(self, key: str) -> bool:
        response = self._client.head(self._object(key), headers=self._headers)
        if response.status_code == 200:
            return True
        if response.status_code in (400, 404):
            return False
        raise self._fail("lookup", response)

    def size(self, key: str) -> int:
        response = self._client.get(self._object(key, "object/info"), headers=self._headers)
        if self._missing(response):
            raise ObjectNotFound(key)
        if response.status_code != 200:
            raise self._fail("lookup", response)
        body = response.json()
        size = body.get("size", (body.get("metadata") or {}).get("size"))
        if size is None:
            raise StorageError("storage did not report the object size")
        return int(size)

    def download_to(self, key: str, destination: Path) -> None:
        with self._client.stream("GET", self._object(key), headers=self._headers) as response:
            if response.status_code != 200:
                response.read()
                raise ObjectNotFound(key) if self._missing(response) else self._fail("download", response)
            with destination.open("wb") as handle:
                for chunk in response.iter_bytes(1024 * 256):
                    handle.write(chunk)

    def put_file(self, key: str, source: Path, *, content_type: str, overwrite: bool = False) -> None:
        headers = {**self._headers, "Content-Type": content_type, "x-upsert": "true" if overwrite else "false"}
        with source.open("rb") as handle:
            response = self._client.post(self._object(key), headers=headers, content=handle)
        if response.status_code in (200, 201):
            return
        if response.status_code == 409 or "already exists" in response.text.lower():
            raise ObjectExists(key)
        raise self._fail("upload", response)

    def delete(self, key: str) -> None:
        response = self._client.delete(self._object(key), headers=self._headers)
        if response.status_code not in (200, 204) and not self._missing(response):
            raise self._fail("delete", response)

    def create_upload_target(self, key: str, *, content_type: str, max_bytes: int, ttl_seconds: int) -> UploadTarget:
        # No upsert: once an object exists a second upload to the same key is refused,
        # which is what keeps an original file from being replaced after it is imported.
        response = self._client.post(self._object(key, "object/upload/sign"), headers=self._headers)
        if response.status_code != 200 or "url" not in response.json():
            raise self._fail("signing", response)
        return UploadTarget(
            method="PUT", url=f"{self._base}{response.json()['url']}", headers={"Content-Type": content_type}
        )

    def create_download_url(self, key: str, *, filename: str, content_type: str, ttl_seconds: int) -> str:
        response = self._client.post(
            self._object(key, "object/sign"), headers=self._headers, json={"expiresIn": ttl_seconds}
        )
        if self._missing(response):
            raise ObjectNotFound(key)
        if response.status_code != 200 or "signedURL" not in response.json():
            raise self._fail("signing", response)
        return f"{self._base}{response.json()['signedURL']}&download={quote(filename)}"
