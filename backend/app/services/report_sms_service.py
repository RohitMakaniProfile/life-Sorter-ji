from __future__ import annotations

import os
from typing import Any

import asyncpg
import httpx
from pypika import Table
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter

from app.db import get_pool
from app.sql_builder import build_query
from app.services.system_config_service import get_config_value, parse_bool

users_t = Table("users")


def _frontend_url() -> str:
    return (os.getenv("FRONTEND_URL", "http://localhost:5173") or "http://localhost:5173").rstrip("/")


async def _already_sent(conversation_id: str) -> bool:
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchval(
                "SELECT 1 FROM report_link_sms_logs WHERE conversation_id = $1 AND status = 'sent' LIMIT 1",
                conversation_id,
            )
            return bool(row)
    except asyncpg.UndefinedTableError:
        return False


async def _mark_log(conversation_id: str, user_id: str, status: str, provider_id: str = "", error: str = "") -> None:
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO report_link_sms_logs (conversation_id, user_id, status, provider_message_id, error) "
                "VALUES ($1, $2, $3, $4, $5) "
                "ON CONFLICT (conversation_id) DO UPDATE SET "
                "status = EXCLUDED.status, provider_message_id = EXCLUDED.provider_message_id, error = EXCLUDED.error, updated_at = NOW()",
                conversation_id,
                user_id,
                status,
                provider_id,
                error,
            )
    except asyncpg.UndefinedTableError:
        return


async def send_report_link_sms_if_enabled(conversation_id: str, user_id: str) -> dict[str, Any]:
    enabled = parse_bool(await get_config_value("sms.report_link_enabled", "false"), default=False)
    if not enabled:
        return {"sent": False, "reason": "disabled"}

    if await _already_sent(conversation_id):
        return {"sent": False, "reason": "already_sent"}

    pool = get_pool()
    async with pool.acquire() as conn:
        q = build_query(
            PostgreSQLQuery.from_(users_t)
            .select(users_t.phone_number)
            .where(users_t.id == Parameter("%s"))
            .limit(1),
            [user_id],
        )
        phone = str(await conn.fetchval(q.sql, *q.params) or "").strip()
    if not phone:
        await _mark_log(conversation_id, user_id, "skipped", error="missing_phone")
        return {"sent": False, "reason": "missing_phone"}

    api_key = (os.getenv("TWO_FACTOR_API_KEY", "") or "").strip()
    sender = (await get_config_value("sms.report_link_sender_id", "")).strip()
    template = (await get_config_value("sms.report_link_template_name", "")).strip()
    if not api_key or not sender or not template:
        await _mark_log(conversation_id, user_id, "skipped", error="missing_sms_config")
        return {"sent": False, "reason": "missing_sms_config"}

    link = f"{_frontend_url()}/chat/{conversation_id}"
    url = f"https://2factor.in/API/V1/{api_key}/ADDON_SERVICES/SEND/TSMS"
    payload = {"From": sender, "To": phone, "TemplateName": template, "VAR1": link}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(url, json=payload)
        if res.status_code >= 400:
            await _mark_log(conversation_id, user_id, "error", error=f"http_{res.status_code}")
            return {"sent": False, "reason": f"http_{res.status_code}"}
        provider_id = ""
        try:
            provider_id = str((res.json() or {}).get("Details") or "")
        except Exception:
            provider_id = ""
        await _mark_log(conversation_id, user_id, "sent", provider_id=provider_id)
        return {"sent": True}
    except Exception as exc:
        await _mark_log(conversation_id, user_id, "error", error=str(exc))
        return {"sent": False, "reason": "send_failed"}
