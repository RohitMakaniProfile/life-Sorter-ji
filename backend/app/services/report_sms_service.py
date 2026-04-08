from __future__ import annotations

from datetime import datetime, timezone

import asyncpg
import httpx
import structlog

from app.config import get_settings
from app.db import get_pool
from app.services.system_config_service import get_config_value, parse_bool

logger = structlog.get_logger()

TWO_FACTOR_BASE = "https://2factor.in/API/V1"


def _normalize_phone(phone_number: str) -> str:
    phone = (phone_number or "").strip().replace(" ", "").replace("-", "")
    if phone.startswith("+"):
        phone = phone[1:]
    return phone


def _mask_phone(phone_number: str) -> str:
    p = (phone_number or "").strip()
    if len(p) <= 4:
        return p
    return f"{'*' * max(0, len(p) - 4)}{p[-4:]}"


async def _mark_log(
    *,
    conversation_id: str,
    user_id: str | None,
    phone_masked: str,
    status: str,
    provider_message_id: str = "",
    error: str = "",
) -> None:
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO report_link_sms_logs (
                  conversation_id, user_id, phone_masked, status, provider_message_id, error, sent_at
                )
                VALUES ($1, $2, $3, $4, $5, $6, CASE WHEN $4 = 'sent' THEN NOW() ELSE NULL END)
                ON CONFLICT (conversation_id)
                DO UPDATE SET
                  user_id = EXCLUDED.user_id,
                  phone_masked = EXCLUDED.phone_masked,
                  status = EXCLUDED.status,
                  provider_message_id = EXCLUDED.provider_message_id,
                  error = EXCLUDED.error,
                  sent_at = CASE WHEN EXCLUDED.status = 'sent' THEN NOW() ELSE report_link_sms_logs.sent_at END,
                  updated_at = NOW()
                """,
                conversation_id,
                (user_id or "").strip() or None,
                phone_masked,
                status,
                provider_message_id,
                error,
            )
    except asyncpg.UndefinedTableError:
        logger.warning("report_link_sms_logs table missing; skipping log write")


async def _already_sent(conversation_id: str) -> bool:
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT status FROM report_link_sms_logs WHERE conversation_id = $1 LIMIT 1",
                conversation_id,
            )
        return bool(row and str(row.get("status") or "") == "sent")
    except asyncpg.UndefinedTableError:
        logger.warning("report_link_sms_logs table missing; skipping duplicate check")
        return False


async def send_report_link_sms_if_enabled(
    *,
    conversation_id: str,
    user_id: str | None,
) -> dict[str, str | bool]:
    """
    Send report link via SMS when enabled.

    Conditions:
      - system_config.sms.report_link_enabled == true
      - user exists and has phone_number
      - no successful prior send for this conversation (dedupe)
      - sender/template config present
    """
    conv_id = (conversation_id or "").strip()
    uid = (user_id or "").strip()
    if not conv_id or not uid:
        return {"sent": False, "reason": "missing_conversation_or_user"}

    if await _already_sent(conv_id):
        return {"sent": False, "reason": "already_sent"}

    enabled_raw = await get_config_value("sms.report_link_enabled", "false")
    if not parse_bool(enabled_raw, default=False):
        await _mark_log(
            conversation_id=conv_id,
            user_id=uid,
            phone_masked="",
            status="skipped",
            error="sms.report_link_enabled=false",
        )
        return {"sent": False, "reason": "disabled"}

    sender_id = (await get_config_value("sms.report_link_sender_id", "")).strip()
    template_name = (await get_config_value("sms.report_link_template_name", "")).strip()
    if not sender_id or not template_name:
        await _mark_log(
            conversation_id=conv_id,
            user_id=uid,
            phone_masked="",
            status="error",
            error="missing sender/template config",
        )
        return {"sent": False, "reason": "missing_sender_or_template"}

    pool = get_pool()
    async with pool.acquire() as conn:
        phone = await conn.fetchval(
            "SELECT phone_number FROM users WHERE id::text = $1 LIMIT 1",
            uid,
        )
    phone_s = str(phone or "").strip()
    if not phone_s:
        await _mark_log(
            conversation_id=conv_id,
            user_id=uid,
            phone_masked="",
            status="skipped",
            error="no phone number",
        )
        return {"sent": False, "reason": "no_phone"}

    settings = get_settings()
    api_key = (settings.TWO_FACTOR_API_KEY or "").strip()
    if not api_key:
        await _mark_log(
            conversation_id=conv_id,
            user_id=uid,
            phone_masked=_mask_phone(phone_s),
            status="error",
            error="2factor api key missing",
        )
        return {"sent": False, "reason": "missing_api_key"}

    frontend_base = (settings.FRONTEND_URL or "").strip().rstrip("/")
    if not frontend_base:
        await _mark_log(
            conversation_id=conv_id,
            user_id=uid,
            phone_masked=_mask_phone(phone_s),
            status="error",
            error="frontend url missing",
        )
        return {"sent": False, "reason": "missing_frontend_url"}

    report_url = f"{frontend_base}/chat/{conv_id}"
    to_phone = _normalize_phone(phone_s)
    req_url = f"{TWO_FACTOR_BASE}/{api_key}/ADDON_SERVICES/SEND/TSMS"
    body = {
        "From": sender_id,
        "To": to_phone,
        "TemplateName": template_name,
        "VAR1": report_url,
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(req_url, json=body)
            data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {"raw": resp.text}
        ok = (resp.status_code // 100) == 2 and str(data.get("Status") or "").lower() in ("success", "ok", "true")
        provider_message_id = str(data.get("Details") or data.get("message_id") or "")
        if ok:
            await _mark_log(
                conversation_id=conv_id,
                user_id=uid,
                phone_masked=_mask_phone(phone_s),
                status="sent",
                provider_message_id=provider_message_id,
            )
            logger.info(
                "report link sms sent",
                conversation_id=conv_id,
                user_id=uid,
                phone_masked=_mask_phone(phone_s),
                provider_message_id=provider_message_id,
                at=datetime.now(timezone.utc).isoformat(),
            )
            return {"sent": True, "reason": "sent"}
        await _mark_log(
            conversation_id=conv_id,
            user_id=uid,
            phone_masked=_mask_phone(phone_s),
            status="error",
            provider_message_id=provider_message_id,
            error=str(data),
        )
        return {"sent": False, "reason": "provider_error"}
    except Exception as exc:
        await _mark_log(
            conversation_id=conv_id,
            user_id=uid,
            phone_masked=_mask_phone(phone_s),
            status="error",
            error=str(exc),
        )
        logger.warning("report link sms send failed", conversation_id=conv_id, user_id=uid, error=str(exc))
        return {"sent": False, "reason": "exception"}

