"""Health endpoint and its response model."""

import asyncio
from collections.abc import Awaitable
from enum import StrEnum
from typing import Any

from fastapi import APIRouter
from pydantic import computed_field
from sqlalchemy import text

from app import __version__
from app.core.db.session import SessionDep
from app.core.models import AppModel
from app.core.redis import RedisDep


class ServiceStatus(StrEnum):
    OK = "ok"
    ERROR = "error"


class HealthStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"


class HealthResponse(AppModel):
    version: str = __version__
    database: ServiceStatus
    redis: ServiceStatus

    @computed_field
    @property
    def status(self) -> HealthStatus:
        """Overall status: ok only while every ServiceStatus field reports ok."""
        services = (
            getattr(self, name)
            for name, field in type(self).model_fields.items()
            if field.annotation is ServiceStatus
        )
        if all(service is ServiceStatus.OK for service in services):
            return HealthStatus.OK
        return HealthStatus.DEGRADED


router = APIRouter(tags=["health"])


async def probe_service(ping: Awaitable[Any]) -> ServiceStatus:
    """OK if the ping returns, ERROR whatever way it fails."""
    try:
        await ping
        return ServiceStatus.OK
    except Exception:
        return ServiceStatus.ERROR


@router.get("/health")
async def get_health(db: SessionDep, redis: RedisDep) -> HealthResponse:
    database, redis_status = await asyncio.gather(
        probe_service(db.execute(text("SELECT 1"))),
        probe_service(redis.ping()),
    )
    return HealthResponse(database=database, redis=redis_status)
