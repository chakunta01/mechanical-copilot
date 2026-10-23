"""Central error taxonomy: one exception type per failure class, mapped to HTTP codes."""

from __future__ import annotations

from typing import Any

from fastapi import Request, status
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Base class for all expected (handled) errors."""

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    code = "internal_error"

    def __init__(self, message: str, *, details: Any | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def to_response(self) -> JSONResponse:
        body: dict[str, Any] = {"error": {"code": self.code, "message": self.message}}
        if self.details is not None:
            body["error"]["details"] = self.details
        return JSONResponse(status_code=self.status_code, content=body)


class ValidationFailure(AppError):
    status_code = status.HTTP_400_BAD_REQUEST
    code = "validation_failure"


class NotFound(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "not_found"


class Unauthorized(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "unauthorized"


class Forbidden(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "forbidden"


class Conflict(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "conflict"


class UpstreamError(AppError):
    """LLM/embedding/vector-store or other downstream service failure."""

    status_code = status.HTTP_502_BAD_GATEWAY
    code = "upstream_error"


class PayloadTooLarge(AppError):
    status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    code = "payload_too_large"


class UnsupportedMediaType(AppError):
    status_code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    code = "unsupported_media_type"


class RateLimited(AppError):
    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    code = "rate_limited"


def install_error_handlers(app) -> None:  # noqa: ANN001 - FastAPI app
    """Register handlers: AppError -> mapped response; everything else -> 500 envelope."""

    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return exc.to_response()

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        # Do not leak internals to clients; full detail goes to logs.
        logger.exception("unhandled_error")
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "internal_error", "message": "Internal server error"}},
        )

    from app.core.logging import get_logger

    logger = get_logger("errors")
