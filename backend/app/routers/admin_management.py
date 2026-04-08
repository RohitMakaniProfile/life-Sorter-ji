from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from urllib.parse import urljoin
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import get_settings
from app.db import get_pool
from app.middleware.auth_context import get_request_auth_claims, require_super_admin
from app.task_stream.redis_client import get_redis
from app.doable_claw_agent.stores import auto_timeout_stale_skill_calls


router = APIRouter(prefix="/admin/management", tags=["Admin-Management"])


class AdminApiEntry(BaseModel):
    id: str
    name: str
    method: str
    path: str
    description: str = ""


class SystemConfigEntry(BaseModel):
    key: str
    value: str
    type: str = "string"
    description: str
    updatedAt: str


class UpsertSystemConfigRequest(BaseModel):
    value: str = Field(..., description="New value for system_config.key")
    type: str = Field("string", description="Value type: string | number | boolean | json | markdown")
    description: str = Field("", description="Human-friendly description (optional)")


def _parse_iso_date(v: str | None) -> str | None:
    """
    Accept ISO date/datetime strings and pass through to Postgres as timestamptz.
    We keep this permissive and let Postgres validate format.
    """
    s = str(v or "").strip()
    return s or None


def _service_status(name: str, ok: bool, detail: str = "") -> dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail}


