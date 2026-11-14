"""File storage behind one interface: local disk, the database itself, or a private Supabase bucket."""

import tempfile
from functools import lru_cache
from pathlib import Path

from ..core.config import Settings, get_settings
from ..core.database import get_engine
from .base import (
    ObjectExists,
    ObjectNotFound,
    Storage,
    StorageError,
    TenantBoundaryError,
    UploadTarget,
    assert_belongs_to,
)
from .database import DatabaseStorage
from .local import LocalStorage
from .supabase import SupabaseStorage

__all__ = [
    "DatabaseStorage",
    "LocalStorage",
    "ObjectExists",
    "ObjectNotFound",
    "Storage",
    "StorageError",
    "SupabaseStorage",
    "TenantBoundaryError",
    "UploadTarget",
    "assert_belongs_to",
    "build_storage",
    "get_storage",
]


def build_storage(settings: Settings) -> Storage:
    if settings.storage_backend == "supabase":
        return SupabaseStorage(
            url=settings.supabase_url, secret_key=settings.supabase_secret_key, bucket=settings.object_storage_bucket
        )
    if settings.storage_backend == "database":
        # Uploads wait in the system's temporary folder until they are complete, then go to the database.
        spool = Path(tempfile.gettempdir()) / "tatmaq-uploads"
        return DatabaseStorage(get_engine, settings.app_secret_key, spool)
    return LocalStorage(settings.storage_local_dir, settings.app_secret_key)


@lru_cache
def get_storage() -> Storage:
    return build_storage(get_settings())
