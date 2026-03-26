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
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS token_usage (
                id BIGSERIAL PRIMARY KEY,
                message_id TEXT NOT NULL,
                model TEXT NOT NULL DEFAULT '',
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_token_usage_message_id ON token_usage (message_id)"
        )

        # ── Insight feedback (per output message, per insight index, per user) ──
        # Stored separately so agents can learn from usefulness votes over time.
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS insight_feedback (
                id BIGSERIAL PRIMARY KEY,
                conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                message_id TEXT NOT NULL,
                insight_index INTEGER NOT NULL,
                user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                rating SMALLINT NOT NULL, -- 1 = thumbs up, -1 = thumbs down
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (user_id, message_id, insight_index)
            )
            """
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_insight_feedback_message_id ON insight_feedback (message_id)"
        )
        await conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_insight_feedback_conversation_id ON insight_feedback (conversation_id)"
        )

        # ── Phase2 multi-user support (agents + conversations ownership/visibility) ──
        # These ALTERs are safe to run multiple times.
        for sql in (
            # agents visibility + locking
            "ALTER TABLE agents ADD COLUMN IF NOT EXISTS created_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL",
            "ALTER TABLE agents ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'private'",
            "ALTER TABLE agents ADD COLUMN IF NOT EXISTS is_locked BOOLEAN NOT NULL DEFAULT FALSE",
            # conversations ownership
            "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS user_id UUID REFERENCES users(id) ON DELETE CASCADE",
            "CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations (user_id)",
        ):
            try:
                await conn.execute(sql)
            except Exception:
                # If schema isn't present yet (or users table missing), don't crash startup.
                # Phase2 will fail later on endpoints that rely on these columns if needed.
                pass


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
