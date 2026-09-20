"""FastAPI application entrypoint."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import __version__
from app.chat.router import router as chat_router
from app.core.config import config
from app.core.db.session import async_engine
from app.core.exceptions import register_exception_handlers
from app.core.health import router as health_router
from app.core.logger import setup_logging
from app.core.middleware import register_middleware
from app.core.redis import redis_client
from app.core.sentry import configure_sentry

setup_logging()
configure_sentry()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifecycle - teardown of shared resources."""
    try:
        yield
    finally:
        await async_engine.dispose()
        await redis_client.aclose()


def configure_app(app: FastAPI) -> None:
    """Wire the app identically for production and tests."""
    register_exception_handlers(app)
    register_middleware(app)
    app.include_router(health_router)
    app.include_router(chat_router)


app = FastAPI(title=config.PROJECT_NAME, version=__version__, lifespan=lifespan)
configure_app(app)
