"""
═══════════════════════════════════════════════════════════════
AGENT ROUTER — AI Agent with Dynamic Persona & Session Context
═══════════════════════════════════════════════════════════════
Endpoints for the AI agent flow:

POST /api/v1/agent/session              — Create a new session
POST /api/v1/agent/session/outcome      — Record Q1 (outcome)
POST /api/v1/agent/session/domain       — Record Q2 (domain)
POST /api/v1/agent/session/task         — Record Q3 (task) + early recs + generate dynamic Qs
POST /api/v1/agent/session/answer       — Submit dynamic question answer
POST /api/v1/agent/session/website      — Submit website for audience analysis
POST /api/v1/agent/session/recommend    — Get final personalized recommendations
GET  /api/v1/agent/session/{id}         — Get full session context
GET  /api/v1/agent/personas             — List available persona domains
"""

import asyncio

import structlog
from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel
from typing import Any, Optional

from app.config import get_settings
from app.middleware.rate_limit import limiter
from app.services import session_store, agent_service
from app.services.crawl_service import detect_url_type, run_background_crawl
from app.services.persona_doc_service import get_available_personas, get_doc_for_domain, get_diagnostic_sections
from app.services.claude_rca_service import generate_next_rca_question, generate_precision_questions, generate_task_alignment_filter
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

router = APIRouter(prefix="/agent", tags=["agent"])


# ── Request/Response Models ────────────────────────────────────


class CreateSessionResponse(BaseModel):
    session_id: str
    stage: str


class SetOutcomeRequest(BaseModel):
    session_id: str
    outcome: str           # e.g., 'lead-generation'
    outcome_label: str     # e.g., 'Lead Generation (Marketing, SEO & Social)'


class SetDomainRequest(BaseModel):
    session_id: str
    domain: str            # e.g., 'Content & Social Media'


class SetTaskRequest(BaseModel):
    session_id: str
    task: str              # e.g., 'Generate social media posts captions & hooks'


class EarlyToolRecommendation(BaseModel):
    name: str
    description: str
    url: Optional[str] = None
    category: str = ""       # 'extension', 'gpt', 'company'
    rating: Optional[float] = None
    why_relevant: str = ""   # Brief relevance note based on Q1-Q3


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
    website_url: str          # e.g., 'https://example.com'


class AudienceInsight(BaseModel):
    intended_audience: str = ""     # Who they seem to be targeting
    actual_audience: str = ""       # Who their content actually reaches
    mismatch_analysis: str = ""     # Gap between intended and actual
    recommendations: list[str] = [] # Actionable suggestions


class WebsiteAnalysisResponse(BaseModel):
    session_id: str
    website_url: str
    audience_insights: AudienceInsight
    business_summary: str = ""      # Brief overview of the business
    analysis_note: str = ""         # Message for the user


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


