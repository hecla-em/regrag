"""Tests for exception handlers: one JSON shape everywhere."""

import logging

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, field_validator
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import NotFoundError
from app.core.storage import StorageError
from tests.conftest import assert_error_shape


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


@router.get("/boom-storage")
def boom_storage() -> None:
    raise StorageError("read", "raw/32023R1805.html")


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


@pytest.mark.parametrize(
    ("path", "status_code", "error", "message", "hidden"),
    [
        pytest.param(
            "/boom-domain", 404, "NotFoundError", "Regulation 'fueleu' not found", None, id="domain"
        ),
        pytest.param(
            "/boom-integrity", 409, "IntegrityError", None, "duplicate key value", id="integrity"
        ),
        pytest.param(
            "/boom-unhandled", 500, "InternalServerError", None, "secret internal", id="unhandled"
        ),
        pytest.param("/nope", 404, "HTTPException", None, None, id="unknown route"),
    ],
)
def test_every_error_leaves_in_one_shape_and_leaks_nothing(
    client: TestClient, path: str, status_code: int, error: str, message: str | None, hidden: str
) -> None:
    response = client.get(path)

    body = assert_error_shape(response, status_code, error)
    assert message is None or body["message"] == message
    assert hidden is None or hidden not in response.text


def test_a_domain_error_is_logged_at_the_level_it_names(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """The caller's mistake is a warning. A fault on our side is an error, which Sentry sends."""
    client.get("/boom-domain")
    client.get("/boom-storage")

    lines = [r for r in caplog.records if " on GET " in r.getMessage()]
    levels = {line.getMessage().split(" ")[0]: line.levelno for line in lines}
    assert levels == {"NotFoundError": logging.WARNING, "StorageError": logging.ERROR}


def test_unhandled_error_is_access_logged(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """The exception handler sits inside the access log, so the 500 it returns is logged."""
    client.get("/boom-unhandled")
    [line] = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert "GET /boom-unhandled 500" in line


def test_validation_error_strips_ctx(client: TestClient) -> None:
    response = client.post("/echo", json={"name": "   ", "count": 1})
    body = assert_error_shape(response, 422, "ValidationError")
    assert body["detail"]
    assert all("ctx" not in item and "input" not in item for item in body["detail"])
