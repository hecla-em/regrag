"""FastAPI application entrypoint."""

import asyncio
import socket
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app import __version__
from app.analytics.router import router as analytics_router
from app.chat.router import router as chat_router
from app.core.config import config
from app.core.db.session import async_engine
from app.core.exceptions import register_exception_handlers
from app.core.health import router as health_router
from app.core.logger import setup_logging
from app.core.middleware import register_middleware
from app.core.redis import redis_client
from app.core.sentry import configure_sentry
from app.core.turnstile import turnstile_client

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
        await turnstile_client.aclose()


def configure_app(app: FastAPI) -> None:
    """Wire the app identically for production and tests."""
    register_exception_handlers(app)
    register_middleware(app)
    app.include_router(health_router)
    app.include_router(chat_router)
    app.include_router(analytics_router)


app = FastAPI(title=config.PROJECT_NAME, version=__version__, lifespan=lifespan)
configure_app(app)


def bind_socket(host: str, port: int) -> socket.socket:
    """Bind host:port, resolving the host first as fly-local-6pn names an IPv6 address."""
    family, _, _, _, address = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)[0]
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(address)
    return sock


def run_server() -> None:
    """Serve the app on the public port and on the private-network port, in one process."""
    server = uvicorn.Server(uvicorn.Config(app))
    sockets = [
        bind_socket("0.0.0.0", config.PUBLIC_PORT),
        bind_socket(config.PRIVATE_HOST, config.PRIVATE_PORT),
    ]
    asyncio.run(server.serve(sockets=sockets))
