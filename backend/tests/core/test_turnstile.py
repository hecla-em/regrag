"""The Turnstile check on chat: what Cloudflare has to say for a question to go through,
and what happens when it says nothing at all."""

import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qsl

import httpx
import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core import turnstile
from app.core.config import Environment, config
from app.core.turnstile import TURNSTILE_ACTION, verify_turnstile
from tests.core.test_exceptions import assert_error_shape

router = APIRouter()

TOKEN = "0.minted-by-the-widget"
SECRET = "0x-the-secret"


@router.post("/verified", dependencies=[Depends(verify_turnstile)])
def verified() -> dict[str, bool]:
    return {"ok": True}


@pytest.fixture(autouse=True)
def verified_route_behind_fly(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    """The route to check, reached as in prod, where the Fly header names the caller."""
    app.include_router(router)
    monkeypatch.setattr(config, "ENVIRONMENT", Environment.PROD)
    monkeypatch.setattr(config, "TURNSTILE_SECRET_KEY", SecretStr(SECRET))
    monkeypatch.setattr(config, "TURNSTILE_ENABLED", True)


@pytest.fixture
def siteverify(monkeypatch: pytest.MonkeyPatch) -> Callable[..., list[dict[str, str]]]:
    """Install Cloudflare's answer to every check, and hand back the list the forms it was
    asked with accumulate in."""

    def install(answer: Callable[[httpx.Request], httpx.Response]) -> list[dict[str, str]]:
        asked: list[dict[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            asked.append(dict(parse_qsl(request.content.decode())))
            return answer(request)

        monkeypatch.setattr(
            turnstile,
            "http_client",
            lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        return asked

    return install


def verdict(**fields: Any) -> Callable[[httpx.Request], httpx.Response]:
    """Cloudflare's reply to a check, vouching for the token unless the test says otherwise."""
    body = {"success": True, "action": TURNSTILE_ACTION, "hostname": "faqs.hecla-em.com"}
    return lambda request: httpx.Response(200, json=body | fields)


def ask(client: TestClient, token: str | None = TOKEN, ip: str | None = None):
    headers = {}
    if token is not None:
        headers["CF-Turnstile-Response"] = token
    if ip is not None:
        headers["Fly-Client-IP"] = ip
    return client.post("/verified", headers=headers)


def test_a_token_cloudflare_vouches_for_goes_through(client: TestClient, siteverify) -> None:
    siteverify(verdict())

    assert ask(client).status_code == 200


def test_a_token_cloudflare_refuses_is_turned_away(client: TestClient, siteverify) -> None:
    siteverify(verdict(success=False, **{"error-codes": ["timeout-or-duplicate"]}))

    assert_error_shape(ask(client), 403, "TurnstileFailedError")


def test_a_token_stamped_for_another_widget_is_turned_away(client: TestClient, siteverify) -> None:
    """A sitekey is public, so a token minted against another of this account's widgets is
    one a script can get. The action the widget stamps is what tells them apart."""
    siteverify(verdict(action="signup"))

    assert_error_shape(ask(client), 403, "TurnstileFailedError")


def test_a_question_without_a_token_never_reaches_cloudflare(
    client: TestClient, siteverify
) -> None:
    asked = siteverify(verdict())

    assert_error_shape(ask(client, token=None), 403, "TurnstileFailedError")
    assert asked == []


def test_an_empty_token_never_reaches_cloudflare(client: TestClient, siteverify) -> None:
    asked = siteverify(verdict())

    assert_error_shape(ask(client, token=""), 403, "TurnstileFailedError")
    assert asked == []


def test_a_token_longer_than_cloudflare_mints_is_refused(client: TestClient, siteverify) -> None:
    asked = siteverify(verdict())

    assert ask(client, token="x" * 3000).status_code == 422
    assert asked == []


def test_the_check_carries_the_secret_and_the_callers_address(
    client: TestClient, siteverify
) -> None:
    asked = siteverify(verdict())

    ask(client, ip="203.0.113.9")

    assert asked == [{"secret": SECRET, "response": TOKEN, "remoteip": "203.0.113.9"}]


def test_cloudflare_unreachable_lets_the_question_through(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    """A check that cannot be made must not take chat down: the rate limit and the spend
    cap are still behind it."""

    def refuse_to_connect(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to challenges.cloudflare.com")

    monkeypatch.setattr(
        turnstile,
        "http_client",
        lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(refuse_to_connect)),
    )

    with caplog.at_level(logging.WARNING, logger=turnstile.logger.name):
        assert ask(client).status_code == 200
    assert "letting the question through" in caplog.text


def test_cloudflare_erroring_lets_the_question_through(client: TestClient, siteverify) -> None:
    siteverify(lambda request: httpx.Response(502, text="bad gateway"))

    assert ask(client).status_code == 200


def test_cloudflare_answering_with_junk_lets_the_question_through(
    client: TestClient, siteverify
) -> None:
    siteverify(lambda request: httpx.Response(200, text="<html>not json</html>"))

    assert ask(client).status_code == 200


def test_on_with_no_secret_key_lets_the_question_through(
    client: TestClient, siteverify, monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    """A deploy that turned the check on and forgot the secret would otherwise refuse every
    question, since Cloudflare recognises no token under an empty one."""
    monkeypatch.setattr(config, "TURNSTILE_SECRET_KEY", SecretStr(""))
    asked = siteverify(verdict())

    with caplog.at_level(logging.ERROR, logger=turnstile.logger.name):
        assert ask(client, token=None).status_code == 200
    assert asked == []
    assert "no secret key" in caplog.text


def test_switched_off_no_token_is_needed(
    client: TestClient, siteverify, monkeypatch: pytest.MonkeyPatch
) -> None:
    """How dev, the tests and the evals run: the check off, so nothing mints a token."""
    monkeypatch.setattr(config, "TURNSTILE_ENABLED", False)
    asked = siteverify(verdict())

    assert ask(client, token=None).status_code == 200
    assert asked == []
