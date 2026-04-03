"""
═══════════════════════════════════════════════════════════════
JUSPAY SERVICE — Payment Gateway Integration
═══════════════════════════════════════════════════════════════
Complete JusPay payment lifecycle:
  • Create Order → returns client_auth_token for SDK
  • Get Order Status → verify payment completion
  • Process Refund → initiate refund via API
  • Webhook verification → HMAC-SHA256 (in middleware/security.py)
"""

from __future__ import annotations

import base64
import uuid
from typing import Optional

import httpx
import structlog

from app.config import Settings, get_settings

logger = structlog.get_logger()


def _juspay_diagnostics(settings: Settings) -> dict:
    """
    Safe fields for debugging 401 / env mismatches (never log full API key).
    """
    key = settings.JUSPAY_API_KEY or ""
    stripped = key.strip()
    tail = stripped[-4:] if len(stripped) >= 4 else ("****" if stripped else "")
    return {
        "juspay_base_url": settings.juspay_base_url,
        "juspay_post_orders_url": f"{settings.juspay_base_url}/orders",
        "juspay_environment": settings.JUSPAY_ENVIRONMENT.value,
        "juspay_merchant_id": (settings.JUSPAY_MERCHANT_ID or "").strip() or "(empty)",
        "juspay_payment_page_client_id_set": bool((settings.JUSPAY_PAYMENT_PAGE_CLIENT_ID or "").strip()),
        "juspay_api_key_length": len(key),
        "juspay_api_key_stripped_length": len(stripped),
        "juspay_api_key_tail": tail,
        "juspay_api_key_has_leading_or_trailing_space": key != stripped,
        "juspay_api_key_has_newline": "\n" in key or "\r" in key,
        "juspay_api_key_configured": bool(stripped),
    }


def _auth_header() -> str:
    """
    Build Basic Auth header for JusPay API.
    Format: Base64(API_KEY:)  (empty password)
    """
    settings = get_settings()
    credentials = f"{settings.JUSPAY_API_KEY}:"
    encoded = base64.b64encode(credentials.encode("utf-8")).decode("utf-8")
    return f"Basic {encoded}"


def _default_headers() -> dict:
    """Common headers for all JusPay API calls."""
    settings = get_settings()
    return {
        "Authorization": _auth_header(),
        "x-merchantid": settings.JUSPAY_MERCHANT_ID,
        "Content-Type": "application/x-www-form-urlencoded",
    }


# ── Create Order ───────────────────────────────────────────────


async def create_order(
    amount: str,
    customer_id: str,
    customer_email: str,
    customer_phone: str = "",
    return_url: str = "",
    description: str = "",
    udf1: str = "",
    udf2: str = "",
) -> dict:
    """
    Create a JusPay order and return the client_auth_token.

    The client_auth_token is used by the frontend SDK to initiate
    the payment flow. It is valid for 15 minutes.

    Args:
        amount: Payment amount as string (e.g., "499.00").
        customer_id: Unique customer identifier.
        customer_email: Customer email address.
        customer_phone: Customer phone number.
        return_url: URL to redirect after payment completion.
        description: Order description.
        udf1: User-defined field 1 (e.g., stage_2_chat).
        udf2: User-defined field 2 (e.g., session_id).

    Returns:
        dict with order_id, client_auth_token, status, and payment_links.
    """
    settings = get_settings()
    order_id = f"ikshan_{uuid.uuid4().hex[:16]}"

    payload = {
        "order_id": order_id,
        "amount": amount,
        "customer_id": customer_id,
        "customer_email": customer_email,
        "customer_phone": customer_phone,
        "return_url": return_url,
        "description": description or "Ikshan Stage 2 — Premium AI Chat",
        "udf1": udf1,
        "udf2": udf2,
    }

    diag = _juspay_diagnostics(settings)
    logger.info(
        "Creating JusPay order",
        order_id=order_id,
        amount=amount,
        customer_id=customer_id,
        **diag,
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        headers = _default_headers()
        headers["x-routing-id"] = customer_id
        post_url = f"{settings.juspay_base_url}/orders"

        response = await client.post(
            post_url,
            headers=headers,
            data=payload,
        )

        if response.status_code != 200:
            error_text = response.text
            log_kw = {
                "status": response.status_code,
                "response": error_text[:800],
                **diag,
                "request_url": post_url,
            }
            if response.status_code == 401:
                log_kw["hint"] = (
                    "401 UNAUTHORIZED: API key rejected for this host. "
                    "Use UAT keys from HDFC SmartGateway dashboard with JUSPAY_BASE_URL=https://smartgateway.hdfcuat.bank.in; "
                    "production keys only work with https://smartgateway.hdfc.bank.in. "
                    "Strip whitespace/newlines from JUSPAY_API_KEY in .env if lengths differ."
                )
            logger.error("JusPay create order failed", **log_kw)
            return {
                "success": False,
                "error": f"JusPay API error: {response.status_code}",
                "details": error_text[:500],
            }

        data = response.json()

        logger.info(
            "JusPay order created",
            order_id=data.get("order_id"),
            status=data.get("status"),
        )

        return {
            "success": True,
            "order_id": data.get("order_id"),
            "client_auth_token": data.get("client_auth_token"),
            "status": data.get("status"),
            "payment_links": data.get("payment_links", {}),
            "sdk_payload": data.get("sdk_payload", {}),
        }


# ── Get Order Status ───────────────────────────────────────────


async def get_order_status(order_id: str) -> dict:
    """
    Check the status of a JusPay order.

    Always verify order status server-side before granting access
    to paid features (Stage 2 chat).

    Args:
        order_id: The JusPay order ID.

    Returns:
        dict with order status, amount, transaction details.
    """
    settings = get_settings()

    headers = _default_headers()
    headers["x-routing-id"] = order_id

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{settings.juspay_base_url}/orders/{order_id}",
            headers=headers,
        )

        if response.status_code != 200:
            logger.error(
                "JusPay order status check failed",
                order_id=order_id,
                status=response.status_code,
            )
            return {
                "success": False,
                "error": f"Failed to fetch order status: {response.status_code}",
            }

        data = response.json()

        return {
            "success": True,
            "order_id": data.get("order_id"),
            "status": data.get("status"),
            "amount": str(data.get("amount")) if data.get("amount") is not None else None,
            "currency": data.get("currency", "INR"),
            "customer_id": data.get("customer_id"),
            "customer_email": data.get("customer_email"),
            "txn_id": data.get("txn_id"),
            "payment_method": data.get("payment_method"),
            "payment_method_type": data.get("payment_method_type"),
            "refunds": data.get("refunds", []),
        }


