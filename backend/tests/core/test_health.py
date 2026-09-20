import logging
from collections.abc import AsyncGenerator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.db.session import get_db
from app.core.redis import get_redis
from tests.conftest import unreachable_redis


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": "0.1.0",
        "database": "ok",
        "redis": "ok",
    }


def test_health_degraded_when_redis_unreachable(app: FastAPI, client: TestClient) -> None:
    app.dependency_overrides[get_redis] = unreachable_redis
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


def test_degraded_health_is_logged(
    app: FastAPI, client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """The access log skips /health, so the warning is the only sign a check went bad."""
    app.dependency_overrides[get_redis] = unreachable_redis
    with caplog.at_level(logging.WARNING, logger="app.core.health"):
        client.get("/health")
    [record] = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert "redis" in record.getMessage()


def test_healthy_check_logs_nothing(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING, logger="app.core.health"):
        client.get("/health")
    assert caplog.records == []
