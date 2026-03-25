"""
═══════════════════════════════════════════════════════════════
OTP SERVICE — 2Factor.in SMS OTP Integration
═══════════════════════════════════════════════════════════════
Sends and verifies OTPs via the 2Factor.in REST API.

Endpoints used:
  Send:   GET https://2factor.in/API/V1/{api_key}/SMS/{phone}/AUTOGEN
  Verify: GET https://2factor.in/API/V1/{api_key}/SMS/VERIFY/{session_id}/{otp}
"""

from __future__ import annotations

import httpx
import structlog

from app.config import get_settings

logger = structlog.get_logger()

TWO_FACTOR_BASE = "https://2factor.in/API/V1"


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

    # Normalize: strip spaces/dashes, ensure no leading +
    phone = phone_number.strip().replace(" ", "").replace("-", "")
    if phone.startswith("+"):
        phone = phone[1:]

    url = f"{TWO_FACTOR_BASE}/{api_key}/SMS/{phone}/AUTOGEN"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url)
            data = resp.json()

        if data.get("Status") == "Success":
            logger.info("OTP sent successfully", phone=phone[-4:])
            return {"success": True, "session_id": data["Details"]}
        else:
            logger.warning("2Factor API returned error", detail=data.get("Details"))
            return {"success": False, "error": data.get("Details", "Failed to send OTP")}

    except httpx.TimeoutException:
        logger.error("2Factor API timeout", phone=phone[-4:])
        return {"success": False, "error": "OTP service timeout — please retry"}
    except Exception as e:
        logger.error("2Factor API error", error=str(e))
        return {"success": False, "error": "Failed to send OTP"}


async def verify_otp(session_id: str, otp_code: str) -> dict:
    """
    Verify an OTP entered by the user.

    Args:
        session_id: The session ID returned by send_otp().
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
    sid = session_id.strip()
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
