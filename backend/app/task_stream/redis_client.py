from __future__ import annotations

import redis.asyncio as redis
from redis.asyncio.cluster import RedisCluster

from app.config import REDIS_URL, is_redis_configured

_redis: redis.Redis | RedisCluster | None = None


async def get_redis() -> redis.Redis | RedisCluster | None:
    """Lazy Redis connection (singleton). Returns None when REDIS_URL is unset or empty."""
    global _redis
    if not is_redis_configured():
        return None
    if _redis is not None:
        return _redis

    url = REDIS_URL.strip()
    # decode_responses=True => we store/receive strings for JSON payloads.
    try:
        client = RedisCluster.from_url(url, decode_responses=True)
        await client.initialize()
        _redis = client
    except Exception:
        _redis = redis.from_url(url, decode_responses=True)
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is None:
        return
    await _redis.aclose()
    _redis = None

