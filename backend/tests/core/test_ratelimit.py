"""The chat rate limiter: one client id's allowance, the address ceiling behind it, and
what happens when Redis is not there."""

import logging
import time

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from redis.asyncio import Redis

from app.core.config import config
from app.core.ratelimit import rate_limit
from tests.core.test_exceptions import assert_error_shape

router = APIRouter()


@router.post("/limited", dependencies=[Depends(rate_limit)])
def limited() -> dict[str, bool]:
    return {"ok": True}


@pytest.fixture
def client(app: FastAPI, rate_limited_client: TestClient) -> TestClient:
    app.include_router(router)
    return rate_limited_client


def ask(client: TestClient, client_id: str | None = None, ip: str | None = None):
    headers = {}
    if client_id is not None:
        headers["X-Client-ID"] = client_id
    if ip is not None:
        headers["Fly-Client-IP"] = ip
    return client.post("/limited", headers=headers)


def test_a_client_is_refused_once_it_has_used_its_allowance(client: TestClient) -> None:
    assert ask(client, "a").status_code == 200
    assert ask(client, "a").status_code == 200

    response = ask(client, "a")

    body = assert_error_shape(response, 429, "RateLimitedError")
    assert response.headers["Retry-After"] == "60"
    assert body["message"] == "Too many questions; try again in 60 seconds"


def test_the_refusal_names_the_wait_left_in_the_window(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "RATE_LIMIT_WINDOW_SECONDS", 1)
    monkeypatch.setattr(config, "RATE_LIMIT_PER_CLIENT", 1)
    ask(client, "a")
    time.sleep(0.5)

    response = ask(client, "a")

    assert response.headers["Retry-After"] == "1"


def test_the_window_slides(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "RATE_LIMIT_WINDOW_SECONDS", 1)
    monkeypatch.setattr(config, "RATE_LIMIT_PER_CLIENT", 1)
    ask(client, "a")
    time.sleep(1.05)

    assert ask(client, "a").status_code == 200


def test_ids_on_one_address_share_its_ceiling(client: TestClient) -> None:
    assert ask(client, "a", ip="203.0.113.9").status_code == 200
    assert ask(client, "b", ip="203.0.113.9").status_code == 200
    assert ask(client, "c", ip="203.0.113.9").status_code == 200

    assert ask(client, "d", ip="203.0.113.9").status_code == 429
    assert ask(client, "d", ip="203.0.113.10").status_code == 200


def test_a_refused_call_counts_against_neither_key(client: TestClient) -> None:
    """Client a is refused its third question; that refusal must not eat the address's
    allowance, or b would be turned away on an address that has only asked twice."""
    ask(client, "a")
    ask(client, "a")
    assert ask(client, "a").status_code == 429

    assert ask(client, "b").status_code == 200


def test_without_an_id_the_client_allowance_is_the_address(client: TestClient) -> None:
    assert ask(client, ip="203.0.113.9").status_code == 200
    assert ask(client, ip="203.0.113.9").status_code == 200

    assert ask(client, ip="203.0.113.9").status_code == 429
    assert ask(client, ip="203.0.113.10").status_code == 200


def test_an_oversized_id_is_rejected_rather_than_stored(client: TestClient) -> None:
    """A key carries the id verbatim, so its length is the one thing a caller could inflate."""
    response = ask(client, "x" * 65)

    assert response.status_code == 422
    assert ask(client, "x" * 64).status_code == 200


def test_off_it_refuses_nothing(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "RATE_LIMIT_ENABLED", False)
    for _ in range(5):
        assert ask(client, "a").status_code == 200


def test_redis_down_lets_the_call_through(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The spend cap is the backstop; a Redis blip must not take the product down."""
    unreachable = Redis.from_url("redis://localhost:9/0", socket_connect_timeout=0.2)
    monkeypatch.setattr("app.core.ratelimit.redis_client", unreachable)

    with caplog.at_level(logging.ERROR):
        response = ask(client, "a")

    assert response.status_code == 200
    [record] = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert "rate limit" in record.getMessage()
