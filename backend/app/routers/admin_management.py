from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from urllib.parse import urljoin
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from pypika import Order, Table, functions as fn
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter

from app.config import get_settings
from app.db import get_pool
from app.middleware.auth_context import get_request_auth_claims, require_super_admin
from app.task_stream.redis_client import get_redis
from app.doable_claw_agent.stores import auto_timeout_stale_skill_calls
from app.sql_builder import build_query


router = APIRouter(prefix="/admin/management", tags=["Admin-Management"])
users_t = Table("users")
otp_logs_t = Table("otp_provider_logs")
plan_runs_t = Table("plan_runs")
task_streams_t = Table("task_stream_streams")
skill_calls_t = Table("skill_calls")
conversations_t = Table("conversations")
onboarding_t = Table("onboarding")
crawl_runs_t = Table("crawl_runs")
playbook_runs_t = Table("playbook_runs")
session_links_t = Table("session_user_links")
system_config_t = Table("system_config")
token_usage_t = Table("token_usage")


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
    type: str | None = Field(None, description="Value type: string, number, boolean, json, markdown")
    description: str = Field("", description="Human-friendly description (optional)")


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
            ping_q = build_query(PostgreSQLQuery.select(1))
            await conn.fetchval(ping_q.sql, *ping_q.params)
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
            otp_failed_q = build_query(
                PostgreSQLQuery.from_(otp_logs_t)
                .select(
                    otp_logs_t.action,
                    otp_logs_t.provider,
                    otp_logs_t.phone_masked,
                    otp_logs_t.error,
                    otp_logs_t.created_at,
                )
                .where(otp_logs_t.success == False)  # noqa: E712
                .orderby(otp_logs_t.created_at, order=Order.desc)
                .limit(20)
            )
            otp_failed = await conn.fetch(otp_failed_q.sql, *otp_failed_q.params)
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
            failed_plans_q = build_query(
                PostgreSQLQuery.from_(plan_runs_t)
                .select(plan_runs_t.id, plan_runs_t.status, plan_runs_t.updated_at)
                .where(plan_runs_t.status == "error")
                .orderby(plan_runs_t.updated_at, order=Order.desc)
                .limit(20)
            )
            failed_plans = await conn.fetch(failed_plans_q.sql, *failed_plans_q.params)
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
            running_streams_q = build_query(
                PostgreSQLQuery.from_(task_streams_t).select(fn.Count(1)).where(task_streams_t.status == "running")
            )
            running_streams = await conn.fetchval(running_streams_q.sql, *running_streams_q.params)
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
            rows_q = build_query(
                PostgreSQLQuery.from_(users_t)
                .select(
                    users_t.id,
                    users_t.email,
                    users_t.phone_number,
                    users_t.name,
                    users_t.auth_provider,
                    users_t.created_at,
                    users_t.last_login_at,
                )
                .where(
                    users_t.email.ilike(Parameter("%s"))
                    | users_t.phone_number.ilike(Parameter("%s"))
                    | users_t.name.ilike(Parameter("%s"))
                )
                .orderby(users_t.created_at, order=Order.desc)
                .limit(Parameter("%s"))
                .offset(Parameter("%s")),
                [pattern, pattern, pattern, limit, offset],
            )
            rows = await conn.fetch(rows_q.sql, *rows_q.params)
            total_q = build_query(
                PostgreSQLQuery.from_(users_t)
                .select(fn.Count(1))
                .where(
                    users_t.email.ilike(Parameter("%s"))
                    | users_t.phone_number.ilike(Parameter("%s"))
                    | users_t.name.ilike(Parameter("%s"))
                ),
                [pattern, pattern, pattern],
            )
            total = await conn.fetchval(total_q.sql, *total_q.params)
        else:
            rows_q = build_query(
                PostgreSQLQuery.from_(users_t)
                .select(
                    users_t.id,
                    users_t.email,
                    users_t.phone_number,
                    users_t.name,
                    users_t.auth_provider,
                    users_t.created_at,
                    users_t.last_login_at,
                )
                .orderby(users_t.created_at, order=Order.desc)
                .limit(Parameter("%s"))
                .offset(Parameter("%s")),
                [limit, offset],
            )
            rows = await conn.fetch(rows_q.sql, *rows_q.params)
            total_q = build_query(PostgreSQLQuery.from_(users_t).select(fn.Count(1)))
            total = await conn.fetchval(total_q.sql, *total_q.params)

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
        sc = skill_calls_t.as_("sc")
        c = conversations_t.as_("c")
        rows_q = build_query(
            PostgreSQLQuery.from_(sc)
            .join(c)
            .on(c.id == sc.conversation_id)
            .select(
                sc.id,
                sc.conversation_id,
                sc.message_id,
                sc.skill_id,
                sc.input,
                sc.state,
                sc.started_at,
                sc.ended_at,
                sc.duration_ms,
            )
            .where(c.user_id == Parameter("%s"))
            .orderby(sc.started_at, order=Order.desc)
            .limit(Parameter("%s"))
            .offset(Parameter("%s")),
            [uid, limit, offset],
        )
        rows = await conn.fetch(rows_q.sql, *rows_q.params)
        total_q = build_query(
            PostgreSQLQuery.from_(sc)
            .join(c)
            .on(c.id == sc.conversation_id)
            .select(fn.Count(1))
            .where(c.user_id == Parameter("%s")),
            [uid],
        )
        total = await conn.fetchval(total_q.sql, *total_q.params)
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