@router.post("/session/outcome", response_model=CreateSessionResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def set_outcome(request: Request, body: SetOutcomeRequest = Body(...)):
    """Record Q1: Outcome / Growth Bucket selection."""
    session = session_store.set_outcome(
        body.session_id, body.outcome, body.outcome_label
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return CreateSessionResponse(
        session_id=session.session_id,
        stage=session.stage.value,
    )


@router.post("/session/domain", response_model=CreateSessionResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def set_domain(request: Request, body: SetDomainRequest = Body(...)):
    """Record Q2: Domain / Sub-Category selection."""
    session = session_store.set_domain(body.session_id, body.domain)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return CreateSessionResponse(
        session_id=session.session_id,
        stage=session.stage.value,
    )


@router.post("/session/task", response_model=SetTaskResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_CHAT)
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
                    rating=t.get("rating"),
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

    # ── First Claude RCA question ──────────────────────────────
    # Run task filter PARALLEL with first RCA question for speed.
    # First RCA uses unfiltered context (fine — it's a wide-form opener).
    # Filtered context is stored in session for Q2+ where it matters.

    async def _run_task_filter():
        if not diagnostic:
            return None, None
        result = await generate_task_alignment_filter(
            task=session.task or "",
            diagnostic_context=diagnostic,
        )
        if result:
            fc = result.get("filtered_items")
            ts = result.get("task_execution_summary", "")
            session_store.set_filtered_context(
                session.session_id,
                filtered_items=fc or {},
                deferred_items=result.get("deferred_items", []),
                task_execution_summary=ts or "",
            )
            return fc, ts
        return None, None

    async def _get_first_rca():
        return await generate_next_rca_question(
            outcome=session.outcome or "",
            outcome_label=session.outcome_label or "",
            domain=session.domain or "",
            task=session.task or "",
            diagnostic_context=diagnostic or {},
            rca_history=[],
            business_profile=session.business_profile or None,
        )

    # Run both in parallel
    (filtered_context, task_execution_summary), claude_result = await asyncio.gather(
        _run_task_filter(), _get_first_rca()
    )

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


@router.post("/session/start-diagnostic", response_model=StartDiagnosticResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_CHAT)
async def start_diagnostic(request: Request, body: StartDiagnosticRequest = Body(...)):
    """
    Generate the first diagnostic question with FULL context:
    crawl summary + business profile + Q1/Q2/Q3.

    Called after scale questions are done (and crawl may have completed).
    Replaces the stashed first question with a context-aware one.
    Only regenerates if crawl data is available (otherwise the stashed
    question from /session/task is already good enough — saves 2-4s).
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

    # Reset RCA history for fresh start
    session.rca_history = []
    session.dynamic_questions = []
    session_store.update_session(session)

    # Only regenerate if we have NEW context (crawl/business_profile)
    # that wasn't available when set_task generated the first question.
    # Otherwise, skip the LLM call — frontend uses the stashed question.
    if not context_used:
        logger.info(
            "start-diagnostic: no new context, skipping LLM call (use stashed question)",
            session_id=session.session_id,
        )
        return StartDiagnosticResponse(
            session_id=session.session_id,
            rca_mode=False,
        )

    logger.info(
        "start-diagnostic: regenerating with crawl context",
        session_id=session.session_id,
        context_used=context_used,
    )

    claude_result = await generate_next_rca_question(
        outcome=session.outcome or "",
        outcome_label=session.outcome_label or "",
        domain=session.domain or "",
        task=session.task or "",
        diagnostic_context=diagnostic,
        rca_history=[],
        business_profile=business_profile,
        crawl_summary=crawl_summary,
        filtered_context=session.rca_filtered_context or None,
        task_execution_summary=session.rca_task_execution_summary or None,
    )

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
        session_store.update_session(session)

        logger.info(
            "start-diagnostic: context-aware question generated",
            session_id=session.session_id,
            context_used=context_used,
            question=claude_result["question"][:80],
        )

        return StartDiagnosticResponse(
            session_id=session.session_id,
            question=first_q,
            acknowledgment=claude_result.get("acknowledgment", ""),
            insight=claude_result.get("insight", ""),
            rca_mode=True,
            context_used=context_used,
        )

    # Claude failed — return empty (frontend will fall back to stashed question)
    logger.warning(
        "start-diagnostic: Claude failed, frontend should use stashed question",
        session_id=session.session_id,
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


@router.post("/session/precision-questions", response_model=PrecisionQuestionsResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_CHAT)
async def get_precision_questions(request: Request, body: PrecisionQuestionsRequest = Body(...)):
    """
    Generate 2 precision questions that cross-reference crawl data with
    the user's diagnostic answers to find contradictions and blind spots.
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


# ── Fallback RCA question generator (when Claude skips too early) ──

_FALLBACK_RCA_QUESTIONS = [
    {
        "question": "What does your current process for this task look like — are you doing it manually, using a tool, or haven't started yet?",
        "options": ["Doing it manually", "Using a basic tool but it's not working well", "Haven't started — not sure where to begin", "Something else"],
        "section": "rca",
        "section_label": "Current Approach",
        "insight": "80% of inefficiency comes from wrong tools, not wrong effort.",
    },
    {
        "question": "What's the biggest friction point right now — is it taking too long, not getting results, or you're unsure if you're doing it right?",
        "options": ["It's taking way too long", "I'm doing it but results are poor", "I'm not confident in my approach", "Something else"],
        "section": "rca",
        "section_label": "Core Friction",
        "insight": "Top performers fix the bottleneck, not all the steps.",
    },
    {
        "question": "If this task worked perfectly, what would change in your business in the next 30 days?",
        "options": ["More revenue / sales", "More time freed up for other things", "Better customer experience", "Something else"],
        "section": "rca",
        "section_label": "Impact Assessment",
        "insight": "Clarity on impact helps prioritize the right fix.",
    },
]


def _generate_fallback_rca_question(session, questions_asked: int) -> DynamicQuestion:
    """Generate a fallback diagnostic question when Claude fails or tries to complete early."""
    idx = min(questions_asked, len(_FALLBACK_RCA_QUESTIONS) - 1)
    fb = _FALLBACK_RCA_QUESTIONS[idx]
    return DynamicQuestion(
        question=fb["question"],
        options=fb["options"],
        allows_free_text=True,
        section=fb["section"],
        section_label=fb["section_label"],
        insight=fb["insight"],
    )


@router.post("/session/answer", response_model=SubmitDynamicAnswerResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_CHAT)
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

        # Ask Claude for the next question
        claude_result = await generate_next_rca_question(
            outcome=session.outcome or "",
            outcome_label=session.outcome_label or "",
            domain=session.domain or "",
            task=session.task or "",
            diagnostic_context=session.rca_diagnostic_context,
            rca_history=session.rca_history,
            business_profile=session.business_profile or None,
            crawl_summary=session.crawl_summary or None,
            filtered_context=session.rca_filtered_context or None,
            task_execution_summary=session.rca_task_execution_summary or None,
        )

        # ── HARD GUARD: minimum 3 questions before allowing "complete" ──
        questions_asked = len(session.rca_history)
        if (claude_result
            and claude_result.get("status") == "complete"
            and questions_asked < 3):
            logger.warning(
                "Claude tried to complete early — overriding to force continuation",
                session_id=session.session_id,
                questions_asked=questions_asked,
            )
            # Override: turn "complete" into None so we generate a fallback question
            claude_result = None

        if claude_result and claude_result.get("status") == "question":
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
            session_store.set_rca_complete(body.session_id, summary)

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
            # Claude failed or was overridden by min-3 guard
            if questions_asked < 3:
                # Generate a fallback question from diagnostic context
                fallback_q = _generate_fallback_rca_question(session, questions_asked)
                session.dynamic_questions.append(fallback_q.question)
                session_store.update_session(session)

                logger.info(
                    "RCA fallback question generated (min-3 guard)",
                    session_id=session.session_id,
                    q_index=questions_asked,
                    question=fallback_q.question[:80],
                )

                return SubmitDynamicAnswerResponse(
                    session_id=session.session_id,
                    next_question=fallback_q,
                    all_answered=False,
                    rca_mode=True,
                )

            # >= 3 questions asked and Claude failed — safe to complete
            logger.warning(
                "Claude RCA failed mid-flow, completing diagnostic",
                session_id=session.session_id,
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


@router.post("/session/recommend", response_model=GetRecommendationsResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_CHAT)
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
    )

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


# ── Instant Q1×Q2×Q3 Tool Lookup ──────────────────────────────

class InstantToolsRequest(BaseModel):
    outcome: str
    domain: str
    task: str
    limit: int = 10


@router.post("/session/instant-tools")
@limiter.limit(lambda: get_settings().RATE_LIMIT_CHAT)
async def get_instant_tools(request: Request, body: InstantToolsRequest = Body(...)):
    """
    Zero-latency tool lookup by Q1 (outcome) × Q2 (domain) × Q3 (task).
    Returns pre-mapped tool recommendations from the static JSON mapping.
    No LLM, no RAG — pure dictionary lookup in <1ms.
    """
    from app.services.instant_tool_service import get_tools_for_q1_q2_q3

    result = get_tools_for_q1_q2_q3(
        outcome=body.outcome,
        domain=body.domain,
        task=body.task,
        limit=body.limit,
    )
    return result


@router.get("/session/{session_id}", response_model=SessionContextResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def get_session_context(request: Request, session_id: str):
    """Get the full session context (for debugging or UI state recovery)."""
    summary = session_store.get_session_summary(session_id)
    if not summary:
        raise HTTPException(status_code=404, detail="Session not found")

    return SessionContextResponse(**summary)


# ── Scale Questions — Business Context Classification ──────────

# Static scale questions asked between URL input and Opus deep-dive.
# These calibrate the Opus diagnostic to the user's business maturity.
# ── Dynamic current stack options by domain ─────────────────────
# Industry-standard tooling options that change based on the user's domain.
CURRENT_STACK_BY_DOMAIN = {
    "Content & Social Media": [
        "Canva + Buffer / Later — design & scheduling",
        "Hootsuite / Sprout Social — social management suite",
        "Adobe Creative Cloud + native platform tools",
        "ChatGPT / Jasper — AI content generation",
        "HubSpot / Semrush — content marketing platform",
        "Nothing yet — posting manually or not at all",
    ],
    "SEO & Organic Visibility": [
        "Google Search Console + Sheets — basic tracking",
        "Semrush / Ahrefs — dedicated SEO platform",
        "Yoast / RankMath — WordPress SEO plugin",
        "HubSpot / Moz — inbound marketing suite",
        "Custom analytics (GA4 + Looker Studio / Data Studio)",
        "Nothing yet — no SEO tracking in place",
    ],
    "Paid Media & Ads": [
        "Meta Ads Manager + Google Ads — native dashboards only",
        "Triple Whale / Hyros — ad attribution platform",
        "Google Analytics + UTM tracking — manual ROAS",
        "Agency-managed — limited visibility into spend",
        "AdEspresso / Revealbot — ad optimization tool",
        "Nothing yet — haven't started paid ads",
    ],
    "B2B Lead Generation": [
        "LinkedIn Sales Navigator — manual prospecting",
        "Apollo.io / ZoomInfo — lead database + outreach",
        "HubSpot CRM + sequences — inbound + outbound",
        "Clay / Instantly — data enrichment + cold email",
        "Google Sheets + email — manual outreach tracking",
        "Nothing yet — leads come through referrals only",
    ],
    "Sales Execution & Enablement": [
        "WhatsApp Business + Google Sheets — manual CRM",
        "HubSpot / Pipedrive — deal pipeline management",
        "Salesforce + CPQ — enterprise sales stack",
        "Freshsales / Zoho CRM — SMB sales suite",
        "Notion / Airtable — custom sales tracker",
        "Nothing yet — no structured sales process",
    ],
    "Lead Management & Conversion": [
        "Google Sheets / Excel — manual lead tracking",
        "HubSpot / Zoho CRM — lead scoring + nurture",
        "Salesforce + Pardot — enterprise lead management",
        "Freshsales / Leadsquared — SMB lead conversion",
        "WhatsApp Business + manual follow-up",
        "Nothing yet — leads aren't systematically tracked",
    ],
    "Customer Success & Reputation": [
        "Google Reviews + manual responses",
        "Zendesk / Freshdesk — support ticketing",
        "Intercom / Drift — conversational support",
        "HubSpot Service Hub — CRM-integrated support",
        "Trustpilot / G2 — review management platform",
        "Nothing yet — no structured support system",
    ],
    "Business Intelligence & Analytics": [
        "Google Sheets / Excel — manual dashboards",
        "Google Analytics + Data Studio / Looker",
        "Power BI / Tableau — enterprise BI",
        "Mixpanel / Amplitude — product analytics",
        "Metabase / Redash — open-source BI",
        "Nothing yet — decisions based on gut feel",
    ],
    "default": [
        "Google Workspace (Sheets, Docs, Drive) — manual workflows",
        "Notion / Airtable — flexible project management",
        "Specialized SaaS tools (CRM, marketing, support)",
        "Enterprise suite (Salesforce, SAP, Microsoft 365)",
        "Custom-built / developer tools (APIs, scripts, Zapier)",
        "Nothing yet — doing everything manually",
    ],
}

# (CONSTRAINT_OPTIONS_BY_STAGE removed — replaced by Channel Selection questions)


def _get_scale_questions(domain: str = "") -> list[dict]:
    """
    Build the Channel Selection & Conversion Lever questions dynamically.
    - 6 questions focused on buying process, revenue, sales cycle,
      existing assets, buyer behavior, and current stack.
    - Current Stack options change per domain (Q1/Q2/Q3 context).
    - Existing Assets is multi-select.
    """
    # Pick domain-specific stack options
    stack_options = CURRENT_STACK_BY_DOMAIN.get(
        domain, CURRENT_STACK_BY_DOMAIN["default"]
    )

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
                "Search Google or AI tools for the category",
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


# Backward compat: static list for the submit endpoint validation
SCALE_QUESTIONS = _get_scale_questions()


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


class SubmitScaleAnswersRequest(BaseModel):
    session_id: str
    answers: dict[str, Any]   # {"buying_process": "...", "existing_assets": ["...", "..."], ...}


class SubmitScaleAnswersResponse(BaseModel):
    session_id: str
    business_profile: dict[str, Any]
    message: str


@router.get("/session/{session_id}/scale-questions", response_model=ScaleQuestionsResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def get_scale_questions_endpoint(request: Request, session_id: str):
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


@router.post("/session/scale-answers", response_model=SubmitScaleAnswersResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def submit_scale_answers(request: Request, body: SubmitScaleAnswersRequest = Body(...)):
    """
    Record all scale question answers at once.

    Builds a business_profile{} and stores it in the session.
    This profile is injected into the Opus system prompt to calibrate
    the depth and complexity of diagnostic questions.
    """
    session = session_store.get_session(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Build business profile from answers (use dynamic questions for validation)
    domain = session.domain or ""
    dynamic_qs = _get_scale_questions(domain=domain)
    valid_ids = {q["id"] for q in dynamic_qs}

    business_profile = {}
    for qid, answer in body.answers.items():
        if qid in valid_ids:
            business_profile[qid] = answer

    # Store in session
    session_store.set_business_profile(body.session_id, business_profile)

    logger.info(
        "Scale questions answered, business profile set",
        session_id=body.session_id,
        profile_keys=list(business_profile.keys()),
    )

    return SubmitScaleAnswersResponse(
        session_id=body.session_id,
        business_profile=business_profile,
        message="Got it — I now understand your business context. Let's dive deeper.",
    )


@router.get("/personas")
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def list_personas(request: Request):
    """List all available persona domains with document mappings."""
    personas = get_available_personas()
    return {"personas": personas, "count": len(personas)}


# ── Business URL & Crawl Endpoints ─────────────────────────────


class SubmitUrlRequest(BaseModel):
    session_id: str
    business_url: str          # e.g., 'https://example.com' or 'instagram.com/brand'


class SubmitUrlResponse(BaseModel):
    session_id: str
    business_url: str
    url_type: str              # "website" or "social_profile"
    crawl_started: bool
    message: str


class CrawlStatusResponse(BaseModel):
    session_id: str
    crawl_status: str          # "in_progress", "complete", "failed", ""
    crawl_summary: Optional[dict] = None


@router.post("/session/url", response_model=SubmitUrlResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_CHAT)
async def submit_business_url(request: Request, body: SubmitUrlRequest = Body(...)):
    """
    Submit business URL immediately after tool recommendations.

    1. Stores the URL in the session
    2. Detects URL type (website vs social profile)
    3. Fires an async background crawl (does NOT block the response)
    4. Returns immediately so the frontend can advance to Scale Questions

    The crawl runs in parallel. Frontend polls /session/{id}/crawl-status
    to check completion before starting Opus deep-dive questions.
    """
    session = session_store.get_session(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Normalize URL
    url = body.business_url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url

    # Detect URL type
    url_type = detect_url_type(url)

    # Store in session
    session_store.set_website_url(body.session_id, url, url_type)
    session_store.set_crawl_status(body.session_id, "in_progress")

    # Fire background crawl (non-blocking)
    asyncio.create_task(run_background_crawl(body.session_id, url))

    logger.info(
        "Business URL submitted, background crawl started",
        session_id=body.session_id,
        url=url,
        url_type=url_type,
    )

    return SubmitUrlResponse(
        session_id=body.session_id,
        business_url=url,
        url_type=url_type,
        crawl_started=True,
        message="Analyzing your business in the background — let's continue!",
    )


@router.get("/session/{session_id}/crawl-status", response_model=CrawlStatusResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def get_crawl_status(request: Request, session_id: str):
    """
    Poll crawl status. Frontend calls this to check if the background
    crawl has completed before starting the Opus deep-dive questions.

    Returns:
      - crawl_status: "in_progress" | "complete" | "failed" | ""
      - crawl_summary: populated only when status is "complete"
    """
    session = session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return CrawlStatusResponse(
        session_id=session_id,
        crawl_status=session.crawl_status or "",
        crawl_summary=session.crawl_summary if session.crawl_status == "complete" else None,
    )


@router.post("/session/skip-url")
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def skip_business_url(request: Request, body: dict = Body(...)):
    """
    User chose to skip URL submission.
    Records the skip and allows flow to continue with generic recommendations.
    """
    session_id = body.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required")

    session = session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Mark as skipped — no crawl, no URL
    session.website_url = None
    session.crawl_status = "skipped"
    session_store.update_session(session)

    logger.info("User skipped URL submission", session_id=session_id)

    return {
        "session_id": session_id,
        "message": "No problem — we'll give general recommendations instead of personalized ones.",
    }


@router.post("/session/website", response_model=WebsiteAnalysisResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_CHAT)
async def submit_website(request: Request, body: SubmitWebsiteRequest = Body(...)):
    """
    Submit business website URL for audience analysis.

    Called during Stage 2 of RCA. Fetches the website, analyzes
    the content to determine:
    - Who the business is targeting (intended audience)
    - Who the content actually reaches (actual audience)
    - Any mismatch between the two
    - Actionable recommendations

    This creates an 'aha' moment for the user — showing them
    a gap they may not have been aware of.
    """
    session = session_store.get_session(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Store the website URL
    session_store.set_website_url(body.session_id, body.website_url)

    # Analyze the website for audience insights
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

    # Store insights in session
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


# ── ICP + Business Insights Endpoint ──────────────────────────


class ICPInsight(BaseModel):
    point: str              # Sharp insight text
    highlight: str = ""     # Key phrase to highlight in the UI


class ICPAnalysis(BaseModel):
    ideal_customer_profile: str = ""   # Who their ICP should be
    targeting_verdict: str = ""        # What a customer feels landing on their site
    improvement_areas: list[str] = []  # Where to improve the business URL/site


class BusinessInsightsResponse(BaseModel):
    session_id: str
    insights: list[ICPInsight] = []    # 5-6 sharp points
    icp_analysis: Optional[ICPAnalysis] = None
    hook: str = ""                     # Catchy hook line before CTA
    available: bool = False


@router.post("/session/insights")
@limiter.limit(lambda: get_settings().RATE_LIMIT_CHAT)
async def get_business_insights(request: Request, body: dict = Body(...)):
    """
    Generate 5-6 sharp business insights + ICP analysis + catchy hook.

    Combines:
    - All Q&A history (outcome, domain, task, diagnostic, scale)
    - Crawl data (website analysis)
    - Business profile

    Returns structured insights for the final report.
    """
    session_id = body.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id required")

    session = session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Build context
    crawl_data = session.crawl_summary or {}
    business_profile = session.business_profile or {}
    rca_history = session.rca_history or []

    if not rca_history and not crawl_data.get("points"):
        return BusinessInsightsResponse(
            session_id=session_id, available=False
        ).model_dump()

    result = await agent_service.generate_business_insights(
        outcome_label=session.outcome_label or "",
        domain=session.domain or "",
        task=session.task or "",
        rca_history=rca_history,
        business_profile=business_profile,
        crawl_summary=crawl_data,
        crawl_raw=session.crawl_raw if hasattr(session, 'crawl_raw') else None,
    )

    if not result:
        return BusinessInsightsResponse(
            session_id=session_id, available=False
        ).model_dump()

    insights = [
        {"point": i.get("point", ""), "highlight": i.get("highlight", "")}
        for i in result.get("insights", [])
    ]

    icp = result.get("icp_analysis")
    icp_data = None
    if icp:
        icp_data = {
            "ideal_customer_profile": icp.get("ideal_customer_profile", ""),
            "targeting_verdict": icp.get("targeting_verdict", ""),
            "improvement_areas": icp.get("improvement_areas", []),
        }

    logger.info(
        "Business insights generated",
        session_id=session_id,
        insights_count=len(insights),
        has_icp=bool(icp_data),
    )

    return {
        "session_id": session_id,
        "insights": insights,
        "icp_analysis": icp_data,
        "hook": result.get("hook", ""),
        "available": True,
    }


