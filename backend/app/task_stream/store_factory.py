from __future__ import annotations

from app.config import get_settings
from app.task_stream.postgres_store import PostgresTaskStreamStore
from app.task_stream.redis_service import RedisTaskStreamStore

_store: RedisTaskStreamStore | PostgresTaskStreamStore | None = None


def get_task_stream_store() -> RedisTaskStreamStore | PostgresTaskStreamStore:
    """
    Singleton store for task-stream SSE (resume / multi-worker).

    Env: TASKSTREAM_BACKEND=redis | postgres
    Postgres requires migration 014_task_stream_postgres.sql applied.
    """
    global _store
    if _store is None:
        backend = (get_settings().TASKSTREAM_BACKEND or "redis").strip().lower()
        if backend in ("postgres", "postgresql", "pg"):
            _store = PostgresTaskStreamStore()
        else:
            _store = RedisTaskStreamStore()
    return _store


def reset_task_stream_store_for_tests() -> None:
    global _store
    _store = None
