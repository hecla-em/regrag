"""Sliding-window rate limits counted in Redis, checked as a route dependency."""

import logging
import math
import time
from typing import Annotated
from uuid import uuid4

from fastapi import Header, Request
from redis.exceptions import RedisError

from app.core.config import config
from app.core.exceptions import RateLimitedError
from app.core.middleware import client_ip
from app.core.redis import redis_client

logger = logging.getLogger(__name__)

TAKE_SLOT = """
local window = tonumber(ARGV[1])
local now = tonumber(ARGV[2])
local wait = 0
for i, key in ipairs(KEYS) do
    redis.call('ZREMRANGEBYSCORE', key, 0, now - window)
    if redis.call('ZCARD', key) >= tonumber(ARGV[3 + i]) then
        local oldest = redis.call('ZRANGE', key, 0, 0, 'WITHSCORES')
        wait = math.max(wait, tonumber(oldest[2]) + window - now)
    end
end
if wait > 0 then
    return wait
end
for _, key in ipairs(KEYS) do
    redis.call('ZADD', key, now, ARGV[3])
    redis.call('PEXPIRE', key, window)
end
return 0
"""
take_slot = redis_client.register_script(TAKE_SLOT)
"""One sorted set per key, scored by the millisecond each call landed. Every key is
checked before any is written, so a refused call counts against none of them, and the
reply is the longest wait among the keys that refused, or zero."""


async def rate_limit(request: Request, x_client_id: Annotated[str | None, Header()] = None) -> None:
    """Refuse the call once its client id, or its address across ids, has used the window's
    allowance. A call without an id counts its client allowance against the address. Redis
    unreachable lets the call through: the spend cap is the backstop."""
    if not config.RATE_LIMIT_ENABLED:
        return
    ip = client_ip(request) or "unknown"
    keys = [f"ratelimit:client:{x_client_id or ip}", f"ratelimit:ip:{ip}"]
    args = [
        config.RATE_LIMIT_WINDOW_SECONDS * 1000,
        int(time.time() * 1000),
        uuid4().hex,
        config.RATE_LIMIT_PER_CLIENT,
        config.RATE_LIMIT_PER_IP,
    ]
    try:
        wait_ms = await take_slot(keys, args, client=redis_client)
    except RedisError:
        logger.exception("rate limit check failed; letting the call through")
        return
    if wait_ms:
        raise RateLimitedError(retry_after=math.ceil(wait_ms / 1000))
