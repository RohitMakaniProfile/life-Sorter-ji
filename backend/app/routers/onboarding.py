"""
POST /api/v1/onboarding — create a new session + onboarding row, or patch onboarding by session_id.
"""

from typing import Any, Optional

import json
import time
import structlog
from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel, Field

from app.config import get_settings
from app.middleware.auth_context import get_request_user, require_request_user
from app.middleware.rate_limit import limiter
from app.models.session import DynamicQuestion
from app.services import onboarding_service
from app.services.claude_rca_service import generate_precision_questions
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


class OnboardingStateResponse(BaseModel):
    """Response for GET /onboarding/state - returns the current onboarding state for session resumption."""
    session_id: str
    stage: str = "start"  # start | url | questions | diagnostic | precision | playbook | complete
    outcome: Optional[str] = None
    domain: Optional[str] = None
    task: Optional[str] = None
    website_url: Optional[str] = None
    gbp_url: Optional[str] = None
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

    # Check if precision questions are in progress
    precision_status = str(row.get("precision_status") or "")
    if precision_status == "awaiting_answers":
        return "precision"

    # Check if playbook is complete or generating
    playbook_status = str(row.get("playbook_status") or "")
    if playbook_status in ("complete", "generating", "started", "ready", "awaiting_gap_answers", "error"):
        return "playbook"

    # Parse rca_qa - handle both raw JSONB (dict/list) and JSON strings
    rca_qa_raw = row.get("rca_qa")
    rca_qa = _as_list(rca_qa_raw) if rca_qa_raw is not None else []

    rca_summary = str(row.get("rca_summary") or "")
    if rca_qa and len(rca_qa) > 0:
        has_unanswered = any(
            isinstance(qa, dict)
            and str(qa.get("question") or "").strip()
            and not str(qa.get("answer") or "").strip()
            for qa in rca_qa
        )
        if has_unanswered:
            return "diagnostic"
        # All RCA questions are answered. Even if summary text is not persisted yet,
        # do not send the UI back to diagnostic (prevents repeat question loops).
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
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> OnboardingStateResponse:
    """
    Get the current onboarding state for a session.
    Used for restoring the onboarding flow after page refresh.
    Supports lookup by user_id (preferred) or session_id.
    """
    from app.db import get_pool

    sid = (session_id or "").strip()
    uid = (user_id or "").strip()

    # Also try to get user_id from JWT if not provided
    if not uid:
        jwt_user = get_request_user(request)
        if jwt_user:
            uid = str(jwt_user.get("id") or "").strip()

    if not sid and not uid:
        raise HTTPException(status_code=400, detail="session_id or user_id is required")

    pool = get_pool()
    async with pool.acquire() as conn:
        row = None

        # Prefer explicit session_id lookup when provided (stable refresh/resume target).
        if sid:
            row = await conn.fetchrow(
                """
                SELECT
                    session_id, outcome, domain, task, website_url, gbp_url,
                    scale_answers, rca_qa, rca_summary, rca_handoff,
                    precision_questions, precision_answers, precision_status,
                    playbook_status, playbook_error, gap_questions, gap_answers, onboarding_completed_at
                FROM onboarding
                WHERE session_id = $1
                """,
                sid,
            )

        # Fall back to user_id lookup if session_id didn't resolve
        if not row and uid:
            row = await conn.fetchrow(
                """
                SELECT
                    session_id, outcome, domain, task, website_url, gbp_url,
                    scale_answers, rca_qa, rca_summary, rca_handoff,
                    precision_questions, precision_answers, precision_status,
                    playbook_status, playbook_error, gap_questions, gap_answers, onboarding_completed_at
                FROM onboarding
                WHERE user_id::text = $1
                ORDER BY updated_at DESC NULLS LAST, created_at DESC
                LIMIT 1
                """,
                uid,
            )

        if not row:
            raise HTTPException(status_code=404, detail="Onboarding session not found")

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

        gap_answers_map = _parse_gap_answers_map(row_dict.get("gap_answers"))
        gap_answers_parsed = {
            k: str(v.get("answer_key") or "")
            for k, v in gap_answers_map.items()
            if str(v.get("answer_key") or "")
        }

        return OnboardingStateResponse(
            session_id=str(row_dict.get("session_id") or ""),
            stage=stage,
            outcome=str(row_dict.get("outcome") or "") or None,
            domain=str(row_dict.get("domain") or "") or None,
            task=str(row_dict.get("task") or "") or None,
            website_url=str(row_dict.get("website_url") or "") or None,
            gbp_url=str(row_dict.get("gbp_url") or "") or None,
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
            gap_answers_parsed=gap_answers_parsed or None,
        )