@router.get("/skill-calls/{skill_call_id}", response_model=dict[str, Any])
async def get_skill_call_detail(request: Request, skill_call_id: str):
    require_super_admin(request)
    scid = (skill_call_id or "").strip()
    if not scid:
        raise HTTPException(status_code=400, detail="skill_call_id is required")
    pool = get_pool()
    async with pool.acquire() as conn:
        await auto_timeout_stale_skill_calls(conn, skill_call_id=int(scid))
        detail_q = build_query(
            PostgreSQLQuery.from_(skill_calls_t)
            .select(
                skill_calls_t.id,
                skill_calls_t.conversation_id,
                skill_calls_t.message_id,
                skill_calls_t.skill_id,
                skill_calls_t.run_id,
                skill_calls_t.input,
                skill_calls_t.streamed_text,
                skill_calls_t.state,
                skill_calls_t.output,
                skill_calls_t.error,
                skill_calls_t.started_at,
                skill_calls_t.ended_at,
                skill_calls_t.duration_ms,
                skill_calls_t.created_at,
            )
            .where(skill_calls_t.id == Parameter("%s"))
            .limit(1),
            [int(scid)],
        )
        row = await conn.fetchrow(detail_q.sql, *detail_q.params)
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
        user_q = build_query(
            PostgreSQLQuery.from_(users_t)
            .select(users_t.id, users_t.email, users_t.phone_number, users_t.onboarding_session_id)
            .where(users_t.id == Parameter("%s"))
            .limit(1),
            [uid],
        )
        user_row = await conn.fetchrow(user_q.sql, *user_q.params)
        if not user_row:
            raise HTTPException(status_code=404, detail="User not found")

        onboarding_session_id = user_row.get("onboarding_session_id") or ""

        async with conn.transaction():
            # 1. Conversations → cascades messages, skill_calls, plan_runs
            del_conversations_q = build_query(
                PostgreSQLQuery.from_(conversations_t).delete().where(conversations_t.user_id == Parameter("%s")),
                [uid],
            )
            await conn.execute(del_conversations_q.sql, *del_conversations_q.params)

            # 2. Onboarding rows linked by user_id (TEXT)
            del_onboarding_user_q = build_query(
                PostgreSQLQuery.from_(onboarding_t).delete().where(onboarding_t.user_id == Parameter("%s")),
                [uid],
            )
            await conn.execute(del_onboarding_user_q.sql, *del_onboarding_user_q.params)

            # 3. Onboarding row linked by session_id (if present and different)
            if onboarding_session_id:
                del_onboarding_session_q = build_query(
                    PostgreSQLQuery.from_(onboarding_t).delete().where(onboarding_t.session_id == Parameter("%s")),
                    [onboarding_session_id],
                )
                await conn.execute(del_onboarding_session_q.sql, *del_onboarding_session_q.params)

            # 4. Crawl runs
            try:
                del_crawl_q = build_query(
                    PostgreSQLQuery.from_(crawl_runs_t).delete().where(crawl_runs_t.user_id == Parameter("%s")),
                    [uid],
                )
                await conn.execute(del_crawl_q.sql, *del_crawl_q.params)
            except Exception:
                pass  # table may not use UUID cast

            # 5. Playbook runs
            try:
                del_playbook_q = build_query(
                    PostgreSQLQuery.from_(playbook_runs_t).delete().where(playbook_runs_t.user_id == Parameter("%s")),
                    [uid],
                )
                await conn.execute(del_playbook_q.sql, *del_playbook_q.params)
            except Exception:
                pass

            # 6. Task stream streams (user_id is TEXT in this table)
            del_streams_q = build_query(
                PostgreSQLQuery.from_(task_streams_t).delete().where(task_streams_t.user_id == Parameter("%s")),
                [uid],
            )
            await conn.execute(del_streams_q.sql, *del_streams_q.params)

            # 7. Session-user links
            del_links_q = build_query(
                PostgreSQLQuery.from_(session_links_t).delete().where(session_links_t.user_id == Parameter("%s")),
                [uid],
            )
            await conn.execute(del_links_q.sql, *del_links_q.params)

            # 8. Delete user — cascades: payment_checkout_context, user_plan_grants,
            #    admin_subscription_grants, admin_subscription_grant_logs
            del_user_q = build_query(
                PostgreSQLQuery.from_(users_t).delete().where(users_t.id == Parameter("%s")),
                [uid],
            )
            await conn.execute(del_user_q.sql, *del_user_q.params)

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
        cfg_q = build_query(
            PostgreSQLQuery.from_(system_config_t)
            .select(
                system_config_t.key,
                system_config_t.value,
                system_config_t.type,
                system_config_t.description,
                system_config_t.updated_at,
            )
            .orderby(system_config_t.key, order=Order.asc)
        )
        rows = await conn.fetch(cfg_q.sql, *cfg_q.params)
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
        cfg_item_q = build_query(
            PostgreSQLQuery.from_(system_config_t)
            .select(
                system_config_t.key,
                system_config_t.value,
                system_config_t.type,
                system_config_t.description,
                system_config_t.updated_at,
            )
            .where(system_config_t.key == Parameter("%s"))
            .limit(1),
            [k],
        )
        row = await conn.fetchrow(cfg_item_q.sql, *cfg_item_q.params)
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
async def upsert_system_config_entry_route(request: Request, key: str, body: UpsertSystemConfigRequest):
    require_super_admin(request)
    k = str(key or "").strip()
    if not k:
        raise HTTPException(status_code=400, detail="key is required")
    
    # Import validation helper
    from app.services.system_config_service import validate_value_for_type, VALID_TYPES
    
    pool = get_pool()
    async with pool.acquire() as conn:
        # Get existing type if not provided
        config_type = body.type
        if config_type and config_type not in VALID_TYPES:
            raise HTTPException(status_code=400, detail=f"Invalid type: {config_type}. Must be one of: {', '.join(VALID_TYPES)}")
        
        if config_type is None:
            existing_q = build_query(
                PostgreSQLQuery.from_(system_config_t)
                .select(system_config_t.type)
                .where(system_config_t.key == Parameter("%s"))
                .limit(1),
                [k],
            )
            existing = await conn.fetchval(existing_q.sql, *existing_q.params)
            config_type = str(existing or "string")
        
        # Validate value against type
        is_valid, err = validate_value_for_type(body.value, config_type)
        if not is_valid:
            raise HTTPException(status_code=400, detail=err)
        
        upsert_q = build_query(
            PostgreSQLQuery.into(system_config_t)
            .columns(system_config_t.key, system_config_t.value, system_config_t.type, system_config_t.description)
            .insert(Parameter("%s"), Parameter("%s"), Parameter("%s"), Parameter("%s"))
            .on_conflict(system_config_t.key)
            .do_update(system_config_t.value)
            .do_update(system_config_t.type)
            .do_update(system_config_t.description),
            [k, body.value, config_type, body.description],
        )
        await conn.execute(upsert_q.sql, *upsert_q.params)

        row_q = build_query(
            PostgreSQLQuery.from_(system_config_t)
            .select(
                system_config_t.key,
                system_config_t.value,
                system_config_t.type,
                system_config_t.description,
                system_config_t.updated_at,
            )
            .where(system_config_t.key == Parameter("%s"))
            .limit(1),
            [k],
        )
        row = await conn.fetchrow(row_q.sql, *row_q.params)

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


