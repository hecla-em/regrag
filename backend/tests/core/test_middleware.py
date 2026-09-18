"""Tests for the request middleware: request IDs, access log, gzip."""

import logging
import uuid
from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from app.core import middleware
from app.core.config import Environment, config


def access_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    """The access-log records the request middleware emitted, with their extras."""
    return [r for r in caplog.records if r.name == middleware.logger.name]


def test_every_response_carries_request_id(client: TestClient) -> None:
    response = client.get("/health")
    uuid.UUID(hex=response.headers["X-Request-ID"])


def test_requests_get_distinct_ids(client: TestClient) -> None:
    r1 = client.get("/health")
    r2 = client.get("/health")
    assert r1.headers["X-Request-ID"] != r2.headers["X-Request-ID"]


def test_incoming_request_id_is_ignored(client: TestClient) -> None:
    incoming = "attacker-chosen-value"
    response = client.get("/health", headers={"X-Request-ID": incoming})
    assert response.headers["X-Request-ID"] != incoming


def test_access_log_line(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    client.get("/health")
    [record] = access_records(caplog)
    assert "GET /health 200" in record.getMessage()


def test_access_log_records_the_connecting_address(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    client.get("/health")
    [record] = access_records(caplog)
    assert record.__dict__["client_ip"] == "testclient"


def test_access_log_prefers_the_address_fly_forwards_in_prod(
    client: TestClient, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Behind Fly's proxy the connecting address is the proxy. The header names the client."""
    monkeypatch.setattr(config, "ENVIRONMENT", Environment.PROD)
    client.get("/health", headers={"Fly-Client-IP": "203.0.113.9"})
    [record] = access_records(caplog)
    assert record.__dict__["client_ip"] == "203.0.113.9"


def test_access_log_ignores_the_fly_header_off_fly(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """Off Fly nothing strips the header, so a caller could name any address."""
    client.get("/health", headers={"Fly-Client-IP": "203.0.113.9"})
    [record] = access_records(caplog)
    assert record.__dict__["client_ip"] == "testclient"


def test_access_log_skips_cors_preflight(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    response = client.options(
        "/health",
        headers={
            "Origin": config.FRONTEND_URL,
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert access_records(caplog) == []


def test_access_log_waits_for_a_streamed_body(
    app: FastAPI, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stream's work happens after its headers, so the line is written when the body ends."""
    order: list[str] = []
    monkeypatch.setattr(
        middleware.logger, "info", lambda msg, *args, **kwargs: order.append(msg % args)
    )

    def body() -> Iterator[bytes]:
        order.append("first chunk")
        yield b"chunk"
        order.append("last chunk")

    @app.get("/stream")
    def stream() -> StreamingResponse:
        return StreamingResponse(body(), media_type="text/plain")

    client.get("/stream")

    assert order[:2] == ["first chunk", "last chunk"]
    assert order[2].startswith("GET /stream 200")


def test_gzip_compresses_large_responses(app: FastAPI, client: TestClient) -> None:
    @app.get("/big")
    def big() -> dict[str, str]:
        return {"payload": "x" * 5000}

    response = client.get("/big", headers={"Accept-Encoding": "gzip"})
    assert response.headers["Content-Encoding"] == "gzip"
    assert response.json()["payload"] == "x" * 5000