@router.get("/observability", response_model=dict[str, Any])
async def observability_snapshot(request: Request):
    require_super_admin(request)
    settings = get_settings()
    now = datetime.now(timezone.utc).isoformat()
    pool = get_pool()

    services: list[dict[str, Any]] = []
    recent_errors: list[dict[str, Any]] = []
    counters: dict[str, int] = {}

    # Core health checks
    db_ok = True
    try:
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
    except Exception as exc:
        db_ok = False
        services.append(_service_status("postgres", False, f"Database ping failed: {exc}"))
    if db_ok:
        services.append(_service_status("postgres", True, "Database reachable"))

    redis_ok = True
    redis_detail = "Redis URL not configured"
    try:
        redis = await get_redis()
        if redis is None:
            redis_ok = False
        else:
            pong = await redis.ping()
            redis_ok = bool(pong)
            redis_detail = "Redis reachable" if redis_ok else "Redis ping failed"
    except Exception as exc:
        redis_ok = False
        redis_detail = f"Redis check failed: {exc}"
    services.append(_service_status("redis", redis_ok, redis_detail))

    # Integration connectivity/config visibility (best-effort)
    openai_key = (os.getenv("OPENAI_API_KEY", "") or "").strip()
    services.append(
        _service_status(
            "openai",
            bool(openai_key),
            "Configured" if openai_key else "Missing API key",
        )
    )
    services.append(
        _service_status(
            "openrouter",
            bool((settings.OPENROUTER_API_KEY or "").strip()),
            "Configured" if (settings.OPENROUTER_API_KEY or "").strip() else "Missing API key",
        )
    )
    # Note: some integration keys are defined as module-level config constants,
    # not fields on the Pydantic `Settings` model returned by get_settings().
    claude_key = (os.getenv("CLAUDE_API_KEY", "") or "").strip()
    services.append(_service_status("claude", bool(claude_key), "Configured" if claude_key else "Missing API key"))
    # Gemini is now served via OpenRouter in this codebase (best-effort visibility only).
    gemini_over_openrouter = bool((settings.OPENROUTER_API_KEY or "").strip())
    services.append(
        _service_status(
            "gemini",
            gemini_over_openrouter,
            "Configured via OpenRouter" if gemini_over_openrouter else "Missing OpenRouter API key",
        )
    )
    juspay_key = (os.getenv("JUSPAY_API_KEY", "") or "").strip()
    services.append(_service_status("juspay", bool(juspay_key), "Configured" if juspay_key else "Missing API key"))
    scraper_base_url = (os.getenv("SCRAPER_BASE_URL", "") or "").strip()
    if not scraper_base_url:
        services.append(_service_status("scraper", False, "SCRAPER_BASE_URL not configured"))
    else:
        scraper_ok = False
        scraper_detail = ""
        try:
            health_url = urljoin(scraper_base_url.rstrip("/") + "/", "health")
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(health_url)
            scraper_ok = resp.status_code < 400
            scraper_detail = f"HTTP {resp.status_code}" if scraper_ok else f"HTTP {resp.status_code} — service unhealthy"
        except httpx.TimeoutException:
            scraper_detail = "Health check timed out (5s)"
        except Exception as exc:
            scraper_detail = f"Health check failed: {exc}"
        services.append(_service_status("scraper", scraper_ok, scraper_detail))

    # Recent failures + counters from DB tables
    async with pool.acquire() as conn:
        try:
            otp_failed = await conn.fetch(
                """
                SELECT action, provider, phone_masked, error, created_at
                FROM otp_provider_logs
                WHERE success = FALSE
                ORDER BY created_at DESC
                LIMIT 20
                """
            )
            for r in otp_failed:
                recent_errors.append(
                    {
                        "source": "otp_provider_logs",
                        "at": r.get("created_at").isoformat() if r.get("created_at") else "",
                        "message": str(r.get("error") or "OTP provider request failed"),
                        "meta": {
                            "action": str(r.get("action") or ""),
                            "provider": str(r.get("provider") or ""),
                            "phoneMasked": str(r.get("phone_masked") or ""),
                        },
                    }
                )
            counters["otp_failures_last_20"] = len(otp_failed)
        except Exception:
            counters["otp_failures_last_20"] = 0

        try:
            failed_plans = await conn.fetch(
                """
                SELECT id, status, updated_at
                FROM plan_runs
                WHERE status = 'error'
                ORDER BY updated_at DESC
                LIMIT 20
                """
            )
            for r in failed_plans:
                recent_errors.append(
                    {
                        "source": "plan_runs",
                        "at": r.get("updated_at").isoformat() if r.get("updated_at") else "",
                        "message": "Plan execution failed",
                        "meta": {"planId": str(r.get("id") or ""), "status": str(r.get("status") or "")},
                    }
                )
            counters["plan_errors_last_20"] = len(failed_plans)
        except Exception:
            counters["plan_errors_last_20"] = 0

        try:
            running_streams = await conn.fetchval(
                "SELECT COUNT(*) FROM task_stream_streams WHERE status = 'running'"
            )
            counters["task_stream_running"] = int(running_streams or 0)
        except Exception:
            counters["task_stream_running"] = 0

    # Most recent first across sources.
    recent_errors.sort(key=lambda x: str(x.get("at") or ""), reverse=True)
    recent_errors = recent_errors[:30]

    return {
        "snapshotAt": now,
        "services": services,
        "counters": counters,
        "recentErrors": recent_errors,
    }


