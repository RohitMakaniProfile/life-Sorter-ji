from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import get_settings
from app.db import get_pool
from app.middleware.auth_context import require_super_admin
from app.task_stream.redis_client import get_redis


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
    description: str
    updatedAt: str


class UpsertSystemConfigRequest(BaseModel):
    value: str = Field(..., description="New value for system_config.key")
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
    services.append(
        _service_status(
            "openai",
            bool(settings.openai_api_key_active),
            "Configured" if settings.openai_api_key_active else "Missing API key",
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
    services.append(_service_status("scraper_base_url", bool((os.getenv("SCRAPER_BASE_URL", "") or "").strip()), "Configured" if (os.getenv("SCRAPER_BASE_URL", "") or "").strip() else "Missing URL"))

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


@router.get("/config", response_model=dict[str, Any])
async def list_system_config(request: Request):
    require_super_admin(request)
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT key, value, description, updated_at FROM system_config ORDER BY key ASC"
        )
    entries = []
    for r in rows:
        updated_at = r.get("updated_at")
        entries.append(
            {
                "key": str(r.get("key") or ""),
                "value": str(r.get("value") or ""),
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
            "SELECT key, value, description, updated_at FROM system_config WHERE key = $1 LIMIT 1",
            k,
        )
    if not row:
        raise HTTPException(status_code=404, detail="Config key not found")
    updated_at = row.get("updated_at")
    return {
        "entry": {
            "key": str(row.get("key") or ""),
            "value": str(row.get("value") or ""),
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
            INSERT INTO system_config (key, value, description)
            VALUES ($1, $2, $3)
            ON CONFLICT (key)
            DO UPDATE SET
              value = EXCLUDED.value,
              description = EXCLUDED.description
            """,
            k,
            body.value,
            body.description,
        )

        row = await conn.fetchrow(
            "SELECT key, value, description, updated_at FROM system_config WHERE key = $1 LIMIT 1",
            k,
        )

    updated_at = row.get("updated_at") if row else None
    return {
        "entry": {
            "key": str(row.get("key") or ""),
            "value": str(row.get("value") or ""),
            "description": str(row.get("description") or ""),
            "updatedAt": updated_at.isoformat() if updated_at else "",
        }
    }