@router.get("/token-usage/summary", response_model=dict[str, Any])
async def token_usage_summary(request: Request):
    require_super_admin(request)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT "
            # Linked (authenticated users) totals used by per-user list.
            "COALESCE(SUM(t.cost_inr), 0) AS spend_inr, "
            "COALESCE(SUM(t.input_tokens), 0) AS input_tokens, "
            "COALESCE(SUM(t.output_tokens), 0) AS output_tokens, "
            "COUNT(*) AS calls_count, "
            "COUNT(*) FILTER (WHERE t.cost_inr IS NULL) AS unknown_priced_calls, "
            "COUNT(DISTINCT t.user_id) AS users_count, "
            # Global totals for full admin visibility (includes unlinked rows).
            "(SELECT COALESCE(SUM(cost_inr), 0) FROM token_usage) AS overall_spend_inr, "
            "(SELECT COALESCE(SUM(input_tokens), 0) FROM token_usage) AS overall_input_tokens, "
            "(SELECT COALESCE(SUM(output_tokens), 0) FROM token_usage) AS overall_output_tokens, "
            "(SELECT COUNT(*) FROM token_usage) AS overall_calls_count, "
            "(SELECT COALESCE(SUM(cost_inr), 0) FROM token_usage WHERE user_id IS NULL) AS unlinked_spend_inr, "
            "(SELECT COUNT(*) FROM token_usage WHERE user_id IS NULL) AS unlinked_calls_count "
            "FROM token_usage t "
            "JOIN users u ON u.id::text = t.user_id "
            "WHERE t.user_id IS NOT NULL"
        )
    return {
        "spendInr": float(row.get("spend_inr") or 0),
        "inputTokens": int(row.get("input_tokens") or 0),
        "outputTokens": int(row.get("output_tokens") or 0),
        "callsCount": int(row.get("calls_count") or 0),
        "unknownPricedCalls": int(row.get("unknown_priced_calls") or 0),
        "usersCount": int(row.get("users_count") or 0),
        "overallSpendInr": float(row.get("overall_spend_inr") or 0),
        "overallInputTokens": int(row.get("overall_input_tokens") or 0),
        "overallOutputTokens": int(row.get("overall_output_tokens") or 0),
        "overallCallsCount": int(row.get("overall_calls_count") or 0),
        "unlinkedSpendInr": float(row.get("unlinked_spend_inr") or 0),
        "unlinkedCallsCount": int(row.get("unlinked_calls_count") or 0),
    }


