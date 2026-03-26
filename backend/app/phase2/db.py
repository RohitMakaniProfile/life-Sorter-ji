from __future__ import annotations

import asyncpg
from asyncpg.pool import Pool

from .config import DATABASE_URL

_pool: Pool | None = None


async def connect_db() -> None:
    global _pool
    if _pool is not None:
        return
    _pool = await asyncpg.create_pool(dsn=DATABASE_URL, min_size=1, max_size=10)
    async with _pool.acquire() as conn:
        await conn.execute("SELECT 1")

        # NOTE: Schema is created/managed by `backend/migrations/cloud_sql_full_setup.sql`.
        # Keep only minimal runtime safety adjustments here.

        # Keep plan_runs status constraint aligned with runtime values.
        # Older DBs only allow ('draft','approved','running','done','error'),
        # while current flow also uses 'executing' and 'cancelled'.
        await conn.execute(
            """
            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'plan_runs_status_check'
              ) THEN
                ALTER TABLE plan_runs DROP CONSTRAINT plan_runs_status_check;
              END IF;
              ALTER TABLE plan_runs
                ADD CONSTRAINT plan_runs_status_check
                CHECK (status IN ('draft', 'approved', 'running', 'executing', 'done', 'error', 'cancelled'));
            EXCEPTION
              WHEN undefined_table THEN
                NULL;
              WHEN duplicate_object THEN
                NULL;
            END
            $$;
            """
        )


async def close_db() -> None:
    global _pool
    if _pool is None:
        return
    await _pool.close()
    _pool = None


def get_pool() -> Pool:
    if _pool is None:
        raise RuntimeError("Phase2 database pool is not initialized")
    return _pool
