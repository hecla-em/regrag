"""Sentry error reporting: every ERROR log line becomes an event, tagged with its request id."""

from typing import Any

import sentry_sdk
from sentry_sdk.integrations.fastapi import FastApiIntegration

from app.core.config import config
from app.core.logger import request_id_var


def _before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any]:
    request_id = request_id_var.get()
    if request_id:
        event.setdefault("tags", {})["request_id"] = request_id
    return event


def configure_sentry() -> None:
    """Start Sentry when a DSN is set. The request body and frame locals both hold the
    question, so neither is sent."""
    if not config.SENTRY_DSN:
        return

    sentry_sdk.init(
        dsn=config.SENTRY_DSN,
        environment=config.ENVIRONMENT.value,
        release=config.BUILD_ID,
        send_default_pii=False,
        max_request_body_size="never",
        include_local_variables=False,
        integrations=[
            FastApiIntegration(transaction_style="endpoint"),
        ],
        before_send=_before_send,  # ty: ignore[invalid-argument-type]
    )
