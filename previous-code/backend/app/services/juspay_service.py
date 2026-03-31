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

from app.config import get_settings

logger = structlog.get_logger()


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

    logger.info(
        "Creating JusPay order",
        order_id=order_id,
        amount=amount,
        customer_id=customer_id,
        environment=settings.JUSPAY_ENVIRONMENT.value,
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        headers = _default_headers()
        headers["x-routing-id"] = customer_id

        response = await client.post(
            f"{settings.juspay_base_url}/orders",
            headers=headers,
            data=payload,
        )

        if response.status_code != 200:
            error_text = response.text
            logger.error(
                "JusPay create order failed",
                status=response.status_code,
                response=error_text[:500],
            )
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


async def verify_payment_for_stage2(order_id: str) -> dict:
    """
    Verify that a payment has been completed for Stage 2 chat access.

    Checks:
      1. Order exists in JusPay
      2. Status is CHARGED (payment completed)
      3. Amount matches expected Stage 2 price

    Args:
        order_id: The JusPay order ID to verify.

    Returns:
        dict with 'verified' bool and details.
    """
    status = await get_order_status(order_id)

    if not status.get("success"):
        return {"verified": False, "reason": "Could not fetch order status"}

    EXPECTED_AMOUNT = 499.0  # ₹499 — must match exactly

    order_status = status.get("status", "").upper()
    paid_amount   = float(status.get("amount") or 0)

    if order_status != "CHARGED":
        logger.warning(
            "Stage 2 payment not completed",
            order_id=order_id,
            status=order_status,
        )
        return {
            "verified": False,
            "reason": f"Order status is {order_status}, expected CHARGED",
            "status": order_status,
        }

    if paid_amount < EXPECTED_AMOUNT:
        logger.warning(
            "Stage 2 payment amount mismatch",
            order_id=order_id,
            paid=paid_amount,
            expected=EXPECTED_AMOUNT,
        )
        return {
            "verified": False,
            "reason": f"Amount paid ₹{paid_amount} is less than required ₹{EXPECTED_AMOUNT}",
            "paid_amount": paid_amount,
        }

    logger.info(
        "Stage 2 payment verified",
        order_id=order_id,
        amount=paid_amount,
    )
    return {
        "verified": True,
        "order_id": order_id,
        "amount": paid_amount,
        "txn_id": status.get("txn_id"),
    }


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
