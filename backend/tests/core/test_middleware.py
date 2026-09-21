"""Tests for the request middleware: request IDs, access log, gzip."""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from app.core import middleware


@pytest.fixture
def logged_path(app: FastAPI) -> str:
    """A route the access log does not skip, for the tests about the line itself."""

    @app.get("/probe")
    def probe() -> dict[str, str]:
        return {"status": "ok"}

    return "/probe"


def test_incoming_request_id_is_ignored(client: TestClient) -> None:
    incoming = "attacker-chosen-value"
    response = client.get("/health", headers={"X-Request-ID": incoming})
    assert response.headers["X-Request-ID"] != incoming


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
