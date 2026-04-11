"""
═══════════════════════════════════════════════════════════════
AUTH ROUTER — OTP-Based 2-Factor Authentication
═══════════════════════════════════════════════════════════════
Endpoints:
  POST /api/v1/auth/send-otp      → Send OTP to phone number
  POST /api/v1/auth/verify-otp    → Verify OTP and issue auth token
  POST /api/v1/auth/google        → Save Google Sign-In for onboarding
"""

from __future__ import annotations

import re
import time
import uuid
from pydantic import BaseModel, field_validator
from fastapi import APIRouter, HTTPException, Header

import structlog

from app.services.otp_service import (
    delete_otp_from_redis,
    load_otp_from_redis,
    send_otp,
    store_otp_in_redis,
    verify_otp as verify_otp_with_2factor_api,
)
from app.services.system_config_service import get_config_value, parse_bool
from app.services.admin_access_service import resolve_admin_flags
from app.services.jwt_service import create_access_token, decode_and_verify_access_token
from app.auth.identity import verify_google_or_firebase_token
from app.db import get_pool
from app.config import get_settings
from app.repositories import users_repository as users_repo
from app.repositories import onboarding_repository as onboarding_repo
from app.repositories import conversations_repository as convs_repo
from app.repositories import session_links_repository as session_links_repo

logger = structlog.get_logger()

router = APIRouter(prefix="/auth", tags=["Authentication"])

# ── Request / Response Models ─────────────────────────────────

class SendOTPRequest(BaseModel):
    onboarding_id: str | None = None
    phone_number: str

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        cleaned = re.sub(r"[\s\-\+]", "", v)
        # Accept 10-digit Indian numbers or with 91 prefix
        if not re.match(r"^(91)?\d{10}$", cleaned):
            raise ValueError("Invalid phone number — provide a 10-digit Indian mobile number")
        return cleaned


class SendOTPResponse(BaseModel):
    success: bool
    message: str


class VerifyOTPRequest(BaseModel):
    phone_number: str
    onboarding_id: str | None = None
    otp_code: str
    # Set when Google was Step 1 of two-step verification
    google_email: str | None = None
    google_name: str | None = None
    # When set, links phone to existing user instead of creating new
    link_to_user_id: str | None = None

    @field_validator("otp_code")
    @classmethod
    def validate_otp(cls, v: str) -> str:
        code = v.strip()
        if not code.isdigit() or len(code) < 4 or len(code) > 8:
            raise ValueError("OTP must be 4-8 digits")
        return code

    @field_validator("phone_number")
    @classmethod
    def validate_verify_phone(cls, v: str) -> str:
        cleaned = re.sub(r"[\s\-\+]", "", v)
        if not re.match(r"^(91)?\d{10}$", cleaned):
            raise ValueError("Invalid phone number — provide a 10-digit Indian mobile number")
        return cleaned


class VerifyOTPResponse(BaseModel):
    success: bool
    verified: bool
    message: str
    token: str | None = None
    user: dict | None = None


class GoogleAuthRequest(BaseModel):
    session_id: str | None = None
    onboarding_id: str
    google_id: str
    email: str
    name: str
    avatar_url: str = ""


class GoogleExchangeRequest(BaseModel):
    idToken: str
    onboarding_id: str | None = None
    session_id: str | None = None
    # When set, links email to existing user instead of creating new
    link_to_user_id: str | None = None


class GoogleAuthResponse(BaseModel):
    success: bool
    message: str
    token: str | None = None
    user: dict | None = None
    # Flags derived from server-side allowlists; used by the frontend to gate admin UI.
    isAdmin: bool = False
    isSuperAdmin: bool = False


class AuthMeResponse(BaseModel):
    authenticated: bool
    user: dict