@router.post("")
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def onboarding_upsert(
    request: Request,
    body: Optional[OnboardingRequest] = Body(default=None),
) -> dict[str, Any]:
    """
    - **No `session_id`**: creates a new onboarding `session_id` and inserts an `onboarding` row
      (with any optional `user_id`, `outcome`, `domain`, `task`, `website_url`, `gbp_url` sent in the body),
      returns `session_id` and `id` for the client to store (e.g. localStorage).
    - **With `session_id`**: inserts or updates the latest `onboarding` row for that session with any provided fields.
    - **If session is complete**: creates a new onboarding row instead of updating, with user_id from JWT if available.
    """
    eff = body if body is not None else OnboardingRequest()
    sid = (eff.session_id or "").strip()

    # Get user_id from JWT if available
    jwt_user = get_request_user(request)
    jwt_user_id = str(jwt_user.get("id") or "").strip() if jwt_user else None

    try:
        create_or_patch_fields = eff.model_dump(exclude={"session_id"}, exclude_unset=True)

        if not sid:
            # Inject JWT user_id so the row is linked to the authenticated user from creation.
            if jwt_user_id and "user_id" not in create_or_patch_fields:
                create_or_patch_fields["user_id"] = jwt_user_id
            return await onboarding_service.create_session_with_onboarding(create_or_patch_fields)

        return await onboarding_service.upsert_onboarding_patch(sid, create_or_patch_fields, user_id=jwt_user_id)
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
    complete_handoff: str = ""


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


class StartOnboardingPlaybookRequest(BaseModel):
    session_id: Optional[str] = None


class SubmitOnboardingGapAnswersRequest(BaseModel):
    session_id: Optional[str] = None
    answers: str


class GapQuestion(BaseModel):
    id: str = ""
    label: str = ""
    question: str = ""
    options: list[str] = []


class StartOnboardingPlaybookResponse(BaseModel):
    session_id: str
    stage: str  # gap_questions | ready
    gap_questions_parsed: list[GapQuestion] = []
    message: str = ""


class LaunchOnboardingPlaybookRequest(BaseModel):
    session_id: Optional[str] = None


class LaunchOnboardingPlaybookResponse(BaseModel):
    session_id: str
    stage: str  # gap_questions | started
    gap_questions_parsed: list[GapQuestion] = []
    gap_answers_parsed: dict[str, str] = {}
    stream_id: str = ""
    stream_status: str = ""
    message: str = ""


class SubmitOnboardingGapAnswersResponse(BaseModel):
    session_id: str
    stage: str  # ready
    message: str = ""


class SubmitOnboardingMcqAnswerRequest(BaseModel):
    session_id: Optional[str] = None
    question_index: int
    answer_key: str
    answer_text: str = ""


class SubmitOnboardingMcqAnswerResponse(BaseModel):
    session_id: str
    stage: str  # awaiting_gap_answers | ready
    all_answered: bool = False
    answered_count: int = 0
    total_questions: int = 0
    next_question_index: Optional[int] = None
    gap_answers_parsed: dict[str, str] = {}
    message: str = ""


