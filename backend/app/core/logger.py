"""Structured logging: JSON in prod, request-ID-prefixed text in dev."""

import logging
import sys
from contextvars import ContextVar

from pythonjsonlogger.json import JsonFormatter

from app.core.config import Environment, config

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)


class _ContextFilter(logging.Filter):
    """Attach the request ID from the contextvar onto every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


class _AppFormatter(logging.Formatter):
    """Dev formatter: time, level, and a short request-ID prefix when available."""

    def __init__(self) -> None:
        super().__init__(
            fmt="%(asctime)s %(levelname)-7s %(request_id_prefix)s%(message)s",
            datefmt="%H:%M:%S",
        )

    def format(self, record: logging.LogRecord) -> str:
        request_id = getattr(record, "request_id", None)
        record.request_id_prefix = f"[{request_id[:8]}] " if request_id else ""
        return super().format(record)


def _build_formatter() -> logging.Formatter:
    if config.ENVIRONMENT == Environment.PROD:
        return JsonFormatter(
            "%(levelname)s %(name)s %(message)s %(request_id)s",
            rename_fields={"levelname": "level", "name": "logger"},
            timestamp=True,
        )
    return _AppFormatter()


def setup_logging() -> None:
    """Configure the app logger and route uvicorn's logs through the same handler."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_build_formatter())
    handler.addFilter(_ContextFilter())

    app_logger = logging.getLogger("app")
    app_logger.handlers = [handler]
    app_logger.setLevel(logging.INFO)
    app_logger.propagate = False

    uvicorn_logger = logging.getLogger("uvicorn")
    uvicorn_logger.handlers = [handler]
    uvicorn_logger.setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").disabled = True
