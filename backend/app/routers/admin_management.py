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
from app.repositories import users_repository as users_repo
from app.repositories import otp_logs_repository as otp_logs_repo
from app.repositories import plan_runs_repository as plan_runs_repo
from app.repositories import task_stream_repository as task_stream_repo
from app.repositories import skill_calls_repository as skill_repo
from app.repositories import conversations_repository as convs_repo
from app.repositories import onboarding_repository as onboarding_repo
from app.repositories import playbook_runs_repository as playbook_repo
from app.repositories import session_links_repository as session_links_repo
from app.repositories import system_config_repository as config_repo
from app.repositories import token_usage_repository as token_usage_repo
from app.repositories import scraped_pages_repository as scraped_pages_repo
from app.repositories import crawl_logs_repository as crawl_logs_repo


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


router = APIRouter(prefix="/admin", tags=["admin"])


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
            otp_failed = await otp_logs_repo.find_recent_failures(conn)
            for r in otp_failed:
                recent_errors.append({
                    "source": "otp_provider_logs",
                    "at": r.get("created_at").isoformat() if r.get("created_at") else "",
                    "message": str(r.get("error") or "OTP provider request failed"),
                    "meta": {
                        "action": str(r.get("action") or ""),
                        "provider": str(r.get("provider") or ""),
                        "phoneMasked": str(r.get("phone_masked") or ""),
                    },
                })
            counters["otp_failures_last_20"] = len(otp_failed)
        except Exception:
            counters["otp_failures_last_20"] = 0

        try:
            failed_plans = await plan_runs_repo.find_recent_errors(conn)
            for r in failed_plans:
                recent_errors.append({
                    "source": "plan_runs",
                    "at": r.get("updated_at").isoformat() if r.get("updated_at") else "",
                    "message": "Plan execution failed",
                    "meta": {"planId": str(r.get("id") or ""), "status": str(r.get("status") or "")},
                })
            counters["plan_errors_last_20"] = len(failed_plans)
        except Exception:
            counters["plan_errors_last_20"] = 0

        try:
            counters["task_stream_running"] = await task_stream_repo.count_running(conn)
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
    search = (q or "").strip() or None
    pool = get_pool()
    async with pool.acquire() as conn:
        rows, total = await users_repo.list_admin(conn, search, limit, offset)
    users = []
    for r in rows:
        created_at = r.get("created_at")
        last_login_at = r.get("last_login_at")
        users.append({
            "id": str(r.get("id") or ""),
            "email": r.get("email") or "",
            "phone_number": r.get("phone_number") or "",
            "name": r.get("name") or "",
            "auth_provider": r.get("auth_provider") or "",
            "created_at": created_at.isoformat() if created_at else "",
            "last_login_at": last_login_at.isoformat() if last_login_at else "",
        })
    return {"users": users, "total": total, "limit": limit, "offset": offset}


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
        await skill_repo.auto_timeout_stale(conn, user_id=uid)
        rows, total = await skill_repo.find_by_user_paginated(conn, uid, limit, offset)
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
    return {"calls": calls, "total": total, "limit": limit, "offset": offset}


@router.get("/skill-calls/{skill_call_id}", response_model=dict[str, Any])
async def get_skill_call_detail(request: Request, skill_call_id: str):
    require_super_admin(request)
    scid = (skill_call_id or "").strip()
    if not scid:
        raise HTTPException(status_code=400, detail="skill_call_id is required")
    pool = get_pool()
    async with pool.acquire() as conn:
        await skill_repo.auto_timeout_stale(conn, skill_call_id=int(scid))
        row = await skill_repo.find_detail_by_id(conn, int(scid))
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


@router.get("/users/{user_id}/onboardings", response_model=dict[str, Any])
async def list_user_onboardings(request: Request, user_id: str, limit: int = 20, offset: int = 0):
    """List all onboarding sessions for a user."""
    require_super_admin(request)
    limit = min(max(1, limit), 100)
    offset = max(0, offset)
    uid = (user_id or "").strip()
    if not uid:
        raise HTTPException(status_code=400, detail="user_id is required")
    pool = get_pool()
    async with pool.acquire() as conn:
        rows, total = await onboarding_repo.find_all_by_user_paginated(conn, uid, limit, offset)
    onboardings = []
    for r in rows:
        created_at = r.get("created_at")
        updated_at = r.get("updated_at")
        onboardings.append({
            "id": str(r.get("id") or ""),
            "outcome": str(r.get("outcome") or ""),
            "domain": str(r.get("domain") or ""),
            "task": str(r.get("task") or ""),
            "website_url": str(r.get("website_url") or ""),
            "playbook_status": str(r.get("playbook_status") or ""),
            "created_at": created_at.isoformat() if created_at else "",
            "updated_at": updated_at.isoformat() if updated_at else "",
        })
    return {"onboardings": onboardings, "total": total, "limit": limit, "offset": offset}


