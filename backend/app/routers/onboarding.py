"""POST /api/v1/onboarding — create or patch onboarding rows keyed by `id`."""

from typing import Any, Optional

import json
import uuid as _uuid
import structlog
from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from app.config import get_settings
from app.middleware.auth_context import get_request_user, require_request_user
from app.middleware.rate_limit import limiter
from app.models.session import DynamicQuestion
from app.services import onboarding_service
from app.services.claude_rca_service import generate_website_audit
from app.services.onboarding_question_service import generate_next_rca_question_for_onboarding

logger = structlog.get_logger()

router = APIRouter(prefix="/onboarding", tags=["Onboarding"])


class OnboardingRequest(BaseModel):
    """Omit onboarding_id (or send empty) to create a new row. Send onboarding_id to patch."""

    onboarding_id: Optional[str] = Field(default=None, description="Existing onboarding row id; when set, body fields update that row.")
    user_id: Optional[str] = None
    outcome: Optional[str] = None
    domain: Optional[str] = None
    task: Optional[str] = None
    website_url: Optional[str] = None
    gbp_url: Optional[str] = None
    scale_answers: Optional[dict[str, Any]] = None

    @field_validator("onboarding_id", mode="before")
    @classmethod
    def _validate_uuid(cls, v: Any) -> Any:
        if v is None:
            return v
        s = str(v).strip()
        if not s:
            return None
        try:
            _uuid.UUID(s)
        except ValueError:
            raise ValueError(f"onboarding_id must be a valid UUID, got '{s}'")
        return s

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


class OnboardingStateResponse(BaseModel):
    """Response for GET /onboarding/state - returns the current onboarding state for resumption."""
    onboarding_id: str
    stage: str = "start"  # start | url | questions | crawling | website_audit | diagnostic | playbook | complete
    outcome: Optional[str] = None
    domain: Optional[str] = None
    task: Optional[str] = None
    website_url: Optional[str] = None
    gbp_url: Optional[str] = None
    business_profile: Optional[str] = None
    scale_answers: Optional[dict[str, Any]] = None
    rca_qa: Optional[list[dict[str, Any]]] = None
    current_rca_question: Optional[DynamicQuestion] = None
    playbook_status: Optional[str] = None
    playbook_error: Optional[str] = None
    website_audit: Optional[str] = None
    web_scrap_done: bool = False


def _as_dict(v: Any) -> dict[str, Any]:
    """Parse JSON string or pass through dict."""
    if isinstance(v, str):
        try:
            vv = json.loads(v)
            return vv if isinstance(vv, dict) else {}
        except Exception:
            return {}
    return v if isinstance(v, dict) else {}


def _as_list(v: Any) -> list[dict[str, Any]]:
    """Parse JSON string or pass through list."""
    if isinstance(v, str):
        try:
            vv = json.loads(v)
            return vv if isinstance(vv, list) else []
        except Exception:
            return []
    return v if isinstance(v, list) else []


def _determine_onboarding_stage(row: dict[str, Any]) -> str:
    """Determine the current onboarding stage based on row data.

    Flow order: url → questions → website_audit → diagnostic → playbook → complete
    """
    # Check if onboarding is complete
    onboarding_completed_at = row.get("onboarding_completed_at")
    if onboarding_completed_at:
        return "complete"

    # Check if playbook is active or complete
    playbook_status = str(row.get("playbook_status") or "")
    if playbook_status in ("complete", "generating", "started", "ready", "error"):
        return "playbook"

    # Parse rca_qa - handle both raw JSONB (dict/list) and JSON strings
    rca_qa_raw = row.get("rca_qa")
    rca_qa = _as_list(rca_qa_raw) if rca_qa_raw is not None else []

    rca_summary = str(row.get("rca_summary") or "")
    if rca_qa and len(rca_qa) > 0:
        # RCA in progress (no summary yet)
        if not rca_summary:
            return "diagnostic"
        # RCA complete → go to playbook
        return "playbook"

    # Parse scale_answers - handle both raw JSONB (dict) and JSON strings
    scale_answers_raw = row.get("scale_answers")
    scale_answers = _as_dict(scale_answers_raw) if scale_answers_raw is not None else {}

    if scale_answers and len(scale_answers) > 0:
        # Must wait for crawl to complete before generating audit
        web_scrap_done = bool(row.get("web_scrap_done"))
        if not web_scrap_done:
            return "crawling"
        # Website audit comes before RCA; if audit is done, proceed to diagnostic
        website_audit = str(row.get("website_audit") or "").strip()
        if website_audit:
            return "diagnostic"
        return "website_audit"

    # Check if URL is provided
    website_url = str(row.get("website_url") or "").strip()
    gbp_url = str(row.get("gbp_url") or "").strip()
    if website_url or gbp_url:
        return "questions"

    # Check if task is selected
    task = str(row.get("task") or "").strip()
    if task:
        return "url"

    return "start"


