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
from app.services.claude_rca_service import generate_precision_questions, generate_gap_questions
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
    stage: str = "start"  # start | url | questions | diagnostic | precision | playbook | complete
    outcome: Optional[str] = None
    domain: Optional[str] = None
    task: Optional[str] = None
    website_url: Optional[str] = None
    gbp_url: Optional[str] = None
    business_profile: Optional[str] = None
    scale_answers: Optional[dict[str, Any]] = None
    rca_qa: Optional[list[dict[str, Any]]] = None
    current_rca_question: Optional[DynamicQuestion] = None
    precision_questions: Optional[list[dict[str, Any]]] = None
    precision_answers: Optional[list[dict[str, Any]]] = None
    precision_status: Optional[str] = None
    playbook_status: Optional[str] = None
    playbook_error: Optional[str] = None
    gap_questions: Optional[list[dict[str, Any]]] = None
    gap_answers: Optional[str] = None
    gap_answers_parsed: Optional[dict[str, str]] = None


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
    """Determine the current onboarding stage based on row data."""
    # Check if onboarding is complete
    onboarding_completed_at = row.get("onboarding_completed_at")
    if onboarding_completed_at:
        return "complete"

    # Check if playbook is complete or generating
    playbook_status = str(row.get("playbook_status") or "")
    if playbook_status in ("complete", "generating", "started", "ready", "awaiting_gap_answers", "error"):
        return "playbook"

    # Check if precision questions are in progress
    precision_status = str(row.get("precision_status") or "")
    if precision_status == "awaiting_answers":
        return "precision"

    # Parse rca_qa - handle both raw JSONB (dict/list) and JSON strings
    rca_qa_raw = row.get("rca_qa")
    rca_qa = _as_list(rca_qa_raw) if rca_qa_raw is not None else []

    rca_summary = str(row.get("rca_summary") or "")
    if rca_qa and len(rca_qa) > 0:
        # If there's no rca_summary, RCA is still in progress
        if not rca_summary:
            return "diagnostic"
        # If RCA is complete, next is precision or playbook
        if precision_status:
            return "precision" if precision_status == "awaiting_answers" else "playbook"
        return "playbook"

    # Parse scale_answers - handle both raw JSONB (dict) and JSON strings
    scale_answers_raw = row.get("scale_answers")
    scale_answers = _as_dict(scale_answers_raw) if scale_answers_raw is not None else {}
    if scale_answers and len(scale_answers) > 0:
        return "diagnostic"

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
        precision_questions = _as_list(row_dict.get("precision_questions"))
        precision_answers = _as_list(row_dict.get("precision_answers"))
        gap_questions = _as_list(row_dict.get("gap_questions"))

        # Get current RCA question if in diagnostic stage
        current_rca_question = None
        if stage == "diagnostic" and rca_qa:
            # Find the last unanswered question
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
            precision_questions=precision_questions if precision_questions else None,
            precision_answers=precision_answers if precision_answers else None,
            precision_status=str(row_dict.get("precision_status") or "") or None,
            playbook_status=str(row_dict.get("playbook_status") or "") or None,
            playbook_error=str(row_dict.get("playbook_error") or "") or None,
            gap_questions=gap_questions if gap_questions else None,
            gap_answers=str(row_dict.get("gap_answers") or "") or None,
            gap_answers_parsed=_parse_gap_answers_map(row_dict.get("gap_answers")) or None,
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


class SubmitOnboardingGapAnswersRequest(BaseModel):
    onboarding_id: Optional[str] = None
    answers: str


class GapQuestion(BaseModel):
    id: str = ""
    label: str = ""
    question: str = ""
    options: list[str] = []


class StartOnboardingPlaybookResponse(BaseModel):
    onboarding_id: str
    stage: str  # gap_questions | ready
    gap_questions_parsed: list[GapQuestion] = []
    message: str = ""


class LaunchOnboardingPlaybookRequest(BaseModel):
    onboarding_id: Optional[str] = None


class LaunchOnboardingPlaybookResponse(BaseModel):
    onboarding_id: str
    stage: str  # gap_questions | started
    gap_questions_parsed: list[GapQuestion] = []
    stream_id: str = ""
    stream_status: str = ""
    message: str = ""
    gap_answers_parsed: Optional[dict[str, str]] = None


class SubmitOnboardingGapAnswersResponse(BaseModel):
    onboarding_id: str
    stage: str  # ready
    message: str = ""


class SubmitOnboardingMcqAnswerRequest(BaseModel):
    onboarding_id: Optional[str] = None
    question_index: int
    answer_key: str
    answer_text: str


