from __future__ import annotations

import json
from typing import Any


async def insert_log(
    conn,
    *,
    onboarding_id: str | None,
    user_id: str | None = None,
    level: str,         # 'info' | 'warn' | 'error'
    source: str,        # 'crawl_task' | 'scraper' | 'summarizer' | etc.
    message: str,
    raw: Any = None,
) -> None:
    """Insert a single crawl log entry."""
    raw_json: str | None = None
    if raw is not None:
        try:
            raw_json = json.dumps(raw, ensure_ascii=False, default=str)
        except Exception:
            raw_json = json.dumps({"raw": str(raw)})

    await conn.execute(
        "INSERT INTO crawl_logs (onboarding_id, user_id, level, source, message, raw) "
        "VALUES ($1, $2, $3, $4, $5, $6::jsonb)",
        onboarding_id or None,
        user_id or None,
        str(level or "info")[:20],
        str(source or "crawl")[:100],
        str(message or ""),
        raw_json,
    )


async def fetch_by_onboarding_id(conn, onboarding_id: str) -> list[Any]:
    """Return all crawl logs for an onboarding, newest first."""
    rows = await conn.fetch(
        "SELECT id, onboarding_id, user_id, level, source, message, raw, created_at "
        "FROM crawl_logs "
        "WHERE onboarding_id = $1 "
        "ORDER BY created_at ASC",
        onboarding_id,
    )
    return list(rows)


def extract_error_message(exc: Any) -> str:
    """
    Extract a clean, human-readable error string from any exception or error value.
    Handles: Exception, str, dict with 'message'/'error'/'detail', nested objects.
    """
    if exc is None:
        return "Unknown error"
    if isinstance(exc, str):
        return exc.strip() or "Unknown error"
    if isinstance(exc, BaseException):
        msg = str(exc).strip()
        return msg or type(exc).__name__
    if isinstance(exc, dict):
        for key in ("message", "error", "detail", "reason", "msg", "description"):
            val = exc.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        # Last resort: serialize
        try:
            s = json.dumps(exc, default=str)
            return s[:500] + ("…" if len(s) > 500 else "")
        except Exception:
            return str(exc)[:500]
    return str(exc)[:500] or "Unknown error"