@router.get("/token-usage/users", response_model=dict[str, Any])
async def token_usage_users(request: Request, q: str = "", limit: int = 30, offset: int = 0):
    require_super_admin(request)
    limit = min(max(1, limit), 200)
    offset = max(0, offset)
    pool = get_pool()
    needle = f"%{(q or '').strip()}%"
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT u.id::text AS user_id, u.email, u.phone_number, "
            "COALESCE(SUM(t.cost_inr), 0) AS spend_inr, "
            "COALESCE(SUM(t.input_tokens), 0) AS input_tokens, "
            "COALESCE(SUM(t.output_tokens), 0) AS output_tokens, "
            "COUNT(*) AS calls_count "
            "FROM token_usage t "
            "JOIN users u ON u.id::text = t.user_id "
            "WHERE t.user_id IS NOT NULL "
            "AND ($1 = '%%' OR u.email ILIKE $1 OR u.phone_number ILIKE $1) "
            "GROUP BY u.id, u.email, u.phone_number "
            "ORDER BY spend_inr DESC, calls_count DESC "
            "LIMIT $2 OFFSET $3",
            needle,
            limit,
            offset,
        )
    users = [
        {
            "userId": str(r.get("user_id") or ""),
            "email": str(r.get("email") or ""),
            "phoneNumber": str(r.get("phone_number") or ""),
            "spendInr": float(r.get("spend_inr") or 0),
            "inputTokens": int(r.get("input_tokens") or 0),
            "outputTokens": int(r.get("output_tokens") or 0),
            "callsCount": int(r.get("calls_count") or 0),
        }
        for r in rows
    ]
    return {"users": users, "limit": limit, "offset": offset}