class SubmitOnboardingMcqAnswerResponse(BaseModel):
    onboarding_id: str
    all_answered: bool
    playbook_status: str
    gap_answers_parsed: dict[str, str] = {}


def _parse_gap_answers_map(value: Any) -> dict[str, str]:
    raw = str(value or "").strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return {str(k): str(v) for k, v in parsed.items()}
    except Exception:
        pass
    out: dict[str, str] = {}
    for part in raw.split(","):
        piece = part.strip()
        if "-" not in piece:
            continue
        k, v = piece.split("-", 1)
        out[str(k).strip()] = str(v).strip()
    return out


def _serialize_gap_answers_text(answer_map: dict[str, str]) -> str:
    return json.dumps(answer_map, ensure_ascii=False)


class PrecisionQuestionItem(BaseModel):
    type: str = ""
    insight: str = ""
    question: str = ""
    options: list[str] = []
    section_label: str = ""


class StartOnboardingPrecisionRequest(BaseModel):
    onboarding_id: Optional[str] = None


class StartOnboardingPrecisionResponse(BaseModel):
    onboarding_id: str
    questions: list[PrecisionQuestionItem] = []
    available: bool = False


class SubmitOnboardingPrecisionAnswerRequest(BaseModel):
    onboarding_id: Optional[str] = None
    question_index: int
    answer: str


class SubmitOnboardingPrecisionAnswerResponse(BaseModel):
    onboarding_id: str
    next_question: Optional[PrecisionQuestionItem] = None
    all_answered: bool = False
    precision_status: str = ""  # awaiting_answers | complete


# ══════════════════════════════════════════════════════════════
#  GAP QUESTIONS — Pre-playbook clarifying questions
# ══════════════════════════════════════════════════════════════

class GapQuestionItem(BaseModel):
    id: str = ""
    label: str = ""
    question: str = ""
    why_matters: str = ""
    options: list[str] = []


class StartGapQuestionsRequest(BaseModel):
    onboarding_id: Optional[str] = None


class StartGapQuestionsResponse(BaseModel):
    onboarding_id: str
    questions: list[GapQuestionItem] = []
    available: bool = False  # True if questions exist


def _parse_gap_questions(agent_output: str) -> list[dict[str, Any]]:
    """
    Parse LLM output into structured gap questions.
    Format expected:
      Q1 — Label: question line
      A) ...
      B) ...
    """
    import re

    q_header_re = re.compile(r'^\*{0,2}Q(\d+)\*{0,2}\s*(?:[—–\-]\s*)?(.+?):\s*(.*)$')
    opt_re = re.compile(r'^([A-E])\)\s*(.+)')
    inline_opt_split_re = re.compile(r'\s*-?\s*([A-E]\)\s*.+?)(?=\s+-?\s*[A-E]\)|$)')

    parsed: list[dict[str, Any]] = []
    current: dict[str, str] | None = None
    body_lines: list[str] = []

    def _flush(q: dict[str, str], lines: list[str]) -> None:
        question_parts: list[str] = []
        options: list[str] = []
        for raw in lines:
            s = raw.strip().strip('*').strip()
            if not s:
                continue
            if opt_re.match(s):
                options.append(s)
            elif not options:
                question_parts.append(s)
        question_text = ' '.join(question_parts) if question_parts else q['label']
        if not options and question_text:
            inline_match = re.search(r'[-–]\s*A\)\s', question_text) or re.search(r'\bA\)\s', question_text)
            if inline_match:
                q_part = question_text[: inline_match.start()].strip().rstrip('-–').strip()
                opt_part = question_text[inline_match.start() :]
                found_opts = inline_opt_split_re.findall(opt_part)
                if found_opts and len(found_opts) >= 2:
                    question_text = q_part
                    options = [o.strip().lstrip('- ').strip() for o in found_opts]
        if question_text:
            parsed.append({"id": q["id"], "label": q["label"], "question": question_text, "options": options})

    for raw_line in (agent_output or "").splitlines():
        line = raw_line.strip()
        m = q_header_re.match(line)
        if m:
            if current is not None:
                _flush(current, body_lines)
            q_num = m.group(1)
            label = re.sub(r'\*+', '', m.group(2)).strip()
            inline = re.sub(r'\*+', '', m.group(3)).strip()
            current = {"id": f"Q{q_num}", "label": label}
            body_lines = [inline] if inline else []
        elif current is not None:
            body_lines.append(raw_line)
    if current is not None:
        _flush(current, body_lines)
    return parsed



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
    """
    Launch playbook generation (post-auth).

    Prerequisites:
    - Must call /gap-questions/start first to check for gap questions
    - If gap questions were returned, must answer them via /playbook/gap-answers

    Flow:
    - If gap_questions is NULL → error "Call /gap-questions/start first"
    - If gap_questions has items AND gap_answers is empty → error "Answer gap questions first"
    - Otherwise → start playbook generation task stream
    """
    require_request_user(request)

    from app.db import get_pool

    onboarding_id = await _resolve_onboarding_id(
        request=request,
        provided_onboarding_id=body.onboarding_id,
    )

    from app.repositories import onboarding_repository as onboarding_repo

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await onboarding_repo.find_gap_launch_state(conn, onboarding_id)
        if not row:
            raise HTTPException(status_code=404, detail="Onboarding row not found")

        onboarding_id = str(row.get("id") or "")
        gap_questions_raw = row.get("gap_questions")
        gap_answers = str(row.get("gap_answers") or "").strip()
        playbook_status = str(row.get("playbook_status") or "")

        # Parse gap_questions
        gap_questions = _as_list(gap_questions_raw)

        # Check if gap questions have been generated
        if gap_questions_raw is None:
            raise HTTPException(
                status_code=400,
                detail="Call /gap-questions/start before launching playbook."
            )

        # Check if gap questions exist but haven't been answered
        if gap_questions and len(gap_questions) > 0 and not gap_answers:
            return LaunchOnboardingPlaybookResponse(
                onboarding_id=onboarding_id,
                stage="gap_questions",
                gap_questions_parsed=[GapQuestion(**q) for q in gap_questions],
                message="Answer gap questions before launching playbook.",
            )

        # Update status to starting
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
        gap_questions_parsed=[],
        stream_id=str(started.get("stream_id") or ""),
        stream_status=str(started.get("status") or ""),
        message="Playbook generation started.",
        gap_answers_parsed=_parse_gap_answers_map(gap_answers),
    )


