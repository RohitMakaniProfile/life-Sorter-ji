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
from pydantic import BaseModel, field_validator
from fastapi import APIRouter, HTTPException

import structlog

from app.services.otp_service import send_otp, verify_otp
from app.services.users_service import get_or_create_user_by_phone
from app.phase2.auth_google import issue_phase2_jwt

logger = structlog.get_logger()

router = APIRouter(prefix="/auth", tags=["Authentication"])
_OTP_PHONE_BY_SESSION: dict[str, str] = {}


# ── Request / Response Models ─────────────────────────────────

class SendOTPRequest(BaseModel):
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
    session_id: str | None = None
    phone_number: str | None = None
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
    token: str = ""
    user_id: str = ""


class GoogleAuthRequest(BaseModel):
    google_id: str
    email: str
    name: str
    avatar_url: str = ""


class GoogleAuthResponse(BaseModel):
    success: bool
    message: str


# ── Endpoints ─────────────────────────────────────────────────

@router.post("/send-otp", response_model=SendOTPResponse)
async def send_otp_endpoint(req: SendOTPRequest):
    """Send an OTP to the user's phone number via 2Factor.in."""

    result = await send_otp(req.phone_number)

    if not result["success"]:
        return SendOTPResponse(
            success=False,
            message=result["error"],
        )

    _OTP_PHONE_BY_SESSION[result["session_id"]] = req.phone_number
    return SendOTPResponse(
        success=True,
        message="OTP sent successfully",
        otp_session_id=result["session_id"],
    )


@router.post("/verify-otp", response_model=VerifyOTPResponse)
async def verify_otp_endpoint(req: VerifyOTPRequest):
    """Verify the OTP and update the session's auth status."""

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

    phone = (req.phone_number or "").strip()
    if not phone:
        phone = _OTP_PHONE_BY_SESSION.get(req.otp_session_id, "").strip()
    if not phone:
        raise HTTPException(status_code=400, detail="phone_number is required")

    user_id = await get_or_create_user_by_phone(phone)
    otp_email = f"otp:{phone}@ikshan.local"
    token = issue_phase2_jwt(
        user_id=user_id,
        email=otp_email,
        is_admin=False,
        is_super_admin=False,
    )

    logger.info("OTP verified and JWT issued", user_id=user_id)

    return VerifyOTPResponse(
        success=True,
        verified=True,
        message="Phone number verified successfully",
        token=token,
        user_id=user_id,
    )


@router.post("/google", response_model=GoogleAuthResponse)
async def google_auth_endpoint(req: GoogleAuthRequest):
    """Legacy endpoint retained for compatibility (session system removed)."""
    logger.info("Legacy /auth/google called in sessionless mode", email=req.email)

    return GoogleAuthResponse(
        success=True,
        message=f"Signed in as {req.name}",
    )