@router.get("/users", response_model=dict[str, Any])
async def list_users(request: Request, q: str = "", limit: int = 50, offset: int = 0):
    require_super_admin(request)
    limit = min(max(1, limit), 200)
    offset = max(0, offset)
    pool = get_pool()
    search = (q or "").strip()
    async with pool.acquire() as conn:
        if search:
            pattern = f"%{search}%"
            rows = await conn.fetch(
                """
                SELECT id, email, phone_number, name, auth_provider, created_at, last_login_at
                FROM users
                WHERE email ILIKE $1 OR phone_number ILIKE $1 OR name ILIKE $1
                ORDER BY created_at DESC
                LIMIT $2 OFFSET $3
                """,
                pattern,
                limit,
                offset,
            )
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM users WHERE email ILIKE $1 OR phone_number ILIKE $1 OR name ILIKE $1",
                pattern,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT id, email, phone_number, name, auth_provider, created_at, last_login_at
                FROM users
                ORDER BY created_at DESC
                LIMIT $1 OFFSET $2
                """,
                limit,
                offset,
            )
            total = await conn.fetchval("SELECT COUNT(*) FROM users")

    users = []
    for r in rows:
        created_at = r.get("created_at")
        last_login_at = r.get("last_login_at")
        users.append(
            {
                "id": str(r.get("id") or ""),
                "email": r.get("email") or "",
                "phone_number": r.get("phone_number") or "",
                "name": r.get("name") or "",
                "auth_provider": r.get("auth_provider") or "",
                "created_at": created_at.isoformat() if created_at else "",
                "last_login_at": last_login_at.isoformat() if last_login_at else "",
            }
        )
    return {"users": users, "total": int(total or 0), "limit": limit, "offset": offset}


@router.get("/users/{user_id}/skill-calls", response_model=dict[str, Any])
async def list_user_skill_calls(request: Request, user_id: str, limit: int = 5, offset: int = 0):
    require_super_admin(request)
    limit = min(max(1, limit), 50)
    offset = max(0, offset)
    uid = (user_id or "").strip()
    if not uid:
        raise HTTPException(status_code=400, detail="user_id is required")
    pool = get_pool()
    async with pool.acquire() as conn:
        await auto_timeout_stale_skill_calls(conn, user_id=uid)
        rows = await conn.fetch(
            """
            SELECT sc.id, sc.conversation_id, sc.message_id, sc.skill_id,
                   sc.input, sc.state, sc.started_at, sc.ended_at, sc.duration_ms
            FROM skill_calls sc
            JOIN conversations c ON c.id = sc.conversation_id
            WHERE c.user_id = $1
            ORDER BY sc.started_at DESC
            LIMIT $2 OFFSET $3
            """,
            uid, limit, offset,
        )
        total = await conn.fetchval(
            """
            SELECT COUNT(*) FROM skill_calls sc
            JOIN conversations c ON c.id = sc.conversation_id
            WHERE c.user_id = $1
            """,
            uid,
        )
    calls = []
    for r in rows:
        started_at = r.get("started_at")
        ended_at = r.get("ended_at")
        calls.append({
            "id": str(r.get("id") or ""),
            "conversation_id": str(r.get("conversation_id") or ""),
            "message_id": str(r.get("message_id") or ""),
            "skill_id": str(r.get("skill_id") or ""),
            "input": r.get("input") or {},
            "state": str(r.get("state") or ""),
            "started_at": started_at.isoformat() if started_at else "",
            "ended_at": ended_at.isoformat() if ended_at else "",
            "duration_ms": r.get("duration_ms"),
        })
    return {"calls": calls, "total": int(total or 0), "limit": limit, "offset": offset}


@router.get("/token-usage/summary", response_model=dict[str, Any])
async def token_usage_summary(request: Request, from_: str | None = None, to: str | None = None):
    """
    Overall spend/tokens summary for authenticated users (user_id not null) in a time window.
    Query params:
      - from_: ISO date/datetime (inclusive) (named from_ because `from` is reserved)
      - to: ISO date/datetime (exclusive)
    """
    require_super_admin(request)
    from_s = _parse_iso_date(from_)
    to_s = _parse_iso_date(to)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
              COALESCE(SUM(input_tokens), 0) AS input_tokens,
              COALESCE(SUM(output_tokens), 0) AS output_tokens,
              COALESCE(SUM(cost_inr), 0) AS spend_inr_priced,
              COUNT(*) FILTER (WHERE cost_inr IS NULL) AS unknown_pricing_calls,
              COUNT(DISTINCT user_id) AS users
            FROM token_usage
            WHERE user_id IS NOT NULL AND BTRIM(user_id) <> ''
              AND ($1::timestamptz IS NULL OR created_at >= $1::timestamptz)
              AND ($2::timestamptz IS NULL OR created_at <  $2::timestamptz)
            """,
            from_s,
            to_s,
        )
    return {
        "from": from_s or "",
        "to": to_s or "",
        "inputTokens": int(row["input_tokens"] or 0),
        "outputTokens": int(row["output_tokens"] or 0),
        "spendInrPriced": float(row["spend_inr_priced"] or 0),
        "unknownPricingCalls": int(row["unknown_pricing_calls"] or 0),
        "users": int(row["users"] or 0),
    }