@router.get("/token-usage/users/{user_id}/conversations", response_model=dict[str, Any])
async def token_usage_user_conversations(request: Request, user_id: str, limit: int = 30, offset: int = 0):
    require_super_admin(request)
    limit = min(max(1, limit), 200)
    offset = max(0, offset)
    uid = str(user_id or "").strip()
    if not uid:
        raise HTTPException(status_code=400, detail="user_id is required")
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT conversation_id, "
            "COALESCE(SUM(cost_inr), 0) AS spend_inr, "
            "COALESCE(SUM(input_tokens), 0) AS input_tokens, "
            "COALESCE(SUM(output_tokens), 0) AS output_tokens, "
            "COUNT(*) AS calls_count, "
            "MAX(created_at) AS last_used_at "
            "FROM token_usage "
            "WHERE user_id = $1 AND conversation_id IS NOT NULL "
            "GROUP BY conversation_id "
            "ORDER BY last_used_at DESC "
            "LIMIT $2 OFFSET $3",
            uid, limit, offset,
        )
    return {
        "conversations": [
            {
                "conversationId": str(r.get("conversation_id") or ""),
                "spendInr": float(r.get("spend_inr") or 0),
                "inputTokens": int(r.get("input_tokens") or 0),
                "outputTokens": int(r.get("output_tokens") or 0),
                "callsCount": int(r.get("calls_count") or 0),
                "lastUsedAt": r.get("last_used_at").isoformat() if r.get("last_used_at") else "",
            }
            for r in rows
        ],
        "limit": limit,
        "offset": offset,
    }


@router.get("/token-usage/conversations/{conversation_id}/calls", response_model=dict[str, Any])
async def token_usage_conversation_calls(request: Request, conversation_id: str, limit: int = 100, offset: int = 0):
    require_super_admin(request)
    limit = min(max(1, limit), 500)
    offset = max(0, offset)
    cid = str(conversation_id or "").strip()
    if not cid:
        raise HTTPException(status_code=400, detail="conversation_id is required")
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT message_id, stage, provider, model_name, input_tokens, output_tokens, cost_inr, created_at "
            "FROM token_usage WHERE conversation_id = $1 "
            "ORDER BY created_at DESC LIMIT $2 OFFSET $3",
            cid, limit, offset,
        )
    return {
        "calls": [
            {
                "messageId": str(r.get("message_id") or ""),
                "stage": str(r.get("stage") or ""),
                "provider": str(r.get("provider") or ""),
                "model": str(r.get("model_name") or ""),
                "inputTokens": int(r.get("input_tokens") or 0),
                "outputTokens": int(r.get("output_tokens") or 0),
                "costInr": float(r.get("cost_inr")) if r.get("cost_inr") is not None else None,
                "createdAt": r.get("created_at").isoformat() if r.get("created_at") else "",
            }
            for r in rows
        ],
        "limit": limit,
        "offset": offset,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# PROMPTS MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════


class PromptEntry(BaseModel):
    slug: str
    name: str
    content: str
    description: str
    category: str
    createdAt: str
    updatedAt: str


class UpsertPromptRequest(BaseModel):
    name: str = Field(..., description="Display name for the prompt")
    content: str = Field(..., description="The prompt content (markdown)")
    description: str = Field("", description="Human-friendly description")
    category: str = Field("general", description="Category for grouping prompts")


@router.get("/prompts", response_model=dict[str, Any])
async def list_prompts(request: Request, category: str | None = None):
    """List all prompts, optionally filtered by category."""
    require_super_admin(request)

    from app.services.prompts_service import list_prompts as list_prompts_svc

    prompts = await list_prompts_svc(category)
    return {"prompts": prompts}


@router.get("/prompts/{slug}", response_model=dict[str, Any])
async def get_prompt(request: Request, slug: str):
    """Get a single prompt by slug."""
    require_super_admin(request)

    from app.services.prompts_service import get_prompt_full

    prompt = await get_prompt_full(slug)
    if prompt is None:
        raise HTTPException(status_code=404, detail=f"Prompt '{slug}' not found")
    return {"prompt": prompt}


@router.put("/prompts/{slug}", response_model=dict[str, Any])
async def upsert_prompt(request: Request, slug: str, body: UpsertPromptRequest):
    """Create or update a prompt."""
    require_super_admin(request)

    from app.services.prompts_service import upsert_prompt as upsert_prompt_svc

    try:
        prompt = await upsert_prompt_svc(
            slug=slug,
            name=body.name,
            content=body.content,
            description=body.description,
            category=body.category,
        )
        return {"prompt": prompt}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/prompts/{slug}", response_model=dict[str, Any])
async def delete_prompt(request: Request, slug: str):
    """Delete a prompt by slug."""
    require_super_admin(request)

    from app.services.prompts_service import delete_prompt as delete_prompt_svc

    deleted = await delete_prompt_svc(slug)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Prompt '{slug}' not found")
    return {"deleted": True, "slug": slug}


