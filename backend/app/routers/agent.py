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
from app.services.claude_rca_service import generate_next_rca_question, generate_precision_questions
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

    # ── Generate EARLY recommendations + first Claude question IN PARALLEL ─
    early_recs = []
    early_message = ""

    async def _get_early_recs():
        nonlocal early_recs, early_message
        try:
            early_result = await agent_service.generate_early_recommendations(
                outcome=session.outcome or "",
                outcome_label=session.outcome_label or "",
                domain=session.domain or "",
                task=session.task or "",
            )
            if early_result and early_result.get("tools"):
                early_recs = [
                    EarlyToolRecommendation(
                        name=t.get("name", ""),
                        description=t.get("description", ""),
                        url=t.get("url"),
                        category=t.get("category", ""),
                        rating=t.get("rating"),
                        why_relevant=t.get("why_relevant", ""),
                        implementation_stage=t.get("implementation_stage", ""),
                        issue_solved=t.get("issue_solved", ""),
                        ease_of_use=t.get("ease_of_use", ""),
                    )
                    for t in early_result["tools"]
                ]
                early_message = early_result.get("message", "")
                session_store.set_early_recommendations(
                    session.session_id,
                    tools=early_result["tools"],
                    message=early_message,
                )
                logger.info(
                    "Early recommendations generated after Q3",
                    session_id=session.session_id,
                    tools_count=len(early_recs),
                )
        except Exception as e:
            logger.warning(
                "Early recommendations failed (non-blocking)",
                session_id=session.session_id,
                error=str(e),
            )

    claude_result_holder = [None]

    async def _get_first_rca():
        claude_result_holder[0] = await generate_next_rca_question(
            outcome=session.outcome or "",
            outcome_label=session.outcome_label or "",
            domain=session.domain or "",
            task=session.task or "",
            diagnostic_context=diagnostic or {},
            rca_history=[],
            business_profile=session.business_profile or None,
        )

    # Run both in parallel — cuts Q3 delay by ~40-50%
    await asyncio.gather(_get_early_recs(), _get_first_rca())

    claude_result = claude_result_holder[0]

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
    )

    # Reset RCA history for fresh start
    session.rca_history = []
    session.dynamic_questions = []
    session_store.update_session(session)

    claude_result = await generate_next_rca_question(
        outcome=session.outcome or "",
        outcome_label=session.outcome_label or "",
        domain=session.domain or "",
        task=session.task or "",
        diagnostic_context=diagnostic,
        rca_history=[],
        business_profile=business_profile,
        crawl_summary=crawl_summary,
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
        )

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
            # Claude failed mid-flow — mark as complete and move on
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

# ── Dynamic constraint options based on business stage ──────────
CONSTRAINT_OPTIONS_BY_STAGE = {
    "Idea / validation stage": [
        "Time — building everything solo, no bandwidth",
        "Money — bootstrapping with zero / tiny budget",
        "Clarity — not sure what to build or sell first",
        "Validation — can't tell if people actually want this",
        "Tech — don't know which tools to start with",
    ],
    "Early traction (some customers)": [
        "Time — too many things, can't prioritize",
        "Money — revenue doesn't cover hiring yet",
        "Leads — getting interest but not enough conversions",
        "Process — nothing is repeatable or documented",
        "Retention — customers buy once but don't return",
    ],
    "Growth mode (scaling what works)": [
        "Time — founder is the bottleneck for everything",
        "People — hard to hire / delegate effectively",
        "Systems — manual processes breaking at scale",
        "Unit economics — growth isn't profitable yet",
        "Quality — speed of growth causing quality gaps",
    ],
    "Established (optimizing & expanding)": [
        "Efficiency — too many tools, not integrated",
        "Talent — key roles hard to fill / keep",
        "Innovation — competitors catching up fast",
        "Data — decisions aren't data-driven enough",
        "Expansion — entering new markets / verticals",
    ],
    "Enterprise / multi-product": [
        "Coordination — teams / products not aligned",
        "Legacy — old systems slowing everything down",
        "Compliance — regulatory / security overhead",
        "Innovation — too slow to ship new initiatives",
        "Data silos — insights fragmented across teams",
    ],
    "default": [
        "Time — I'm doing everything myself",
        "Money — limited budget for tools / hiring",
        "Knowledge — not sure what to do next",
        "People — can't find / manage the right team",
        "Systems — no repeatable process in place",
    ],
}