@router.get("/token-usage/users", response_model=dict[str, Any])
async def token_usage_users(
    request: Request,
    from_: str | None = None,
    to: str | None = None,
    q: str = "",
    limit: int = 50,
    offset: int = 0,
):
    """Users list with spend/tokens aggregated from token_usage."""
    require_super_admin(request)
    limit = min(max(1, limit), 200)
    offset = max(0, offset)
    from_s = _parse_iso_date(from_)
    to_s = _parse_iso_date(to)
    search = (q or "").strip()
    pool = get_pool()
    async with pool.acquire() as conn:
        where = [
            "tu.user_id IS NOT NULL",
            "BTRIM(tu.user_id) <> ''",
            "($1::timestamptz IS NULL OR tu.created_at >= $1::timestamptz)",
            "($2::timestamptz IS NULL OR tu.created_at <  $2::timestamptz)",
        ]
        params: list[Any] = [from_s, to_s]
        if search:
            where.append("(u.email ILIKE $3 OR u.phone_number ILIKE $3 OR u.name ILIKE $3)")
            params.append(f"%{search}%")
            lim_i = 4
        else:
            lim_i = 3

        rows = await conn.fetch(
            f"""
            SELECT
              tu.user_id,
              COALESCE(u.email, '') AS email,
              COALESCE(u.phone_number, '') AS phone_number,
              COALESCE(u.name, '') AS name,
              COALESCE(SUM(tu.cost_inr), 0) AS spend_inr_priced,
              COALESCE(SUM(tu.input_tokens), 0) AS input_tokens,
              COALESCE(SUM(tu.output_tokens), 0) AS output_tokens,
              COUNT(*) FILTER (WHERE tu.cost_inr IS NULL) AS unknown_pricing_calls,
              MAX(tu.created_at) AS last_at
            FROM token_usage tu
            LEFT JOIN users u ON u.id::text = tu.user_id
            WHERE {' AND '.join(where)}
            GROUP BY tu.user_id, u.email, u.phone_number, u.name
            ORDER BY spend_inr_priced DESC, last_at DESC
            LIMIT ${lim_i} OFFSET ${lim_i + 1}
            """,
            *params,
            limit,
            offset,
        )
        total = await conn.fetchval(
            f"""
            SELECT COUNT(*) FROM (
              SELECT tu.user_id
              FROM token_usage tu
              LEFT JOIN users u ON u.id::text = tu.user_id
              WHERE {' AND '.join(where)}
              GROUP BY tu.user_id
            ) x
            """,
            *params,
        )
    users = []
    for r in rows:
        last_at = r.get("last_at")
        users.append(
            {
                "user_id": str(r.get("user_id") or ""),
                "email": str(r.get("email") or ""),
                "phone_number": str(r.get("phone_number") or ""),
                "name": str(r.get("name") or ""),
                "spendInrPriced": float(r.get("spend_inr_priced") or 0),
                "inputTokens": int(r.get("input_tokens") or 0),
                "outputTokens": int(r.get("output_tokens") or 0),
                "unknownPricingCalls": int(r.get("unknown_pricing_calls") or 0),
                "lastAt": last_at.isoformat() if last_at else "",
            }
        )
    return {"users": users, "total": int(total or 0), "limit": limit, "offset": offset}


