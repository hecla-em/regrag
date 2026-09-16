"""The one Redis client the process shares, and the dependency routes take it through."""

from typing import Annotated

from fastapi import Depends
from redis.asyncio import Redis

from app.core.config import config

redis_client: Redis = Redis.from_url(
    config.REDIS_URL,
    socket_connect_timeout=config.REDIS_TIMEOUT,
    socket_timeout=config.REDIS_TIMEOUT,
)


def get_redis() -> Redis:
    return redis_client


RedisDep = Annotated[Redis, Depends(get_redis)]
