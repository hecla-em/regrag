"""Domain errors and exception handlers returning one consistent JSON shape."""

import logging
from collections.abc import Mapping, Sequence
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException

from app.core.logger import request_id_var
from app.core.models import ErrorResponse

logger = logging.getLogger(__name__)


class DomainError(Exception):
    """Base for application errors that map to HTTP responses via one handler."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR

    def __init__(self, message: str, headers: Mapping[str, str] | None = None):
        self.message = message
        self.headers = headers
        super().__init__(message)


class NotFoundError(DomainError):
    """Raised when a resource is not found."""

    status_code = status.HTTP_404_NOT_FOUND

    def __init__(self, resource: str, identifier: str | int):
        super().__init__(f"{resource} '{identifier}' not found")
        self.resource = resource
        self.identifier = identifier


class RateLimitedError(DomainError):
    """The caller has asked as often as the window allows; the header says how long to wait."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS

    def __init__(self, retry_after: int):
        super().__init__(
            f"Too many questions; try again in {retry_after} seconds",
            headers={"Retry-After": str(retry_after)},
        )


def describe(exc: Exception) -> tuple[str, str]:
    """The (error, message) pair an exception reports: a DomainError speaks for itself,
    anything else is the one generic failure whose detail stays in the log."""
    if isinstance(exc, DomainError):
        return type(exc).__name__, exc.message
    return "InternalServerError", "An unexpected error occurred"


def error_response(
    status_code: int,
    *,
    error: str,
    message: str,
    detail: list[Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Build the single error shape every handler returns."""
    body = ErrorResponse(
        error=error,
        message=message,
        request_id=request_id_var.get(),
        detail=detail,
    )
    return JSONResponse(
        status_code=status_code,
        content=body.model_dump(),
        headers=headers,
    )


def _sanitize_validation_errors(errors: Sequence[Any]) -> list[dict[str, Any]]:
    """Strip input and ctx to avoid leaking request payloads into responses and logs.

    ctx goes too: for value_error entries it holds the raw ValueError, whose
    message usually embeds the offending input value."""
    return [{k: v for k, v in e.items() if k not in ("input", "ctx")} for e in errors]


async def validation_error_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Handle Pydantic validation errors: 422 with sanitized error details."""
    sanitized = _sanitize_validation_errors(exc.errors())
    logger.warning("ValidationError on %s %s: %s", request.method, request.url.path, sanitized)
    return error_response(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        error="ValidationError",
        message="Request validation failed",
        detail=jsonable_encoder(sanitized),
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> Response:
    """Handle HTTP exceptions, preserving status and headers."""
    logger.warning(
        "HTTPException on %s %s: %s %s",
        request.method,
        request.url.path,
        exc.status_code,
        exc.detail,
    )
    if exc.status_code in {status.HTTP_204_NO_CONTENT, status.HTTP_304_NOT_MODIFIED}:
        return Response(status_code=exc.status_code, headers=exc.headers)
    if isinstance(exc.detail, str):
        message, detail = exc.detail, None
    else:
        message, detail = HTTPStatus(exc.status_code).phrase, [jsonable_encoder(exc.detail)]
    return error_response(
        exc.status_code,
        error="HTTPException",
        message=message,
        detail=detail,
        headers=exc.headers,
    )


async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    """Map any DomainError subclass to a JSON response using its status_code."""
    name, message = describe(exc)
    logger.warning("%s on %s %s: %s", name, request.method, request.url.path, message)
    return error_response(exc.status_code, error=name, message=message, headers=exc.headers)


async def integrity_error_handler(request: Request, exc: IntegrityError) -> JSONResponse:
    """Handle database constraint violations as 409 Conflict."""
    logger.warning("IntegrityError on %s %s: %s", request.method, request.url.path, exc.orig)
    return error_response(
        status.HTTP_409_CONFLICT,
        error="IntegrityError",
        message="This conflicts with an existing record",
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Register all handlers via a loop: ty doesn't model Starlette's async
    handler variance, so this needs one suppression instead of four."""
    handlers = [
        (RequestValidationError, validation_error_handler),
        (HTTPException, http_exception_handler),
        (DomainError, domain_error_handler),
        (IntegrityError, integrity_error_handler),
    ]
    for exc_type, handler in handlers:
        app.add_exception_handler(exc_type, handler)  # ty: ignore[invalid-argument-type]