def _parse_bearer_token(authorization: str | None) -> str:
    raw = (authorization or "").strip()
    if not raw:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    if not raw.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header")
    token = raw[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return token


async def _user_exists(user_id: str, email: str | None) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        if await users_repo.exists_by_id(conn, user_id):
            return True
        if email and await users_repo.exists_by_email(conn, email):
            return True
        if await convs_repo.exists_by_user(conn, user_id):
            return True
        if await session_links_repo.exists_by_user(conn, user_id):
            return True
    return False


async def _otp_runtime_flags() -> dict[str, object]:
    settings = get_settings()
    is_dev = bool(settings.is_development)

    bypass_cfg = await get_config_value("auth.otp_bypass_enabled", "false")
    send_sms_cfg = await get_config_value("auth.otp_send_sms_enabled", "true")
    expiry_cfg = await get_config_value("auth.otp_expiry_seconds", "300")
    bypass_code = await get_config_value("auth.otp_bypass_code", "000000")

    # Always allow OTP bypass in development/local runtime.
    # In non-dev environments, this is controlled via system_config.
    otp_bypass_enabled = is_dev or parse_bool(bypass_cfg, default=False)
    otp_send_sms_enabled = parse_bool(send_sms_cfg, default=True)

    try:
        otp_expiry_seconds = max(60, int(expiry_cfg))
    except Exception:
        otp_expiry_seconds = 300

    return {
        "otp_bypass_enabled": otp_bypass_enabled,
        "otp_send_sms_enabled": otp_send_sms_enabled,
        "otp_expiry_seconds": otp_expiry_seconds,
        "otp_bypass_code": bypass_code or "000000",
    }


async def _upsert_user_from_otp(phone_number: str, onboarding_session_id: str | None) -> dict:
    pool = get_pool()
    phone = (phone_number or "").strip()
    sid = (onboarding_session_id or "").strip() or None
    async with pool.acquire() as conn:
        existing = await users_repo.find_by_phone(conn, phone)
        if existing:
            provider_now = str(existing.get("auth_provider") or "otp")
            next_provider = "both" if provider_now == "google" else "otp"
            row = await users_repo.update_on_otp_login(conn, str(existing.get("id") or ""), next_provider, sid)
        else:
            row = await users_repo.insert_otp_user(conn, phone, sid)
    return dict(row) if row else {}


async def _upsert_user_from_google(email: str, name: str, onboarding_session_id: str | None) -> dict:
    pool = get_pool()
    em = (email or "").strip().lower()
    sid = (onboarding_session_id or "").strip() or None
    async with pool.acquire() as conn:
        existing = await users_repo.find_by_email(conn, em)
        if existing:
            provider_now = str(existing.get("auth_provider") or "google")
            next_provider = "both" if provider_now == "otp" else "google"
            row = await users_repo.update_on_google_login(conn, str(existing.get("id") or ""), name, next_provider, sid)
        else:
            row = await users_repo.insert_google_user(conn, em, name, sid)
    return dict(row) if row else {}


async def _link_phone_to_user(user_id: str, phone_number: str) -> dict:
    """Link a verified phone number to an existing user (update user row)."""
    pool = get_pool()
    phone = (phone_number or "").strip()
    uid = (user_id or "").strip()
    if not uid or not phone:
        return {}
    async with pool.acquire() as conn:
        if await users_repo.phone_used_by_other(conn, phone, uid):
            raise HTTPException(status_code=400, detail="This phone number is already linked to another account")
        row = await users_repo.link_phone(conn, uid, phone)
    return dict(row) if row else {}


async def _link_email_to_user(user_id: str, email: str, name: str | None = None) -> dict:
    """Link a verified Google email to an existing user (update user row)."""
    pool = get_pool()
    em = (email or "").strip().lower()
    uid = (user_id or "").strip()
    if not uid or not em:
        return {}
    async with pool.acquire() as conn:
        if await users_repo.email_used_by_other(conn, em, uid):
            raise HTTPException(status_code=400, detail="This email is already linked to another account")
        row = await users_repo.link_email(conn, uid, em, name)
    return dict(row) if row else {}


# ── Endpoints ─────────────────────────────────────────────────

@router.post("/send-otp", response_model=SendOTPResponse)
async def send_otp_endpoint(req: SendOTPRequest):
    """Independent OTP send: stores OTP by phone number, optionally sends SMS via 2Factor."""
    flags = await _otp_runtime_flags()
    otp_bypass_enabled = bool(flags["otp_bypass_enabled"])
    otp_send_sms_enabled = bool(flags["otp_send_sms_enabled"])
    otp_expiry_seconds = int(flags["otp_expiry_seconds"])
    otp_bypass_code = str(flags["otp_bypass_code"])

    onboarding_session_id = (req.onboarding_id or "").strip() or None
    sms_result = {"success": True, "session_id": "", "error": ""}

    if otp_bypass_enabled:
        otp_code = otp_bypass_code
    else:
        otp_code = str(uuid.uuid4().int)[-6:]

    if otp_send_sms_enabled and not otp_bypass_enabled:
        sms_result = await send_otp(req.phone_number)
        if not sms_result.get("success"):
            return SendOTPResponse(success=False, message=str(sms_result.get("error") or "Failed to send OTP"))
        # 2Factor AUTOGEN owns the OTP; do not store a local random code (verify uses provider session + 2Factor VERIFY API).
        otp_code = ""

    await store_otp_in_redis(
        phone_number=req.phone_number,
        otp_code=otp_code,
        onboarding_session_id=onboarding_session_id,
        expiry_seconds=otp_expiry_seconds,
        provider_session_id=str(sms_result.get("session_id") or ""),
    )

    return SendOTPResponse(success=True, message="OTP sent successfully")


@router.post("/verify-otp", response_model=VerifyOTPResponse)
async def verify_otp_endpoint(req: VerifyOTPRequest):
    """Verify OTP by phone number, upsert user row, and issue JWT."""
    flags = await _otp_runtime_flags()
    otp_bypass_enabled = bool(flags["otp_bypass_enabled"])
    otp_bypass_code = str(flags["otp_bypass_code"])

    rec = await load_otp_from_redis(req.phone_number)
    if not rec:
        return VerifyOTPResponse(success=False, verified=False, message="OTP expired or invalid phone number")

    expected_code = str(rec.get("otp_code") or "")
    provided_code = str(req.otp_code or "").strip()
    provider_sid = str(rec.get("provider_session_id") or "").strip()

    matched = False
    if otp_bypass_enabled and provided_code == otp_bypass_code:
        matched = True
    elif provider_sid:
        api_out = await verify_otp_with_2factor_api(provider_sid, provided_code)
        if not api_out.get("success"):
            return VerifyOTPResponse(
                success=False,
                verified=False,
                message=str(api_out.get("error") or "OTP verification failed — please try again"),
            )
        matched = bool(api_out.get("matched"))
    else:
        matched = provided_code == expected_code

    if not matched:
        return VerifyOTPResponse(success=True, verified=False, message="Incorrect OTP — please try again")

    onboarding_session_id = (
        req.onboarding_id
        or rec.get("onboarding_session_id")
        or ""
    ).strip() or None
    phone_number = str(rec.get("phone_number") or "").strip()

    # If link_to_user_id is provided, link phone to existing user instead of creating new
    link_uid = (req.link_to_user_id or "").strip()
    if link_uid:
        user_row = await _link_phone_to_user(user_id=link_uid, phone_number=phone_number)
        if not user_row:
            return VerifyOTPResponse(success=False, verified=False, message="Failed to link phone to user")
    else:
        user_row = await _upsert_user_from_otp(phone_number=phone_number, onboarding_session_id=onboarding_session_id)

    user_id = str(user_row.get("id") or "")
    provider = str(user_row.get("auth_provider") or "otp")
    email = user_row.get("email")
    name = user_row.get("name") or "Verified User"

    # Link the onboarding row to the user if we have both user_id and onboarding_session_id
    if user_id and onboarding_session_id:
        try:
            pool = get_pool()
            async with pool.acquire() as conn:
                await onboarding_repo.link_user(conn, user_id, onboarding_session_id)
        except Exception as exc:
            logger.warning("Failed to link onboarding to user", error=str(exc), user_id=user_id, onboarding_id=onboarding_session_id)

    token = create_access_token(
        subject=user_id,
        claims={
            "provider": provider,
            "email": email,
            "name": name,
            "phone_number": phone_number,
            "onboarding_id": onboarding_session_id,
            "onboarding_session_id": onboarding_session_id,
            **(await resolve_admin_flags(email, phone_number)),
        },
    )
    await delete_otp_from_redis(phone_number)

    logger.info("OTP verified", user_id=user_id, has_onboarding_session=bool(onboarding_session_id))

    return VerifyOTPResponse(
        success=True,
        verified=True,
        message="Phone number verified successfully",
        token=token,
        user={
            "user_id": user_id,
            "provider": provider,
            "email": email,
            "name": name,
            "phone_number": phone_number,
            "onboarding_id": onboarding_session_id,
            "onboarding_session_id": onboarding_session_id,
        },
    )


@router.post("/google", response_model=GoogleAuthResponse)
async def google_auth_endpoint(req: GoogleAuthRequest):
    """Save Google Sign-In data to the session."""

    # Legacy endpoint retained for compatibility; independent auth uses /google/exchange.

    google_sub = (req.google_id or "").strip()
    if not google_sub:
        raise HTTPException(status_code=400, detail="Missing Google subject (sub)")

    email = req.email.strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Missing email")

    onboarding_id = (req.onboarding_id or req.session_id or "").strip()
    row = await _upsert_user_from_google(email=email, name=req.name, onboarding_session_id=onboarding_id)
    user_id = str(row.get("id") or email)
    token = create_access_token(
        subject=user_id,
        claims={
            "provider": "google",
            "email": email,
            "name": req.name,
            "avatar_url": req.avatar_url,
            "google_sub": google_sub,
            "onboarding_id": onboarding_id,
            "onboarding_session_id": onboarding_id,
        },
    )

    logger.info("Google auth saved for onboarding", onboarding_id=onboarding_id, email=req.email)

    return GoogleAuthResponse(
        success=True,
        message=f"Signed in as {req.name}",
        token=token,
        user={
            "user_id": user_id,
            "provider": "google",
            "email": email,
            "name": req.name,
            "avatar_url": req.avatar_url,
            "onboarding_id": onboarding_id,
            "onboarding_session_id": onboarding_id,
        },
    )


@router.post("/google/exchange", response_model=GoogleAuthResponse)
async def google_exchange_endpoint(req: GoogleExchangeRequest):
    """Verify a Google / Firebase ID token and return a signed JWT."""
    try:
        claims = await verify_google_or_firebase_token(req.idToken)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Token verification failed: {exc}") from exc

    email = str(claims.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=401, detail="Token has no email claim")

    name = str(claims.get("name") or claims.get("display_name") or "").strip()
    avatar_url = str(claims.get("picture") or claims.get("photo_url") or "").strip()
    google_sub = str(claims.get("sub") or claims.get("user_id") or "").strip()
    onboarding_id = (req.onboarding_id or req.session_id or "").strip() or None

    # If link_to_user_id is provided, link email to existing user instead of creating new
    link_uid = (req.link_to_user_id or "").strip()
    if link_uid:
        row = await _link_email_to_user(user_id=link_uid, email=email, name=name)
        if not row:
            raise HTTPException(status_code=400, detail="Failed to link email to user")
    else:
        # Independent auth path: create/update users row with onboarding_session_id reference.
        row = await _upsert_user_from_google(email=email, name=name, onboarding_session_id=onboarding_id)

    user_id = str(row.get("id") or email)
    phone_number = row.get("phone_number") or ""

    # Link the onboarding row to the user if we have both user_id and session_id
    if user_id and onboarding_id:
        try:
            pool = get_pool()
            async with pool.acquire() as conn:
                link_onboarding_q = build_query(
                    PostgreSQLQuery.update(Table("onboarding"))
                    .set(Table("onboarding").user_id, Parameter("%s"))
                    .set(Table("onboarding").updated_at, fn.Now())
                    .where(Table("onboarding").id == Parameter("%s"))
                    .where(
                        Table("onboarding").user_id.isnull()
                        | (Table("onboarding").user_id == Parameter("%s"))
                    ),
                    [user_id, onboarding_id, user_id],
                )
                await conn.execute(link_onboarding_q.sql, *link_onboarding_q.params)
        except Exception as exc:
            logger.warning("Failed to link onboarding to user", error=str(exc), user_id=user_id, onboarding_id=onboarding_id)

    token = create_access_token(
        subject=user_id,
        claims={
            "provider": "google",
            "email": email,
            "name": name,
            "phone_number": phone_number,
            "avatar_url": avatar_url,
            "google_sub": google_sub,
            "onboarding_id": onboarding_id,
            "onboarding_session_id": onboarding_id,
            **(await resolve_admin_flags(email, phone_number)),
        },
    )

    logger.info("Google exchange successful", email=email, has_onboarding=bool(onboarding_id), linked_to_user=bool(link_uid))

    flags = await resolve_admin_flags(email, phone_number)
    return GoogleAuthResponse(
        success=True,
        message=f"Signed in as {name or email}",
        token=token,
        user={
            "user_id": user_id,
            "provider": "google",
            "email": email,
            "name": name,
            "phone_number": phone_number,
            "avatar_url": avatar_url,
            "onboarding_id": onboarding_id,
            "onboarding_session_id": onboarding_id,
        },
        isAdmin=flags.get("admin", False),
        isSuperAdmin=flags.get("super", False),
    )


@router.get("/me", response_model=AuthMeResponse)
async def auth_me_endpoint(authorization: str | None = Header(default=None)):
    token = _parse_bearer_token(authorization)
    try:
        payload = decode_and_verify_access_token(token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {str(exc)}") from exc

    user_id = str(payload.get("sub") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token subject")

    # Fetch fresh user data from database
    pool = get_pool()
    async with pool.acquire() as conn:
        user_row = await users_repo.find_by_id(conn, user_id)

    if not user_row:
        raise HTTPException(status_code=404, detail="User not found")

    email = user_row.get("email")
    if isinstance(email, str):
        email = email.strip().lower() or None
    else:
        email = None

    phone_number = user_row.get("phone_number") or None

    exp = int(payload.get("exp", 0))
    now = int(time.time())
    expires_in_seconds = max(0, exp - now)
    return AuthMeResponse(
        authenticated=True,
        user={
            "user_id": user_id,
            "provider": user_row.get("auth_provider") or payload.get("provider") or "unknown",
            "email": email,
            "phone_number": phone_number,
            "name": user_row.get("name") or payload.get("name"),
            "avatar_url": payload.get("avatar_url"),
            "onboarding_id": payload.get("onboarding_id") or user_row.get("onboarding_session_id") or payload.get("onboarding_session_id"),
            "onboarding_session_id": user_row.get("onboarding_session_id") or payload.get("onboarding_session_id"),
            "expires_in_seconds": expires_in_seconds,
            "token_ttl_hours": get_settings().JWT_ACCESS_TOKEN_EXPIRES_HOURS,
        },
    )
