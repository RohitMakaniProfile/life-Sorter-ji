from __future__ import annotations

import asyncpg
from asyncpg.pool import Pool

from app.config import get_settings

_pool: Pool | None = None


def _get_database_url() -> str:
    settings = get_settings()
    url = getattr(settings, "DATABASE_URL", "") or ""
    return str(url).strip()


async def connect_db() -> None:
    global _pool
    if _pool is not None:
        return
    dsn = _get_database_url()
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set")
    _pool = await asyncpg.create_pool(dsn=dsn, min_size=1, max_size=10)
    async with _pool.acquire() as conn:
        await conn.execute("SELECT 1")


async def close_db() -> None:
    global _pool
    if _pool is None:
        return
    await _pool.close()
    _pool = None


def get_pool() -> Pool:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")
    return _pool

