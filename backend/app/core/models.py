"""Shared Pydantic models."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AppModel(BaseModel):
    """Base for every model: builds from ORM rows and Row objects as well as dicts."""

    model_config = ConfigDict(from_attributes=True)


class FrozenModel(AppModel):
    """Base for immutable, hashable domain values."""

    model_config = ConfigDict(frozen=True)


def _is_none(value: object) -> bool:
    return value is None


class ErrorResponse(FrozenModel):
    """The single JSON shape every error response uses, however it is serialized:
    the optional fields are left out rather than sent as null."""

    error: str
    message: str
    request_id: str | None = Field(default=None, exclude_if=_is_none)
    detail: list[Any] | None = Field(default=None, exclude_if=_is_none)
