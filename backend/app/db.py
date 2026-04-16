from __future__ import annotations

import asyncpg
from asyncpg.pool import Pool

from app.config import DATABASE_URL

_pool: Pool | None = None


async def connect_db() -> None:
    global _pool
    if _pool is not None:
        return
    print("[DB] Connecting to PostgreSQL…")
    try:
        # Fail fast if Postgres is down (avoids hanging startup → browser ERR_CONNECTION_TIMED_OUT on :8000).
        _pool = await asyncpg.create_pool(
            dsn=DATABASE_URL,
            min_size=1,
            max_size=10,
            timeout=30,
            command_timeout=60,
        )
    except Exception as e:
        raise RuntimeError(
            "PostgreSQL connection failed. Start Postgres locally and set DATABASE_URL in backend/.env "
            "(copy from .env.example). Default without env is postgresql://localhost:5432/ikshan — "
            "database must exist and user must have access. "
            f"Underlying error: {e}",
        ) from e
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

