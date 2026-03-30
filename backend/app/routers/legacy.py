"""
Legacy API Compatibility Routes
"""

import structlog
import httpx
from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional, List, Dict, Any

from app.config import get_settings
from app.services import sheets_service, unified_chat_service

logger = structlog.get_logger()
router = APIRouter()

# ── Legacy Models ──────────────────────────────────────────────

class LegacyChatRequest(BaseModel):
    message: str
    persona: str = "assistant"
    context: Optional[Dict[str, Any]] = None
    conversationHistory: Optional[List[Dict[str, Any]]] = None
    conversationId: Optional[str] = None
    sessionId: Optional[str] = None
    userId: Optional[str] = None

class LegacySearchRequest(BaseModel):
    domain: str = ""
    subdomain: str = ""
    requirement: str = ""
    goal: str = ""
    role: str = ""
    userContext: Optional[Dict[str, Any]] = None

class LegacySaveIdeaRequest(BaseModel):
    userMessage: str = ""
    botResponse: str = ""
    timestamp: str = ""
    userName: str = ""
    userEmail: str = ""
    domain: str = ""
    subdomain: str = ""
    requirement: str = ""
    source: str = "Ikshan Website - New Flow"

# Force Pydantic to resolve types immediately for Python 3.13
LegacyChatRequest.model_rebuild()
LegacySearchRequest.model_rebuild()
LegacySaveIdeaRequest.model_rebuild()

# ── Endpoints ──────────────────────────────────────────────────

@router.post("/chat")
async def legacy_chat(request: Request, body: LegacyChatRequest = Body(...)):
    """Legacy chat endpoint matching old Vercel /api/chat."""
    settings = get_settings()
    if not settings.openai_api_key_active:
        raise HTTPException(status_code=500, detail="API key not configured")

    try:
        result = await unified_chat_service.run_standard_chat(
            message=body.message,
            persona=body.persona,
            context=body.context,
            conversation_history=body.conversationHistory,
            conversation_id=body.conversationId,
            session_id=body.sessionId,
            user_id=body.userId,
        )
        return {
            "message": result["message"],
            "usage": result.get("usage"),
            "conversationId": result.get("conversationId"),
        }
    except Exception as e:
        logger.error("Legacy chat error", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/companies")
async def legacy_companies(domain: Optional[str] = Query(None)):
    return await sheets_service.fetch_companies_by_domain(domain)

@router.post("/search-companies")
async def legacy_search_companies(request: Request, body: LegacySearchRequest = Body(...)):
    """Legacy search endpoint matching old Vercel /api/search-companies."""
    result = await sheets_service.search_companies(
        domain=body.domain,
        subdomain=body.subdomain,
        requirement=body.requirement,
        user_context=body.userContext,
    )

@router.post("/save-idea")
async def legacy_save_idea(request: Request, body: LegacySaveIdeaRequest = Body(...)):
    """Legacy save-idea endpoint matching old Vercel /api/save-idea."""
    settings = get_settings()
    if not settings.GOOGLE_SHEETS_WEBHOOK_URL:
        return {"success": True, "message": "Skipped (webhook not configured)"}

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            await client.post(settings.GOOGLE_SHEETS_WEBHOOK_URL, json=body.model_dump())
        return {"success": True, "message": "Saved"}
    except Exception as e:
        logger.error("Save idea error", error=str(e))
        return {"success": False, "error": str(e)}