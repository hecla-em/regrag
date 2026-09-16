"""Health endpoint and its response model."""

from enum import StrEnum

from fastapi import APIRouter
from pydantic import computed_field
from sqlalchemy import text

from app import __version__
from app.core.db.session import SessionDep
from app.core.models import AppModel
from app.core.redis import redis_client


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


@router.get("/health")
async def get_health(db: SessionDep) -> HealthResponse:
    try:
        await db.execute(text("SELECT 1"))
        database = ServiceStatus.OK
    except Exception:
        database = ServiceStatus.ERROR
    try:
        await redis_client.ping()
        redis = ServiceStatus.OK
    except Exception:
        redis = ServiceStatus.ERROR
    return HealthResponse(database=database, redis=redis)
