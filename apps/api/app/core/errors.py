"""Application errors and their mapping to HTTP responses.

Every error leaves the API in one shape, ``{"error": {"code", "message"}}``, so the
web app handles failures in a single place. Unexpected exceptions are logged in full
and reported to the client without internal detail.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, code: str | None = None, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code:
            self.code = code
        self.details = details


class AuthenticationError(AppError):
    status_code = 401
    code = "not_authenticated"


class PermissionDenied(AppError):
    status_code = 403
    code = "permission_denied"


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class PayloadTooLarge(AppError):
    status_code = 413
    code = "payload_too_large"


class UnsupportedFile(AppError):
    status_code = 415
    code = "unsupported_file"


class LimitExceeded(AppError):
    status_code = 429
    code = "limit_exceeded"


class ConfigurationError(AppError):
    status_code = 500
    code = "configuration_error"


def _body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error["details"] = details
    return {"error": error}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, error: AppError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if error.status_code == 401 else None
        return JSONResponse(_body(error.code, error.message, error.details), error.status_code, headers=headers)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, error: RequestValidationError) -> JSONResponse:
        problems = [
            {"field": ".".join(str(part) for part in item["loc"] if part != "body"), "problem": item["msg"]}
            for item in error.errors()
        ]
        first = problems[0] if problems else {"field": "", "problem": "invalid request"}
        message = f"{first['field']}: {first['problem']}" if first["field"] else first["problem"]
        return JSONResponse(_body("invalid_request", message, {"fields": problems}), 422)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, error: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(error.status_code, "http_error")
        return JSONResponse(_body(code, str(error.detail)), error.status_code)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, error: Exception) -> JSONResponse:
        logger.exception("unhandled error on %s %s", request.method, request.url.path, exc_info=error)
        return JSONResponse(_body("internal_error", "Something went wrong on our side. Please try again."), 500)