@router.get("/token-usage/users/{user_id}/conversations", response_model=dict[str, Any])
async def token_usage_user_conversations(
    request: Request,
    user_id: str,
    from_: str | None = None,
    to: str | None = None,
    limit: int = 50,
    offset: int = 0,
):
    require_super_admin(request)
    uid = (user_id or "").strip()
    if not uid:
        raise HTTPException(status_code=400, detail="user_id is required")
    limit = min(max(1, limit), 200)
    offset = max(0, offset)
    from_s = _parse_iso_date(from_)
    to_s = _parse_iso_date(to)
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
              tu.conversation_id,
              COALESCE(c.title, 'New conversation') AS title,
              COALESCE(SUM(tu.cost_inr), 0) AS spend_inr_priced,
              COALESCE(SUM(tu.input_tokens), 0) AS input_tokens,
              COALESCE(SUM(tu.output_tokens), 0) AS output_tokens,
              COUNT(*) FILTER (WHERE tu.cost_inr IS NULL) AS unknown_pricing_calls,
              MAX(tu.created_at) AS last_at
            FROM token_usage tu
            LEFT JOIN conversations c ON c.id = tu.conversation_id
            WHERE tu.user_id = $1
              AND tu.conversation_id IS NOT NULL AND BTRIM(tu.conversation_id) <> ''
              AND ($2::timestamptz IS NULL OR tu.created_at >= $2::timestamptz)
              AND ($3::timestamptz IS NULL OR tu.created_at <  $3::timestamptz)
            GROUP BY tu.conversation_id, c.title
            ORDER BY spend_inr_priced DESC, last_at DESC
            LIMIT $4 OFFSET $5
            """,
            uid,
            from_s,
            to_s,
            limit,
            offset,
        )
        total = await conn.fetchval(
            """
            SELECT COUNT(*) FROM (
              SELECT tu.conversation_id
              FROM token_usage tu
              WHERE tu.user_id = $1
                AND tu.conversation_id IS NOT NULL AND BTRIM(tu.conversation_id) <> ''
                AND ($2::timestamptz IS NULL OR tu.created_at >= $2::timestamptz)
                AND ($3::timestamptz IS NULL OR tu.created_at <  $3::timestamptz)
              GROUP BY tu.conversation_id
            ) x
            """,
            uid,
            from_s,
            to_s,
        )
    conversations = []
    for r in rows:
        last_at = r.get("last_at")
        conversations.append(
            {
                "conversation_id": str(r.get("conversation_id") or ""),
                "title": str(r.get("title") or "New conversation"),
                "spendInrPriced": float(r.get("spend_inr_priced") or 0),
                "inputTokens": int(r.get("input_tokens") or 0),
                "outputTokens": int(r.get("output_tokens") or 0),
                "unknownPricingCalls": int(r.get("unknown_pricing_calls") or 0),
                "lastAt": last_at.isoformat() if last_at else "",
            }
        )
    return {"conversations": conversations, "total": int(total or 0), "limit": limit, "offset": offset}


@router.get("/token-usage/conversations/{conversation_id}/calls", response_model=dict[str, Any])
async def token_usage_conversation_calls(
    request: Request,
    conversation_id: str,
    limit: int = 50,
    offset: int = 0,
):
    require_super_admin(request)
    cid = (conversation_id or "").strip()
    if not cid:
        raise HTTPException(status_code=400, detail="conversation_id is required")
    limit = min(max(1, limit), 200)
    offset = max(0, offset)
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
              message_id, stage, provider, model_name,
              input_tokens, output_tokens, cost_inr, created_at
            FROM token_usage
            WHERE conversation_id = $1
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
            """,
            cid,
            limit,
            offset,
        )
        total = await conn.fetchval(
            "SELECT COUNT(*) FROM token_usage WHERE conversation_id = $1",
            cid,
        )
    calls = []
    for r in rows:
        at = r.get("created_at")
        calls.append(
            {
                "message_id": str(r.get("message_id") or ""),
                "stage": str(r.get("stage") or ""),
                "provider": str(r.get("provider") or ""),
                "model": str(r.get("model_name") or ""),
                "inputTokens": int(r.get("input_tokens") or 0),
                "outputTokens": int(r.get("output_tokens") or 0),
                "costInr": float(r.get("cost_inr")) if r.get("cost_inr") is not None else None,
                "createdAt": at.isoformat() if at else "",
            }
        )
    return {"calls": calls, "total": int(total or 0), "limit": limit, "offset": offset}


