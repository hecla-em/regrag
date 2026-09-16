"""Tests for application lifespan."""

from fastapi.testclient import TestClient

from app.main import app


def test_lifespan_disposes_engine(monkeypatch) -> None:
    calls: list[bool] = []

    class FakeEngine:
        async def dispose(self) -> None:
            calls.append(True)

    monkeypatch.setattr("app.main.async_engine", FakeEngine())
    with TestClient(app):
        pass
    assert calls == [True]


def test_lifespan_closes_the_redis_client(monkeypatch) -> None:
    calls: list[bool] = []

    class FakeRedis:
        async def aclose(self) -> None:
            calls.append(True)

    monkeypatch.setattr("app.main.redis_client", FakeRedis())
    with TestClient(app):
        pass
    assert calls == [True]
