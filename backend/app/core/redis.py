"""The one Redis client the process shares."""

from redis.asyncio import Redis

from app.core.config import config

redis_client: Redis = Redis.from_url(
    config.REDIS_URL,
    socket_connect_timeout=config.REDIS_TIMEOUT,
    socket_timeout=config.REDIS_TIMEOUT,
)