# ── Verify Payment for Stage 2 Access ─────────────────────────


async def verify_charged_order(order_id: str, minimum_amount_inr: float) -> dict:
    """
    Verify that a JusPay order is CHARGED and paid amount is at least minimum_amount_inr.

    Use plan-specific `minimum_amount_inr` from the catalog when completing a purchase.
    """
    from decimal import Decimal

    status = await get_order_status(order_id)

    if not status.get("success"):
        return {"verified": False, "reason": "Could not fetch order status"}

    order_status = status.get("status", "").upper()
    raw_amt = status.get("amount")
    try:
        paid_amount = Decimal(str(raw_amt or 0))
    except Exception:
        paid_amount = Decimal(0)

    minimum = Decimal(str(minimum_amount_inr))

    if order_status != "CHARGED":
        logger.warning(
            "JusPay order not charged",
            order_id=order_id,
            status=order_status,
        )
        return {
            "verified": False,
            "reason": f"Order status is {order_status}, expected CHARGED",
            "status": order_status,
        }

    if paid_amount < minimum:
        logger.warning(
            "JusPay payment amount below minimum",
            order_id=order_id,
            paid=str(paid_amount),
            minimum=str(minimum),
        )
        return {
            "verified": False,
            "reason": f"Amount paid ₹{paid_amount} is less than required ₹{minimum}",
            "paid_amount": float(paid_amount),
        }

    logger.info(
        "JusPay order verified",
        order_id=order_id,
        amount=str(paid_amount),
    )
    return {
        "verified": True,
        "order_id": order_id,
        "amount": float(paid_amount),
        "txn_id": status.get("txn_id"),
    }


async def verify_payment_for_stage2(order_id: str) -> dict:
    """
    Legacy Stage 2 gate (₹499 minimum). Prefer plan-based verification for new flows.
    """
    return await verify_charged_order(order_id, 499.0)


# ── Refund ─────────────────────────────────────────────────────


async def process_refund(
    order_id: str,
    amount: Optional[str] = None,
    unique_request_id: Optional[str] = None,
) -> dict:
    """
    Initiate a refund for a JusPay order.

    Args:
        order_id: The JusPay order ID to refund.
        amount: Refund amount (optional — full refund if omitted).
        unique_request_id: Idempotency key for the refund.

    Returns:
        dict with refund status.
    """
    settings = get_settings()
    request_id = unique_request_id or f"refund_{uuid.uuid4().hex[:12]}"

    payload = {
        "order_id": order_id,
        "unique_request_id": request_id,
    }
    if amount:
        payload["amount"] = amount

    logger.info("Initiating JusPay refund", order_id=order_id, amount=amount)

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{settings.juspay_base_url}/orders/{order_id}/refunds",
            headers=_default_headers(),
            json=payload,
        )

        if response.status_code != 200:
            logger.error(
                "JusPay refund failed",
                order_id=order_id,
                status=response.status_code,
            )
            return {
                "success": False,
                "error": f"Refund failed: {response.status_code}",
            }

        data = response.json()

        return {
            "success": True,
            "order_id": order_id,
            "refund_id": data.get("id"),
            "refund_status": data.get("status"),
            "amount": data.get("amount"),
        }