@router.post("/playbook/gap-answers", response_model=SubmitOnboardingGapAnswersResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def onboarding_playbook_gap_answers(request: Request, body: SubmitOnboardingGapAnswersRequest = Body(...)):
    """
    Persist user's gap answers into onboarding row.
    """
    from app.db import get_pool

    require_request_user(request)
    onboarding_id = await _resolve_onboarding_id(
        request=request,
        provided_onboarding_id=body.onboarding_id,
    )

    from app.repositories import onboarding_repository as onboarding_repo
    answers = str(body.answers or "").strip()
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await onboarding_repo.find_by_id(conn, onboarding_id)
        if not row:
            raise HTTPException(status_code=404, detail="Onboarding row not found")
        await onboarding_repo.set_gap_answers_ready(conn, onboarding_id, answers)

    return SubmitOnboardingGapAnswersResponse(onboarding_id=onboarding_id, stage="ready", message="Gap answers saved.")


@router.post("/playbook/mcq-answer", response_model=SubmitOnboardingMcqAnswerResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def onboarding_playbook_mcq_answer(request: Request, body: SubmitOnboardingMcqAnswerRequest = Body(...)):
    require_request_user(request)
    onboarding_id = await _resolve_onboarding_id(request=request, provided_onboarding_id=body.onboarding_id)
    if body.question_index < 0:
        raise HTTPException(status_code=400, detail="question_index must be >= 0")

    from app.db import get_pool
    from app.repositories import onboarding_repository as onboarding_repo

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await onboarding_repo.find_mcq_gap_state(conn, onboarding_id)
        if not row:
            raise HTTPException(status_code=404, detail="Onboarding row not found")

        gap_questions = _as_list(row.get("gap_questions"))
        answer_map = _parse_gap_answers_map(row.get("gap_answers"))
        answer_map[f"Q{body.question_index + 1}"] = str(body.answer_key or body.answer_text or "").strip()
        all_answered = len(gap_questions) > 0 and len(answer_map) >= len(gap_questions)
        status = "ready" if all_answered else "awaiting_gap_answers"

        await onboarding_repo.update_gap_answers(conn, onboarding_id, _serialize_gap_answers_text(answer_map), status)

    return SubmitOnboardingMcqAnswerResponse(
        onboarding_id=onboarding_id,
        all_answered=all_answered,
        playbook_status=status,
        gap_answers_parsed=answer_map,
    )


@router.post("/precision/start", response_model=StartOnboardingPrecisionResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_CHAT)
async def onboarding_precision_start(request: Request, body: StartOnboardingPrecisionRequest = Body(...)):
    onboarding_id = await _resolve_onboarding_id(
        request=request,
        provided_onboarding_id=body.onboarding_id,
    )

    from app.db import get_pool
    from app.repositories import onboarding_repository as onboarding_repo

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await onboarding_repo.find_precision_context(conn, onboarding_id)
        if not row:
            raise HTTPException(status_code=404, detail="Onboarding row not found")

        outcome = str(row.get("outcome") or "")
        domain = str(row.get("domain") or "")
        task = str(row.get("task") or "")
        scale_answers = _as_dict(row.get("scale_answers"))
        rca_qa = _as_list(row.get("rca_qa"))
        rca_history = [
            {"question": str(it.get("question") or ""), "answer": str(it.get("answer") or "")}
            for it in rca_qa
            if isinstance(it, dict) and it.get("answer") not in (None, "")
        ]
        if not rca_history:
            return StartOnboardingPrecisionResponse(onboarding_id=onboarding_id, questions=[], available=False)

        outcome_label = {
            "lead-generation": "Lead Generation",
            "sales-retention": "Sales & Retention",
            "business-strategy": "Business Strategy",
            "save-time": "Save Time",
        }.get(outcome, "")

        generated = await generate_precision_questions(
            outcome=outcome,
            outcome_label=outcome_label,
            domain=domain,
            task=task,
            rca_history=rca_history,
            scale_answers=scale_answers or None,
            web_summary=str(row.get("web_summary") or ""),
            business_profile_text=str(row.get("business_profile") or ""),
            onboarding_id=onboarding_id,
        )
        if not generated:
            await onboarding_repo.mark_precision_empty(conn, onboarding_id)
            return StartOnboardingPrecisionResponse(onboarding_id=onboarding_id, questions=[], available=False)

        cleaned = [
            {
                "type": str(q.get("type") or ""),
                "insight": str(q.get("insight") or ""),
                "question": str(q.get("question") or ""),
                "options": q.get("options") or [],
                "section_label": str(q.get("section_label") or ""),
            }
            for q in generated[:3]
        ]
        await onboarding_repo.save_precision_questions(conn, onboarding_id, json.dumps(cleaned))
        return StartOnboardingPrecisionResponse(
            onboarding_id=onboarding_id,
            questions=[PrecisionQuestionItem(**q) for q in cleaned],
            available=len(cleaned) > 0,
        )


@router.post("/precision/answer", response_model=SubmitOnboardingPrecisionAnswerResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_CHAT)
async def onboarding_precision_answer(request: Request, body: SubmitOnboardingPrecisionAnswerRequest = Body(...)):
    onboarding_id = await _resolve_onboarding_id(
        request=request,
        provided_onboarding_id=body.onboarding_id,
    )
    if body.question_index < 0:
        raise HTTPException(status_code=400, detail="question_index must be >= 0")

    from app.db import get_pool
    from app.repositories import onboarding_repository as onboarding_repo

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await onboarding_repo.find_precision_state(conn, onboarding_id)
        if not row:
            raise HTTPException(status_code=404, detail="Onboarding row not found")

        precision_questions = _as_list(row.get("precision_questions"))
        if body.question_index >= len(precision_questions):
            raise HTTPException(status_code=400, detail="Invalid precision question index")

        precision_answers = _as_list(row.get("precision_answers"))
        answer_payload = {
            "question_index": body.question_index,
            "answer": str(body.answer or ""),
        }
        if body.question_index < len(precision_questions):
            q = precision_questions[body.question_index]
            answer_payload["question"] = str(q.get("question") or "")
            answer_payload["type"] = str(q.get("type") or "")
        precision_answers.append(answer_payload)

        qa_log = _as_list(row.get("questions_answers"))
        qa_log.append(
            {
                "question": answer_payload.get("question", f"Precision Question {body.question_index + 1}"),
                "answer": answer_payload.get("answer", ""),
                "question_type": "precision",
            }
        )

        next_idx = body.question_index + 1
        all_answered = next_idx >= len(precision_questions)
        if all_answered:
            await onboarding_repo.mark_precision_complete(conn, onboarding_id, json.dumps(precision_answers), json.dumps(qa_log))
            return SubmitOnboardingPrecisionAnswerResponse(
                onboarding_id=onboarding_id,
                all_answered=True,
                precision_status="complete",
            )

        await onboarding_repo.update_precision_progress(conn, onboarding_id, json.dumps(precision_answers), json.dumps(qa_log))
        next_q = precision_questions[next_idx]
        return SubmitOnboardingPrecisionAnswerResponse(
            onboarding_id=onboarding_id,
            next_question=PrecisionQuestionItem(**next_q),
            all_answered=False,
            precision_status="awaiting_answers",
        )


# ══════════════════════════════════════════════════════════════
#  GAP QUESTIONS ENDPOINT — Pre-playbook clarifying questions
# ══════════════════════════════════════════════════════════════

@router.post("/gap-questions/start", response_model=StartGapQuestionsResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_CHAT)
async def onboarding_gap_questions_start(request: Request, body: StartGapQuestionsRequest = Body(...)):
    """
    Generate gap questions before playbook generation.
    Similar to precision/start but for pre-playbook context gaps.

    Returns:
      - questions: list of gap questions (0-3)
      - available: True if questions exist and need answers

    If questions=[] and available=False, frontend should proceed directly to playbook.
    """
    onboarding_id = await _resolve_onboarding_id(
        request=request,
        provided_onboarding_id=body.onboarding_id,
    )

    from app.db import get_pool
    from app.repositories import onboarding_repository as onboarding_repo

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await onboarding_repo.find_gap_questions_context(conn, onboarding_id)
        if not row:
            raise HTTPException(status_code=404, detail="Onboarding row not found")

        outcome = str(row.get("outcome") or "")
        domain = str(row.get("domain") or "")
        task = str(row.get("task") or "")
        scale_answers = _as_dict(row.get("scale_answers"))
        rca_qa = _as_list(row.get("rca_qa"))
        rca_history = [
            {"question": str(it.get("question") or ""), "answer": str(it.get("answer") or "")}
            for it in rca_qa
            if isinstance(it, dict) and it.get("answer") not in (None, "")
        ]
        rca_summary = str(row.get("rca_summary") or "")
        rca_handoff = str(row.get("rca_handoff") or "")
        web_summary = str(row.get("web_summary") or "")

        # Get precision answers with their questions for context
        precision_questions = _as_list(row.get("precision_questions"))
        precision_answers_raw = _as_list(row.get("precision_answers"))
        precision_answers = []
        for ans in precision_answers_raw:
            q_idx = ans.get("question_index", 0)
            q_obj = precision_questions[q_idx] if q_idx < len(precision_questions) else {}
            q_text = ans.get("question", "") or q_obj.get("question", "")
            precision_answers.append({
                "question": q_text,
                "answer": str(ans.get("answer") or ""),
                "type": str(ans.get("type") or q_obj.get("type", "")),
                "insight": str(q_obj.get("insight", "")),  # Why this question was asked
            })

        outcome_label = {
            "lead-generation": "Lead Generation",
            "sales-retention": "Sales & Retention",
            "business-strategy": "Business Strategy",
            "save-time": "Save Time",
        }.get(outcome, "")

        # Generate gap questions using the new generator
        generated = await generate_gap_questions(
            outcome=outcome,
            outcome_label=outcome_label,
            domain=domain,
            task=task,
            rca_history=rca_history,
            scale_answers=scale_answers or None,
            web_summary=web_summary,
            rca_handoff=rca_handoff,
            rca_summary=rca_summary,
            precision_answers=precision_answers if precision_answers else None,
            onboarding_id=onboarding_id,
        )

        # Handle generation failure or empty questions
        if generated is None:
            # LLM call failed — treat as no questions needed, allow playbook to proceed
            logger.warning("Gap questions generation failed — treating as no questions needed")
            await onboarding_repo.set_gap_questions_ready(conn, onboarding_id)
            return StartGapQuestionsResponse(onboarding_id=onboarding_id, questions=[], available=False)

        if not generated or len(generated) == 0:
            # No questions needed — context is sufficient
            await onboarding_repo.set_gap_questions_ready(conn, onboarding_id)
            return StartGapQuestionsResponse(onboarding_id=onboarding_id, questions=[], available=False)

        # Clean up and store questions
        cleaned = [
            {
                "id": str(q.get("id") or f"Q{i+1}"),
                "label": str(q.get("label") or ""),
                "question": str(q.get("question") or ""),
                "why_matters": str(q.get("why_matters") or ""),
                "options": q.get("options") or [],
            }
            for i, q in enumerate(generated[:3])
        ]

        await onboarding_repo.set_gap_questions_awaiting(conn, onboarding_id, json.dumps(cleaned))

        return StartGapQuestionsResponse(
            onboarding_id=onboarding_id,
            questions=[GapQuestionItem(**q) for q in cleaned],
            available=len(cleaned) > 0,
        )

