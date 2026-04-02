from __future__ import annotations

import redis.asyncio as redis

from app.config import REDIS_URL

_redis: redis.Redis | None = None


async def get_redis() -> redis.Redis:
    """Lazy Redis connection (singleton) for the task-stream subsystem."""
    global _redis
    if _redis is not None:
        return _redis

    # decode_responses=True => we store/receive strings for JSON payloads.
    _redis = redis.from_url(REDIS_URL, decode_responses=True)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is None:
        return
    await _redis.close()
    _redis = None

