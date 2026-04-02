"""
Persist Phase 1 onboarding selections in `onboarding` (linked to user_sessions).
"""

from __future__ import annotations

from typing import Any, Optional

import structlog

from app.db import get_pool
from app.services import session_store, user_session_service
from app.utils.url_sanitize import sanitize_http_url

logger = structlog.get_logger()

ALLOWED_PATCH_FIELDS = frozenset(
    {"user_id", "outcome", "domain", "task", "website_url", "gbp_url"}
)


def _sanitize_onboarding_url_fields(d: dict[str, Any]) -> dict[str, Any]:
    out = dict(d)
    for key in ("website_url", "gbp_url"):
        if key not in out:
            continue
        val = out[key]
        if isinstance(val, str):
            out[key] = sanitize_http_url(val)
    return out


def _allowed_updates(updates: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not updates:
        return {}
    raw = {k: v for k, v in updates.items() if k in ALLOWED_PATCH_FIELDS}
    return _sanitize_onboarding_url_fields(raw)


def _serialize_row(row: Any) -> dict[str, Any]:
    if not row:
        return {}
    d = dict(row)
    for k, v in list(d.items()):
        if hasattr(v, "hex"):  # UUID
            d[k] = str(v)
        elif k in ("created_at", "updated_at") and v is not None:
            d[k] = v.isoformat() if hasattr(v, "isoformat") else str(v)
    return d


async def create_session_with_onboarding(initial: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """
    New agent session (in-memory + user_sessions) plus one onboarding row.
    Optional `initial` may include user_id, outcome, domain, task, website_url, gbp_url (same as patch).
    """
    allowed = _allowed_updates(initial)
    session = session_store.create_session()
    await user_session_service.upsert_session(session)
    sid = session.session_id

    pool = get_pool()
    async with pool.acquire() as conn:
        if not allowed:
            row = await conn.fetchrow(
                """
                INSERT INTO onboarding (session_id)
                VALUES ($1)
                RETURNING id, session_id, user_id, outcome, domain, task,
                          website_url, gbp_url, created_at, updated_at
                """,
                sid,
            )
        else:
            cols = ["session_id"] + list(allowed.keys())
            vals: list[Any] = [sid] + list(allowed.values())
            placeholders = ", ".join(f"${i + 1}" for i in range(len(vals)))
            col_sql = ", ".join(cols)
            row = await conn.fetchrow(
                f"""
                INSERT INTO onboarding ({col_sql})
                VALUES ({placeholders})
                RETURNING id, session_id, user_id, outcome, domain, task,
                          website_url, gbp_url, created_at, updated_at
                """,
                *vals,
            )

    out = _serialize_row(row)
    out["session_id"] = sid
    logger.info(
        "onboarding row created",
        session_id=sid,
        onboarding_id=out.get("id"),
        initial_fields=list(allowed.keys()) if allowed else [],
    )
    return out


async def upsert_onboarding_patch(session_id: str, updates: dict[str, Any]) -> dict[str, Any]:
    """
    Ensure user_sessions exists, then insert onboarding row if missing else patch allowed columns.
    """
    sid = (session_id or "").strip()
    if not sid:
        raise ValueError("session_id is required for patch")

    allowed = _allowed_updates(updates)

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """
                INSERT INTO user_sessions (session_id)
                VALUES ($1)
                ON CONFLICT (session_id) DO NOTHING
                """,
                sid,
            )

            row_id: Optional[Any] = await conn.fetchval(
                """
                SELECT id FROM onboarding
                WHERE session_id = $1
                ORDER BY created_at DESC
                LIMIT 1
                """,
                sid,
            )

            if row_id is None:
                if not allowed:
                    row = await conn.fetchrow(
                        """
                        INSERT INTO onboarding (session_id)
                        VALUES ($1)
                        RETURNING id, session_id, user_id, outcome, domain, task,
                                  website_url, gbp_url, created_at, updated_at
                        """,
                        sid,
                    )
                else:
                    cols = ["session_id"] + list(allowed.keys())
                    vals = [sid] + list(allowed.values())
                    placeholders = ", ".join(f"${i + 1}" for i in range(len(vals)))
                    col_sql = ", ".join(cols)
                    row = await conn.fetchrow(
                        f"""
                        INSERT INTO onboarding ({col_sql})
                        VALUES ({placeholders})
                        RETURNING id, session_id, user_id, outcome, domain, task,
                                  website_url, gbp_url, created_at, updated_at
                        """,
                        *vals,
                    )
            elif allowed:
                set_parts: list[str] = []
                vals_u: list[Any] = []
                for i, (k, v) in enumerate(allowed.items(), start=1):
                    set_parts.append(f"{k} = ${i}")
                    vals_u.append(v)
                vals_u.append(row_id)
                set_sql = ", ".join(set_parts)
                row = await conn.fetchrow(
                    f"""
                    UPDATE onboarding
                    SET {set_sql}, updated_at = NOW()
                    WHERE id = ${len(vals_u)}
                    RETURNING id, session_id, user_id, outcome, domain, task,
                              website_url, gbp_url, created_at, updated_at
                    """,
                    *vals_u,
                )
            else:
                row = await conn.fetchrow(
                    """
                    SELECT id, session_id, user_id, outcome, domain, task,
                           website_url, gbp_url, created_at, updated_at
                    FROM onboarding
                    WHERE id = $1
                    """,
                    row_id,
                )

    out = _serialize_row(row)
    logger.debug("onboarding patched", session_id=sid, fields=list(allowed.keys()))
    return out
