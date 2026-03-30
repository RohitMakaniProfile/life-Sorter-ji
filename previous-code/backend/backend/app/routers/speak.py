"""
═══════════════════════════════════════════════════════════════
TEXT-TO-SPEECH ROUTER — OpenAI TTS with Hindi Translation
═══════════════════════════════════════════════════════════════
POST /api/v1/speak — Convert text to speech (English or Hindi)
"""

# ❌ REMOVED: from __future__ import annotations

import structlog
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import Response

from app.config import get_settings
from app.middleware.rate_limit import limiter
from app.models.speak import SpeakRequest
from app.services import openai_service

logger = structlog.get_logger()

router = APIRouter()

@router.post("/speak")
@limiter.limit(lambda: get_settings().RATE_LIMIT_SPEAK)
async def text_to_speech(request: Request, body: SpeakRequest = Body(...)):
    """
    Convert text to speech using OpenAI TTS.

    Supports English and Hindi. For Hindi, the text is automatically
    translated before generating speech. Returns an MP3 audio stream.
    """
    settings = get_settings()

    if not settings.openai_api_key_active:
        raise HTTPException(
            status_code=503,
            detail="TTS service unavailable — OpenAI API key not configured.",
        )

    try:
        audio_bytes = await openai_service.text_to_speech(
            text=body.text,
            language=body.language,
        )

        return Response(
            content=audio_bytes,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "inline; filename=speech.mp3",
                "Cache-Control": "no-cache",
            },
        )

    except Exception as e:
        logger.error("TTS failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"TTS service error: {str(e)}",
        )