"""Tests for application lifespan."""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.mark.parametrize(
    ("target", "method"),
    [("app.main.async_engine", "dispose"), ("app.main.redis_client", "aclose")],
)
def test_lifespan_closes_its_clients(monkeypatch, target: str, method: str) -> None:
    calls: list[str] = []

    async def record() -> None:
        calls.append(method)

    monkeypatch.setattr(target, SimpleNamespace(**{method: record}))
    with TestClient(app):
        pass
    assert calls == [method]
