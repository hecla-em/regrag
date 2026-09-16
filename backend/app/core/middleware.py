"""HTTP middleware for the FastAPI application."""

import logging
import time
import uuid
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.core.clock import elapsed_ms
from app.core.config import Environment, config
from app.core.exceptions import describe, error_response
from app.core.logger import request_id_var

logger = logging.getLogger(__name__)


async def request_id_middleware(request: Request, call_next):
    """Bind a server-generated request ID for the request's lifetime."""
    request_id = uuid.uuid4().hex
    token = request_id_var.set(request_id)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        request_id_var.reset(token)


def client_ip(request: Request) -> str | None:
    """The address the request came from. In prod the connection is Fly's proxy and the
    header carries the client's. Anywhere else the header is whatever the caller wrote."""
    if config.ENVIRONMENT is Environment.PROD and (fly := request.headers.get("Fly-Client-IP")):
        return fly
    return request.client.host if request.client else None


def _log_access(request: Request, status_code: int, duration_ms: int) -> None:
    """The one access-log line per request."""
    logger.info(
        "%s %s %s - %sms",
        request.method,
        request.scope["path"],
        status_code,
        duration_ms,
        extra={
            "method": request.method,
            "path": request.scope["path"],
            "route": getattr(request.scope.get("route"), "path", None),
            "status": status_code,
            "duration_ms": duration_ms,
            "client_ip": client_ip(request),
        },
    )


async def access_log_middleware(request: Request, call_next):
    """Log the request once its body has been sent: a streamed answer does its work
    after the headers go out, so that is the first point its duration is known."""
    start = time.perf_counter()
    response = await call_next(request)
    body = response.body_iterator

    async def logged_body() -> AsyncIterator[bytes]:
        try:
            async for chunk in body:
                yield chunk
        finally:
            _log_access(request, response.status_code, elapsed_ms(start))

    response.body_iterator = logged_body()
    return response


async def exception_middleware(request: Request, call_next):
    """Convert unhandled exceptions into the shared 500 error shape."""
    try:
        return await call_next(request)
    except Exception as exc:
        logger.exception("Unhandled error on %s %s", request.method, request.scope["path"])
        error, message = describe(exc)
        return error_response(status.HTTP_500_INTERNAL_SERVER_ERROR, error=error, message=message)


def register_middleware(app: FastAPI) -> None:
    """Register middleware, innermost first (Starlette runs the last-added
    middleware first): exception sits innermost so the access log records the
    500, request-ID outermost of the three so the contextvar is set for all
    downstream logging."""
    app.middleware("http")(exception_middleware)
    app.middleware("http")(access_log_middleware)
    app.middleware("http")(request_id_middleware)
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.CORS_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )
