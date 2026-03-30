"""
═══════════════════════════════════════════════════════════════
PAYMENTS ROUTER — JusPay Payment Lifecycle
═══════════════════════════════════════════════════════════════
POST /api/v1/payments/create-order   — create JusPay order
POST /api/v1/payments/webhook        — receive & verify webhook
GET  /api/v1/payments/status/{id}    — check order status
POST /api/v1/payments/refund         — initiate refund
"""

# Note: Do NOT use `from __future__ import annotations` here — it breaks

import structlog
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.config import get_settings
from app.middleware.rate_limit import limiter
from app.middleware.security import verify_juspay_signature
from app.models.payment import (
    CreateOrderRequest,
    CreateOrderResponse,
    PaymentStatusResponse,
    PaymentVerification,
    RefundRequest,
    WebhookPayload,
)
from app.services import juspay_service

logger = structlog.get_logger()

router = APIRouter()


@router.post("/payments/callback")
async def payment_callback(request: Request):
    """
    Handle JusPay/HDFC POST redirect after payment.
    JusPay POSTs to return_url — we convert it to a GET redirect to the frontend.
    Passes the actual payment status (not hardcoded success).
    """
    settings = get_settings()
    form_data = await request.form()
    order_id = form_data.get("order_id") or request.query_params.get("order_id", "")
    status = form_data.get("status") or request.query_params.get("status", "")

    logger.info("Payment callback received", order_id=order_id, status=status)

    # Pass actual status from JusPay — do NOT hardcode "success"
    safe_status = status.lower() if status else "unknown"
    frontend_url = f"{settings.FRONTEND_URL}?payment_status={safe_status}&order_id={order_id}"
    return RedirectResponse(url=frontend_url, status_code=303)


@router.post("/payments/create-order", response_model=CreateOrderResponse)
@limiter.limit("10/minute")
async def create_order(request: Request, body: CreateOrderRequest = Body(...)):
    """
    Create a JusPay payment order.

    Returns a `client_auth_token` that the frontend uses to initialize
    the JusPay payment SDK. The token is valid for 15 minutes.
    """
    settings = get_settings()

    if not settings.JUSPAY_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Payment service unavailable — JusPay not configured.",
        )

    result = await juspay_service.create_order(
        amount=str(body.amount),
        customer_id=body.customer_id,
        customer_email=body.customer_email,
        customer_phone=body.customer_phone,
        return_url=body.return_url,
        description=body.description,
        udf1=body.udf1,
        udf2=body.udf2,
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=502,
            detail=result.get("error", "Failed to create order"),
        )

    return CreateOrderResponse(**result)


@router.post("/payments/webhook")
async def payment_webhook(request: Request, body: WebhookPayload = Body(...)):
    """
    Receive and verify JusPay webhook callbacks.

    Verifies the HMAC-SHA256 signature using the Response Key,
    then processes the payment status update.
    """
    settings = get_settings()

    if not settings.JUSPAY_RESPONSE_KEY:
        raise HTTPException(
            status_code=503,
            detail="Webhook verification unavailable — Response Key not configured.",
        )

    # Get the full payload as dict (including extra fields)
    payload = body.model_dump()

    # Verify signature
    if not body.signature:
        raise HTTPException(
            status_code=400,
            detail="Missing signature in webhook payload.",
        )

    is_valid = verify_juspay_signature(
        payload=payload,
        received_signature=body.signature,
        response_key=settings.JUSPAY_RESPONSE_KEY,
    )

    if not is_valid:
        logger.warning(
            "Webhook signature verification failed",
            order_id=body.order_id,
        )
        raise HTTPException(
            status_code=403,
            detail="Invalid webhook signature.",
        )

    # Process the verified webhook
    logger.info(
        "Verified JusPay webhook received",
        order_id=body.order_id,
        status=body.status,
        txn_id=body.txn_id,
    )

    # TODO: Update order status in database
    # TODO: Trigger Stage 2 access if status == "CHARGED"

    return {
        "success": True,
        "message": "Webhook received and verified",
        "order_id": body.order_id,
        "status": body.status,
    }


@router.get("/payments/status/{order_id}", response_model=PaymentStatusResponse)
@limiter.limit("20/minute")
async def check_order_status(request: Request, order_id: str):
    """
    Check the status of a JusPay order.

    Use this to verify payment completion before granting Stage 2 access.
    """
    settings = get_settings()

    if not settings.JUSPAY_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Payment service unavailable — JusPay not configured.",
        )

    result = await juspay_service.get_order_status(order_id)

    if not result.get("success"):
        raise HTTPException(
            status_code=502,
            detail=result.get("error", "Failed to check order status"),
        )

    return PaymentStatusResponse(**result)


@router.post("/payments/verify-stage2", response_model=PaymentVerification)
@limiter.limit("10/minute")
async def verify_stage2_payment(request: Request, body: dict = Body(...)):
    """
    Verify payment for Stage 2 chat access.

    Checks that the order status is CHARGED (payment completed).
    """
    order_id = body.get("order_id", "")
    if not order_id:
        raise HTTPException(status_code=400, detail="order_id is required")
    result = await juspay_service.verify_payment_for_stage2(order_id)
    return PaymentVerification(**result)


@router.post("/payments/refund")
@limiter.limit("5/minute")
async def initiate_refund(request: Request, body: RefundRequest = Body(...)):
    """
    Initiate a refund for a JusPay order.

    Supports both full and partial refunds.
    """
    settings = get_settings()

    if not settings.JUSPAY_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Payment service unavailable.",
        )

    result = await juspay_service.process_refund(
        order_id=body.order_id,
        amount=body.amount,
        unique_request_id=body.unique_request_id,
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=502,
            detail=result.get("error", "Refund failed"),
        )

    return result