class PrecisionQuestionItem(BaseModel):
    type: str = ""
    insight: str = ""
    question: str = ""
    options: list[str] = []
    section_label: str = ""


class StartOnboardingPrecisionRequest(BaseModel):
    session_id: Optional[str] = None


class StartOnboardingPrecisionResponse(BaseModel):
    session_id: str
    questions: list[PrecisionQuestionItem] = []
    available: bool = False


class SubmitOnboardingPrecisionAnswerRequest(BaseModel):
    session_id: Optional[str] = None
    question_index: int
    answer: str


class SubmitOnboardingPrecisionAnswerResponse(BaseModel):
    session_id: str
    next_question: Optional[PrecisionQuestionItem] = None
    all_answered: bool = False
    precision_status: str = ""  # awaiting_answers | complete


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


def _fallback_mcq_questions(domain: str, task: str) -> list[dict[str, Any]]:
    domain_label = domain.strip() or "your domain"
    task_label = task.strip() or "your key goal"
    return [
        {
            "id": "Q1",
            "label": "Target Customer",
            "question": f"For {task_label}, who is your primary customer segment in {domain_label}?",
            "options": [
                "A) Local businesses / SMB",
                "B) Mid-market companies",
                "C) Enterprise accounts",
                "D) Mixed audience",
            ],
        },
        {
            "id": "Q2",
            "label": "Urgent Pain",
            "question": "Which pain point is the most urgent to solve right now?",
            "options": [
                "A) Low lead volume",
                "B) Poor conversion quality",
                "C) Slow sales cycle",
                "D) Retention / repeat revenue",
            ],
        },
        {
            "id": "Q3",
            "label": "Growth Channel",
            "question": "Which channel drives the highest intent users today?",
            "options": [
                "A) Organic (SEO/content)",
                "B) Paid ads",
                "C) Outbound / direct outreach",
                "D) Referrals / communities",
            ],
        },
        {
            "id": "Q4",
            "label": "Execution Capacity",
            "question": "How much execution bandwidth can you allocate weekly?",
            "options": [
                "A) <5 hours",
                "B) 5-10 hours",
                "C) 10-20 hours",
                "D) Dedicated team capacity",
            ],
        },
    ]


def _normalize_mcq_questions(parsed: list[dict[str, Any]], domain: str, task: str) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for i, raw in enumerate(parsed):
        if not isinstance(raw, dict):
            continue
        qid = str(raw.get("id") or f"Q{i + 1}").strip() or f"Q{i + 1}"
        label = str(raw.get("label") or "").strip() or f"Question {i + 1}"
        question = str(raw.get("question") or "").strip()
        options_raw = raw.get("options") if isinstance(raw.get("options"), list) else []
        options: list[str] = []
        for oi, opt in enumerate(options_raw):
            text = str(opt or "").strip()
            if not text:
                continue
            if len(text) >= 2 and text[0] in "ABCDE" and text[1] == ")":
                options.append(text)
            else:
                letter = chr(ord("A") + oi)
                options.append(f"{letter}) {text}")
        options = options[:4]
        if question and len(options) >= 2:
            normalized.append(
                {
                    "id": qid,
                    "label": label,
                    "question": question,
                    "options": options,
                }
            )
        if len(normalized) >= 4:
            break
    if len(normalized) < 3:
        return _fallback_mcq_questions(domain=domain, task=task)
    return normalized[:4]


