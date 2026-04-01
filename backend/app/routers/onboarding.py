"""
POST /api/v1/onboarding — create a new session + onboarding row, or patch onboarding by session_id.
"""

from typing import Any, Optional

import structlog
from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import get_settings
from app.middleware.rate_limit import limiter
from app.services import onboarding_service

logger = structlog.get_logger()

router = APIRouter(prefix="/onboarding", tags=["Onboarding"])


class OnboardingRequest(BaseModel):
    """Omit session_id (or send empty) to create a new session. Send session_id to patch."""

    session_id: Optional[str] = Field(default=None, description="Existing session; when set, body fields update onboarding row.")
    user_id: Optional[str] = None
    outcome: Optional[str] = None
    domain: Optional[str] = None
    task: Optional[str] = None
    website_url: Optional[str] = None
    gbp_url: Optional[str] = None

    model_config = {"extra": "ignore"}


@router.post("")
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def onboarding_upsert(
    request: Request,
    body: Optional[OnboardingRequest] = Body(default=None),
) -> dict[str, Any]:
    """
    - **No `session_id`**: creates `user_sessions` + in-memory agent session, inserts `onboarding` row
      (with any optional `user_id`, `outcome`, `domain`, `task`, `website_url`, `gbp_url` sent in the body),
      returns `session_id` and `id` for the client to store (e.g. localStorage).
    - **With `session_id`**: ensures `user_sessions` exists, then inserts or updates the latest
      `onboarding` row for that session with any provided fields.
    """
    eff = body if body is not None else OnboardingRequest()
    sid = (eff.session_id or "").strip()

    try:
        create_or_patch_fields = eff.model_dump(exclude={"session_id"}, exclude_unset=True)

        if not sid:
            return await onboarding_service.create_session_with_onboarding(create_or_patch_fields)

        return await onboarding_service.upsert_onboarding_patch(sid, create_or_patch_fields)
    except RuntimeError as e:
        if "pool" in str(e).lower() or "not initialized" in str(e).lower():
            raise HTTPException(status_code=503, detail="Database unavailable") from e
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("onboarding_upsert failed", error=str(e))
        raise HTTPException(status_code=500, detail="Onboarding save failed") from e
