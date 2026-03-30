"""
═══════════════════════════════════════════════════════════════
CHAT ROUTER — 2-Stage AI Chat with JusPay Payment Gating
═══════════════════════════════════════════════════════════════
"""

# REMOVED: from __future__ import annotations
import structlog
from fastapi import APIRouter, Body, HTTPException, Request

from app.config import get_settings
from app.middleware.rate_limit import limiter
from app.models.chat import ChatRequest, ChatResponse
from app.services import openai_service, juspay_service

logger = structlog.get_logger()
router = APIRouter()

@router.post("/chat", response_model=ChatResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_CHAT)
async def chat(request: Request, body: ChatRequest = Body(...)):
    """
    AI-powered chat endpoint with persona support and 2-stage gating.
    """
    settings = get_settings()

    if not settings.openai_api_key_active:
        raise HTTPException(
            status_code=503,
            detail="Chat service unavailable — OpenAI API key not configured.",
        )

    # ── Stage 2 Payment Gate ───────────────────────────────────
    if body.stage == 2:
        if not body.payment_order_id:
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "Payment required for Stage 2 chat",
                    "message": "Please complete payment to access premium features.",
                    "action": "create_order",
                },
            )

        verification = await juspay_service.verify_payment_for_stage2(
            body.payment_order_id,
        )
        if not verification.get("verified"):
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "Payment not verified",
                    "reason": verification.get("reason", "Unknown"),
                    "status": verification.get("status"),
                },
            )

    # ── Build context and history ──────────────────────────────
    context = body.context.model_dump() if body.context else None
    history = [msg.model_dump() for msg in body.conversationHistory] if body.conversationHistory else None

    # ── Call OpenAI ────────────────────────────────────────────
    try:
        result = await openai_service.chat_completion(
            message=body.message,
            persona=body.persona.value,
            context=context,
            conversation_history=history,
        )

        return ChatResponse(
            message=result["message"],
            usage=result.get("usage"),
        )

    except Exception as e:
        logger.error("Chat completion failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Chat service error: {str(e)}",
        )