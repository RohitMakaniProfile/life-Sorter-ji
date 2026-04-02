"""
POST /api/v1/onboarding — create a new session + onboarding row, or patch onboarding by session_id.
"""

from typing import Any, Optional

import structlog
from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import get_settings
from app.middleware.rate_limit import limiter
from app.models.session import DynamicQuestion
from app.services import onboarding_service
from app.services.onboarding_question_service import generate_next_rca_question_for_onboarding

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
    scale_answers: Optional[dict[str, Any]] = None

    model_config = {"extra": "ignore"}


class ToolsByQ1Q2Q3Request(BaseModel):
    outcome: str
    domain: str
    task: str
    limit: int = 10


class ToolsByQ1Q2Q3Response(BaseModel):
    tools: list[dict[str, Any]]
    match_type: str = ""
    count: int = 0


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


@router.post("/tools/by-q1-q2-q3", response_model=ToolsByQ1Q2Q3Response)
async def tools_by_q1_q2_q3(body: ToolsByQ1Q2Q3Request = Body(...)):
    """
    Static/deterministic Q1×Q2×Q3 tool lookup (no DB, no LLM).
    Returns raw tool entries from `tools_by_q1_q2_q3.json` (same dataset used for backend playbook context).
    """
    from app.services.instant_tool_service import get_tools_for_q1_q2_q3

    res = get_tools_for_q1_q2_q3(outcome=body.outcome, domain=body.domain, task=body.task, limit=body.limit)
    tools = res.get("tools") or []
    return ToolsByQ1Q2Q3Response(
        tools=tools,
        match_type=res.get("match_type") or "",
        count=res.get("count") or len(tools),
    )


class GenerateRcaQuestionRequest(BaseModel):
    session_id: str
    # Answer to the previously generated question.
    # When omitted, the endpoint generates the FIRST RCA question.
    answer: Optional[str] = None


class GenerateRcaQuestionResponse(BaseModel):
    status: str = "question"  # question | complete
    question: Optional[DynamicQuestion] = None
    match_source: str = ""  # tree | llm | static_fallback
    complete_summary: str = ""


@router.post("/rca-next-question", response_model=GenerateRcaQuestionResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_CHAT)
async def rca_next_question(request: Request, body: GenerateRcaQuestionRequest = Body(...)):
    """
    Generate the next RCA question using:
    - static hit: `rca_decision_tree.json` (tree)
    - fallback: LLM (`generate_next_rca_question`)

    Persists question/answer history into `onboarding.rca_qa` (JSONB) so future
    questions can be generated and later replayed as chat messages.
    """
    res = await generate_next_rca_question_for_onboarding(
        session_id=body.session_id,
        answer=body.answer,
    )
    return GenerateRcaQuestionResponse(**res)
