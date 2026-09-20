"""The Cloudflare Turnstile check on a question, made as a route dependency."""

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
"""What the widget stamps on every token it mints, and what a token must come back stamped
with. A sitekey is public, so without this a token minted against another widget of the
account would pass here. The page it was minted on has to be this deployment's frontend for
the same reason: the widget's domains include localhost, and FRONTEND_URL already names the
one origin this deployment serves chat to."""

TurnstileHeader = Annotated[str | None, Header(max_length=2048)]
"""The token a browser sends with every question, bounded at Cloudflare's own cap because a
longer one is junk that should cost no outbound call."""

turnstile_client = http_client(timeout=config.TURNSTILE_TIMEOUT)
"""The one client every check shares, so a question pays no fresh handshake to Cloudflare."""


async def ask_cloudflare(token: str, ip: str | None) -> dict[str, Any] | None:
    """Cloudflare's verdict on a token, or None when it could not be asked: unreachable,
    erroring, or answering with something that is not the verdict."""
    form = {"secret": config.TURNSTILE_SECRET_KEY.get_secret_value(), "response": token}
    if ip:
        form["remoteip"] = ip
    try:
        response = await turnstile_client.post(SITEVERIFY_URL, data=form)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("turnstile check failed, letting the question through: %s", exc)
        return None


async def verify_turnstile(request: Request, cf_turnstile_response: TurnstileHeader = None) -> None:
    """Refuse the question unless Cloudflare vouches for the token the widget minted for it.
    A check that cannot be made lets the question through, as the rate limiter does when
    Redis is gone: the limit and the spend cap are the backstops."""
    if not config.TURNSTILE_ENABLED:
        return
    if not config.TURNSTILE_SECRET_KEY.get_secret_value():
        logger.error("TURNSTILE_ENABLED is set with no secret key, so questions go unchecked")
        return
    if not cf_turnstile_response:
        raise TurnstileFailedError()
    verdict = await ask_cloudflare(cf_turnstile_response, client_ip(request))
    if verdict is None:
        return
    if (
        not verdict.get("success")
        or verdict.get("action") != TURNSTILE_ACTION
        or verdict.get("hostname") != urlparse(config.FRONTEND_URL).hostname
    ):
        logger.warning(
            "turnstile refused the question: codes=%s action=%s hostname=%s",
            verdict.get("error-codes"),
            verdict.get("action"),
            verdict.get("hostname"),
        )
        raise TurnstileFailedError()