@router.get("/state")
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def get_onboarding_state(
    request: Request,
    onboarding_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> OnboardingStateResponse:
    """
    Get the current onboarding state for a row.
    Used for restoring the onboarding flow after page refresh.
    Supports lookup by user_id (preferred) or onboarding_id.
    """
    from app.db import get_pool

    oid = (onboarding_id or "").strip()

    jwt_user = get_request_user(request)
    uid = None
    if jwt_user:
        uid = str(jwt_user.get("id") or "").strip()

    if not oid and not uid:
        raise HTTPException(status_code=400, detail="onboarding_id or user_id is required")

    from app.repositories import onboarding_repository as onboarding_repo

    pool = get_pool()
    async with pool.acquire() as conn:
        row = None

        # Prefer explicit onboarding_id when provided; it is the only unambiguous row identifier.
        if oid:
            row = await onboarding_repo.find_full_state(conn, oid)

        # Fall back to user_id lookup only when onboarding_id is absent.
        # Only return non-complete rows — if the latest row is complete the user should start fresh.
        if not row and uid:
            row = await onboarding_repo.find_latest_incomplete_by_user(conn, uid)

        if not row:
            raise HTTPException(status_code=404, detail="Onboarding row not found")

        row_dict = dict(row)
        stage = _determine_onboarding_stage(row_dict)

        # Parse JSONB fields
        scale_answers = _as_dict(row_dict.get("scale_answers"))
        rca_qa = _as_list(row_dict.get("rca_qa"))

        # Get current RCA question if in diagnostic stage
        current_rca_question = None
        if stage == "diagnostic" and rca_qa:
            for qa in reversed(rca_qa):
                if isinstance(qa, dict) and qa.get("question") and not qa.get("answer"):
                    current_rca_question = DynamicQuestion(
                        question=str(qa.get("question") or ""),
                        options=qa.get("options") or [],
                    )
                    break

        return OnboardingStateResponse(
            onboarding_id=str(row_dict.get("id") or ""),
            stage=stage,
            outcome=str(row_dict.get("outcome") or "") or None,
            domain=str(row_dict.get("domain") or "") or None,
            task=str(row_dict.get("task") or "") or None,
            website_url=str(row_dict.get("website_url") or "") or None,
            gbp_url=str(row_dict.get("gbp_url") or "") or None,
            business_profile=str(row_dict.get("business_profile") or "") or None,
            scale_answers=scale_answers if scale_answers else None,
            rca_qa=rca_qa if rca_qa else None,
            current_rca_question=current_rca_question,
            playbook_status=str(row_dict.get("playbook_status") or "") or None,
            playbook_error=str(row_dict.get("playbook_error") or "") or None,
            website_audit=str(row_dict.get("website_audit") or "") or None,
            web_scrap_done=bool(row_dict.get("web_scrap_done")),
        )


@router.post("")
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def onboarding_upsert(
    request: Request,
    body: Optional[OnboardingRequest] = Body(default=None),
) -> dict[str, Any]:
    """
    - **No `onboarding_id`**: creates a new onboarding row
      (with any optional `user_id`, `outcome`, `domain`, `task`, `website_url`, `gbp_url` sent in the body),
      returns `onboarding_id` and `id` for the client to store.
    - **With `onboarding_id`**: updates that onboarding row with any provided fields.
    - **If the row is complete**: creates a new onboarding row instead of updating, with user_id from JWT if available.
    """
    eff = body if body is not None else OnboardingRequest()
    oid = (eff.onboarding_id or "").strip()

    # Get user_id from JWT if available
    jwt_user = get_request_user(request)
    jwt_user_id = str(jwt_user.get("id") or "").strip() if jwt_user else None

    try:
        create_or_patch_fields = eff.model_dump(exclude={"onboarding_id"}, exclude_unset=True)

        result: dict[str, Any]
        if not oid:
            # Inject JWT user_id so the row is linked to the authenticated user from creation.
            if jwt_user_id and "user_id" not in create_or_patch_fields:
                create_or_patch_fields["user_id"] = jwt_user_id
            result = await onboarding_service.create_session_with_onboarding(create_or_patch_fields)
        else:
            result = await onboarding_service.upsert_onboarding_patch(oid, create_or_patch_fields, user_id=jwt_user_id)

        return result
    except RuntimeError as e:
        if "pool" in str(e).lower() or "not initialized" in str(e).lower():
            raise HTTPException(status_code=503, detail="Database unavailable") from e
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("onboarding_upsert failed", error=str(e))
        raise HTTPException(status_code=500, detail="Onboarding save failed") from e


class OnboardingResetRequest(BaseModel):
    onboarding_id: str


class CreateOnboardingFromProductRequest(BaseModel):
    product_id: str


class CreateOnboardingFromProductResponse(BaseModel):
    onboarding_id: str
    id: str
    outcome: Optional[str] = None
    domain: Optional[str] = None
    task: Optional[str] = None
    website_url: Optional[str] = None
    scale_answers: Optional[dict[str, Any]] = None
    web_scrap_done: bool = False


@router.post("/from-product", response_model=CreateOnboardingFromProductResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def create_onboarding_from_product(
    request: Request,
    body: CreateOnboardingFromProductRequest = Body(...),
) -> CreateOnboardingFromProductResponse:
    """
    Create a new onboarding for a claw product.

    - Reads outcome/domain/task from the product row.
    - Copies website_url and scale_answers from the user's most recent onboarding that has a URL.
    - Sets web_scrap_done=True when 5+ scraped_pages rows exist for that URL (crawling can be skipped).
    """
    from app.db import get_pool
    from app.repositories import onboarding_repository as onboarding_repo
    from app.repositories import products_repository as products_repo
    from app.repositories import scraped_pages_repository as scraped_pages_repo

    product_id = (body.product_id or "").strip()
    if not product_id:
        raise HTTPException(status_code=400, detail="product_id is required")

    jwt_user = get_request_user(request)
    user_id = str(jwt_user.get("id") or "").strip() if jwt_user else None

    pool = get_pool()
    async with pool.acquire() as conn:
        product = await products_repo.find_by_id(conn, product_id)
        if not product:
            raise HTTPException(status_code=404, detail="Product not found")

        outcome = str(product.get("outcome") or "")
        domain = str(product.get("domain") or "")
        task = str(product.get("task") or "")

        # Copy website_url and scale_answers from previous onboarding if available
        website_url: Optional[str] = None
        scale_answers: Optional[dict[str, Any]] = None
        if user_id:
            prev = await onboarding_repo.find_website_scale_by_user(conn, user_id)
            if prev:
                website_url = str(prev.get("website_url") or "").strip() or None
                raw_sa = prev.get("scale_answers")
                if isinstance(raw_sa, dict) and raw_sa:
                    scale_answers = raw_sa
                elif isinstance(raw_sa, str):
                    try:
                        parsed_sa = json.loads(raw_sa)
                        if isinstance(parsed_sa, dict) and parsed_sa:
                            scale_answers = parsed_sa
                    except Exception:
                        pass

        # Decide if crawling can be skipped
        web_scrap_done = False
        if website_url:
            page_count = await scraped_pages_repo.count_by_base_url(conn, website_url)
            web_scrap_done = page_count >= 5

        # Build onboarding row
        cols = ["outcome", "domain", "task", "web_scrap_done"]
        vals: list[Any] = [outcome, domain, task, web_scrap_done]

        if user_id:
            cols.append("user_id")
            vals.append(user_id)
        if website_url:
            cols.append("website_url")
            vals.append(website_url)
        if scale_answers:
            cols.append("scale_answers")
            vals.append(json.dumps(scale_answers))

        row = await onboarding_repo.insert_with_fields(conn, cols, vals)

    row_dict = dict(row)
    oid = str(row_dict.get("id") or "")

    sa = row_dict.get("scale_answers")
    if isinstance(sa, str):
        try:
            sa = json.loads(sa)
        except Exception:
            sa = None

    return CreateOnboardingFromProductResponse(
        onboarding_id=oid,
        id=oid,
        outcome=outcome or None,
        domain=domain or None,
        task=task or None,
        website_url=website_url,
        scale_answers=sa if isinstance(sa, dict) else None,
        web_scrap_done=web_scrap_done,
    )


@router.get("/playbook-status")
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def get_onboarding_playbook_status(
    request: Request,
    onboarding_id: str,
) -> dict[str, Any]:
    """
    Return playbook status (and content if complete) for a given onboarding_id.
    Requires authentication; the onboarding row must belong to the requesting user.
    404 if the onboarding row does not exist.
    """
    user = require_request_user(request)
    requesting_user_id = str(user.get("id") or "").strip()

    from app.db import get_pool
    from app.repositories import onboarding_repository as onboarding_repo
    from app.repositories import playbook_runs_repository as playbook_repo

    oid = (onboarding_id or "").strip()
    if not oid:
        raise HTTPException(status_code=400, detail="onboarding_id is required")

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await onboarding_repo.find_by_id(conn, oid)
        if not row:
            raise HTTPException(status_code=404, detail="Playbook not found")

        row_dict = dict(row)
        row_user_id = str(row_dict.get("user_id") or "").strip()
        if row_user_id and row_user_id != requesting_user_id:
            raise HTTPException(status_code=403, detail="Access denied")

        playbook_status = str(row_dict.get("playbook_status") or "")
        website_url = str(row_dict.get("website_url") or "").strip()
        task = str(row_dict.get("task") or "").strip()
        domain = str(row_dict.get("domain") or "").strip()
        outcome = str(row_dict.get("outcome") or "").strip()

        content = None
        if playbook_status == "complete":
            pr = await playbook_repo.find_latest_complete_by_session(conn, oid)
            if not pr:
                pr = await playbook_repo.find_latest_via_onboarding_fk(conn, oid)
            if pr:
                pr_dict = dict(pr)
                playbook_text = str(pr_dict.get("playbook") or "").strip()
                if playbook_text:
                    content = {
                        "playbook": playbook_text,
                        "website_audit": str(pr_dict.get("website_audit") or ""),
                        "context_brief": str(pr_dict.get("context_brief") or ""),
                        "icp_card": str(pr_dict.get("icp_card") or ""),
                    }

    return {
        "onboarding_id": oid,
        "playbook_status": playbook_status,
        "website_url": website_url,
        "task": task,
        "domain": domain,
        "outcome": outcome,
        "content": content,
    }


@router.post("/reset")
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def reset_onboarding(
    request: Request,
    body: OnboardingResetRequest,
) -> dict[str, Any]:
    """Reset an onboarding row — clears all journey data, keeping only id and user_id."""
    try:
        result = await onboarding_service.reset_onboarding(body.onboarding_id)
        return {"onboarding_id": result.get("onboarding_id"), "reset": True}
    except PermissionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.exception("reset_onboarding failed", error=str(e))
        raise HTTPException(status_code=500, detail="Onboarding reset failed") from e


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
    onboarding_id: Optional[str] = None
    # Answer to the previously generated question.
    # When omitted, the endpoint generates the FIRST RCA question.
    answer: Optional[str] = None


class GenerateRcaQuestionResponse(BaseModel):
    status: str = "question"  # question | complete
    question: Optional[DynamicQuestion] = None
    match_source: str = ""  # tree | llm | static_fallback
    complete_summary: str = ""
    complete_handoff: str = ""
    scale_answers: Optional[dict[str, Any]] = None
    business_profile: Optional[str] = None


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
    onboarding_id = await _resolve_onboarding_id(
        request=request,
        provided_onboarding_id=body.onboarding_id,
    )
    res = await generate_next_rca_question_for_onboarding(
        onboarding_id=onboarding_id,
        answer=body.answer,
    )
    return GenerateRcaQuestionResponse(**res)


class StartOnboardingPlaybookRequest(BaseModel):
    onboarding_id: Optional[str] = None


class LaunchOnboardingPlaybookRequest(BaseModel):
    onboarding_id: Optional[str] = None


class LaunchOnboardingPlaybookResponse(BaseModel):
    onboarding_id: str
    stage: str  # started
    stream_id: str = ""
    stream_status: str = ""
    message: str = ""


class WebsiteAuditGenerateRequest(BaseModel):
    onboarding_id: Optional[str] = None








async def _resolve_onboarding_id(
    *,
    request: Request,
    provided_onboarding_id: Optional[str],
) -> str:
    user = get_request_user(request) or {}
    sub = str(user.get("id") or "").strip()
    oid = (provided_onboarding_id or "").strip()

    # Authenticated path: resolve to latest onboarding row by created_at for this user.
    if sub:
        from app.db import get_pool
        from app.repositories import onboarding_repository as onboarding_repo

        pool = get_pool()
        async with pool.acquire() as conn:
            oid_db = await onboarding_repo.find_latest_id_by_user(conn, sub)
        if oid_db:
            return oid_db
        raise HTTPException(status_code=400, detail="onboarding row not found for user")

    # Guest path: onboarding_id must be explicitly provided.
    if oid:
        try:
            _uuid.UUID(oid)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"onboarding_id must be a valid UUID, got '{oid}'")
        return oid
    claims = getattr(request.state, "auth_claims", None) or {}
    sid_claim = str(claims.get("onboarding_id") or claims.get("onboarding_session_id") or claims.get("session_id") or "").strip()
    if sid_claim:
        return sid_claim
    raise HTTPException(status_code=400, detail="onboarding_id is required")


@router.post("/playbook/launch", response_model=LaunchOnboardingPlaybookResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def onboarding_playbook_launch(request: Request, body: LaunchOnboardingPlaybookRequest = Body(...)):
    """Launch playbook generation (post-auth)."""
    require_request_user(request)

    from app.db import get_pool

    onboarding_id = await _resolve_onboarding_id(
        request=request,
        provided_onboarding_id=body.onboarding_id,
    )

    from app.repositories import onboarding_repository as onboarding_repo

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await onboarding_repo.find_by_id(conn, onboarding_id)
        if not row:
            raise HTTPException(status_code=404, detail="Onboarding row not found")

        await onboarding_repo.set_playbook_starting(conn, onboarding_id)

    # Create conversation for the onboarding before playbook generation
    # This ensures the playbook can be accessed later via conversations even if user leaves
    user = require_request_user(request)
    user_id = str(user.get("id") or "").strip() or None
    from app.doable_claw_agent.stores import create_new_conversation
    try:
        conv = await create_new_conversation(
            agent_id="business_problem_identifier",
            onboarding_id=onboarding_id,
            user_id=user_id,
        )
        conversation_id = conv.get("id")
        logger.info(
            "Created conversation for playbook generation",
            onboarding_id=onboarding_id,
            conversation_id=conversation_id,
            user_id=user_id,
        )
        # Update onboarding row with the conversation_id
        if conversation_id:
            async with pool.acquire() as conn:
                await onboarding_repo.set_conversation_id(conn, onboarding_id, conversation_id)
    except Exception as conv_err:
        # Don't fail playbook generation if conversation creation fails
        logger.warning(
            "Failed to create conversation for playbook",
            onboarding_id=onboarding_id,
            error=str(conv_err),
        )

    # Start the playbook generation task stream
    from app.task_stream.service import TaskStreamService
    from app.task_stream.registry import TASK_STREAM_REGISTRY

    task_type = "playbook/onboarding-generate"
    task_fn = TASK_STREAM_REGISTRY.get(task_type)
    if not task_fn:
        raise HTTPException(status_code=500, detail=f"Task not registered: {task_type}")

    service = TaskStreamService()
    started = await service.start_task_stream(
        task_type=task_type,
        task_fn=task_fn,
        payload={"onboarding_id": onboarding_id},
        onboarding_id=onboarding_id,
        user_id=None,
        force_fresh=True,
    )
    return LaunchOnboardingPlaybookResponse(
        onboarding_id=onboarding_id,
        stage="started",
        stream_id=str(started.get("stream_id") or ""),
        stream_status=str(started.get("status") or ""),
        message="Playbook generation started.",
    )


class WebsiteAuditRequest(BaseModel):
    onboarding_id: str
    force_fresh: bool = False


@router.post("/website-audit/stream")
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def stream_website_audit_endpoint(
    request: Request,
    body: WebsiteAuditRequest,
):
    """
    Stream website audit generation as SSE tokens.
    If audit already exists in DB → returns it immediately as a single 'done' event.
    Otherwise streams tokens from LLM, saves result to DB, then sends 'done'.

    SSE events:
      data: {"type": "token", "token": "..."}
      data: {"type": "done",  "full_text": "..."}
      data: {"type": "error", "message": "..."}
    """
    import asyncio
    from fastapi.responses import StreamingResponse
    from app.db import get_pool
    from app.repositories import onboarding_repository as onboarding_repo

    onboarding_id = body.onboarding_id.strip()
    force_fresh = body.force_fresh
    if not onboarding_id:
        raise HTTPException(status_code=400, detail="onboarding_id is required")

    pool = get_pool()

    async def generate():
        from app.repositories import scraped_pages_repository as scraped_pages_repo

        # 1. Fetch context row
        async with pool.acquire() as conn:
            row = await onboarding_repo.find_website_audit_context(conn, onboarding_id)
            if not row:
                yield f"data: {json.dumps({'type': 'error', 'message': 'Onboarding session not found'})}\n\n"
                return

            row_dict = dict(row)
            existing_audit = str(row_dict.get("website_audit") or "").strip()
            scraped_page_ids = list(row_dict.get("scraped_page_ids") or [])

        # 2. Return cached audit only if:
        #    - not force_fresh, AND
        #    - we have scraped page data (crawl completed)
        if existing_audit and not force_fresh and scraped_page_ids:
            yield f"data: {json.dumps({'type': 'done', 'full_text': existing_audit})}\n\n"
            return

        # If force_fresh or crawl data is now available but audit was stale, clear old audit
        if existing_audit and (force_fresh or scraped_page_ids):
            try:
                async with pool.acquire() as conn:
                    await onboarding_repo.save_website_audit(conn, onboarding_id, "")
            except Exception:
                pass

        # 3. If scraped_page_ids is empty, poll for up to 5 min waiting for the crawl task to finish.
        #    This handles the case where the frontend called the audit before the crawl task wrote
        #    scraped_page_ids (e.g., waitForCrawlDone timed out on a slow site).
        if not scraped_page_ids:
            import asyncio as _asyncio
            poll_deadline = 300  # seconds
            poll_interval = 5    # seconds
            elapsed = 0
            while elapsed < poll_deadline:
                await _asyncio.sleep(poll_interval)
                elapsed += poll_interval
                async with pool.acquire() as conn:
                    row2 = await onboarding_repo.find_website_audit_context(conn, onboarding_id)
                if row2:
                    scraped_page_ids = list(dict(row2).get("scraped_page_ids") or [])
                if scraped_page_ids:
                    break

        # 4. Fetch scraped page markdowns
        pages_markdown: list[dict] = []
        if scraped_page_ids:
            async with pool.acquire() as conn:
                pages = await scraped_pages_repo.fetch_by_ids(conn, scraped_page_ids)
            pages_markdown = [
                {"url": str(p["url"] or ""), "markdown": str(p["markdown"] or "")}
                for p in pages
                if str(p.get("markdown") or "").strip()
            ]

        # 5. Stream from LLM
        outcome = str(row_dict.get("outcome") or "").strip()
        domain = str(row_dict.get("domain") or "").strip()
        task = str(row_dict.get("task") or "").strip()
        website_url = str(row_dict.get("website_url") or "").strip()
        scale_answers = _as_dict(row_dict.get("scale_answers")) or {}
        rca_qa_raw = _as_list(row_dict.get("rca_qa")) or []
        rca_summary = str(row_dict.get("rca_summary") or "").strip()
        rca_handoff = str(row_dict.get("rca_handoff") or "").strip()

        queue: asyncio.Queue = asyncio.Queue()

        async def on_token(token: str) -> None:
            await queue.put(("token", token))

        async def run_llm() -> None:
            try:
                result = await generate_website_audit(
                    outcome=outcome,
                    domain=domain,
                    task=task,
                    website_url=website_url,
                    scale_answers=scale_answers,
                    rca_history=rca_qa_raw,
                    rca_summary=rca_summary,
                    rca_handoff=rca_handoff,
                    pages_markdown=pages_markdown,
                    onboarding_id=onboarding_id,
                    on_token=on_token,
                )
                full_text = result or ""
                # Save to DB only if not ESTIMATED (don't cache degraded results)
                if full_text and "ESTIMATED" not in full_text:
                    async with pool.acquire() as conn:
                        await onboarding_repo.save_website_audit(conn, onboarding_id, full_text)
                await queue.put(("done", full_text))
            except Exception as e:
                logger.error("Website audit stream failed", error=str(e))
                await queue.put(("error", str(e)))

        task_handle = asyncio.create_task(run_llm())

        try:
            while True:
                event_type, data = await asyncio.wait_for(queue.get(), timeout=120.0)
                if event_type == "token":
                    yield f"data: {json.dumps({'type': 'token', 'token': data})}\n\n"
                elif event_type == "done":
                    yield f"data: {json.dumps({'type': 'done', 'full_text': data})}\n\n"
                    break
                elif event_type == "error":
                    yield f"data: {json.dumps({'type': 'error', 'message': data})}\n\n"
                    break
        except asyncio.TimeoutError:
            yield f"data: {json.dumps({'type': 'error', 'message': 'Generation timed out'})}\n\n"
        finally:
            task_handle.cancel()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