def _parse_gap_answers_map(raw: Any) -> dict[str, dict[str, str]]:
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
    except Exception:
        return {}
    if not isinstance(parsed, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    for k, v in parsed.items():
        if not isinstance(v, dict):
            continue
        key = str(k).strip()
        if not key:
            continue
        out[key] = {
            "answer_key": str(v.get("answer_key") or "").strip(),
            "answer_text": str(v.get("answer_text") or "").strip(),
            "question_id": str(v.get("question_id") or "").strip(),
            "question": str(v.get("question") or "").strip(),
        }
    return out


def _serialize_gap_answers_text(
    questions: list[dict[str, Any]],
    answers_map: dict[str, dict[str, str]],
) -> str:
    lines: list[str] = []
    for i, q in enumerate(questions):
        key = str(i)
        ans = answers_map.get(key) or {}
        if not str(ans.get("answer_key") or "").strip():
            continue
        qid = str(q.get("id") or f"Q{i + 1}").strip() or f"Q{i + 1}"
        answer_key = str(ans.get("answer_key") or "").strip()
        answer_text = str(ans.get("answer_text") or "").strip()
        if answer_text:
            lines.append(f"{qid}-{answer_key}) {answer_text}")
        else:
            lines.append(f"{qid}-{answer_key}")
    return "\n".join(lines).strip()



async def _resolve_onboarding_session_id(
    *,
    request: Request,
    provided_session_id: Optional[str],
) -> str:
    sid = (provided_session_id or "").strip()
    if sid:
        return sid
    user = get_request_user(request) or {}
    sid_from_user = str(user.get("onboarding_session_id") or "").strip()
    if sid_from_user:
        return sid_from_user
    claims = getattr(request.state, "auth_claims", None) or {}
    sid_claim = str(claims.get("onboarding_session_id") or claims.get("session_id") or "").strip()
    if sid_claim:
        return sid_claim
    sub = str(user.get("id") or claims.get("sub") or "").strip()
    if not sub:
        raise HTTPException(status_code=400, detail="session_id is required")
    from app.db import get_pool
    pool = get_pool()
    async with pool.acquire() as conn:
        linked_sid = await conn.fetchval(
            "SELECT onboarding_session_id FROM users WHERE id::text = $1 LIMIT 1",
            sub,
        )
    sid_db = str(linked_sid or "").strip()
    if sid_db:
        return sid_db
    raise HTTPException(status_code=400, detail="session_id is required")


async def _prepare_onboarding_playbook(request: Request, body: StartOnboardingPlaybookRequest) -> StartOnboardingPlaybookResponse:
    """
    Onboarding-native playbook start:
    - Reads context from `onboarding` table
    - Generates Phase 0 gap questions (if any)
    - Persists `gap_questions` and `playbook_status` in onboarding
    """
    from app.db import get_pool
    from app.services.playbook_service import run_phase0_gap_questions

    sid = await _resolve_onboarding_session_id(
        request=request,
        provided_session_id=body.session_id,
    )

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                id, outcome, domain, task,
                scale_answers, rca_qa, rca_summary, rca_handoff,
                crawl_run_id, crawl_cache_key,
                playbook_status, gap_questions, gap_answers,
                precision_status, precision_questions, precision_answers
            FROM onboarding
            WHERE session_id = $1
            """,
            sid,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Onboarding session not found")

        onboarding_id = row.get("id")
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
        playbook_status = str(row.get("playbook_status") or "").strip()
        existing_gap_questions = _as_list(row.get("gap_questions"))
        existing_answers_map = _parse_gap_answers_map(row.get("gap_answers"))
        precision_status = str(row.get("precision_status") or "").strip()
        precision_questions = _as_list(row.get("precision_questions"))
        precision_answers = _as_list(row.get("precision_answers"))

        if precision_status == "awaiting_answers" and precision_questions:
            answered = len([x for x in precision_answers if isinstance(x, dict) and str(x.get("answer") or "").strip()])
            if answered < len(precision_questions):
                raise HTTPException(
                    status_code=409,
                    detail="Complete precision questions before starting playbook.",
                )

        if existing_gap_questions:
            answered_count = sum(
                1
                for i in range(len(existing_gap_questions))
                if str((existing_answers_map.get(str(i)) or {}).get("answer_key") or "").strip()
            )
            total_count = len(existing_gap_questions)
            if answered_count >= total_count and total_count > 0:
                await conn.execute(
                    """
                    UPDATE onboarding
                    SET playbook_status = 'ready',
                        updated_at = NOW()
                    WHERE id = $1
                    """,
                    onboarding_id,
                )
                return StartOnboardingPlaybookResponse(
                    session_id=sid,
                    stage="ready",
                    gap_questions_parsed=[],
                    message="Ready to generate playbook.",
                )

            await conn.execute(
                """
                UPDATE onboarding
                SET playbook_status = 'awaiting_gap_answers',
                    updated_at = NOW()
                WHERE id = $1
                """,
                onboarding_id,
            )
            return StartOnboardingPlaybookResponse(
                session_id=sid,
                stage="gap_questions",
                gap_questions_parsed=[GapQuestion(**g) for g in existing_gap_questions],
                message="Answer these quick MCQs to personalize your playbook.",
            )

        if playbook_status in ("ready", "started", "generating", "complete"):
            return StartOnboardingPlaybookResponse(
                session_id=sid,
                stage="ready",
                gap_questions_parsed=[],
                message="Ready to generate playbook.",
            )

        outcome_label = {
            "lead-generation": "Lead Generation",
            "sales-retention": "Sales & Retention",
            "business-strategy": "Business Strategy",
            "save-time": "Save Time",
        }.get(outcome, "")

        await conn.execute(
            """
            UPDATE onboarding
            SET playbook_status = 'starting',
                playbook_started_at = COALESCE(playbook_started_at, NOW()),
                playbook_error = '',
                updated_at = NOW()
            WHERE id = $1
            """,
            onboarding_id,
        )

        # Crawl snapshots (best-effort): resolve via crawl_run_id -> crawl_cache, or crawl_cache_key -> crawl_cache.
        crawl_summary: dict[str, Any] = {}
        try:
            crawl_row = None
            crawl_run_id = row.get("crawl_run_id")
            crawl_cache_key = str(row.get("crawl_cache_key") or "").strip()
            if crawl_run_id:
                crawl_row = await conn.fetchrow(
                    """
                    SELECT cc.crawl_summary
                    FROM crawl_runs cr
                    JOIN crawl_cache cc ON cc.id = cr.crawl_cache_id
                    WHERE cr.id = $1
                    """,
                    crawl_run_id,
                )
            elif crawl_cache_key:
                crawl_row = await conn.fetchrow(
                    """
                    SELECT crawl_summary
                    FROM crawl_cache
                    WHERE normalized_url = $1 AND crawler_version = 'v1'
                    """,
                    crawl_cache_key,
                )
            if crawl_row:
                v = crawl_row.get("crawl_summary")
                if isinstance(v, str):
                    crawl_summary = json.loads(v) if v else {}
                elif isinstance(v, dict):
                    crawl_summary = v
        except Exception:
            crawl_summary = {}

        phase0 = await run_phase0_gap_questions(
            outcome_label=outcome_label,
            domain=domain,
            task=task,
            business_profile=scale_answers,
            rca_history=rca_history,
            rca_summary=rca_summary,
            crawl_summary=crawl_summary,
            rca_handoff=rca_handoff,
        )
        try:
            from app.doable_claw_agent.stores import save_token_usage

            usage = phase0.get("usage") if isinstance(phase0, dict) else {}
            input_tokens = int((usage or {}).get("prompt_tokens") or 0)
            output_tokens = int((usage or {}).get("completion_tokens") or 0)
            if input_tokens > 0 or output_tokens > 0:
                await save_token_usage(
                    f"onboarding-gap:{sid}:{int(time.time() * 1000)}",
                    "anthropic/claude-sonnet-4-6",
                    input_tokens,
                    output_tokens,
                    stage="onboarding_gap",
                    provider="openrouter",
                    session_id=sid,
                )
        except Exception:
            logger.warning("phase0 gap token usage save failed", session_id=sid)
        gap_text = str(phase0.get("gap_questions_text") or "")
        parsed_raw = _parse_gap_questions(gap_text) if gap_text else []
        parsed = _normalize_mcq_questions(parsed_raw, domain=domain, task=task)

        if parsed:
            await conn.execute(
                """
                UPDATE onboarding
                SET gap_questions = $1::jsonb,
                    gap_answers = '',
                    playbook_status = 'awaiting_gap_answers',
                    updated_at = NOW()
                WHERE id = $2
                """,
                json.dumps(parsed),
                onboarding_id,
            )
            return StartOnboardingPlaybookResponse(
                session_id=sid,
                stage="gap_questions",
                gap_questions_parsed=[GapQuestion(**g) for g in parsed],
                message="Answer these quick MCQs to personalize your playbook.",
            )

        await conn.execute(
            """
            UPDATE onboarding
            SET gap_questions = '[]'::jsonb,
                playbook_status = 'ready',
                updated_at = NOW()
            WHERE id = $1
            """,
            onboarding_id,
        )
        return StartOnboardingPlaybookResponse(
            session_id=sid,
            stage="ready",
            gap_questions_parsed=[],
            message="Ready to generate playbook.",
        )


@router.post("/playbook/launch", response_model=LaunchOnboardingPlaybookResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def onboarding_playbook_launch(request: Request, body: LaunchOnboardingPlaybookRequest = Body(...)):
    """
    Transactional playbook launch (post-auth):
    - Ensures prep state (gap questions) is computed.
    - If gap questions needed: returns `stage=gap_questions`.
    - Else starts/resumes background stream and returns `stage=started` + stream_id.
    """
    require_request_user(request)

    sid = await _resolve_onboarding_session_id(
        request=request,
        provided_session_id=body.session_id,
    )
    prep = await _prepare_onboarding_playbook(
        request=request,
        body=StartOnboardingPlaybookRequest(session_id=sid),
    )
    if prep.stage == "gap_questions":
        from app.db import get_pool
        pool = get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT gap_answers FROM onboarding WHERE session_id = $1 LIMIT 1",
                sid,
            )
        answers_map = _parse_gap_answers_map(row.get("gap_answers") if row else None)
        gap_answers_parsed = {
            k: str(v.get("answer_key") or "")
            for k, v in answers_map.items()
            if str(v.get("answer_key") or "")
        }
        return LaunchOnboardingPlaybookResponse(
            session_id=prep.session_id,
            stage="gap_questions",
            gap_questions_parsed=prep.gap_questions_parsed,
            gap_answers_parsed=gap_answers_parsed,
            message=prep.message,
        )

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
        payload={"session_id": prep.session_id},
        session_id=prep.session_id,
        user_id=None,
        resume_if_exists=True,
    )
    return LaunchOnboardingPlaybookResponse(
        session_id=prep.session_id,
        stage="started",
        gap_questions_parsed=[],
        gap_answers_parsed={},
        stream_id=str(started.get("stream_id") or ""),
        stream_status=str(started.get("status") or ""),
        message="Playbook generation started.",
    )


@router.post("/playbook/gap-answers", response_model=SubmitOnboardingGapAnswersResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def onboarding_playbook_gap_answers(request: Request, body: SubmitOnboardingGapAnswersRequest = Body(...)):
    """
    Persist user's gap answers into onboarding row.
    """
    from app.db import get_pool

    require_request_user(request)
    sid = await _resolve_onboarding_session_id(
        request=request,
        provided_session_id=body.session_id,
    )

    answers = str(body.answers or "").strip()
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id
            FROM onboarding
            WHERE session_id = $1
            """,
            sid,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Onboarding session not found")

        await conn.execute(
            """
            UPDATE onboarding
            SET gap_answers = $1,
                playbook_status = 'ready',
                updated_at = NOW()
            WHERE id = $2
            """,
            answers,
            row.get("id"),
        )

    return SubmitOnboardingGapAnswersResponse(session_id=sid, stage="ready", message="Gap answers saved.")


@router.post("/playbook/mcq-answer", response_model=SubmitOnboardingMcqAnswerResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def onboarding_playbook_mcq_answer(
    request: Request,
    body: SubmitOnboardingMcqAnswerRequest = Body(...),
):
    """
    Save one MCQ answer at a time for playbook personalization.
    """
    from app.db import get_pool

    require_request_user(request)
    sid = await _resolve_onboarding_session_id(
        request=request,
        provided_session_id=body.session_id,
    )
    idx = int(body.question_index)
    if idx < 0:
        raise HTTPException(status_code=400, detail="question_index must be >= 0")
    answer_key = str(body.answer_key or "").strip().upper()
    if answer_key not in {"A", "B", "C", "D", "E"}:
        raise HTTPException(status_code=400, detail="answer_key must be one of A,B,C,D,E")
    answer_text = str(body.answer_text or "").strip()

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, gap_questions, gap_answers
            FROM onboarding
            WHERE session_id = $1
            LIMIT 1
            """,
            sid,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Onboarding session not found")

        gap_questions = _as_list(row.get("gap_questions"))
        if not gap_questions:
            raise HTTPException(status_code=400, detail="No MCQ questions available for this session")
        if idx >= len(gap_questions):
            raise HTTPException(status_code=400, detail="Invalid question_index")

        q = gap_questions[idx] if isinstance(gap_questions[idx], dict) else {}
        answers_map = _parse_gap_answers_map(row.get("gap_answers"))
        answers_map[str(idx)] = {
            "answer_key": answer_key,
            "answer_text": answer_text,
            "question_id": str(q.get("id") or f"Q{idx + 1}"),
            "question": str(q.get("question") or ""),
        }

        answered_count = sum(
            1
            for i in range(len(gap_questions))
            if str((answers_map.get(str(i)) or {}).get("answer_key") or "").strip()
        )
        total_questions = len(gap_questions)
        all_answered = answered_count >= total_questions and total_questions > 0
        stage = "ready" if all_answered else "awaiting_gap_answers"
        next_question_index = None if all_answered else answered_count
        serialized_map = json.dumps(answers_map)
        serialized_text = _serialize_gap_answers_text(gap_questions, answers_map)

        await conn.execute(
            """
            UPDATE onboarding
            SET gap_answers = $1,
                playbook_status = $2,
                updated_at = NOW()
            WHERE id = $3
            """,
            serialized_map if serialized_map else serialized_text,
            stage,
            row.get("id"),
        )

    simple_map = {
        k: str(v.get("answer_key") or "")
        for k, v in answers_map.items()
        if str(v.get("answer_key") or "")
    }
    return SubmitOnboardingMcqAnswerResponse(
        session_id=sid,
        stage=stage,
        all_answered=all_answered,
        answered_count=answered_count,
        total_questions=total_questions,
        next_question_index=next_question_index,
        gap_answers_parsed=simple_map,
        message="MCQ answer saved.",
    )


@router.post("/precision/start", response_model=StartOnboardingPrecisionResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_CHAT)
async def onboarding_precision_start(request: Request, body: StartOnboardingPrecisionRequest = Body(...)):
    sid = await _resolve_onboarding_session_id(
        request=request,
        provided_session_id=body.session_id,
    )

    from app.db import get_pool

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT outcome, domain, task, scale_answers, rca_qa, crawl_run_id, crawl_cache_key
            FROM onboarding
            WHERE session_id = $1
            """,
            sid,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Onboarding session not found")

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
            return StartOnboardingPrecisionResponse(session_id=sid, questions=[], available=False)

        crawl_summary: dict[str, Any] = {}
        crawl_raw: dict[str, Any] = {}
        try:
            crawl_row = None
            crawl_run_id = row.get("crawl_run_id")
            crawl_cache_key = str(row.get("crawl_cache_key") or "").strip()
            if crawl_run_id:
                crawl_row = await conn.fetchrow(
                    """
                    SELECT cc.crawl_summary, cc.crawl_raw
                    FROM crawl_runs cr
                    JOIN crawl_cache cc ON cc.id = cr.crawl_cache_id
                    WHERE cr.id = $1
                    """,
                    crawl_run_id,
                )
            elif crawl_cache_key:
                crawl_row = await conn.fetchrow(
                    """
                    SELECT crawl_summary, crawl_raw
                    FROM crawl_cache
                    WHERE normalized_url = $1 AND crawler_version = 'v1'
                    """,
                    crawl_cache_key,
                )
            if crawl_row:
                crawl_summary = _as_dict(crawl_row.get("crawl_summary"))
                crawl_raw = _as_dict(crawl_row.get("crawl_raw"))
        except Exception:
            crawl_summary, crawl_raw = {}, {}

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
            crawl_summary=crawl_summary or None,
            crawl_raw=crawl_raw or None,
            business_profile=scale_answers or None,
        )
        if not generated:
            await conn.execute(
                """
                UPDATE onboarding
                SET precision_questions = '[]'::jsonb,
                    precision_answers = '[]'::jsonb,
                    precision_status = 'complete',
                    precision_completed_at = NOW(),
                    updated_at = NOW()
                WHERE session_id = $1
                """,
                sid,
            )
            return StartOnboardingPrecisionResponse(session_id=sid, questions=[], available=False)

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
        await conn.execute(
            """
            UPDATE onboarding
            SET precision_questions = $1::jsonb,
                precision_answers = '[]'::jsonb,
                precision_status = 'awaiting_answers',
                precision_completed_at = NULL,
                updated_at = NOW()
            WHERE session_id = $2
            """,
            json.dumps(cleaned),
            sid,
        )
        return StartOnboardingPrecisionResponse(
            session_id=sid,
            questions=[PrecisionQuestionItem(**q) for q in cleaned],
            available=len(cleaned) > 0,
        )


@router.post("/precision/answer", response_model=SubmitOnboardingPrecisionAnswerResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_CHAT)
async def onboarding_precision_answer(request: Request, body: SubmitOnboardingPrecisionAnswerRequest = Body(...)):
    sid = await _resolve_onboarding_session_id(
        request=request,
        provided_session_id=body.session_id,
    )
    if body.question_index < 0:
        raise HTTPException(status_code=400, detail="question_index must be >= 0")

    from app.db import get_pool

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, precision_questions, precision_answers, questions_answers
            FROM onboarding
            WHERE session_id = $1
            """,
            sid,
        )
        if not row:
            raise HTTPException(status_code=404, detail="Onboarding session not found")

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
            await conn.execute(
                """
                UPDATE onboarding
                SET precision_answers = $1::jsonb,
                    precision_status = 'complete',
                    precision_completed_at = NOW(),
                    questions_answers = $2::jsonb,
                    updated_at = NOW()
                WHERE session_id = $3
                """,
                json.dumps(precision_answers),
                json.dumps(qa_log),
                sid,
            )
            return SubmitOnboardingPrecisionAnswerResponse(
                session_id=sid,
                all_answered=True,
                precision_status="complete",
            )

        await conn.execute(
            """
            UPDATE onboarding
            SET precision_answers = $1::jsonb,
                precision_status = 'awaiting_answers',
                questions_answers = $2::jsonb,
                updated_at = NOW()
            WHERE session_id = $3
            """,
            json.dumps(precision_answers),
            json.dumps(qa_log),
            sid,
        )
        next_q = precision_questions[next_idx]
        return SubmitOnboardingPrecisionAnswerResponse(
            session_id=sid,
            next_question=PrecisionQuestionItem(**next_q),
            all_answered=False,
            precision_status="awaiting_answers",
        )