@router.get("/skill-calls/{skill_call_id}", response_model=dict[str, Any])
async def get_skill_call_detail(request: Request, skill_call_id: str):
    require_super_admin(request)
    scid = (skill_call_id or "").strip()
    if not scid:
        raise HTTPException(status_code=400, detail="skill_call_id is required")
    pool = get_pool()
    async with pool.acquire() as conn:
        await auto_timeout_stale_skill_calls(conn, skill_call_id=int(scid))
        row = await conn.fetchrow(
            """
            SELECT id, conversation_id, message_id, skill_id, run_id,
                   input, streamed_text, state, output, error,
                   started_at, ended_at, duration_ms, created_at
            FROM skill_calls WHERE id = $1 LIMIT 1
            """,
            int(scid),
        )
    if not row:
        raise HTTPException(status_code=404, detail="Skill call not found")
    started_at = row.get("started_at")
    ended_at = row.get("ended_at")
    created_at = row.get("created_at")
    return {
        "call": {
            "id": str(row.get("id") or ""),
            "conversation_id": str(row.get("conversation_id") or ""),
            "message_id": str(row.get("message_id") or ""),
            "skill_id": str(row.get("skill_id") or ""),
            "run_id": str(row.get("run_id") or ""),
            "input": row.get("input") or {},
            "streamed_text": str(row.get("streamed_text") or ""),
            "state": str(row.get("state") or ""),
            "output": row.get("output") or [],
            "error": str(row.get("error") or ""),
            "started_at": started_at.isoformat() if started_at else "",
            "ended_at": ended_at.isoformat() if ended_at else "",
            "duration_ms": row.get("duration_ms"),
            "created_at": created_at.isoformat() if created_at else "",
        }
    }


# Hard-coded identities permitted to delete users. Intentionally not configurable.
# Phone stored in JWT without '+' (validator strips it), so compare digits only.
_USER_DELETE_ALLOWED_EMAILS = {"code.harshkanjariya@gmail.com"}
_USER_DELETE_ALLOWED_PHONES = {"917802004735", "7802004735"}


def _require_delete_permission(request: Request) -> None:
    """Raises 403 unless the caller is one of the hard-coded delete-permitted identities."""
    claims = get_request_auth_claims(request) or {}
    email = str(claims.get("email") or "").strip().lower()
    # Normalise: strip +, spaces, dashes to match whatever format the JWT carries
    raw_phone = str(claims.get("phone_number") or "")
    phone = re.sub(r"[\s\-+]", "", raw_phone)
    if email not in _USER_DELETE_ALLOWED_EMAILS and phone not in _USER_DELETE_ALLOWED_PHONES:
        raise HTTPException(
            status_code=403,
            detail="User deletion is restricted to authorised identities only.",
        )


