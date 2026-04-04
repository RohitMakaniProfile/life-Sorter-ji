"""
Persist Phase 1 onboarding selections in `onboarding` (canonical session_id row).
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

import json
import structlog

from app.db import get_pool
from app.utils.url_sanitize import sanitize_http_url

logger = structlog.get_logger()

ALLOWED_PATCH_FIELDS = frozenset(
    {
        "user_id",
        "outcome",
        "domain",
        "task",
        "website_url",
        "gbp_url",
        "scale_answers",
    }
)

# Backend-managed fields (should not be patched via onboarding upsert).
# These are updated by RCA/playbook/crawl subsystems directly.
BACKEND_MANAGED_FIELDS = frozenset(
    {"questions_answers", "crawl_cache_key", "crawl_run_id", "onboarding_completed_at"}
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


def _coerce_onboarding_jsonb_fields(d: dict[str, Any]) -> dict[str, Any]:
    """
    asyncpg JSONB binding expects a JSON string unless a custom codec is configured.
    Normalize JSONB payloads into strings for safe INSERT/UPDATE placeholders.
    """
    out = dict(d)
    if "scale_answers" in out:
        v = out.get("scale_answers")
        if isinstance(v, (dict, list)):
            out["scale_answers"] = json.dumps(v)
    return out


def _allowed_updates(updates: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not updates:
        return {}
    raw = {k: v for k, v in updates.items() if k in ALLOWED_PATCH_FIELDS}
    return _coerce_onboarding_jsonb_fields(_sanitize_onboarding_url_fields(raw))


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
    Create a new onboarding session_id plus one onboarding row.
    Optional `initial` may include user_id, outcome, domain, task, website_url, gbp_url, scale_answers (same as patch).
    """
    allowed = _allowed_updates(initial)
    sid = str(uuid.uuid4())

    pool = get_pool()
    async with pool.acquire() as conn:
        if not allowed:
            row = await conn.fetchrow(
                """
                INSERT INTO onboarding (session_id)
                VALUES ($1)
                RETURNING id, session_id, user_id, outcome, domain, task,
                          website_url, gbp_url, scale_answers, questions_answers, crawl_cache_key,
                          onboarding_completed_at, created_at, updated_at
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
                          website_url, gbp_url, scale_answers, questions_answers, crawl_cache_key,
                          onboarding_completed_at, created_at, updated_at
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


async def upsert_onboarding_patch(
    session_id: str,
    updates: dict[str, Any],
    user_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Insert onboarding row if missing else patch allowed columns.

    If the existing session has `onboarding_completed_at` set (completed onboarding),
    creates a new onboarding row instead of updating the completed one.

    Assumption: `onboarding.session_id` is unique (1 row per session).
    """
    sid = (session_id or "").strip()
    if not sid:
        raise ValueError("session_id is required for patch")

    allowed = _allowed_updates(updates)
    uid = (user_id or "").strip() if user_id else None

    pool = get_pool()
    async with pool.acquire() as conn:
        # Check if the existing session is complete
        existing = await conn.fetchrow(
            "SELECT onboarding_completed_at FROM onboarding WHERE session_id = $1",
            sid,
        )

        # If the session exists and is complete, create a new session
        if existing and existing.get("onboarding_completed_at"):
            logger.info(
                "onboarding session is complete, creating new session",
                old_session_id=sid,
                user_id=uid,
            )
            # Generate new session_id
            new_sid = str(uuid.uuid4())

            # Prepare initial fields including user_id if provided
            initial_fields = dict(allowed)
            if uid:
                initial_fields["user_id"] = uid

            if not initial_fields:
                row = await conn.fetchrow(
                    """
                    INSERT INTO onboarding (session_id)
                    VALUES ($1)
                    RETURNING id, session_id, user_id, outcome, domain, task,
                              website_url, gbp_url, scale_answers, questions_answers, crawl_cache_key,
                              onboarding_completed_at, created_at, updated_at
                    """,
                    new_sid,
                )
            else:
                cols = ["session_id"] + list(initial_fields.keys())
                vals: list[Any] = [new_sid] + list(initial_fields.values())
                placeholders = ", ".join(f"${i + 1}" for i in range(len(vals)))
                col_sql = ", ".join(cols)
                row = await conn.fetchrow(
                    f"""
                    INSERT INTO onboarding ({col_sql})
                    VALUES ({placeholders})
                    RETURNING id, session_id, user_id, outcome, domain, task,
                              website_url, gbp_url, scale_answers, questions_answers, crawl_cache_key,
                              onboarding_completed_at, created_at, updated_at
                    """,
                    *vals,
                )

            out = _serialize_row(row)
            out["session_id"] = new_sid
            out["new_session"] = True  # Flag to indicate a new session was created
            logger.info(
                "new onboarding row created (previous was complete)",
                session_id=new_sid,
                onboarding_id=out.get("id"),
            )
            return out

        # Normal upsert for non-complete sessions
        if not allowed:
            row = await conn.fetchrow(
                """
                INSERT INTO onboarding (session_id)
                VALUES ($1)
                ON CONFLICT (session_id) DO UPDATE
                SET updated_at = onboarding.updated_at
                RETURNING id, session_id, user_id, outcome, domain, task,
                          website_url, gbp_url, scale_answers, questions_answers, crawl_cache_key,
                          onboarding_completed_at, created_at, updated_at
                """,
                sid,
            )
        else:
            cols = list(allowed.keys())
            vals = list(allowed.values())
            placeholders = ", ".join(f"${i + 2}" for i in range(len(vals)))
            insert_cols = ", ".join(["session_id"] + cols)
            insert_vals = ", ".join(["$1", placeholders]) if placeholders else "$1"
            set_sql = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols)

            row = await conn.fetchrow(
                f"""
                INSERT INTO onboarding ({insert_cols})
                VALUES ({insert_vals})
                ON CONFLICT (session_id) DO UPDATE
                SET {set_sql}, updated_at = NOW()
                RETURNING id, session_id, user_id, outcome, domain, task,
                          website_url, gbp_url, scale_answers, questions_answers, crawl_cache_key,
                          onboarding_completed_at, created_at, updated_at
                """,
                sid,
                *vals,
            )

    out = _serialize_row(row)
    logger.debug("onboarding patched", session_id=sid, fields=list(allowed.keys()))
    return out
