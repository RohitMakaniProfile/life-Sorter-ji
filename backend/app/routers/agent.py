"""
═══════════════════════════════════════════════════════════════
AGENT ROUTER — AI Agent with Dynamic Persona & Session Context
═══════════════════════════════════════════════════════════════
Endpoints for the AI agent flow:

POST  /api/v1/agent/session                     — Create a new session
PATCH /api/v1/agent/session/{id}                — Update simple session fields
POST  /api/v1/agent/session/{id}/advance        — Execute workflow step
GET   /api/v1/agent/session/{id}/status         — Lightweight progress status
GET   /api/v1/agent/session/{id}                — Get full session context
GET   /api/v1/agent/session/{id}/context-pool   — Full LLM/debug context
GET   /api/v1/agent/session/{id}/website-snapshot — Structured crawl snapshot
"""

import asyncio

import structlog
from fastapi import APIRouter, Body, HTTPException, Query, Request
from pydantic import BaseModel
from typing import Any, Literal, Optional

from app.config import get_settings
from app.middleware.rate_limit import limiter
from app.utils.url_sanitize import sanitize_http_url
from app.services import session_store, agent_service
from app.services.crawl_service import detect_url_type, run_background_crawl
from app.services.persona_doc_service import get_doc_for_domain, get_diagnostic_sections
from app.services.claude_rca_service import generate_next_rca_question, generate_precision_questions, generate_task_alignment_filter
from app.services.rca_tree_service import get_first_question, get_task_filter, get_next_from_tree, load_tree
from app.models.session import (
    SessionStage,
    GenerateDynamicQuestionsRequest,
    GenerateDynamicQuestionsResponse,
    DynamicQuestion,
    SubmitDynamicAnswerRequest,
    SubmitDynamicAnswerResponse,
    GetRecommendationsRequest,
    GetRecommendationsResponse,
    ToolRecommendation,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/agent", tags=["Agent"])


# ── Request/Response Models ────────────────────────────────────


class CreateSessionResponse(BaseModel):
    session_id: str
    stage: str


class SetTaskRequest(BaseModel):
    session_id: str
    task: str              # e.g., 'Generate social media posts captions & hooks'


class EarlyToolRecommendation(BaseModel):
    name: str
    description: str
    url: Optional[str] = None
    category: str = ""       # 'extension', 'gpt', 'company'
    rating: Optional[str] = None
    why_relevant: str = ""   # Brief relevance note based on Q1-Q3
    implementation_stage: str = ""   # When to implement in their workflow
    issue_solved: str = ""           # What issue this tool addresses
    ease_of_use: str = ""            # How easy to adopt given current process


class SetTaskResponse(BaseModel):
    session_id: str
    stage: str
    persona_loaded: str
    task_matched: str = ""
    questions: list[DynamicQuestion]
    rca_mode: bool = False          # True = Claude adaptive, False = static fallback
    acknowledgment: str = ""        # Claude's acknowledgment text (first question only)
    insight: str = ""               # Teaching insight for the first question
    # Early recommendations after Q3
    early_recommendations: list[EarlyToolRecommendation] = []
    early_recommendations_message: str = ""  # Message urging user to continue RCA


class SubmitWebsiteRequest(BaseModel):
    session_id: str
    website_url: str


class AudienceInsight(BaseModel):
    intended_audience: str = ""
    actual_audience: str = ""
    mismatch_analysis: str = ""
    recommendations: list[str] = []


class WebsiteAnalysisResponse(BaseModel):
    session_id: str
    website_url: str
    audience_insights: AudienceInsight
    business_summary: str = ""
    analysis_note: str = ""


class SessionContextResponse(BaseModel):
    session_id: str
    stage: str
    outcome: Optional[str] = None
    outcome_label: Optional[str] = None
    domain: Optional[str] = None
    task: Optional[str] = None
    persona_doc: Optional[str] = None
    questions_answers: list[dict[str, Any]] = []
    dynamic_questions_progress: str = "0/0"
    recommendations: dict[str, Any] = {}
    website_url: Optional[str] = None
    url_type: Optional[str] = None
    audience_insights: Optional[dict[str, Any]] = None
    crawl_status: Optional[str] = None
    crawl_summary: Optional[dict[str, Any]] = None
    business_profile: Optional[dict[str, Any]] = None
    scale_questions_complete: bool = False


class SessionPatchRequest(BaseModel):
    outcome: Optional[str] = None
    outcome_label: Optional[str] = None
    domain: Optional[str] = None
    task: Optional[str] = None
    business_url: Optional[str] = None
    gbp_url: Optional[str] = None
    skip_url: Optional[bool] = None
    scale_answers: Optional[dict[str, Any]] = None
    dynamic_question: Optional[str] = None
    dynamic_answer: Optional[str] = None
    stage: Optional[str] = None


class SessionAdvanceRequest(BaseModel):
    action: str = "auto"  # auto | task_setup | submit_answer | scale_questions | website_analysis | start_diagnostic | precision_questions | recommend
    task: Optional[str] = None
    question_index: Optional[int] = None
    answer: Optional[str] = None
    website_url: Optional[str] = None


class SessionAdvanceResponse(BaseModel):
    session_id: str
    action: str
    stage: str
    result: dict[str, Any] = {}
    snapshot: SessionContextResponse


class SessionStatusResponse(BaseModel):
    session_id: str
    stage: str
    crawl_status: str = ""
    crawl_summary: Optional[dict[str, Any]] = None
    rca_complete: bool = False
    scale_questions_complete: bool = False
    playbook_stage: str = ""


# ── Endpoints ──────────────────────────────────────────────────


@router.post("/session", response_model=CreateSessionResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def create_session(request: Request):
    """Create a new chat session."""
    session = session_store.create_session()
    return CreateSessionResponse(
        session_id=session.session_id,
        stage=session.stage.value,
    )


async def set_task_and_generate_questions(request: Request, body: SetTaskRequest = Body(...)):
    """
    Record Q3: Task selection.
    1. Loads diagnostic context from persona docs (internal only).
    2. Generates EARLY tool recommendations based on Q1+Q2+Q3 context.
    3. Calls Claude via OpenRouter for the FIRST adaptive RCA question.
    4. Falls back to static persona-doc questions if Claude fails.

    The early recommendations give the user immediate value while
    encouraging them to continue the RCA for more precise tools.
    """
    session = session_store.set_task(body.session_id, body.task)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Look up which persona doc this domain maps to
    persona_doc_name = get_doc_for_domain(session.domain or "")
    session.persona_doc_name = persona_doc_name
    session.persona_context_loaded = persona_doc_name is not None

    # Load diagnostic context from pre-parsed document (used as internal context)
    diagnostic = get_diagnostic_sections(
        domain=session.domain or "",
        task=session.task or "",
    )

    task_matched = ""
    if diagnostic:
        task_matched = diagnostic.get("task_matched", "")
        # Store the full diagnostic context for Claude to use
        session_store.set_rca_context(session.session_id, diagnostic)

    # ── INSTANT early recommendations (pre-mapped JSON, <1ms) ────
    from app.services.instant_tool_service import get_tools_for_q1_q2_q3

    early_recs = []
    early_message = ""
    try:
        instant_result = get_tools_for_q1_q2_q3(
            outcome=session.outcome or "",
            domain=session.domain or "",
            task=session.task or "",
        )
        if instant_result and instant_result.get("tools"):
            early_recs = [
                EarlyToolRecommendation(
                    name=t.get("name", ""),
                    description=t.get("description", ""),
                    url=t.get("url"),
                    category=t.get("category", ""),
                    rating=str(t.get("rating", "")) if t.get("rating") is not None else None,
                    why_relevant=t.get("best_use_case", ""),
                )
                for t in instant_result["tools"]
            ]
            early_message = instant_result.get("message", "")
            session_store.set_early_recommendations(
                session.session_id,
                tools=instant_result["tools"],
                message=early_message,
            )
            logger.info(
                "Instant early recommendations after Q3",
                session_id=session.session_id,
                tools_count=len(early_recs),
                match_type=instant_result.get("match_type"),
            )
    except Exception as e:
        logger.warning(
            "Instant recommendations failed (non-blocking)",
            session_id=session.session_id,
            error=str(e),
        )

    # ── First RCA question: try pre-generated tree first, then LLM fallback ──
    tree_q1 = get_first_question(
        outcome=session.outcome or "",
        domain=session.domain or "",
        task=session.task or "",
    )

    if tree_q1:
        # Instant hit from pre-generated tree — 0ms instead of 15-40s
        claude_result = {"status": "question", **tree_q1}
        logger.info("RCA Q1 served from tree (0ms)", session_id=session.session_id)
    else:
        logger.warning(
            "RCA Q1 tree miss; attempting LLM generation",
            session_id=session.session_id,
            outcome=session.outcome or "",
            domain=session.domain or "",
            task=session.task or "",
            has_diagnostic_context=bool(diagnostic),
        )
        # Fallback to live LLM call
        try:
            claude_result = await generate_next_rca_question(
                outcome=session.outcome or "",
                outcome_label=session.outcome_label or "",
                domain=session.domain or "",
                task=session.task or "",
                diagnostic_context=diagnostic or {},
                rca_history=[],
                business_profile=session.business_profile or None,
                gbp_data=session.gbp_data or None,
            )
        except Exception as exc:
            logger.exception(
                "RCA Q1 LLM generation failed",
                session_id=session.session_id,
                error=str(exc),
            )
            claude_result = None

        # Log Claude RCA call to context pool
        if claude_result and claude_result.get("_meta"):
            session_store.add_llm_call_log(session.session_id, **claude_result["_meta"])

    if claude_result and claude_result.get("status") == "question":
        # Claude gave us the first adaptive question
        first_q = DynamicQuestion(
            question=claude_result["question"],
            options=claude_result.get("options", []),
            allows_free_text=True,
            section=claude_result.get("section", "rca"),
            section_label=claude_result.get("section_label", "Diagnostic"),
            insight=claude_result.get("insight", ""),
        )

        # Store question text for tracking
        session.dynamic_questions = [claude_result["question"]]
        session.dynamic_questions_total = -1  # Unknown — Claude decides
        session_store.update_session(session)

        logger.info(
            "Claude RCA: first question generated",
            session_id=session.session_id,
            question=claude_result["question"][:80],
        )

        return SetTaskResponse(
            session_id=session.session_id,
            stage=session.stage.value,
            persona_loaded=persona_doc_name or "generic",
            task_matched=task_matched,
            questions=[first_q],  # Single question — frontend handles adaptively
            rca_mode=True,
            acknowledgment=claude_result.get("acknowledgment", ""),
            insight=claude_result.get("insight", ""),
            early_recommendations=early_recs,
            early_recommendations_message=early_message,
        )

    # ── Fallback: static persona-doc questions ─────────────────
    logger.warning(
        "Claude RCA unavailable, falling back to static questions",
        session_id=session.session_id,
        fallback_reason=(
            "empty_or_invalid_llm_result"
            if not claude_result
            else f"llm_status_{claude_result.get('status', 'unknown')}"
        ),
        tree_q1_found=bool(tree_q1),
        has_diagnostic_sections=bool((diagnostic or {}).get("sections")),
    )
    session_store.set_rca_fallback(session.session_id)

    dynamic_qs = []
    if diagnostic and diagnostic.get("sections"):
        for section in diagnostic["sections"]:
            dq = DynamicQuestion(
                question=section["question"],
                options=section["items"],
                allows_free_text=section.get("allows_free_text", True),
                section=section["key"],
                section_label=section["label"],
            )
            dynamic_qs.append(dq)
            session.dynamic_questions.append(section["question"])

    session.dynamic_questions_total = len(dynamic_qs)
    session_store.update_session(session)

    logger.info(
        "Fallback: static diagnostic sections loaded",
        session_id=session.session_id,
        num_sections=len(dynamic_qs),
        questions_stored=len(session.dynamic_questions),
        dynamic_questions_total=session.dynamic_questions_total,
    )

    return SetTaskResponse(
        session_id=session.session_id,
        stage=session.stage.value,
        persona_loaded=persona_doc_name or "generic",
        task_matched=task_matched,
        questions=dynamic_qs,
        rca_mode=False,
        early_recommendations=early_recs,
        early_recommendations_message=early_message,
    )


# ── New: Context-aware first diagnostic question ───────────────


class StartDiagnosticRequest(BaseModel):
    session_id: str


class StartDiagnosticResponse(BaseModel):
    session_id: str
    question: Optional[DynamicQuestion] = None
    acknowledgment: str = ""
    insight: str = ""
    rca_mode: bool = True
    context_used: list[str] = []   # What context influenced the question


async def start_diagnostic(request: Request, body: StartDiagnosticRequest = Body(...)):
    """
    Generate the first diagnostic question with FULL context:
    crawl summary + business profile + Q1/Q2/Q3.

    NEW: Runs Task Alignment Filter first to focus the RCA context
    on METHOD/SPEED/QUALITY dimensions of the specific task.

    Called after scale questions are done (and crawl may have completed).
    Replaces the stashed first question with a context-aware one.
    """
    session = session_store.get_session(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Gather all available context
    diagnostic = session.rca_diagnostic_context or {}
    business_profile = session.business_profile or None
    crawl_summary = session.crawl_summary or None

    context_used = []
    if business_profile:
        context_used.append("business_profile")
    if crawl_summary and crawl_summary.get("points"):
        context_used.append("crawl_summary")

    logger.info(
        "start-diagnostic: generating context-aware first question",
        session_id=session.session_id,
        context_used=context_used,
        has_diagnostic_context=bool(diagnostic),
        has_business_profile=bool(business_profile),
        has_crawl_summary=bool(crawl_summary),
        previous_dynamic_questions_count=len(session.dynamic_questions or []),
        previous_dynamic_total=session.dynamic_questions_total,
        previous_fallback_active=session.rca_fallback_active,
    )

    # Keep previous fallback questions in case adaptive question generation fails.
    previous_dynamic_questions = list(session.dynamic_questions or [])
    previous_dynamic_total = session.dynamic_questions_total

    # Reset RCA history for fresh start
    session.rca_history = []
    session.dynamic_questions = []
    session_store.update_session(session)

    # ── Step 3: Task Filter + First Question — try tree first, then LLM ──

    # Try pre-generated tree for both
    tree_filter = get_task_filter(
        outcome=session.outcome or "",
        domain=session.domain or "",
        task=session.task or "",
    )
    tree_q1 = get_first_question(
        outcome=session.outcome or "",
        domain=session.domain or "",
        task=session.task or "",
    )

    if tree_filter and tree_q1:
        # Both from tree — instant (0ms)
        filter_result = tree_filter
        claude_result = {"status": "question", **tree_q1}
        logger.info("start-diagnostic: both served from tree (0ms)", session_id=session.session_id)
    else:
        logger.warning(
            "start-diagnostic: tree miss; running LLM fallback path",
            session_id=session.session_id,
            tree_filter_found=bool(tree_filter),
            tree_q1_found=bool(tree_q1),
        )
        # Fallback to parallel LLM calls
        async def _run_filter():
            """Run task alignment filter — non-blocking, best-effort."""
            try:
                return await generate_task_alignment_filter(
                    task=session.task or "",
                    diagnostic_context=diagnostic,
                )
            except Exception as exc:
                logger.warning(
                    "Task filter error (non-blocking)",
                    session_id=session.session_id,
                    error=str(exc),
                )
                return None

        async def _run_first_question():
            """Generate first RCA question — critical path."""
            try:
                return await generate_next_rca_question(
                    outcome=session.outcome or "",
                    outcome_label=session.outcome_label or "",
                    domain=session.domain or "",
                    task=session.task or "",
                    diagnostic_context=diagnostic,
                    rca_history=[],
                    business_profile=business_profile,
                    crawl_summary=crawl_summary,
                    gbp_data=session.gbp_data or None,
                )
            except Exception as exc:
                logger.exception(
                    "start-diagnostic: first-question LLM call failed",
                    session_id=session.session_id,
                    error=str(exc),
                )
                return None

        filter_result, claude_result = await asyncio.gather(
            _run_filter(),
            _run_first_question(),
        )

    # Store filter result if it succeeded (will be used in subsequent questions)
    if filter_result:
        if filter_result.get("_meta"):
            session_store.add_llm_call_log(session.session_id, **filter_result["_meta"])

        session_store.set_filtered_context(
            session.session_id,
            filtered_items=filter_result.get("filtered_items", {}),
            deferred_items=filter_result.get("deferred_items", []),
            task_execution_summary=filter_result.get("task_execution_summary", ""),
            validation=filter_result.get("_validation"),
        )
        context_used.append("task_filter")

        validation = filter_result.get("_validation", {})
        logger.info(
            "start-diagnostic: task filter applied",
            session_id=session.session_id,
            method=validation.get("method_count", 0),
            speed=validation.get("speed_count", 0),
            quality=validation.get("quality_count", 0),
            empty_categories=validation.get("empty_categories", []),
        )
    else:
        logger.warning(
            "start-diagnostic: task filter failed/skipped, using full context",
            session_id=session.session_id,
            has_filter_result=False,
        )

    # Log to context pool
    if claude_result and claude_result.get("_meta"):
        session_store.add_llm_call_log(session.session_id, **claude_result["_meta"])

    if claude_result and claude_result.get("status") == "question":
        first_q = DynamicQuestion(
            question=claude_result["question"],
            options=claude_result.get("options", []),
            allows_free_text=True,
            section=claude_result.get("section", "rca"),
            section_label=claude_result.get("section_label", "Diagnostic"),
            insight=claude_result.get("insight", ""),
        )

        session.dynamic_questions = [claude_result["question"]]
        session.dynamic_questions_total = -1
        # Adaptive mode is active now; don't keep stale fallback flag enabled.
        session.rca_fallback_active = False
        session_store.update_session(session)

        logger.info(
            "start-diagnostic: context-aware question generated",
            session_id=session.session_id,
            context_used=context_used,
            question=claude_result["question"][:80],
            question_options_count=len(claude_result.get("options") or []),
            source=("tree" if tree_q1 and tree_filter else "llm"),
        )

        return StartDiagnosticResponse(
            session_id=session.session_id,
            question=first_q,
            acknowledgment=claude_result.get("acknowledgment", ""),
            insight=claude_result.get("insight", ""),
            rca_mode=True,
            context_used=context_used,
        )

    # Claude failed — restore prior fallback questions when available so submit_answer
    # with index 0 does not crash with "Invalid question index".
    if previous_dynamic_questions:
        session.dynamic_questions = previous_dynamic_questions
        session.dynamic_questions_total = previous_dynamic_total
        session_store.update_session(session)

        first_question_text = previous_dynamic_questions[0]
        fallback_options: list[str] = []
        fallback_allows_free_text = True
        fallback_section = "rca"
        fallback_section_label = "Diagnostic"

        # Recover rich metadata (options/section) from stored diagnostic context when possible.
        sections = (diagnostic or {}).get("sections") or []
        for sec in sections:
            if not isinstance(sec, dict):
                continue
            if str(sec.get("question") or "").strip() != first_question_text.strip():
                continue
            raw_items = sec.get("items") or []
            if isinstance(raw_items, list):
                fallback_options = [str(x) for x in raw_items if str(x).strip()]
            fallback_allows_free_text = bool(sec.get("allows_free_text", True))
            fallback_section = str(sec.get("key") or "rca")
            fallback_section_label = str(sec.get("label") or "Diagnostic")
            break

        first_fallback = DynamicQuestion(
            question=first_question_text,
            options=fallback_options,
            allows_free_text=fallback_allows_free_text,
            section=fallback_section,
            section_label=fallback_section_label,
        )
        logger.warning(
            "start-diagnostic: Claude failed, restored fallback questions",
            session_id=session.session_id,
            restored_count=len(previous_dynamic_questions),
            fallback_reason=(
                "empty_or_invalid_llm_result"
                if not claude_result
                else f"llm_status_{claude_result.get('status', 'unknown')}"
            ),
            restored_options_count=len(fallback_options),
        )
        return StartDiagnosticResponse(
            session_id=session.session_id,
            question=first_fallback,
            rca_mode=False,
            context_used=context_used,
        )

    # Claude failed and no fallback questions exist.
    logger.warning(
        "start-diagnostic: Claude failed, no fallback questions available",
        session_id=session.session_id,
        fallback_reason=(
            "empty_or_invalid_llm_result"
            if not claude_result
            else f"llm_status_{claude_result.get('status', 'unknown')}"
        ),
        diagnostic_sections_count=len((diagnostic or {}).get("sections") or []),
    )
    return StartDiagnosticResponse(
        session_id=session.session_id,
        rca_mode=False,
    )


# ── Precision Questions (Crawl × Answers cross-reference) ─────

class PrecisionQuestionItem(BaseModel):
    type: str                   # contradiction, blind_spot, unlock
    insight: str = ""
    question: str
    options: list[str] = []
    section_label: str = ""

class PrecisionQuestionsRequest(BaseModel):
    session_id: str

class PrecisionQuestionsResponse(BaseModel):
    session_id: str
    questions: list[PrecisionQuestionItem] = []
    available: bool = False     # True if questions were generated


async def get_precision_questions(request: Request, body: PrecisionQuestionsRequest = Body(...)):
    """
    Generate 3 precision questions that cross-reference crawl data with
    the user's diagnostic answers to find contradictions, blind spots,
    and unlock opportunities.
    """
    session = session_store.get_session(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Need crawl data OR answers to generate precision questions
    has_crawl = bool(session.crawl_summary and session.crawl_summary.get("points"))
    has_answers = bool(session.rca_history)

    if not has_answers:
        return PrecisionQuestionsResponse(
            session_id=session.session_id,
            questions=[],
            available=False,
        )

    result = await generate_precision_questions(
        outcome=session.outcome or "",
        outcome_label=session.outcome_label or "",
        domain=session.domain or "",
        task=session.task or "",
        rca_history=session.rca_history,
        crawl_summary=session.crawl_summary or None,
        crawl_raw=session.crawl_raw or None,
        business_profile=session.business_profile or None,
    )

    # Log precision questions to context pool
    if result and len(result) > 0 and result[0].get("_meta"):
        session_store.add_llm_call_log(session.session_id, **result[0]["_meta"])

    if not result:
        return PrecisionQuestionsResponse(
            session_id=session.session_id,
            questions=[],
            available=False,
        )

    questions = [
        PrecisionQuestionItem(
            type=q.get("type", "unknown"),
            insight=q.get("insight", ""),
            question=q.get("question", ""),
            options=q.get("options", []),
            section_label=q.get("section_label", ""),
        )
        for q in result
    ]

    logger.info(
        "Precision questions ready",
        session_id=session.session_id,
        count=len(questions),
    )

    return PrecisionQuestionsResponse(
        session_id=session.session_id,
        questions=questions,
        available=True,
    )


async def submit_dynamic_answer(request: Request, body: SubmitDynamicAnswerRequest = Body(...)):
    """
    Submit an answer to a diagnostic question.
    In RCA mode: sends all context + history to Claude → gets next adaptive question.
    In fallback mode: advances through static question list.
    """
    session = session_store.get_session(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # ── RCA Mode (Claude adaptive) ─────────────────────────────
    if not session.rca_fallback_active:
        # Record this answer
        question_text = (
            session.dynamic_questions[body.question_index]
            if body.question_index < len(session.dynamic_questions)
            else f"RCA Question {body.question_index + 1}"
        )
        session_store.add_rca_answer(
            body.session_id, question_text, body.answer
        )

        # Refresh session after adding answer
        session = session_store.get_session(body.session_id)

        # ── Step 6: Deferred context expansion ─────────────────
        # After 3 RCA questions, check if answers suggest broader scope
        if len(session.rca_history) >= 3 and not session.rca_context_expanded:
            session_store.expand_rca_context(body.session_id)
            session = session_store.get_session(body.session_id)

        # Try pre-generated tree first, then LLM fallback
        tree_result = get_next_from_tree(
            outcome=session.outcome or "",
            domain=session.domain or "",
            task=session.task or "",
            rca_history=session.rca_history,
        )

        if tree_result:
            # Instant hit from tree — 0ms instead of 15s
            claude_result = tree_result
            logger.info(
                "RCA answer served from tree (0ms)",
                session_id=session.session_id,
                q_index=len(session.rca_history),
            )
        else:
            logger.warning(
                "RCA next-question tree miss; attempting LLM generation",
                session_id=session.session_id,
                q_index=len(session.rca_history),
                rca_history_len=len(session.rca_history),
                has_filtered_context=bool(session.rca_filtered_context),
                has_running_summary=bool(session.rca_running_summary),
            )
            # Fallback to live LLM call
            try:
                claude_result = await generate_next_rca_question(
                    outcome=session.outcome or "",
                    outcome_label=session.outcome_label or "",
                    domain=session.domain or "",
                    task=session.task or "",
                    diagnostic_context=session.rca_diagnostic_context,
                    rca_history=session.rca_history,
                    business_profile=session.business_profile or None,
                    crawl_summary=session.crawl_summary or None,
                    gbp_data=session.gbp_data or None,
                    filtered_context=session.rca_filtered_context or None,
                    task_execution_summary=session.rca_task_execution_summary or None,
                    rca_running_summary=session.rca_running_summary or None,
                )
            except Exception as exc:
                logger.exception(
                    "RCA next-question LLM generation failed",
                    session_id=session.session_id,
                    q_index=len(session.rca_history),
                    error=str(exc),
                )
                claude_result = None

        # Log to context pool
        if claude_result and claude_result.get("_meta"):
            session_store.add_llm_call_log(body.session_id, **claude_result["_meta"])

        if claude_result and claude_result.get("status") == "question":
            # Store the running summary (compressed context for next turn)
            cumulative = claude_result.get("cumulative_insight", "")
            if cumulative:
                session_store.set_rca_running_summary(body.session_id, cumulative)

            next_q = DynamicQuestion(
                question=claude_result["question"],
                options=claude_result.get("options", []),
                allows_free_text=True,
                section=claude_result.get("section", "rca"),
                section_label=claude_result.get("section_label", "Diagnostic"),
                insight=claude_result.get("insight", ""),
            )
            # Track the question text
            session.dynamic_questions.append(claude_result["question"])
            session_store.update_session(session)

            logger.info(
                "Claude RCA: next question",
                session_id=session.session_id,
                q_index=len(session.rca_history),
                question=claude_result["question"][:80],
            )

            return SubmitDynamicAnswerResponse(
                session_id=session.session_id,
                next_question=next_q,
                all_answered=False,
                rca_mode=True,
                acknowledgment=claude_result.get("acknowledgment", ""),
                insight=claude_result.get("insight", ""),
            )

        elif claude_result and claude_result.get("status") == "complete":
            # Claude says we have enough — move to recommendation
            summary = claude_result.get("summary", "")
            raw_handoff = claude_result.get("handoff", "")
            # handoff may come as a list of bullet points — join into string
            if isinstance(raw_handoff, list):
                handoff = "\n".join(f"• {item}" for item in raw_handoff)
            else:
                handoff = raw_handoff or ""
            session_store.set_rca_complete(body.session_id, summary, handoff=handoff)

            logger.info(
                "Claude RCA: diagnostic complete",
                session_id=session.session_id,
                total_questions=len(session.rca_history),
                summary=summary[:100],
            )

            return SubmitDynamicAnswerResponse(
                session_id=session.session_id,
                next_question=None,
                all_answered=True,
                rca_mode=True,
                acknowledgment=claude_result.get("acknowledgment", ""),
                rca_summary=summary,
            )

        else:
            # Claude failed mid-flow — mark as complete and move on
            logger.warning(
                "Claude RCA failed mid-flow, completing diagnostic",
                session_id=session.session_id,
                q_index=len(session.rca_history),
                fallback_reason=(
                    "empty_or_invalid_llm_result"
                    if not claude_result
                    else f"llm_status_{claude_result.get('status', 'unknown')}"
                ),
            )
            session_store.set_rca_complete(body.session_id, "")
            return SubmitDynamicAnswerResponse(
                session_id=session.session_id,
                next_question=None,
                all_answered=True,
                rca_mode=True,
            )

    # ── Fallback Mode (static questions) ───────────────────────
    if body.question_index >= len(session.dynamic_questions):
        raise HTTPException(status_code=400, detail="Invalid question index")

    question_text = session.dynamic_questions[body.question_index]

    session = session_store.add_dynamic_answer(
        body.session_id, question_text, body.answer
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Determine next question or if all done
    next_index = body.question_index + 1
    all_answered = next_index >= session.dynamic_questions_total

    next_question = None
    if not all_answered and next_index < len(session.dynamic_questions):
        next_question = DynamicQuestion(
            question=session.dynamic_questions[next_index],
            options=[],
            allows_free_text=True,
        )

    return SubmitDynamicAnswerResponse(
        session_id=session.session_id,
        next_question=next_question,
        all_answered=all_answered,
        rca_mode=False,
    )


async def get_recommendations(request: Request, body: GetRecommendationsRequest = Body(...)):
    """
    Generate final personalized tool recommendations based on
    all Q&A (static Q1-Q3 + dynamic questions).
    """
    settings = get_settings()
    if not settings.openai_api_key_active:
        raise HTTPException(
            status_code=503,
            detail="AI service unavailable — OpenAI API key not configured.",
        )

    session = session_store.get_session(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Build Q&A list
    qa_list = [
        {"q": qa.question, "a": qa.answer, "type": qa.question_type}
        for qa in session.questions_answers
    ]

    # Generate personalized recommendations
    recs = await agent_service.generate_personalized_recommendations(
        outcome=session.outcome or "",
        outcome_label=session.outcome_label or "",
        domain=session.domain or "",
        task=session.task or "",
        questions_answers=qa_list,
        crawl_summary=session.crawl_summary or {},
        crawl_raw=session.crawl_raw if hasattr(session, 'crawl_raw') else None,
        business_profile=session.business_profile or {},
        rca_diagnostic_context=session.rca_diagnostic_context or {},
        rca_summary=session.rca_summary or "",
        gbp_data=session.gbp_data or None,
    )

    # Log to context pool
    if recs.get("_meta"):
        session_store.add_llm_call_log(body.session_id, **recs["_meta"])

    # Store in session
    session_store.set_recommendations(
        session.session_id,
        extensions=recs.get("extensions", []),
        gpts=recs.get("gpts", []),
        companies=recs.get("companies", []),
    )

    # Build response
    extensions = [
        ToolRecommendation(
            name=ext.get("name", ""),
            description=ext.get("description", ""),
            url=ext.get("url"),
            category="extension",
            free=ext.get("free"),
            why_recommended=ext.get("why_recommended", ""),
            implementation_stage=ext.get("implementation_stage", ""),
            issue_solved=ext.get("issue_solved", ""),
            ease_of_use=ext.get("ease_of_use", ""),
        )
        for ext in recs.get("extensions", [])
    ]

    gpts = [
        ToolRecommendation(
            name=gpt.get("name", ""),
            description=gpt.get("description", ""),
            url=gpt.get("url"),
            category="gpt",
            rating=gpt.get("rating"),
            why_recommended=gpt.get("why_recommended", ""),
            implementation_stage=gpt.get("implementation_stage", ""),
            issue_solved=gpt.get("issue_solved", ""),
            ease_of_use=gpt.get("ease_of_use", ""),
        )
        for gpt in recs.get("gpts", [])
    ]

    companies = [
        ToolRecommendation(
            name=co.get("name", ""),
            description=co.get("description", ""),
            url=co.get("url"),
            category="company",
            why_recommended=co.get("why_recommended", ""),
            implementation_stage=co.get("implementation_stage", ""),
            issue_solved=co.get("issue_solved", ""),
            ease_of_use=co.get("ease_of_use", ""),
        )
        for co in recs.get("companies", [])
    ]

    # Get session summary for context
    summary = session_store.get_session_summary(session.session_id) or {}

    return GetRecommendationsResponse(
        session_id=session.session_id,
        extensions=extensions,
        gpts=gpts,
        companies=companies,
        summary=recs.get("summary", ""),
        session_context=summary,
    )




def _get_session_or_404(session_id: str):
    session = session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def _get_snapshot_or_404(session_id: str) -> SessionContextResponse:
    summary = session_store.get_session_summary(session_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionContextResponse(**summary)


@router.patch("/session/{session_id}", response_model=SessionContextResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def patch_session(request: Request, session_id: str, body: SessionPatchRequest = Body(...)):
    """
    Consolidated state update endpoint for simple session fields.
    Keeps legacy step endpoints intact while enabling simplified frontend flow.
    """
    _get_session_or_404(session_id)

    if body.outcome is not None or body.outcome_label is not None:
        if not body.outcome or not body.outcome_label:
            raise HTTPException(status_code=400, detail="Both outcome and outcome_label are required")
        session_store.set_outcome(session_id, body.outcome, body.outcome_label)

    if body.domain is not None:
        session_store.set_domain(session_id, body.domain)

    if body.task is not None:
        # Patch path sets only task/stage; heavy generation remains in /advance
        session_store.set_task(session_id, body.task)

    if body.scale_answers is not None:
        session_store.set_business_profile(session_id, body.scale_answers)

    if body.business_url:
        normalized = sanitize_http_url(body.business_url)
        if normalized:
            url_type = detect_url_type(normalized)
            session_store.set_website_url(session_id, normalized, url_type)
            session_store.set_crawl_status(session_id, "in_progress")
            asyncio.create_task(run_background_crawl(session_id, normalized))

    if body.gbp_url:
        session = _get_session_or_404(session_id)
        normalized_gbp = sanitize_http_url(body.gbp_url)
        if normalized_gbp:
            session.gbp_url = normalized_gbp
            session_store.update_session(session)

    if body.skip_url:
        session = _get_session_or_404(session_id)
        session.website_url = None
        session.crawl_status = "skipped"
        session_store.update_session(session)

    if body.dynamic_answer:
        question = body.dynamic_question or f"RCA Question {len(_get_session_or_404(session_id).rca_history) + 1}"
        session_store.add_rca_answer(session_id, question, body.dynamic_answer)

    if body.stage:
        session = _get_session_or_404(session_id)
        try:
            session.stage = SessionStage(body.stage)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid stage: {body.stage}") from exc
        session_store.update_session(session)

    return _get_snapshot_or_404(session_id)


@router.post("/session/{session_id}/advance", response_model=SessionAdvanceResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_CHAT)
async def advance_session(request: Request, session_id: str, body: SessionAdvanceRequest = Body(...)):
    """
    Consolidated workflow progression endpoint.
    Runs heavyweight transitions while returning a fresh session snapshot.
    """
    session = _get_session_or_404(session_id)
    action = (body.action or "auto").strip().lower()

    if action == "auto":
        if session.stage in {SessionStage.DYNAMIC_QUESTIONS, SessionStage.SCALE_QUESTIONS, SessionStage.TASK}:
            action = "start_diagnostic"
        elif session.rca_complete:
            action = "recommend"
        else:
            action = "precision_questions"

    if action == "task_setup":
        if not body.task:
            raise HTTPException(status_code=400, detail="task is required for action=task_setup")
        result_model = await set_task_and_generate_questions(
            request,
            SetTaskRequest(session_id=session_id, task=body.task),
        )
        result = result_model.model_dump()
    elif action == "submit_answer":
        if body.question_index is None or body.answer is None:
            raise HTTPException(status_code=400, detail="question_index and answer are required for action=submit_answer")
        result_model = await submit_dynamic_answer(
            request,
            SubmitDynamicAnswerRequest(
                session_id=session_id,
                question_index=body.question_index,
                answer=body.answer,
            ),
        )
        result = result_model.model_dump()
    elif action == "scale_questions":
        result_model = await get_scale_questions_endpoint(session_id)
        result = result_model.model_dump()
    elif action == "website_analysis":
        if not body.website_url:
            raise HTTPException(status_code=400, detail="website_url is required for action=website_analysis")
        result_model = await submit_website(SubmitWebsiteRequest(session_id=session_id, website_url=body.website_url))
        result = result_model.model_dump()
    elif action == "start_diagnostic":
        result_model = await start_diagnostic(request, StartDiagnosticRequest(session_id=session_id))
        result = result_model.model_dump()
    elif action == "precision_questions":
        result_model = await get_precision_questions(request, PrecisionQuestionsRequest(session_id=session_id))
        result = result_model.model_dump()
    elif action == "recommend":
        result_model = await get_recommendations(request, GetRecommendationsRequest(session_id=session_id))
        result = result_model.model_dump()
    else:
        raise HTTPException(
            status_code=400,
            detail=(
                "Unsupported action. Use one of: auto, task_setup, submit_answer, "
                "scale_questions, website_analysis, start_diagnostic, precision_questions, recommend"
            ),
        )

    snapshot = _get_snapshot_or_404(session_id)
    return SessionAdvanceResponse(
        session_id=session_id,
        action=action,
        stage=snapshot.stage,
        result=result,
        snapshot=snapshot,
    )


def _build_session_status(session_id: str) -> SessionStatusResponse:
    session = _get_session_or_404(session_id)
    return SessionStatusResponse(
        session_id=session_id,
        stage=session.stage.value,
        crawl_status=session.crawl_status or "",
        crawl_summary=session.crawl_summary if session.crawl_status == "complete" else None,
        rca_complete=bool(session.rca_complete),
        scale_questions_complete=bool(session.scale_questions_complete),
        playbook_stage=session.playbook_stage or "",
    )


def _build_context_pool(session_id: str) -> dict[str, Any]:
    """
    Return the full context pool for this session:
    - Session profile (outcome, domain, task, stage)
    - Business profile & crawl data
    - All LLM call logs with prompts, responses, and metadata
    - RCA history
    """
    session = _get_session_or_404(session_id)

    return {
        "session_id": session.session_id,
        "stage": session.stage.value,
        "profile": {
            "outcome": session.outcome,
            "outcome_label": session.outcome_label,
            "domain": session.domain,
            "task": session.task,
            "persona_doc": session.persona_doc_name,
        },
        "business_profile": session.business_profile,
        "crawl_status": session.crawl_status,
        "crawl_summary": session.crawl_summary,
        "crawl_raw": session.crawl_raw,
        "crawl_progress": session.crawl_progress,
        "rca_diagnostic_context": session.rca_diagnostic_context or {},
        "rca_history": session.rca_history,
        "rca_complete": session.rca_complete,
        "rca_summary": session.rca_summary,
        "questions_answers": [
            {"question": qa.question, "answer": qa.answer, "type": qa.question_type}
            for qa in session.questions_answers
        ],
        "llm_call_log": [
            entry.model_dump() for entry in session.llm_call_log
        ],
        "early_recommendations_count": len(session.early_recommendations),
        # ── Playbook tracking ──
        "playbook_stage": session.playbook_stage or "not_started",
        "playbook_complete": session.playbook_complete,
        "playbook_agent1_output": session.playbook_agent1_output or "",
        "playbook_agent2_output": session.playbook_agent2_output or "",
        "playbook_agent3_output": session.playbook_agent3_output or "",
        "playbook_agent4_output": session.playbook_agent4_output or "",
        "playbook_agent5_output": session.playbook_agent5_output or "",
        "playbook_latencies": session.playbook_latencies or {},
    }


# ── Scale Questions — Business Context Classification ──────────

# Static scale questions asked between URL input and Opus deep-dive.
# These calibrate the Opus diagnostic to the user's business maturity.
# ── Dynamic current stack options by domain ─────────────────────
# Industry-standard tooling options that change based on the user's domain.
CURRENT_STACK_BY_DOMAIN = {
    # ── Lead Generation Domains ──────────────────────────────
    "Content & Social Media": [
        "Canva + Buffer / Later — design & scheduling",
        "Hootsuite / Sprout Social — social management suite",
        "Adobe Creative Cloud + native platform tools",
        "ChatGPT / Jasper — AI content generation",
        "HubSpot / Semrush — content marketing platform",
        "Nothing yet — posting manually or not at all",
    ],
    "SEO & Organic Visibility": [
        "Google Search Console + GA4 — basic tracking only",
        "Semrush / Ahrefs — dedicated SEO platform",
        "Yoast / RankMath — WordPress SEO plugin",
        "Surfer SEO / Clearscope — content optimization",
        "Screaming Frog + Moz — technical SEO audit",
        "Nothing yet — no SEO tracking in place",
    ],
    "Paid Media & Ads": [
        "Google Ads + Meta Ads Manager — native dashboards",
        "Triple Whale / Hyros — ad attribution & ROAS",
        "AdEspresso / Revealbot — ad optimization & rules",
        "Google Analytics + UTM tracking — manual reporting",
        "Agency-managed — limited visibility into spend",
        "Nothing yet — haven't started paid ads",
    ],
    "B2B Lead Generation": [
        "LinkedIn Sales Navigator — manual prospecting",
        "Apollo.io / ZoomInfo — lead database + outreach",
        "Clay / Instantly — enrichment + cold email at scale",
        "HubSpot CRM + sequences — inbound + outbound",
        "Google Sheets + email — manual outreach tracking",
        "Nothing yet — leads come through referrals only",
    ],

    # ── Sales & Retention Domains ────────────────────────────
    "Sales Execution & Enablement": [
        "WhatsApp Business + Google Sheets — manual CRM",
        "HubSpot / Pipedrive — deal pipeline & tracking",
        "Salesforce + CPQ — enterprise sales stack",
        "Freshsales / Zoho CRM — SMB sales suite",
        "Gong / Chorus — conversation intelligence",
        "Nothing yet — no structured sales process",
    ],
    "Lead Management & Conversion": [
        "Google Sheets / Excel — manual lead tracking",
        "HubSpot / Zoho CRM — lead scoring + nurture flows",
        "Salesforce + Pardot — enterprise lead management",
        "Freshsales / LeadSquared — SMB lead conversion",
        "WhatsApp Business + manual follow-up",
        "Nothing yet — leads aren't systematically tracked",
    ],
    "Customer Success & Reputation": [
        "Google Reviews + manual responses",
        "Zendesk / Freshdesk — support ticketing system",
        "Intercom / Drift — live chat & conversations",
        "HubSpot Service Hub — CRM-integrated support",
        "Trustpilot / G2 / Birdeye — review management",
        "Nothing yet — no structured support system",
    ],
    "Repeat Sales": [
        "Mailchimp / Klaviyo — email marketing & re-engagement",
        "WhatsApp Business — manual repeat outreach",
        "Shopify + loyalty plugin (Smile.io, Yotpo)",
        "HubSpot / Zoho — CRM workflows for upsell",
        "Google Sheets — manual customer reorder tracking",
        "Nothing yet — no repeat purchase strategy",
    ],

    # ── Business Strategy Domains ────────────────────────────
    "Business Intelligence & Analytics": [
        "Google Sheets / Excel — manual dashboards",
        "Google Analytics + Looker Studio (Data Studio)",
        "Power BI / Tableau — enterprise BI & visualization",
        "Mixpanel / Amplitude — product & user analytics",
        "Metabase / Redash — open-source SQL dashboards",
        "Nothing yet — decisions based on gut feel",
    ],
    "Market Strategy & Innovation": [
        "Google Trends + manual research — ad-hoc insights",
        "Semrush / SimilarWeb — competitor & market analysis",
        "Crayon / Klue — competitive intelligence platform",
        "ChatGPT / Perplexity — AI-powered research",
        "Industry reports + newsletters — passive tracking",
        "Nothing yet — not tracking market shifts",
    ],
    "Financial Health & Risk": [
        "Google Sheets / Excel — manual bookkeeping",
        "QuickBooks / Xero — accounting & invoicing",
        "Zoho Books / FreshBooks — SMB finance suite",
        "SAP / Oracle NetSuite — enterprise ERP",
        "Tally / Wave — basic accounting software",
        "Nothing yet — no financial tracking system",
    ],
    "Org Efficiency & Hiring": [
        "Google Docs / Sheets — manual SOPs & tracking",
        "Notion / Confluence — knowledge base & wiki",
        "Slack / Microsoft Teams — internal communication",
        "Monday.com / Asana — project management",
        "Jira / ClickUp — task & workflow management",
        "Nothing yet — no process documentation",
    ],
    "Improve Yourself": [
        "Google Calendar + Notes app — basic planning",
        "Notion / Obsidian — personal knowledge management",
        "ChatGPT / Claude — AI assistant for writing & ideas",
        "Todoist / TickTick — task & habit tracking",
        "LinkedIn + Medium — personal branding content",
        "Nothing yet — no productivity system in place",
    ],

    # ── Save Time / Automation Domains ───────────────────────
    "Sales & Content Automation": [
        "Zapier / Make (Integromat) — no-code automation",
        "HubSpot / ActiveCampaign — marketing automation",
        "Mailchimp + Google Sheets — semi-manual workflows",
        "n8n / Pabbly — self-hosted automation platform",
        "Custom scripts (Python, Apps Script) — developer-built",
        "Nothing yet — all workflows are manual",
    ],
    "Finance Legal & Admin": [
        "Google Sheets / Excel — manual data entry & tracking",
        "QuickBooks / Xero — accounting & invoicing",
        "DocuSign / PandaDoc — contract & e-signature",
        "Zoho Invoice / FreshBooks — billing automation",
        "SAP / Oracle — enterprise finance & procurement",
        "Nothing yet — paper-based or email-based process",
    ],
    "Customer Support Ops": [
        "WhatsApp Business + manual replies",
        "Zendesk / Freshdesk — ticketing & knowledge base",
        "Intercom / Tidio — live chat & chatbot",
        "HubSpot Service Hub — CRM-integrated support",
        "Email / phone — no ticketing system",
        "Nothing yet — no dedicated support workflow",
    ],
    "Recruiting & HR Ops": [
        "LinkedIn Recruiter + Google Sheets — manual tracking",
        "Greenhouse / Lever — applicant tracking system (ATS)",
        "Workday / BambooHR — HR management platform",
        "Naukri / Indeed — job boards + manual screening",
        "Zoho Recruit / Freshteam — SMB recruiting suite",
        "Nothing yet — hiring is ad-hoc / word-of-mouth",
    ],
    "Personal & Team Productivity": [
        "Google Workspace (Docs, Sheets, Drive) — manual workflow",
        "Notion / Obsidian — notes & knowledge management",
        "Slack + Asana / Trello — communication + tasks",
        "Microsoft 365 (Teams, OneDrive, Excel)",
        "Zapier / Make — automation between apps",
        "Nothing yet — using email & paper for everything",
    ],
}

def _get_scale_questions(domain: str = "", **_kwargs) -> list[dict]:
    """
    Build the scale questions dynamically.
    6 questions for Channel Selection & Conversion Lever.
    The last question (current_stack) loads dynamic options based on domain from Q1-Q3.
    """
    # Pick domain-specific stack options (fallback to generic if domain not mapped)
    _default_stack = [
        "Canva + Buffer / Later — design & scheduling",
        "Hootsuite / Sprout Social — social management suite",
        "Adobe Creative Cloud + native platform tools",
        "ChatGPT / Jasper — AI content generation",
        "HubSpot / Semrush — content marketing platform",
        "Nothing yet — posting manually or not at all",
    ]
    stack_options = CURRENT_STACK_BY_DOMAIN.get(domain, _default_stack)

    return [
        {
            "id": "buying_process",
            "question": "How do customers typically buy from you?",
            "options": [
                "They sign up and pay on their own (self-serve)",
                "They sign up free, then upgrade later (freemium / trial)",
                "They request a demo or consultation first",
                "A sales rep guides them through the purchase",
                "They buy through a marketplace or platform",
                "Mix — depends on customer size",
            ],
            "icon": "🛒",
        },
        {
            "id": "revenue_model",
            "question": "How do you make money?",
            "options": [
                "One-time product purchases",
                "Subscription / recurring billing",
                "Usage-based or pay-as-you-go",
                "Service retainers / project fees",
                "Marketplace commissions / transaction fees",
                "Freemium with paid upgrades",
                "Advertising / sponsorship revenue",
            ],
            "icon": "💰",
        },
        {
            "id": "sales_cycle",
            "question": "How quickly do customers usually go from discovering you to paying?",
            "options": [
                "Minutes to hours (impulse / instant)",
                "A few days (1–7 days)",
                "A few weeks (1–4 weeks)",
                "A month or more",
                "Varies wildly by customer",
            ],
            "icon": "⏱️",
        },
        {
            "id": "existing_assets",
            "question": "Which of these do you already have?",
            "options": [
                "Customer testimonials or reviews",
                "Case studies with measurable results",
                "Blog posts or educational articles",
                "Video content (demos, tutorials, or social)",
                "A free tool, calculator, or template",
                "Active social media presence",
                "An email list of 1,000+ contacts",
                "None of the above — starting from scratch",
            ],
            "icon": "📦",
            "multiSelect": True,
        },
        {
            "id": "buyer_behavior",
            "question": "When customers look for a solution like yours, what do they usually do?",
            "options": [
                'Search Google or AI tools for the category (e.g., "best project management tool")',
                "Ask peers, colleagues, or communities for recommendations",
                "They don't know this category exists — we have to educate them",
                "They compare us against 2–3 well-known competitors",
                "They find us through the platform or marketplace we're listed on",
            ],
            "icon": "🔍",
        },
        {
            "id": "current_stack",
            "question": "What tools are you currently using for this?",
            "options": stack_options,
            "icon": "🛠️",
        },
    ]


class ScaleQuestionItem(BaseModel):
    id: str
    question: str
    options: list[str]
    icon: str = ""
    multiSelect: bool = False


class ScaleQuestionsResponse(BaseModel):
    session_id: str
    questions: list[ScaleQuestionItem]
    total: int


async def get_scale_questions_endpoint(session_id: str):
    """
    Return the business scale / context classification questions.

    Dynamic: Current Stack options change based on the user's domain,
    and Biggest Constraint options change based on business stage.
    Team Size question is removed. Business Stage is asked first.
    """
    session = session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Build domain-aware scale questions
    domain = session.domain or ""
    dynamic_qs = _get_scale_questions(domain=domain)

    questions = [
        ScaleQuestionItem(
            id=q["id"],
            question=q["question"],
            options=q["options"],
            icon=q.get("icon", ""),
            multiSelect=q.get("multiSelect", False),
        )
        for q in dynamic_qs
    ]

    return ScaleQuestionsResponse(
        session_id=session_id,
        questions=questions,
        total=len(questions),
    )


# ── Business URL & Crawl Endpoints ─────────────────────────────


# ── Website Snapshot — rich crawl data for display while playbook generates ──


class WebsiteSnapshotResponse(BaseModel):
    session_id: str
    available: bool = False
    homepage_title: str = ""
    homepage_description: str = ""
    homepage_h1s: list[str] = []
    pages_found: int = 0
    page_types: list[str] = []           # ["about", "pricing", "blog", ...]
    tech_stack: list[str] = []           # ["React", "Stripe", "Google Analytics", ...]
    cta_patterns: list[str] = []         # ["Book a Demo", "Sign Up Free", ...]
    social_links: list[str] = []         # ["instagram.com/...", ...]
    seo_health: dict = {}                # {"has_meta": true, "has_viewport": true, "has_sitemap": false}
    js_rendered: bool = False
    nav_links: list[str] = []            # Top nav items
    crawl_summary_points: list[str] = [] # 5-bullet summary from LLM


def _build_website_snapshot(session_id: str) -> WebsiteSnapshotResponse:
    """
    Return structured website insights from crawl_raw.
    No LLM call — instant response. Frontend shows this while playbook generates.

    Available as soon as crawl_status == "complete".
    """
    session = _get_session_or_404(session_id)

    if session.crawl_status != "complete" or not session.crawl_raw:
        return WebsiteSnapshotResponse(session_id=session_id, available=False)

    raw = session.crawl_raw
    homepage = raw.get("homepage", {})

    # Extract page types from crawled pages
    pages_crawled = raw.get("pages_crawled", [])
    page_types = list({p.get("type", "other") for p in pages_crawled if p.get("type") and p.get("type") != "other"})

    # Get summary points if available
    summary_points = []
    if session.crawl_summary and isinstance(session.crawl_summary, dict):
        summary_points = session.crawl_summary.get("points", [])

    return WebsiteSnapshotResponse(
        session_id=session_id,
        available=True,
        homepage_title=homepage.get("title", ""),
        homepage_description=homepage.get("meta_desc", ""),
        homepage_h1s=homepage.get("h1s", []),
        pages_found=len(pages_crawled),
        page_types=sorted(page_types),
        tech_stack=raw.get("tech_signals", []),
        cta_patterns=raw.get("cta_patterns", []),
        social_links=raw.get("social_links", []),
        seo_health=raw.get("seo_basics", {}),
        js_rendered=raw.get("js_rendered", False),
        nav_links=homepage.get("nav_links", [])[:15],
        crawl_summary_points=summary_points,
    )


@router.get("/session/{session_id}")
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def get_session_context(
    request: Request,
    session_id: str,
    view: Literal["summary", "status", "context_pool", "website_snapshot"] = Query(default="summary"),
):
    """Fetch session data by view: summary|status|context_pool|website_snapshot."""
    if view == "status":
        return _build_session_status(session_id).model_dump()
    if view == "context_pool":
        return _build_context_pool(session_id)
    if view == "website_snapshot":
        return _build_website_snapshot(session_id).model_dump()

    summary = session_store.get_session_summary(session_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Session not found")
    return SessionContextResponse(**summary).model_dump()


async def submit_website(body: SubmitWebsiteRequest = Body(...)):
    session = session_store.get_session(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session_store.set_website_url(body.session_id, body.website_url)

    try:
        analysis = await agent_service.analyze_website_audience(
            website_url=body.website_url,
            outcome_label=session.outcome_label or "",
            domain=session.domain or "",
            task=session.task or "",
            rca_history=session.rca_history,
        )
    except Exception as e:
        logger.error(
            "Website analysis failed",
            session_id=body.session_id,
            url=body.website_url,
            error=str(e),
        )
        analysis = {
            "intended_audience": "",
            "actual_audience": "",
            "mismatch_analysis": "We couldn't fully analyze this website right now, but we've noted it for your diagnostic.",
            "recommendations": [],
            "business_summary": "",
        }

    session_store.set_audience_insights(body.session_id, analysis)

    audience_insights = AudienceInsight(
        intended_audience=analysis.get("intended_audience", ""),
        actual_audience=analysis.get("actual_audience", ""),
        mismatch_analysis=analysis.get("mismatch_analysis", ""),
        recommendations=analysis.get("recommendations", []),
    )

    logger.info(
        "Website analysis complete",
        session_id=body.session_id,
        url=body.website_url,
        has_mismatch=bool(analysis.get("mismatch_analysis")),
    )

    return WebsiteAnalysisResponse(
        session_id=body.session_id,
        website_url=body.website_url,
        audience_insights=audience_insights,
        business_summary=analysis.get("business_summary", ""),
        analysis_note=(
            "I've analyzed your website to understand your audience positioning. "
            "This insight will help us refine your tool recommendations even further."
        ),
    )



