"""The chat rate limiter: one client id's allowance, the address ceiling behind it, and
what happens when Redis is not there."""

import logging
from types import SimpleNamespace

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from app.core import ratelimit
from app.core.config import Environment, config
from app.core.ratelimit import rate_limit
from app.core.redis import get_redis
from tests.conftest import unreachable_redis
from tests.core.test_exceptions import assert_error_shape

router = APIRouter()


@router.post("/limited", dependencies=[Depends(rate_limit)])
def limited() -> dict[str, bool]:
    return {"ok": True}


@pytest.fixture(autouse=True)
def limited_route_behind_fly(app: FastAPI, monkeypatch: pytest.MonkeyPatch) -> None:
    """The route to count, reached as in prod, where the Fly header names the caller."""
    app.include_router(router)
    monkeypatch.setattr(config, "ENVIRONMENT", Environment.PROD)


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    """The limiter's view of time, pinned so tests move the window instead of waiting for it."""
    fake = SimpleNamespace(now_ms=1_700_000_000_000)
    monkeypatch.setattr("app.core.ratelimit.now_ms", lambda: fake.now_ms)
    return fake


def ask(client: TestClient, client_id: str | None = None, ip: str | None = None):
    headers = {}
    if client_id is not None:
        headers["X-Client-ID"] = client_id
    if ip is not None:
        headers["Fly-Client-IP"] = ip
    return client.post("/limited", headers=headers)


def test_a_client_is_refused_once_it_has_used_its_allowance(
    rate_limited_client: TestClient,
) -> None:
    assert ask(rate_limited_client, "a").status_code == 200
    assert ask(rate_limited_client, "a").status_code == 200

    response = ask(rate_limited_client, "a")

    assert_error_shape(response, 429, "RateLimitedError")
    assert response.headers["Retry-After"] == "60"


def test_the_refusal_names_the_wait_left_in_the_window(
    rate_limited_client: TestClient, clock: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "RATE_LIMIT_PER_CLIENT", 1)
    ask(rate_limited_client, "a")
    clock.now_ms += 30_000

    response = ask(rate_limited_client, "a")

    assert response.headers["Retry-After"] == "30"


def test_the_window_slides(
    rate_limited_client: TestClient, clock: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "RATE_LIMIT_PER_CLIENT", 1)
    ask(rate_limited_client, "a")
    clock.now_ms += 60_050

    assert ask(rate_limited_client, "a").status_code == 200


def test_ids_on_one_address_share_its_ceiling(rate_limited_client: TestClient) -> None:
    assert ask(rate_limited_client, "a", ip="203.0.113.9").status_code == 200
    assert ask(rate_limited_client, "b", ip="203.0.113.9").status_code == 200
    assert ask(rate_limited_client, "c", ip="203.0.113.9").status_code == 200

    assert ask(rate_limited_client, "d", ip="203.0.113.9").status_code == 429
    assert ask(rate_limited_client, "d", ip="203.0.113.10").status_code == 200


def test_a_refused_call_counts_against_neither_key(rate_limited_client: TestClient) -> None:
    """Client a is refused its third question. That refusal must not eat the address's
    allowance, or b would be turned away on an address that has only asked twice."""
    ask(rate_limited_client, "a")
    ask(rate_limited_client, "a")
    assert ask(rate_limited_client, "a").status_code == 429

    assert ask(rate_limited_client, "b").status_code == 200


def test_without_an_id_the_client_allowance_is_the_address(
    rate_limited_client: TestClient,
) -> None:
    assert ask(rate_limited_client, ip="203.0.113.9").status_code == 200
    assert ask(rate_limited_client, ip="203.0.113.9").status_code == 200

    assert ask(rate_limited_client, ip="203.0.113.9").status_code == 429
    assert ask(rate_limited_client, ip="203.0.113.10").status_code == 200


def test_an_id_naming_an_address_cannot_spend_its_allowance(
    rate_limited_client: TestClient,
) -> None:
    """The id-less allowance lives in its own namespace, or anyone could send a victim's
    address as their id and lock its curl users out."""
    assert ask(rate_limited_client, "203.0.113.9", ip="198.51.100.1").status_code == 200
    assert ask(rate_limited_client, "203.0.113.9", ip="198.51.100.1").status_code == 200

    assert ask(rate_limited_client, ip="203.0.113.9").status_code == 200


def test_an_oversized_id_is_rejected_rather_than_stored(rate_limited_client: TestClient) -> None:
    """A key carries the id verbatim, so its length is the one thing a caller could inflate."""
    response = ask(rate_limited_client, "x" * 65)

    assert response.status_code == 422
    assert ask(rate_limited_client, "x" * 64).status_code == 200


def test_off_it_refuses_nothing(
    rate_limited_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(config, "RATE_LIMIT_ENABLED", False)
    for _ in range(5):
        assert ask(rate_limited_client, "a").status_code == 200


def test_redis_down_lets_the_call_through(
    app: FastAPI, rate_limited_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """The spend cap is the backstop. A Redis blip must not take the product down, nor fill
    the log with a traceback per question."""
    app.dependency_overrides[get_redis] = unreachable_redis

    with caplog.at_level(logging.WARNING, logger=ratelimit.logger.name):
        response = ask(rate_limited_client, "a")

    assert response.status_code == 200
    [record] = [r for r in caplog.records if r.name == ratelimit.logger.name]
    assert record.levelno == logging.WARNING
    assert record.getMessage().startswith("rate limit check failed")
