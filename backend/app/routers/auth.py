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
from app.services.user_session_service import update_session_auth
from app.services.session_store import get_session

logger = structlog.get_logger()

router = APIRouter(prefix="/auth", tags=["Authentication"])


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


class GoogleAuthRequest(BaseModel):
    session_id: str
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

    # Ensure session exists
    session = get_session(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

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
        raise HTTPException(status_code=404, detail="Session not found")

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

    # OTP matched → persist auth to Supabase
    # Extract phone from the send-otp step (stored in session or passed again)
    await update_session_auth(
        session_id=req.session_id,
        otp_verified=True,
        auth_provider="otp",
    )

    logger.info("OTP verified for session", session_id=req.session_id)

    return VerifyOTPResponse(
        success=True,
        verified=True,
        message="Phone number verified successfully",
    )


@router.post("/google", response_model=GoogleAuthResponse)
async def google_auth_endpoint(req: GoogleAuthRequest):
    """Save Google Sign-In data to the session."""

    session = get_session(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    await update_session_auth(
        session_id=req.session_id,
        google_id=req.google_id,
        google_email=req.email,
        google_name=req.name,
        google_avatar_url=req.avatar_url,
        auth_provider="google",
    )

    logger.info("Google auth saved for session", session_id=req.session_id, email=req.email)

    return GoogleAuthResponse(
        success=True,
        message=f"Signed in as {req.name}",
    )
