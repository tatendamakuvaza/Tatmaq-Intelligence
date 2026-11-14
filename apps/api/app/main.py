"""The API application.

Run locally:   uvicorn app.main:app --reload --port 8000
Interactive documentation (outside production): http://localhost:8000/docs
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from . import __version__
from .api.router import build_router
from .core.config import get_settings
from .core.database import get_engine
from .core.errors import install_error_handlers
from .core.logging import configure_logging

SECURITY_HEADERS = (
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
)


class SecurityHeaders:
    """Adds baseline security headers. Plain ASGI, so request bodies still stream."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                present = {name for name, _ in message.get("headers", [])}
                message.setdefault("headers", []).extend(h for h in SECURITY_HEADERS if h[0] not in present)
                if b"cache-control" not in present:
                    message["headers"].append((b"cache-control", b"no-store"))
            await send(message)

        await self.app(scope, receive, send_with_headers)


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()
    public_docs = settings.app_env != "production"
    app = FastAPI(
        title="TATMAQ Intelligence API",
        version=__version__,
        docs_url="/docs" if public_docs else None,
        openapi_url="/openapi.json" if public_docs else None,
        redoc_url=None,
    )
    install_error_handlers(app)
    app.add_middleware(SecurityHeaders)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_methods=["GET", "POST", "PUT", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Organisation-Id", "Idempotency-Key"],
            max_age=600,
        )
    app.include_router(build_router(settings), prefix="/v1")

    @app.get("/healthz", tags=["meta"])
    def healthz() -> dict:
        """The process is up."""
        return {"status": "ok", "version": __version__}

    @app.get("/readyz", tags=["meta"])
    def readyz() -> dict:
        """The process can reach its database."""
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ready"}

    return app


app = create_app()
