"""The Cloudflare Turnstile check, as a route dependency."""

import logging
from typing import Annotated, Any
from urllib.parse import urlparse

import httpx
from fastapi import Header, Request

from app.core.config import config
from app.core.exceptions import TurnstileFailedError
from app.core.http import http_client
from app.core.middleware import client_ip

logger = logging.getLogger(__name__)

SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
TURNSTILE_ACTION = "chat"

TurnstileHeader = Annotated[str | None, Header(max_length=2048)]

turnstile_client = http_client(timeout=config.TURNSTILE_TIMEOUT)


async def ask_cloudflare(token: str, ip: str | None) -> dict[str, Any] | None:
    """Cloudflare's verdict on a token, or None when it could not be asked."""
    form = {"secret": config.TURNSTILE_SECRET_KEY.get_secret_value(), "response": token}
    if ip:
        form["remoteip"] = ip
    try:
        response = await turnstile_client.post(SITEVERIFY_URL, data=form)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("turnstile check failed, letting the request through: %s", exc)
        return None


def is_from_chat_page(verdict: dict[str, Any]) -> bool:
    """Whether the token was minted by the chat page's widget. Cloudflare's test keys answer
    as example.com with no action, so their verdicts are taken as they come."""
    if verdict.get("metadata", {}).get("result_with_testing_key"):
        return True
    return (
        verdict.get("action") == TURNSTILE_ACTION
        and verdict.get("hostname") == urlparse(config.FRONTEND_URL).hostname
    )


async def verify_turnstile(request: Request, cf_turnstile_response: TurnstileHeader = None) -> None:
    """Refuse the request unless Cloudflare vouches for its token, action and page. A check
    that cannot be made lets it through: the rate limit and spend cap are the backstops."""
    if not config.TURNSTILE_ENABLED:
        return
    if not config.TURNSTILE_SECRET_KEY.get_secret_value():
        logger.error("TURNSTILE_ENABLED is set with no secret key, so requests go unchecked")
        return
    if not cf_turnstile_response:
        raise TurnstileFailedError()
    verdict = await ask_cloudflare(cf_turnstile_response, client_ip(request))
    if verdict is None:
        return
    if not verdict.get("success") or not is_from_chat_page(verdict):
        logger.warning(
            "turnstile refused the request: codes=%s action=%s hostname=%s",
            verdict.get("error-codes"),
            verdict.get("action"),
            verdict.get("hostname"),
        )
        raise TurnstileFailedError()
