"""
═══════════════════════════════════════════════════════════════
OTP SERVICE — 2Factor.in SMS OTP
═══════════════════════════════════════════════════════════════
Sends and verifies OTP via 2Factor.in REST API.

Endpoint (confirmed by 2Factor support):
  Send:   GET https://2factor.in/API/V1/{api_key}/SMS/{phone}/AUTOGEN/aiplaybook
  Verify: GET https://2factor.in/API/V1/{api_key}/SMS/VERIFY/{session_id}/{otp}

DLT Details:
  Sender ID:   IKSNAI
  PE ID:       1101400090000093353
  CT ID:       1107177445600375949
"""

from __future__ import annotations

import httpx
import structlog

from app.config import get_settings

logger = structlog.get_logger()

TWO_FACTOR_BASE = "https://2factor.in/API/V1"


def _normalize_phone(phone_number: str) -> str:
    """Normalize to +91XXXXXXXXXX format."""
    phone = phone_number.strip().replace(" ", "").replace("-", "")
    if phone.startswith("+"):
        phone = phone[1:]
    if phone.startswith("91") and len(phone) == 12:
        return f"+{phone}"
    if len(phone) == 10:
        return f"+91{phone}"
    return f"+{phone}"


async def send_otp(phone_number: str) -> dict:
    """Send OTP via 2Factor AUTOGEN with DLT template."""
    settings = get_settings()
    api_key = settings.TWO_FACTOR_API_KEY

    if not api_key:
        logger.error("2Factor API key not configured")
        return {"success": False, "error": "OTP service not configured"}

    phone = _normalize_phone(phone_number)
    url = f"{TWO_FACTOR_BASE}/{api_key}/SMS/{phone}/AUTOGEN/aiplaybook"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            logger.info("2Factor AUTOGEN call", phone=phone[-4:])
            resp = await client.get(url)
            data = resp.json()
            logger.info("2Factor response", status_code=resp.status_code, body=data)

        if data.get("Status") == "Success":
            logger.info("OTP sent successfully", phone=phone[-4:])
            return {"success": True, "session_id": data["Details"]}
        else:
            logger.warning("2Factor error", detail=data.get("Details"))
            return {"success": False, "error": data.get("Details", "Failed to send OTP")}

    except httpx.TimeoutException:
        logger.error("2Factor timeout", phone=phone[-4:])
        return {"success": False, "error": "OTP service timeout — please retry"}
    except Exception as e:
        logger.error("2Factor error", error=str(e))
        return {"success": False, "error": "Failed to send OTP"}


async def verify_otp(session_id: str, otp_code: str) -> dict:
    """Verify OTP via 2Factor VERIFY endpoint."""
    settings = get_settings()
    api_key = settings.TWO_FACTOR_API_KEY

    if not api_key:
        return {"success": False, "error": "OTP service not configured"}

    code = otp_code.strip()
    sid = session_id.strip()

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