@router.delete("/users/{user_id}", response_model=dict[str, Any])
async def delete_user(request: Request, user_id: str):
    require_super_admin(request)
    _require_delete_permission(request)

    uid = (user_id or "").strip()
    if not uid:
        raise HTTPException(status_code=400, detail="user_id is required")

    pool = get_pool()
    async with pool.acquire() as conn:
        # Fetch user to confirm existence and grab onboarding_session_id
        user_row = await conn.fetchrow(
            "SELECT id, email, phone_number, onboarding_session_id FROM users WHERE id::text = $1 LIMIT 1",
            uid,
        )
        if not user_row:
            raise HTTPException(status_code=404, detail="User not found")

        onboarding_session_id = user_row.get("onboarding_session_id") or ""

        async with conn.transaction():
            # 1. Conversations → cascades messages, skill_calls, plan_runs
            await conn.execute("DELETE FROM conversations WHERE user_id = $1", uid)

            # 2. Onboarding rows linked by user_id (TEXT)
            await conn.execute("DELETE FROM onboarding WHERE user_id = $1", uid)

            # 3. Onboarding row linked by session_id (if present and different)
            if onboarding_session_id:
                await conn.execute(
                    "DELETE FROM onboarding WHERE session_id = $1",
                    onboarding_session_id,
                )

            # 4. Crawl runs
            try:
                await conn.execute("DELETE FROM crawl_runs WHERE user_id::text = $1", uid)
            except Exception:
                pass  # table may not use UUID cast

            # 5. Playbook runs
            try:
                await conn.execute("DELETE FROM playbook_runs WHERE user_id::text = $1", uid)
            except Exception:
                pass

            # 6. Task stream streams (user_id is TEXT in this table)
            await conn.execute("DELETE FROM task_stream_streams WHERE user_id = $1", uid)

            # 7. Session-user links
            await conn.execute("DELETE FROM session_user_links WHERE user_id = $1", uid)

            # 8. Delete user — cascades: payment_checkout_context, user_plan_grants,
            #    admin_subscription_grants, admin_subscription_grant_logs
            await conn.execute("DELETE FROM users WHERE id::text = $1", uid)

    return {
        "success": True,
        "deleted_user_id": uid,
        "deleted_email": str(user_row.get("email") or ""),
        "deleted_phone": str(user_row.get("phone_number") or ""),
    }


@router.get("/config", response_model=dict[str, Any])
async def list_system_config(request: Request):
    require_super_admin(request)
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT key, value, type, description, updated_at FROM system_config ORDER BY key ASC"
        )
    entries = []
    for r in rows:
        updated_at = r.get("updated_at")
        entries.append(
            {
                "key": str(r.get("key") or ""),
                "value": str(r.get("value") or ""),
                "type": str(r.get("type") or "string"),
                "description": str(r.get("description") or ""),
                "updatedAt": updated_at.isoformat() if updated_at else "",
            }
        )
    return {"entries": entries}


@router.get("/config/{key}", response_model=dict[str, Any])
async def get_system_config_entry(request: Request, key: str):
    require_super_admin(request)
    k = str(key or "").strip()
    if not k:
        raise HTTPException(status_code=400, detail="key is required")
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT key, value, type, description, updated_at FROM system_config WHERE key = $1 LIMIT 1",
            k,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Config key not found")
    updated_at = row.get("updated_at")
    return {
        "entry": {
            "key": str(row.get("key") or ""),
            "value": str(row.get("value") or ""),
            "type": str(row.get("type") or "string"),
            "description": str(row.get("description") or ""),
            "updatedAt": updated_at.isoformat() if updated_at else "",
        }
    }


@router.patch("/config/{key}", response_model=dict[str, Any])
async def upsert_system_config_entry(request: Request, key: str, body: UpsertSystemConfigRequest):
    require_super_admin(request)
    k = str(key or "").strip()
    if not k:
        raise HTTPException(status_code=400, detail="key is required")
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO system_config (key, value, type, description)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (key)
            DO UPDATE SET
              value = EXCLUDED.value,
              type = EXCLUDED.type,
              description = EXCLUDED.description
            """,
            k,
            body.value,
            body.type,
            body.description,
        )

        row = await conn.fetchrow(
            "SELECT key, value, type, description, updated_at FROM system_config WHERE key = $1 LIMIT 1",
            k,
        )

    updated_at = row.get("updated_at") if row else None
    return {
        "entry": {
            "key": str(row.get("key") or ""),
            "value": str(row.get("value") or ""),
            "type": str(row.get("type") or "string"),
            "description": str(row.get("description") or ""),
            "updatedAt": updated_at.isoformat() if updated_at else "",
        }
    }

