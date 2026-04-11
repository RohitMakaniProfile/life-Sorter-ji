"""
═══════════════════════════════════════════════════════════════
OTP SERVICE — 2Factor.in SMS OTP Integration
═══════════════════════════════════════════════════════════════
Sends and verifies OTPs via the 2Factor.in REST API.

Endpoints used:
  Send:   GET https://2factor.in/API/V1/{api_key}/SMS/{phone}/AUTOGEN
  Verify: GET https://2factor.in/API/V1/{api_key}/SMS/VERIFY/{provider_session_id}/{otp}
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import structlog

from app.config import get_settings
from app.db import get_pool
from app.task_stream.redis_client import get_redis

_OTP_PREFIX = "ikshan:otp"

logger = structlog.get_logger()

TWO_FACTOR_BASE = "https://2factor.in/API/V1"


async def _store_otp_postgres(
    *,
    phone_number: str,
    otp_code: str,
    onboarding_session_id: str | None,
    expiry_seconds: int,
    provider_session_id: str = "",
) -> None:
    from app.repositories import otp_sessions_repository as otp_repo
    phone_key = _normalize_phone(phone_number)
    payload = {
        "phone_number": phone_key,
        "otp_code": otp_code,
        "onboarding_session_id": onboarding_session_id or "",
        "provider_session_id": provider_session_id or "",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(60, int(expiry_seconds)))
    pool = get_pool()
    async with pool.acquire() as conn:
        await otp_repo.upsert_otp(conn, phone_key, json.dumps(payload), expires_at)


async def _load_otp_postgres(phone_number: str) -> dict | None:
    from app.repositories import otp_sessions_repository as otp_repo
    phone_key = _normalize_phone(phone_number)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await otp_repo.find_active_by_phone(conn, phone_key)
    if not row or row.get("payload") is None:
        return None
    raw = row["payload"]
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except Exception:
            return None
    elif isinstance(raw, dict):
        data = raw
    else:
        return None
    return data if isinstance(data, dict) else None


async def _delete_otp_postgres(phone_number: str) -> None:
    from app.repositories import otp_sessions_repository as otp_repo
    phone_key = _normalize_phone(phone_number)
    pool = get_pool()
    async with pool.acquire() as conn:
        await otp_repo.delete_by_phone(conn, phone_key)


def _mask_phone(phone: str) -> str:
    p = (phone or "").strip()
    if len(p) <= 4:
        return p
    return f"{'*' * max(0, len(p) - 4)}{p[-4:]}"


def _normalize_phone(phone_number: str) -> str:
    phone = phone_number.strip().replace(" ", "").replace("-", "")
    if phone.startswith("+"):
        phone = phone[1:]
    return phone


async def log_provider_call(
    *,
    action: str,
    phone_number: str,
    request_url: str,
    response_payload: dict,
    provider_session_id: str = "",
    success: bool = False,
    error: str = "",
) -> None:
    from app.repositories import otp_sessions_repository as otp_repo
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await otp_repo.insert_provider_log(
                conn,
                action=action,
                phone_masked=_mask_phone(phone_number),
                request_url=request_url,
                response_payload_json=json.dumps(response_payload or {}),
                provider_session_id=provider_session_id or "",
                success=bool(success),
                error=error or "",
            )
    except Exception as exc:
        logger.warning("otp provider log insert failed", error=str(exc))


async def store_otp_in_redis(
    *,
    phone_number: str,
    otp_code: str,
    onboarding_session_id: str | None,
    expiry_seconds: int,
    provider_session_id: str = "",
) -> None:
    phone_key = _normalize_phone(phone_number)
    redis = await get_redis()
    if redis:
        payload = json.dumps({
            "phone_number": phone_key,
            "otp_code": otp_code,
            "onboarding_session_id": onboarding_session_id or "",
            "provider_session_id": provider_session_id or "",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        ttl = max(60, int(expiry_seconds))
        await redis.set(f"{_OTP_PREFIX}:{phone_key}", payload, ex=ttl)
        return

    await _store_otp_postgres(
        phone_number=phone_key,
        otp_code=otp_code,
        onboarding_session_id=onboarding_session_id,
        expiry_seconds=expiry_seconds,
        provider_session_id=provider_session_id,
    )


async def load_otp_from_redis(phone_number: str) -> dict | None:
    phone_key = _normalize_phone(phone_number)
    redis = await get_redis()
    if redis:
        raw = await redis.get(f"{_OTP_PREFIX}:{phone_key}")
        if not raw:
            return None
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
        except Exception:
            return None

    return await _load_otp_postgres(phone_key)


async def delete_otp_from_redis(phone_number: str) -> None:
    phone_key = _normalize_phone(phone_number)
    redis = await get_redis()
    if redis:
        await redis.delete(f"{_OTP_PREFIX}:{phone_key}")
        return

    await _delete_otp_postgres(phone_key)


async def send_otp(phone_number: str) -> dict:
    """
    Send an auto-generated OTP to the given phone number.

    Args:
        phone_number: Indian mobile number (10 digits, with or without 91 prefix).

    Returns:
        {"success": True, "session_id": "..."} on success
        {"success": False, "error": "..."} on failure
    """
    settings = get_settings()
    api_key = settings.TWO_FACTOR_API_KEY

    if not api_key:
        logger.error("2Factor API key not configured")
        return {"success": False, "error": "OTP service not configured"}

    phone = _normalize_phone(phone_number)

    url = f"{TWO_FACTOR_BASE}/{api_key}/SMS/{phone}/AUTOGEN/aiplaybook"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
            data = resp.json()

        if data.get("Status") == "Success":
            provider_sid = str(data.get("Details") or "")
            await log_provider_call(
                action="send",
                phone_number=phone,
                request_url=url,
                response_payload=data,
                provider_session_id=provider_sid,
                success=True,
            )
            logger.info("OTP sent successfully", phone=phone[-4:])
            return {"success": True, "session_id": provider_sid}
        else:
            await log_provider_call(
                action="send",
                phone_number=phone,
                request_url=url,
                response_payload=data,
                provider_session_id=str(data.get("Details") or ""),
                success=False,
                error=str(data.get("Details") or "Failed to send OTP"),
            )
            logger.warning("2Factor API returned error", detail=data.get("Details"))
            return {"success": False, "error": data.get("Details", "Failed to send OTP")}

    except httpx.TimeoutException:
        await log_provider_call(
            action="send",
            phone_number=phone,
            request_url=url,
            response_payload={},
            success=False,
            error="timeout",
        )
        logger.error("2Factor API timeout", phone=phone[-4:])
        return {"success": False, "error": "OTP service timeout — please retry"}
    except Exception as e:
        await log_provider_call(
            action="send",
            phone_number=phone,
            request_url=url,
            response_payload={},
            success=False,
            error=str(e),
        )
        logger.error("2Factor API error", error=str(e))
        return {"success": False, "error": "Failed to send OTP"}


async def verify_otp(provider_session_id: str, otp_code: str) -> dict:
    """
    Verify an OTP entered by the user.

    Args:
        provider_session_id: The provider session ID returned by send_otp().
        otp_code: The OTP code entered by the user.

    Returns:
        {"success": True, "matched": True}  if OTP is correct
        {"success": True, "matched": False} if OTP is wrong
        {"success": False, "error": "..."}  on API failure
    """
    settings = get_settings()
    api_key = settings.TWO_FACTOR_API_KEY

    if not api_key:
        logger.error("2Factor API key not configured")
        return {"success": False, "error": "OTP service not configured"}

    # Sanitize inputs
    sid = provider_session_id.strip()
    code = otp_code.strip()

    if not code.isdigit() or len(code) < 4 or len(code) > 8:
        return {"success": True, "matched": False}

    url = f"{TWO_FACTOR_BASE}/{api_key}/SMS/VERIFY/{sid}/{code}"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
            data = resp.json()

        if data.get("Status") == "Success" and "Matched" in str(data.get("Details", "")):
            logger.info("OTP verified successfully")
            return {"success": True, "matched": True}
        else:
            logger.info("OTP verification failed", detail=data.get("Details"))
            return {"success": True, "matched": False}

    except httpx.TimeoutException:
        logger.error("2Factor verify timeout")
        return {"success": False, "error": "OTP verification timeout — please retry"}
    except Exception as e:
        logger.error("2Factor verify error", error=str(e))
        return {"success": False, "error": "OTP verification failed"}