def _get_scale_questions(domain: str = "", business_stage: str = "") -> list[dict]:
    """
    Build the scale questions dynamically.
    - Team Size is REMOVED
    - Business Stage is FIRST
    - Current Stack options change per domain
    - Biggest Constraint options change per business stage
    """
    # Pick domain-specific stack options (fallback to generic if domain not mapped)
    _default_stack = [
        "Google Workspace (Sheets, Docs, Drive) — manual workflows",
        "Notion / Airtable — flexible project management",
        "Specialized SaaS tools (CRM, marketing, support)",
        "Enterprise suite (Salesforce, SAP, Microsoft 365)",
        "Custom-built / developer tools (APIs, scripts, Zapier)",
        "Nothing yet — doing everything manually",
    ]
    stack_options = CURRENT_STACK_BY_DOMAIN.get(domain, _default_stack)

    # Pick stage-specific constraint options
    constraint_options = CONSTRAINT_OPTIONS_BY_STAGE.get(
        business_stage, CONSTRAINT_OPTIONS_BY_STAGE["default"]
    )

    return [
        {
            "id": "business_stage",
            "question": "Which stage best describes your business?",
            "options": [
                "Idea / validation stage",
                "Early traction (some customers)",
                "Growth mode (scaling what works)",
                "Established (optimizing & expanding)",
                "Enterprise / multi-product",
            ],
            "icon": "🚀",
        },
        {
            "id": "current_stack",
            "question": "What tools are you currently using for this?",
            "options": stack_options,
            "icon": "🛠️",
        },
        {
            "id": "primary_channel",
            "question": "Where do most of your customers come from today?",
            "options": [
                "Word of mouth / referrals",
                "Social media (organic)",
                "Paid ads (Google, Meta, etc.)",
                "Content / SEO / inbound",
                "Outbound sales / cold outreach",
                "Marketplace / platform (Amazon, Upwork, etc.)",
            ],
            "icon": "📣",
            "multiSelect": True,
        },
        {
            "id": "biggest_constraint",
            "question": "What's the single biggest constraint you face right now?",
            "options": constraint_options,
            "icon": "🔒",
            "multiSelect": True,
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
    answers: dict[str, str | list[str]]   # values can be a string or list for multi-select


class SubmitScaleAnswersResponse(BaseModel):
    session_id: str
    business_profile: dict[str, str | list[str]]
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
    business_stage = body.answers.get("business_stage", "")
    dynamic_qs = _get_scale_questions(domain=domain, business_stage=business_stage)
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


# ── Business Intelligence Verdict (Pre-RCA, Crawl-Powered) ────

class BusinessIntelRequest(BaseModel):
    session_id: str


class SEOHealth(BaseModel):
    score: int = 0
    diagnosis: str = ""
    working: str = ""
    missing: str = ""
    quick_win: str = ""


class FunnelStrategy(BaseModel):
    strategy: str = ""
    action: str = ""


class BusinessIntelResponse(BaseModel):
    session_id: str
    available: bool = False
    icp_snapshot: str = ""
    seo_health: Optional[SEOHealth] = None
    top_funnel: list[FunnelStrategy] = []
    mid_funnel: list[FunnelStrategy] = []
    bottom_funnel: list[FunnelStrategy] = []
    verdict_line: str = ""


@router.post("/session/business-intel", response_model=BusinessIntelResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_CHAT)
async def get_business_intel(request: Request, body: BusinessIntelRequest = Body(...)):
    """
    Generate a Business Intelligence Verdict from crawl data.

    Shows ICP snapshot, SEO health score, and funnel growth strategies
    BEFORE the RCA diagnostic — empowering users with strategic insights.

    Requires crawl to be complete.
    """
    session = session_store.get_session(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Need crawl data
    if not session.crawl_raw or session.crawl_status != "complete":
        return BusinessIntelResponse(
            session_id=body.session_id,
            available=False,
        )

    result = await agent_service.generate_business_intel_verdict(
        outcome_label=session.outcome_label or "",
        domain=session.domain or "",
        task=session.task or "",
        crawl_raw=session.crawl_raw,
        crawl_summary=session.crawl_summary or {},
        business_profile=session.business_profile or None,
    )

    if not result:
        return BusinessIntelResponse(
            session_id=body.session_id,
            available=False,
        )

    seo = result.get("seo_health")
    seo_data = None
    if seo and isinstance(seo, dict):
        seo_data = SEOHealth(
            score=seo.get("score", 0),
            diagnosis=seo.get("diagnosis", ""),
            working=seo.get("working", ""),
            missing=seo.get("missing", ""),
            quick_win=seo.get("quick_win", ""),
        )

    top = [FunnelStrategy(**s) for s in result.get("top_funnel", []) if isinstance(s, dict)]
    mid = [FunnelStrategy(**s) for s in result.get("mid_funnel", []) if isinstance(s, dict)]
    bot = [FunnelStrategy(**s) for s in result.get("bottom_funnel", []) if isinstance(s, dict)]

    logger.info(
        "Business intel verdict served",
        session_id=body.session_id,
        seo_score=seo_data.score if seo_data else None,
        strategies=len(top) + len(mid) + len(bot),
    )

    return BusinessIntelResponse(
        session_id=body.session_id,
        available=True,
        icp_snapshot=result.get("icp_snapshot", ""),
        seo_health=seo_data,
        top_funnel=top,
        mid_funnel=mid,
        bottom_funnel=bot,
        verdict_line=result.get("verdict_line", ""),
    )
