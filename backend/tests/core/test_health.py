from collections.abc import AsyncGenerator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db.session import get_db


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": "0.1.0",
        "database": "ok",
        "redis": "ok",
    }


def test_health_survives_being_asked_again(client: TestClient) -> None:
    """Each request here runs on its own event loop; the Redis check must not keep a
    connection the next loop cannot use."""
    for _ in range(3):
        assert client.get("/health").json()["redis"] == "ok"


def test_health_degraded_when_redis_unreachable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    unreachable = Redis.from_url("redis://localhost:9/0", socket_connect_timeout=0.2)
    monkeypatch.setattr("app.core.health.redis_client", unreachable)
    body = client.get("/health").json()
    assert body["status"] == "degraded"
    assert body["redis"] == "error"
    assert body["database"] == "ok"


def test_health_degraded_when_db_unreachable(app: FastAPI, client: TestClient) -> None:
    bad_engine = create_async_engine("postgresql+psycopg://postgres:postgres@localhost:9/regrag")
    bad_factory = async_sessionmaker(bind=bad_engine, class_=AsyncSession)

    async def bad_db() -> AsyncGenerator[AsyncSession, None]:
        async with bad_factory() as session:
            yield session

    app.dependency_overrides[get_db] = bad_db
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "degraded"
    assert body["database"] == "error"
