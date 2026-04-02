from __future__ import annotations

import structlog

from app.config import get_settings, is_redis_configured
from app.task_stream.postgres_store import PostgresTaskStreamStore
from app.task_stream.redis_service import RedisTaskStreamStore

_store: RedisTaskStreamStore | PostgresTaskStreamStore | None = None

logger = structlog.get_logger()


def get_task_stream_store() -> RedisTaskStreamStore | PostgresTaskStreamStore:
    """
    Singleton store for task-stream SSE (resume / multi-worker).

    Env: TASKSTREAM_BACKEND=redis | postgres
    If backend requests redis but REDIS_URL is not set, falls back to postgres.
    Postgres requires migration 014_task_stream_postgres.sql applied.
    """
    global _store
    if _store is None:
        backend = (get_settings().TASKSTREAM_BACKEND or "postgres").strip().lower()
        wants_redis = backend in ("redis", "rediss")
        if wants_redis and not is_redis_configured():
            logger.warning(
                "taskstream_backend_redis_without_url",
                message="TASKSTREAM_BACKEND=redis but REDIS_URL is empty; using postgres store",
            )
            wants_redis = False
        if wants_redis:
            _store = RedisTaskStreamStore()
        else:
            _store = PostgresTaskStreamStore()
    return _store


def reset_task_stream_store_for_tests() -> None:
    global _store
    _store = None
