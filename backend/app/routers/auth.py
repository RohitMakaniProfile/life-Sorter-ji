"""
═══════════════════════════════════════════════════════════════
AUTH ROUTER — OTP-Based 2-Factor Authentication
═══════════════════════════════════════════════════════════════
Endpoints:
  POST /api/v1/auth/send-otp      → Send OTP to phone number
  POST /api/v1/auth/verify-otp    → Verify OTP and mark session
  POST /api/v1/auth/google        → Save Google Sign-In to session
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

logger = structlog.get_logger()

router = APIRouter(prefix="/auth", tags=["Authentication"])

# ── Request / Response Models ─────────────────────────────────

class SendOTPRequest(BaseModel):
    session_id: str | None = None  # backward compatibility (legacy client field)
    onboarding_session_id: str | None = None
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
    otp_session_id: str = ""


class VerifyOTPRequest(BaseModel):
    session_id: str | None = None  # backward compatibility (legacy client field)
    onboarding_session_id: str | None = None
    otp_session_id: str
    otp_code: str
    # Set when Google was Step 1 of two-step verification
    google_email: str | None = None
    google_name: str | None = None

    @field_validator("otp_code")
    @classmethod
    def validate_otp(cls, v: str) -> str:
        code = v.strip()
        if not code.isdigit() or len(code) < 4 or len(code) > 8:
            raise ValueError("OTP must be 4-8 digits")
        return code


class VerifyOTPResponse(BaseModel):
    success: bool
    verified: bool
    message: str
    token: str | None = None
    user: dict | None = None


class GoogleAuthRequest(BaseModel):
    session_id: str
    google_id: str
    email: str
    name: str
    avatar_url: str = ""


class GoogleExchangeRequest(BaseModel):
    idToken: str
    session_id: str | None = None


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
        if await conn.fetchval("SELECT 1 FROM users WHERE id::text = $1 LIMIT 1", user_id):
            return True
        if email and await conn.fetchval("SELECT 1 FROM users WHERE email = $1 LIMIT 1", email):
            return True
        if await conn.fetchval("SELECT 1 FROM conversations WHERE user_id = $1 LIMIT 1", user_id):
            return True
        if await conn.fetchval("SELECT 1 FROM session_user_links WHERE user_id = $1 LIMIT 1", user_id):
            return True
        if email and await conn.fetchval("SELECT 1 FROM users WHERE email = $1 LIMIT 1", email):
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
        existing = await conn.fetchrow(
            """
            SELECT id::text AS id, phone_number, email, name, auth_provider, onboarding_session_id
            FROM users
            WHERE phone_number = $1
            LIMIT 1
            """,
            phone,
        )
        if existing:
            provider_now = str(existing.get("auth_provider") or "otp")
            next_provider = "both" if provider_now == "google" else "otp"
            row = await conn.fetchrow(
                """
                UPDATE users
                SET last_login_at = NOW(),
                    auth_provider = $1,
                    onboarding_session_id = COALESCE($2, onboarding_session_id),
                    updated_at = NOW()
                WHERE id = $3::uuid
                RETURNING id::text AS id, phone_number, email, name, auth_provider, onboarding_session_id
                """,
                next_provider,
                sid,
                str(existing.get("id") or ""),
            )
        else:
            row = await conn.fetchrow(
                """
                INSERT INTO users (phone_number, name, auth_provider, onboarding_session_id, last_login_at)
                VALUES ($1, '', 'otp', $2, NOW())
                RETURNING id::text AS id, phone_number, email, name, auth_provider, onboarding_session_id
                """,
                phone,
                sid,
            )
    return dict(row) if row else {}


async def _upsert_user_from_google(email: str, name: str, onboarding_session_id: str | None) -> dict:
    pool = get_pool()
    em = (email or "").strip().lower()
    sid = (onboarding_session_id or "").strip() or None
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            """
            SELECT id::text AS id, phone_number, email, name, auth_provider, onboarding_session_id
            FROM users
            WHERE email = $1
            LIMIT 1
            """,
            em,
        )
        if existing:
            provider_now = str(existing.get("auth_provider") or "google")
            next_provider = "both" if provider_now == "otp" else "google"
            row = await conn.fetchrow(
                """
                UPDATE users
                SET name = COALESCE($1, name),
                    auth_provider = $2,
                    onboarding_session_id = COALESCE($3, onboarding_session_id),
                    last_login_at = NOW(),
                    updated_at = NOW()
                WHERE id = $4::uuid
                RETURNING id::text AS id, phone_number, email, name, auth_provider, onboarding_session_id
                """,
                name,
                next_provider,
                sid,
                str(existing.get("id") or ""),
            )
        else:
            row = await conn.fetchrow(
                """
                INSERT INTO users (email, name, auth_provider, onboarding_session_id, last_login_at)
                VALUES ($1, $2, 'google', $3, NOW())
                RETURNING id::text AS id, phone_number, email, name, auth_provider, onboarding_session_id
                """,
                em,
                name,
                sid,
            )
    return dict(row) if row else {}


# ── Endpoints ─────────────────────────────────────────────────

@router.post("/send-otp", response_model=SendOTPResponse)
async def send_otp_endpoint(req: SendOTPRequest):
    """Independent OTP send: stores OTP in Redis, optionally sends SMS via 2Factor."""
    flags = await _otp_runtime_flags()
    otp_bypass_enabled = bool(flags["otp_bypass_enabled"])
    otp_send_sms_enabled = bool(flags["otp_send_sms_enabled"])
    otp_expiry_seconds = int(flags["otp_expiry_seconds"])
    otp_bypass_code = str(flags["otp_bypass_code"])

    onboarding_session_id = (req.onboarding_session_id or req.session_id or "").strip() or None
    otp_session_id = str(uuid.uuid4())
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
        otp_session_id=otp_session_id,
        phone_number=req.phone_number,
        otp_code=otp_code,
        onboarding_session_id=onboarding_session_id,
        expiry_seconds=otp_expiry_seconds,
        provider_session_id=str(sms_result.get("session_id") or ""),
    )

    return SendOTPResponse(success=True, message="OTP sent successfully", otp_session_id=otp_session_id)


@router.post("/verify-otp", response_model=VerifyOTPResponse)
async def verify_otp_endpoint(req: VerifyOTPRequest):
    """Verify OTP (Redis or Postgres otp_sessions), upsert user row, and issue JWT."""
    flags = await _otp_runtime_flags()
    otp_bypass_enabled = bool(flags["otp_bypass_enabled"])
    otp_bypass_code = str(flags["otp_bypass_code"])

    rec = await load_otp_from_redis(req.otp_session_id)
    if not rec:
        return VerifyOTPResponse(success=False, verified=False, message="OTP expired or invalid session")

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

    onboarding_session_id = (req.onboarding_session_id or req.session_id or rec.get("onboarding_session_id") or "").strip() or None
    phone_number = str(rec.get("phone_number") or "").strip()
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
                await conn.execute(
                    """
                    UPDATE onboarding
                    SET user_id = $1::uuid,
                        updated_at = NOW()
                    WHERE session_id = $2 AND (user_id IS NULL OR user_id = $1::uuid)
                    """,
                    user_id,
                    onboarding_session_id,
                )
        except Exception as exc:
            logger.warning("Failed to link onboarding to user", error=str(exc), user_id=user_id, session_id=onboarding_session_id)

    token = create_access_token(
        subject=user_id,
        claims={
            "provider": provider,
            "email": email,
            "name": name,
            "phone_number": phone_number,
            "onboarding_session_id": onboarding_session_id,
            **(await resolve_admin_flags(email)),
        },
    )
    await delete_otp_from_redis(req.otp_session_id)

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

    row = await _upsert_user_from_google(email=email, name=req.name, onboarding_session_id=req.session_id)
    user_id = str(row.get("id") or email)
    token = create_access_token(
        subject=user_id,
        claims={
            "provider": "google",
            "email": email,
            "name": req.name,
            "avatar_url": req.avatar_url,
            "google_sub": google_sub,
            "onboarding_session_id": req.session_id,
        },
    )

    logger.info("Google auth saved for session", session_id=req.session_id, email=req.email)

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
            "onboarding_session_id": req.session_id,
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

    # Independent auth path: create/update users row with onboarding_session_id reference.
    row = await _upsert_user_from_google(email=email, name=name, onboarding_session_id=req.session_id)
    user_id = str(row.get("id") or email)

    # Link the onboarding row to the user if we have both user_id and session_id
    if user_id and req.session_id:
        try:
            pool = get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE onboarding
                    SET user_id = $1::uuid,
                        updated_at = NOW()
                    WHERE session_id = $2 AND (user_id IS NULL OR user_id = $1::uuid)
                    """,
                    user_id,
                    req.session_id,
                )
        except Exception as exc:
            logger.warning("Failed to link onboarding to user", error=str(exc), user_id=user_id, session_id=req.session_id)

    token = create_access_token(
        subject=user_id,
        claims={
            "provider": "google",
            "email": email,
            "name": name,
            "avatar_url": avatar_url,
            "google_sub": google_sub,
            "onboarding_session_id": req.session_id,
            **(await resolve_admin_flags(email)),
        },
    )

    logger.info("Google exchange successful", email=email, has_session=bool(req.session_id))

    flags = await resolve_admin_flags(email)
    return GoogleAuthResponse(
        success=True,
        message=f"Signed in as {name or email}",
        token=token,
        user={
            "user_id": user_id,
            "provider": "google",
            "email": email,
            "name": name,
            "avatar_url": avatar_url,
            "onboarding_session_id": req.session_id,
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

    email = payload.get("email")
    if isinstance(email, str):
        email = email.strip().lower() or None
    else:
        email = None

    if not await _user_exists(user_id, email):
        raise HTTPException(status_code=404, detail="User not found")

    exp = int(payload.get("exp", 0))
    now = int(time.time())
    expires_in_seconds = max(0, exp - now)
    return AuthMeResponse(
        authenticated=True,
        user={
            "user_id": user_id,
            "provider": payload.get("provider") or "unknown",
            "email": email,
            "name": payload.get("name"),
            "avatar_url": payload.get("avatar_url"),
            "session_id": payload.get("session_id"),
            "onboarding_session_id": payload.get("onboarding_session_id"),
            "expires_in_seconds": expires_in_seconds,
            "token_ttl_hours": get_settings().JWT_ACCESS_TOKEN_EXPIRES_HOURS,
        },
    )
