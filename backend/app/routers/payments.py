"""
═══════════════════════════════════════════════════════════════
PAYMENTS ROUTER — JusPay + plan catalog checkout
═══════════════════════════════════════════════════════════════
POST /api/v1/payments/create-order     — JusPay order (Bearer JWT; plan_slug; binds checkout to users.id)
GET  /api/v1/payments/entitlements     — user grants + capabilities (Bearer JWT)
POST /api/v1/payments/complete         — verify payment + insert user_plan_grants (Bearer JWT)
POST /api/v1/payments/webhook          — receive & verify webhook
GET  /api/v1/payments/status/{id}      — check order status
POST /api/v1/payments/refund           — initiate refund
"""

# Note: Do NOT use `from __future__ import annotations` here — it breaks

import structlog
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.config import get_settings
from app.middleware.auth_context import require_request_user
from app.middleware.rate_limit import limiter
from app.middleware.security import verify_juspay_signature
from app.models.payment import (
    CapabilityState,
    CreateOrderRequest,
    CreateOrderResponse,
    PaymentCompleteRequest,
    PaymentStatusResponse,
    PaymentVerification,
    PlanGrantSummary,
    RefundRequest,
    UserEntitlementsResponse,
    WebhookPayload,
)
from app.services import juspay_service, payment_entitlement_service

logger = structlog.get_logger()

router = APIRouter()


@router.get("/payments/entitlements", response_model=UserEntitlementsResponse)
@limiter.limit("60/minute")
async def user_entitlements(request: Request):
    """
    Plans granted to the authenticated user (JWT), merged capabilities, and credit pools (NULL = unlimited).
    """
    user = require_request_user(request)
    uid = str(user.get("id") or "").strip()
    raw = await payment_entitlement_service.get_user_entitlements(user_id=uid)
    caps = {k: CapabilityState(**v) for k, v in raw.get("capabilities", {}).items()}
    grants = [PlanGrantSummary(**g) for g in raw.get("grants", [])]
    return UserEntitlementsResponse(
        user_id=raw["user_id"],
        grants=grants,
        capabilities=caps,
    )


@router.post("/payments/complete", response_model=dict)
@limiter.limit("20/minute")
async def complete_plan_checkout(request: Request, body: PaymentCompleteRequest = Body(...)):
    """
    After JusPay redirect: verify payment and insert a plan grant (same user as checkout; JWT required).
    """
    settings = get_settings()
    if not settings.JUSPAY_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Payment service unavailable — JusPay not configured.",
        )

    user = require_request_user(request)
    uid = str(user.get("id") or "").strip()

    ok, err = await payment_entitlement_service.complete_plan_purchase(
        user_id=uid,
        order_id=body.order_id,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=err or "Could not complete payment")
    return {"success": True}


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

    Requires `Authorization: Bearer` and `plan_slug`. Amount and checkout binding use `plans` + `users.id`.
    """
    settings = get_settings()

    if not settings.JUSPAY_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="Payment service unavailable — JusPay not configured.",
        )

    user = require_request_user(request)
    uid = str(user.get("id") or "").strip()

    slug = (body.plan_slug or "").strip()
    if not slug:
        raise HTTPException(
            status_code=400,
            detail="plan_slug is required.",
        )

    from app.services import plan_catalog_service as _plan_catalog

    plan = await _plan_catalog.fetch_plan_by_slug(slug)
    if not plan:
        raise HTTPException(status_code=404, detail=f"Unknown or inactive plan: {slug}")

    amount_str = str(plan["price_inr"])
    desc = (body.description or "").strip() or str(plan.get("name") or slug)
    udf1 = slug

    extra_udf2 = (body.udf2 or "").strip()
    user_tag = f"user:{uid}"
    udf2_val = f"{user_tag}|{extra_udf2}" if extra_udf2 else user_tag

    result = await juspay_service.create_order(
        amount=amount_str,
        customer_id=uid,
        customer_email=(body.customer_email or "").strip() or str(user.get("email") or ""),
        customer_phone=(body.customer_phone or "").strip() or str(user.get("phone_number") or ""),
        return_url=body.return_url,
        description=desc,
        udf1=udf1,
        udf2=udf2_val,
    )

    if not result.get("success"):
        raise HTTPException(
            status_code=502,
            detail=result.get("error", "Failed to create order"),
        )

    order_id = result.get("order_id")
    if order_id:
        try:
            await payment_entitlement_service.save_checkout_context(
                order_id=str(order_id),
                user_id=uid,
                plan_id=str(plan["id"]),
            )
        except Exception as e:
            logger.error(
                "payment_checkout_context insert failed",
                order_id=order_id,
                error=str(e),
            )
            raise HTTPException(
                status_code=500,
                detail="Could not record checkout. Please try again.",
            ) from e

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