@router.get("/onboardings/{onboarding_id}/token-usage", response_model=dict[str, Any])
async def get_onboarding_token_usage(request: Request, onboarding_id: str, limit: int = 100, offset: int = 0):
    """Get token usage details for an onboarding session."""
    require_super_admin(request)
    limit = min(max(1, limit), 500)
    offset = max(0, offset)
    oid = (onboarding_id or "").strip()
    if not oid:
        raise HTTPException(status_code=400, detail="onboarding_id is required")
    pool = get_pool()
    async with pool.acquire() as conn:
        rows, total = await token_usage_repo.fetch_by_session_id(conn, oid, limit, offset)
        summary = await token_usage_repo.fetch_session_summary(conn, oid)
        onboarding = await onboarding_repo.find_full_by_id(conn, oid)

    calls = []
    for r in rows:
        created_at = r.get("created_at")
        calls.append({
            "message_id": str(r.get("message_id") or ""),
            "stage": str(r.get("stage") or ""),
            "provider": str(r.get("provider") or ""),
            "model_name": str(r.get("model_name") or ""),
            "input_tokens": int(r.get("input_tokens") or 0),
            "output_tokens": int(r.get("output_tokens") or 0),
            "cost_usd": float(r.get("cost_usd") or 0),
            "cost_inr": float(r.get("cost_inr") or 0),
            "success": r.get("success"),  # bool or None for older rows
            "error_msg": str(r.get("error_msg") or ""),
            "has_raw_output": bool(r.get("error_msg")),  # hint to frontend
            "created_at": created_at.isoformat() if created_at else "",
        })

    onboarding_info = None
    if onboarding:
        onboarding_info = {
            "id": str(onboarding.get("id") or ""),
            "outcome": str(onboarding.get("outcome") or ""),
            "domain": str(onboarding.get("domain") or ""),
            "task": str(onboarding.get("task") or ""),
            "website_url": str(onboarding.get("website_url") or ""),
        }

    return {
        "onboarding": onboarding_info,
        "summary": {
            "input_tokens": int(summary.get("input_tokens") or 0) if summary else 0,
            "output_tokens": int(summary.get("output_tokens") or 0) if summary else 0,
            "cost_usd": float(summary.get("cost_usd") or 0) if summary else 0,
            "cost_inr": float(summary.get("cost_inr") or 0) if summary else 0,
            "calls_count": int(summary.get("calls_count") or 0) if summary else 0,
        },
        "calls": calls,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/onboardings/{onboarding_id}/crawl-pages", response_model=dict[str, Any])
async def get_onboarding_crawl_pages(
    request: Request,
    onboarding_id: str,
    limit: int = 50,
    offset: int = 0,
):
    """Get scraped pages and crawl logs for an onboarding session."""
    require_super_admin(request)
    limit = min(max(1, limit), 200)
    offset = max(0, offset)
    oid = (onboarding_id or "").strip()
    if not oid:
        raise HTTPException(status_code=400, detail="onboarding_id is required")

    pool = get_pool()
    async with pool.acquire() as conn:
        rows, total = await scraped_pages_repo.fetch_by_onboarding_id(conn, oid, limit, offset)
        log_rows = await crawl_logs_repo.fetch_by_onboarding_id(conn, oid)

    pages = []
    for r in rows:
        created_at = r.get("created_at")
        pages.append({
            "id": str(r.get("id") or ""),
            "onboarding_id": str(r.get("onboarding_id") or ""),
            "url": str(r.get("url") or ""),
            "markdown": r.get("markdown") or None,
            "raw_html": r.get("raw") or None,
            "page_title": str(r.get("page_title") or ""),
            "status_code": r.get("status_code"),
            "crawl_status": str(r.get("crawl_status") or "done"),
            "error": r.get("error") or None,
            "created_at": created_at.isoformat() if created_at else "",
        })

    logs = []
    for r in log_rows:
        created_at = r.get("created_at")
        logs.append({
            "id": str(r.get("id") or ""),
            "onboarding_id": str(r.get("onboarding_id") or ""),
            "level": str(r.get("level") or "info"),
            "source": str(r.get("source") or ""),
            "message": str(r.get("message") or ""),
            "raw": r.get("raw"),
            "created_at": created_at.isoformat() if created_at else "",
        })

    # Derive overall crawl error: if no pages at all and logs exist, surface latest error
    crawl_error: str | None = None
    if total == 0 and logs:
        error_logs = [lg for lg in logs if lg["level"] == "error"]
        if error_logs:
            crawl_error = error_logs[-1]["message"]

    return {
        "pages": pages,
        "logs": logs,
        "total": total,
        "limit": limit,
        "offset": offset,
        "error": crawl_error,
    }


@router.get("/users/{user_id}/crawl-pages", response_model=dict[str, Any])
async def get_user_crawl_pages(
    request: Request,
    user_id: str,
    limit: int = 50,
    offset: int = 0,
):
    """Get all scraped pages across a user's onboardings."""
    require_super_admin(request)
    limit = min(max(1, limit), 200)
    offset = max(0, offset)
    uid = (user_id or "").strip()
    if not uid:
        raise HTTPException(status_code=400, detail="user_id is required")

    pool = get_pool()
    async with pool.acquire() as conn:
        rows, total = await scraped_pages_repo.fetch_by_user_id(conn, uid, limit, offset)

    pages = []
    for r in rows:
        created_at = r.get("created_at")
        pages.append({
            "id": str(r.get("id") or ""),
            "onboarding_id": str(r.get("onboarding_id") or ""),
            "url": str(r.get("url") or ""),
            "markdown": r.get("markdown") or None,
            "raw_html": r.get("raw") or None,
            "page_title": str(r.get("page_title") or ""),
            "status_code": r.get("status_code"),
            "crawl_status": str(r.get("crawl_status") or "done"),
            "error": r.get("error") or None,
            "created_at": created_at.isoformat() if created_at else "",
        })

    return {
        "pages": pages,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/token-usage/{message_id}/raw-output", response_model=dict[str, Any])
async def get_token_usage_raw_output(request: Request, message_id: str):
    """Fetch the full raw LLM output stored for a failed token usage record."""
    require_super_admin(request)
    mid = (message_id or "").strip()
    if not mid:
        raise HTTPException(status_code=400, detail="message_id is required")
    pool = get_pool()
    async with pool.acquire() as conn:
        raw = await token_usage_repo.fetch_raw_output(conn, mid)
    if raw is None:
        raise HTTPException(
            status_code=404,
            detail="No raw_output found for this message_id (only stored on failure)",
        )
    return {"message_id": mid, "raw_output": raw}


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
        user_row = await users_repo.find_with_onboarding_session(conn, uid)
        if not user_row:
            raise HTTPException(status_code=404, detail="User not found")

        onboarding_session_id = user_row.get("onboarding_session_id") or ""

        async with conn.transaction():
            # 1. Conversations → cascades messages, skill_calls, plan_runs
            await convs_repo.delete_by_user_id(conn, uid)

            # 2. Onboarding rows linked by user_id
            await onboarding_repo.delete_by_user_id(conn, uid)

            # 3. Onboarding row linked by session_id (if present)
            if onboarding_session_id:
                await onboarding_repo.delete_by_session_id(conn, onboarding_session_id)

            # 4. Crawl runs (no dedicated repository yet)
            try:
                await conn.execute("DELETE FROM crawl_runs WHERE user_id = $1", uid)
            except Exception:
                pass  # table may not exist or use different user_id type

            # 5. Playbook runs
            try:
                await playbook_repo.delete_by_user_id(conn, uid)
            except Exception:
                pass

            # 6. Task stream streams
            await task_stream_repo.delete_by_user(conn, uid)

            # 7. Session-user links
            await session_links_repo.delete_by_user(conn, uid)

            # 8. Delete user — cascades: payment_checkout_context, user_plan_grants,
            #    admin_subscription_grants, admin_subscription_grant_logs
            await users_repo.delete_by_id(conn, uid)

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
        rows = await config_repo.find_all_ordered(conn)
    entries = []
    for r in rows:
        updated_at = r.get("updated_at")
        entries.append({
            "key": str(r.get("key") or ""),
            "value": str(r.get("value") or ""),
            "type": str(r.get("type") or "string"),
            "description": str(r.get("description") or ""),
            "updatedAt": updated_at.isoformat() if updated_at else "",
        })
    return {"entries": entries}


@router.get("/config/{key}", response_model=dict[str, Any])
async def get_system_config_entry(request: Request, key: str):
    require_super_admin(request)
    k = str(key or "").strip()
    if not k:
        raise HTTPException(status_code=400, detail="key is required")
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await config_repo.find_entry_by_key(conn, k)
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

    from app.services.system_config_service import validate_value_for_type, VALID_TYPES

    config_type = body.type
    if config_type and config_type not in VALID_TYPES:
        raise HTTPException(status_code=400, detail=f"Invalid type: {config_type}. Must be one of: {', '.join(VALID_TYPES)}")

    pool = get_pool()
    async with pool.acquire() as conn:
        if config_type is None:
            existing_type = await config_repo.get_existing_type(conn, k)
            config_type = existing_type or "string"

        is_valid, err = validate_value_for_type(body.value, config_type)
        if not is_valid:
            raise HTTPException(status_code=400, detail=err)

        await config_repo.upsert_with_type(conn, k, body.value, config_type, body.description)
        row = await config_repo.find_entry_by_key(conn, k)

    updated_at = row.get("updated_at") if row else None
    return {
        "entry": {
            "key": str(row.get("key") or "") if row else k,
            "value": str(row.get("value") or "") if row else body.value,
            "type": str(row.get("type") or "string") if row else config_type,
            "description": str(row.get("description") or "") if row else body.description,
            "updatedAt": updated_at.isoformat() if updated_at else "",
        }
    }


@router.get("/token-usage/summary", response_model=dict[str, Any])
async def token_usage_summary(request: Request):
    require_super_admin(request)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await token_usage_repo.fetch_summary(conn)
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
    needle = f"%{(q or '').strip()}%"
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await token_usage_repo.fetch_users(conn, needle, limit, offset)
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
        rows = await token_usage_repo.fetch_user_conversations(conn, uid, limit, offset)
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
        rows = await token_usage_repo.fetch_conversation_calls(conn, cid, limit, offset)
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


