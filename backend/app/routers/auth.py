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
from pydantic import BaseModel, field_validator
from fastapi import APIRouter, HTTPException, Header

import structlog

from app.services.otp_service import send_otp, verify_otp
from app.services.user_session_service import update_session_auth
from app.services.session_store import get_session
from app.services.jwt_service import create_access_token, decode_and_verify_access_token
from app.phase2.stores import promote_session_conversations
from app.db import get_pool
from app.config import get_settings

logger = structlog.get_logger()

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Use 400 (not 404) when the agent session_id is missing from memory so clients do not confuse
# this with "route not found". Sessions are in-process only until replaced by Redis/DB.
_AGENT_SESSION_GONE = (
    "Agent session not found or expired (server restart, wrong id, or different backend "
    "instance). Call POST /api/v1/agent/session first, then retry auth on the same server."
)


# ── Request / Response Models ─────────────────────────────────

class SendOTPRequest(BaseModel):
    session_id: str
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
    session_id: str
    otp_session_id: str
    otp_code: str

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


class GoogleAuthResponse(BaseModel):
    success: bool
    message: str
    token: str | None = None
    user: dict | None = None


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
        if await conn.fetchval("SELECT 1 FROM conversations WHERE user_id = $1 LIMIT 1", user_id):
            return True
        if await conn.fetchval("SELECT 1 FROM session_user_links WHERE user_id = $1 LIMIT 1", user_id):
            return True
        if email and await conn.fetchval("SELECT 1 FROM user_sessions WHERE google_email = $1 LIMIT 1", email):
            return True
    return False


# ── Endpoints ─────────────────────────────────────────────────

@router.post("/send-otp", response_model=SendOTPResponse)
async def send_otp_endpoint(req: SendOTPRequest):
    """Send an OTP to the user's phone number via 2Factor.in."""

    # Ensure session exists
    session = get_session(req.session_id)
    if not session:
        raise HTTPException(status_code=400, detail=_AGENT_SESSION_GONE)

    result = await send_otp(req.phone_number)

    if not result["success"]:
        return SendOTPResponse(
            success=False,
            message=result["error"],
        )

    return SendOTPResponse(
        success=True,
        message="OTP sent successfully",
        otp_session_id=result["session_id"],
    )


@router.post("/verify-otp", response_model=VerifyOTPResponse)
async def verify_otp_endpoint(req: VerifyOTPRequest):
    """Verify the OTP and update the session's auth status."""

    # Ensure session exists
    session = get_session(req.session_id)
    if not session:
        raise HTTPException(status_code=400, detail=_AGENT_SESSION_GONE)

    result = await verify_otp(req.otp_session_id, req.otp_code)

    if not result["success"]:
        return VerifyOTPResponse(
            success=False,
            verified=False,
            message=result["error"],
        )

    if not result["matched"]:
        return VerifyOTPResponse(
            success=True,
            verified=False,
            message="Incorrect OTP — please try again",
        )

    # OTP matched -> persist auth state
    # Extract phone from the send-otp step (stored in session or passed again)
    await update_session_auth(
        session_id=req.session_id,
        otp_verified=True,
        auth_provider="otp",
    )
    user_id = f"otp:{req.session_id}"
    await promote_session_conversations(req.session_id, user_id)
    token = create_access_token(
        subject=user_id,
        claims={
            "provider": "otp",
            "session_id": req.session_id,
        },
    )

    logger.info("OTP verified for session", session_id=req.session_id)

    return VerifyOTPResponse(
        success=True,
        verified=True,
        message="Phone number verified successfully",
        token=token,
        user={
            "user_id": user_id,
            "provider": "otp",
            "email": None,
            "name": "Verified User",
            "session_id": req.session_id,
        },
    )


@router.post("/google", response_model=GoogleAuthResponse)
async def google_auth_endpoint(req: GoogleAuthRequest):
    """Save Google Sign-In data to the session."""

    session = get_session(req.session_id)
    if not session:
        raise HTTPException(status_code=400, detail=_AGENT_SESSION_GONE)

    google_sub = (req.google_id or "").strip()
    if not google_sub:
        raise HTTPException(status_code=400, detail="Missing Google subject (sub)")

    email = req.email.strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Missing email")

    await update_session_auth(
        session_id=req.session_id,
        google_id=google_sub,
        google_email=email,
        google_name=req.name,
        google_avatar_url=req.avatar_url,
        auth_provider="google",
    )
    await promote_session_conversations(req.session_id, email)
    token = create_access_token(
        subject=email,
        claims={
            "provider": "google",
            "email": email,
            "name": req.name,
            "avatar_url": req.avatar_url,
            "session_id": req.session_id,
        },
    )

    logger.info("Google auth saved for session", session_id=req.session_id, email=req.email)

    return GoogleAuthResponse(
        success=True,
        message=f"Signed in as {req.name}",
        token=token,
        user={
            "user_id": email,
            "provider": "google",
            "email": email,
            "name": req.name,
            "avatar_url": req.avatar_url,
            "session_id": req.session_id,
        },
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
            "expires_in_seconds": expires_in_seconds,
            "token_ttl_hours": get_settings().JWT_ACCESS_TOKEN_EXPIRES_HOURS,
        },
    )
