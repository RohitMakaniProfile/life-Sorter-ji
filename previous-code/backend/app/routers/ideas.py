"""
═══════════════════════════════════════════════════════════════
IDEAS ROUTER — Idea Capture to Google Sheets
═══════════════════════════════════════════════════════════════
POST /api/v1/ideas — Save user ideas via Google Sheets webhook
"""


import structlog
import httpx
from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Optional

from app.config import get_settings
from app.middleware.rate_limit import limiter

logger = structlog.get_logger()

router = APIRouter()


class IdeaRequest(BaseModel):
    """Request body for saving an idea."""
    timestamp: str = ""
    userName: str = Field(default="", description="User's name")
    userEmail: str = Field(default="", description="User's email")
    domain: str = Field(default="", description="Business domain")
    subdomain: str = Field(default="", description="Business subdomain")
    requirement: str = Field(default="", description="User's specific requirement")
    userMessage: str = Field(default="", description="Original user message")
    botResponse: str = Field(default="", description="Bot's response")
    source: str = Field(default="Ikshan Website - New Flow", description="Source identifier")


@router.post("/ideas")
@limiter.limit("10/minute")
async def save_idea(request: Request, body: IdeaRequest = Body(...)):
    """
    Save a user's idea/product request to Google Sheets via webhook.

    The webhook URL must be configured in the GOOGLE_SHEETS_WEBHOOK_URL
    environment variable.
    """
    settings = get_settings()

    if not settings.GOOGLE_SHEETS_WEBHOOK_URL:
        raise HTTPException(
            status_code=503,
            detail="Ideas service unavailable — Google Sheets webhook not configured.",
        )

    try:
        payload = body.model_dump()

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                settings.GOOGLE_SHEETS_WEBHOOK_URL,
                json=payload,
            )

        if response.status_code < 200 or response.status_code >= 300:
            logger.error(
                "Google Sheets webhook failed",
                status=response.status_code,
                response=response.text[:200],
            )
            raise HTTPException(
                status_code=502,
                detail="Failed to save idea to Google Sheets.",
            )

        logger.info(
            "Idea saved to Google Sheets",
            domain=body.domain,
            user_email=body.userEmail,
        )

        return {
            "success": True,
            "message": "Idea saved successfully! We'll review it and get back to you.",
        }

    except httpx.HTTPError as e:
        logger.error("Ideas webhook error", error=str(e))
        raise HTTPException(
            status_code=502,
            detail=f"Failed to save idea: {str(e)}",
        )
