"""Assembles the versioned API (everything here is served under /v1)."""

from __future__ import annotations

from fastapi import APIRouter

from .. import __version__
from ..core.config import Settings
from ..services.datasets import CONTENT_TYPES
from .routes import accounts, arena, datasets, files, jobs, learning


def build_router(settings: Settings) -> APIRouter:
    router = APIRouter()

    @router.get("/config", tags=["meta"])
    def client_config() -> dict:
        """What the web app needs to know before anyone signs in. Contains no secrets."""
        return {
            "version": __version__,
            "auth_mode": settings.auth_mode,
            # Under Supabase Auth, sign-up is switched on or off in the Supabase project instead.
            "signups_open": settings.allow_signups or not settings.builtin_sign_in,
            "max_upload_mb": settings.max_upload_mb,
            "file_types": sorted(CONTENT_TYPES),
            "ai_enabled": settings.ai_enabled,
            "ai_provider": settings.ai_provider,
        }

    router.include_router(accounts.router)
    if settings.builtin_sign_in:
        router.include_router(accounts.sign_in_router)
    router.include_router(datasets.router)
    router.include_router(jobs.router)
    router.include_router(learning.router)
    router.include_router(arena.router)
    if settings.storage_backend in ("local", "database"):
        router.include_router(files.router)
    return router
