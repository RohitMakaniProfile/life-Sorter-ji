from __future__ import annotations

import asyncpg
from asyncpg.pool import Pool

from app.config import DATABASE_URL

_pool: Pool | None = None


async def connect_db() -> None:
    global _pool
    if _pool is not None:
        return
    print(f"[DB] Connecting with DATABASE_URL: {DATABASE_URL}")
    _pool = await asyncpg.create_pool(dsn=DATABASE_URL, min_size=1, max_size=10)
    print(f"[DB] Pool initialized: {_pool}")


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

