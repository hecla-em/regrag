"""Tests for exception handlers: one JSON shape everywhere."""

import logging
from typing import Any

import pytest
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.testclient import TestClient
from httpx import Response
from pydantic import BaseModel, field_validator
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import NotFoundError, RateLimitedError, describe


class _Payload(BaseModel):
    name: str
    count: int

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("name must not be blank")
        return value


router = APIRouter()


@router.get("/boom-domain")
def boom_domain() -> None:
    raise NotFoundError("Regulation", "fueleu")


@router.get("/boom-rate-limited")
def boom_rate_limited() -> None:
    raise RateLimitedError(retry_after=7)


@router.get("/boom-http")
def boom_http() -> None:
    raise HTTPException(status_code=418, detail="teapot", headers={"X-Tea": "yes"})


@router.get("/boom-not-modified")
def boom_not_modified() -> None:
    raise HTTPException(status_code=304)


@router.get("/boom-dict-detail")
def boom_dict_detail() -> None:
    raise HTTPException(status_code=403, detail={"code": "quota_exceeded"})


@router.get("/boom-integrity")
def boom_integrity() -> None:
    raise IntegrityError("INSERT ...", {}, Exception("duplicate key value"))


@router.get("/boom-unhandled")
def boom_unhandled() -> None:
    raise RuntimeError("secret internal detail")


@router.post("/echo")
def echo(payload: _Payload) -> _Payload:
    return payload


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    app.include_router(router)
    return TestClient(app)


def assert_error_shape(response: Response, status_code: int, error: str) -> dict[str, Any]:
    """Assert the single error schema: {error, message, request_id} + optional detail."""
    assert response.status_code == status_code
    body = response.json()
    assert body["error"] == error
    assert isinstance(body["message"], str) and body["message"]
    assert body["request_id"] == response.headers["X-Request-ID"]
    assert set(body) <= {"error", "message", "request_id", "detail"}
    return body


def test_domain_error(client: TestClient) -> None:
    body = assert_error_shape(client.get("/boom-domain"), 404, "NotFoundError")
    assert body["message"] == "Regulation 'fueleu' not found"


def test_rate_limited_error_says_when_to_retry(client: TestClient) -> None:
    """A DomainError may carry headers, which the handler forwards like HTTPException's."""
    response = client.get("/boom-rate-limited")
    body = assert_error_shape(response, 429, "RateLimitedError")
    assert response.headers["Retry-After"] == "7"
    assert body["message"] == "Too many questions; try again in 7 seconds"


def test_http_exception_preserves_headers(client: TestClient) -> None:
    response = client.get("/boom-http")
    assert_error_shape(response, 418, "HTTPException")
    assert response.headers["X-Tea"] == "yes"


def test_integrity_error_hides_db_detail(client: TestClient) -> None:
    body = assert_error_shape(client.get("/boom-integrity"), 409, "IntegrityError")
    assert "duplicate key value" not in body["message"]


def test_unhandled_error_leaks_nothing(client: TestClient) -> None:
    response = client.get("/boom-unhandled")
    assert_error_shape(response, 500, "InternalServerError")
    assert "secret internal detail" not in response.text


def test_unhandled_error_is_access_logged(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """The exception handler sits inside the access log, so the 500 it returns is logged."""
    client.get("/boom-unhandled")
    [line] = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert "GET /boom-unhandled 500" in line


def test_http_exception_304_has_no_body(client: TestClient) -> None:
    response = client.get("/boom-not-modified")
    assert response.status_code == 304
    assert response.content == b""


def test_http_exception_structured_detail(client: TestClient) -> None:
    body = assert_error_shape(client.get("/boom-dict-detail"), 403, "HTTPException")
    assert body["message"] == "Forbidden"
    assert body["detail"] == [{"code": "quota_exceeded"}]


def test_validation_error_strips_input(client: TestClient) -> None:
    response = client.post("/echo", json={"name": "x", "count": "not-a-number"})
    body = assert_error_shape(response, 422, "ValidationError")
    assert body["detail"]
    assert all("input" not in item for item in body["detail"])


def test_validation_error_strips_ctx(client: TestClient) -> None:
    response = client.post("/echo", json={"name": "   ", "count": 1})
    body = assert_error_shape(response, 422, "ValidationError")
    assert body["detail"]
    assert all("ctx" not in item and "input" not in item for item in body["detail"])


def test_unknown_route_uses_shared_schema(client: TestClient) -> None:
    assert_error_shape(client.get("/nope"), 404, "HTTPException")


def test_describe_lets_a_domain_error_speak_for_itself() -> None:
    assert describe(NotFoundError("Regulation", "fueleu")) == (
        "NotFoundError",
        "Regulation 'fueleu' not found",
    )


def test_describe_keeps_anything_else_generic() -> None:
    assert describe(RuntimeError("secret internal detail")) == (
        "InternalServerError",
        "An unexpected error occurred",
    )
