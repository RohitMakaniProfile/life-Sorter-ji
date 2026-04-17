from __future__ import annotations

import json
from typing import Any


async def insert_log(
    conn,
    *,
    onboarding_id: str | None,
    model: str,
    input_payload: dict[str, Any],
    output: str,
    success: bool,
    error_msg: str | None,
    input_tokens: int,
    output_tokens: int,
    latency_ms: int,
) -> int:
    """Insert a website audit log entry. Returns the new row id."""
    try:
        input_json = json.dumps(input_payload, ensure_ascii=False, default=str)
    except Exception:
        input_json = "{}"

    row = await conn.fetchrow(
        """
        INSERT INTO website_audit_logs
            (onboarding_id, model, input_payload, output, success,
             error_msg, input_tokens, output_tokens, latency_ms)
        VALUES ($1, $2, $3::jsonb, $4, $5, $6, $7, $8, $9)
        RETURNING id
        """,
        onboarding_id or None,
        str(model or ""),
        input_json,
        str(output or ""),
        bool(success),
        str(error_msg or "") or None,
        int(input_tokens or 0),
        int(output_tokens or 0),
        int(latency_ms or 0),
    )
    return int(row["id"])


async def list_logs(
    conn,
    *,
    onboarding_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Return audit logs newest-first. Optionally filtered by onboarding_id."""
    if onboarding_id:
        rows = await conn.fetch(
            """
            SELECT id, onboarding_id, model, success, error_msg,
                   input_tokens, output_tokens, latency_ms, created_at
            FROM website_audit_logs
            WHERE onboarding_id = $1
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
            """,
            onboarding_id,
            limit,
            offset,
        )
    else:
        rows = await conn.fetch(
            """
            SELECT id, onboarding_id, model, success, error_msg,
                   input_tokens, output_tokens, latency_ms, created_at
            FROM website_audit_logs
            ORDER BY created_at DESC
            LIMIT $1 OFFSET $2
            """,
            limit,
            offset,
        )
    return [dict(r) for r in rows]


async def get_by_id(conn, log_id: int) -> dict[str, Any] | None:
    """Return a single log row including full input_payload and output."""
    row = await conn.fetchrow(
        """
        SELECT id, onboarding_id, model, input_payload, output, success,
               error_msg, input_tokens, output_tokens, latency_ms, created_at
        FROM website_audit_logs
        WHERE id = $1
        """,
        int(log_id),
    )
    if not row:
        return None
    d = dict(row)
    # input_payload comes back as a dict from asyncpg JSONB
    if isinstance(d.get("input_payload"), str):
        try:
            d["input_payload"] = json.loads(d["input_payload"])
        except Exception:
            pass
    return d


async def count_logs(conn, *, onboarding_id: str | None = None) -> int:
    if onboarding_id:
        row = await conn.fetchrow(
            "SELECT COUNT(*) AS n FROM website_audit_logs WHERE onboarding_id = $1",
            onboarding_id,
        )
    else:
        row = await conn.fetchrow("SELECT COUNT(*) AS n FROM website_audit_logs")
    return int(row["n"])