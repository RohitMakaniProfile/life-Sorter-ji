"""
═══════════════════════════════════════════════════════════════
SANDBOX ROUTER — Developer panel API endpoints
═══════════════════════════════════════════════════════════════
Endpoints:
  POST /sandbox/login           — Authenticate developer access
  POST /sandbox/test/session    — Create test session (no auth/payment)
  POST /sandbox/test/outcome    — Set outcome in test mode
  POST /sandbox/test/domain     — Set domain in test mode
  POST /sandbox/test/task       — Set task + generate questions (logged)
  POST /sandbox/test/answer     — Submit answer (logged)
  POST /sandbox/test/recommend  — Get recommendations (logged, free)
  GET  /sandbox/logs            — Get all session summaries
  GET  /sandbox/logs/{id}       — Get logs for a session
  GET  /sandbox/logs/{id}/context — Get context snapshot
  GET  /sandbox/logs/export/{id}  — Export session logs as .txt
  GET  /sandbox/logs/export/all   — Export global logs as .txt
  DELETE /sandbox/logs          — Clear all logs
"""

from __future__ import annotations

import time

import structlog
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from typing import Any, Optional

from app.config import get_settings
from app.services import session_store
from app.services.sandbox_logger import (
    LogLevel,
    clear_logs,
    export_session_txt,
    get_all_sessions,
    get_session_context,
    get_session_logs,
    log_event,
    update_context_snapshot,
)
from app.services.persona_doc_service import get_doc_for_domain, get_diagnostic_sections
from app.services import agent_service
from app.models.session import (
    DynamicQuestion,
    ToolRecommendation,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/sandbox", tags=["Sandbox"])

# ── Hardcoded credentials ──────────────────────────────────────
SANDBOX_ID = "ikshan"
SANDBOX_PASSWORD = "123"


# ══════════════════════════════════════════════════════════════
# Request / Response Models
# ══════════════════════════════════════════════════════════════


class LoginRequest(BaseModel):
    id: str
    password: str


class LoginResponse(BaseModel):
    authenticated: bool
    token: str = ""
    message: str = ""


class TestSessionResponse(BaseModel):
    session_id: str
    stage: str


class TestSetOutcomeRequest(BaseModel):
    session_id: str
    outcome: str
    outcome_label: str


class TestSetDomainRequest(BaseModel):
    session_id: str
    domain: str


class TestSetTaskRequest(BaseModel):
    session_id: str
    task: str


class TestSetTaskResponse(BaseModel):
    session_id: str
    stage: str
    persona_loaded: str
    task_matched: str = ""
    questions: list[DynamicQuestion] = []


class TestAnswerRequest(BaseModel):
    session_id: str
    question_index: int
    answer: str


class TestAnswerResponse(BaseModel):
    session_id: str
    all_answered: bool = False
    next_question: Optional[DynamicQuestion] = None


class TestRecommendRequest(BaseModel):
    session_id: str


class TestRecommendResponse(BaseModel):
    session_id: str
    extensions: list[dict[str, Any]] = []
    gpts: list[dict[str, Any]] = []
    companies: list[dict[str, Any]] = []
    summary: str = ""
    session_context: dict[str, Any] = {}


# ══════════════════════════════════════════════════════════════
# Authentication
# ══════════════════════════════════════════════════════════════


@router.post("/login", response_model=LoginResponse)
async def sandbox_login(body: LoginRequest):
    """Authenticate for sandbox access. Hardcoded credentials."""
    if body.id == SANDBOX_ID and body.password == SANDBOX_PASSWORD:
        # Simple token (not JWT — sandbox only, not production auth)
        token = f"sandbox-{SANDBOX_ID}-{int(time.time())}"
        logger.info("Sandbox login successful", user=body.id)
        return LoginResponse(
            authenticated=True,
            token=token,
            message="Access granted",
        )

    logger.warning("Sandbox login failed", user=body.id)
    raise HTTPException(status_code=401, detail="Invalid credentials")


# ══════════════════════════════════════════════════════════════
# Test Flow — Mirrors agent flow with full logging, no auth/payment
# ══════════════════════════════════════════════════════════════


def _log_and_snapshot(session_id: str, level: LogLevel, category: str, event: str,
                      detail: dict = None, code_file: str = ""):
    """Log an event and update context snapshot."""
    log_event(session_id, level, category, event, detail, code_file)

    # Update context snapshot from session store
    summary = session_store.get_session_summary(session_id)
    if summary:
        update_context_snapshot(session_id, summary)


@router.post("/test/session", response_model=TestSessionResponse)
async def create_test_session():
    """Create a new test session — identical to agent session but logged."""
    session = session_store.create_session()

    _log_and_snapshot(
        session.session_id,
        LogLevel.FLOW,
        "session",
        "Test session created",
        {"session_id": session.session_id, "stage": "outcome"},
        code_file="services/session_store.py → create_session()",
    )

    return TestSessionResponse(
        session_id=session.session_id,
        stage=session.stage.value,
    )


@router.post("/test/outcome", response_model=TestSessionResponse)
async def test_set_outcome(body: TestSetOutcomeRequest):
    """Set outcome in test mode with logging."""
    t0 = time.time()

    session = session_store.set_outcome(body.session_id, body.outcome, body.outcome_label)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    duration = (time.time() - t0) * 1000

    _log_and_snapshot(
        body.session_id,
        LogLevel.FLOW,
        "session",
        f"Outcome set: {body.outcome_label}",
        {
            "outcome_id": body.outcome,
            "outcome_label": body.outcome_label,
            "stage_after": session.stage.value,
        },
        code_file="services/session_store.py → set_outcome()",
    )

    log_event(
        body.session_id, LogLevel.CONTEXT, "context",
        "Q1 answer recorded",
        {"question": "What matters most to you right now?", "answer": body.outcome_label},
        code_file="models/session.py → QuestionAnswer",
    )

    return TestSessionResponse(
        session_id=session.session_id,
        stage=session.stage.value,
    )


@router.post("/test/domain", response_model=TestSessionResponse)
async def test_set_domain(body: TestSetDomainRequest):
    """Set domain in test mode with logging."""
    session = session_store.set_domain(body.session_id, body.domain)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    _log_and_snapshot(
        body.session_id,
        LogLevel.FLOW,
        "session",
        f"Domain set: {body.domain}",
        {
            "domain": body.domain,
            "stage_after": session.stage.value,
        },
        code_file="services/session_store.py → set_domain()",
    )

    log_event(
        body.session_id, LogLevel.CONTEXT, "context",
        "Q2 answer recorded",
        {"question": "Which domain best matches your need?", "answer": body.domain},
        code_file="models/session.py → QuestionAnswer",
    )

    # Log persona doc lookup
    persona_doc = get_doc_for_domain(body.domain)
    log_event(
        body.session_id, LogLevel.FILE, "persona",
        f"Persona doc lookup: {persona_doc or 'not found'}",
        {"domain": body.domain, "persona_doc": persona_doc or "none"},
        code_file="services/persona_doc_service.py → get_doc_for_domain()",
    )

    return TestSessionResponse(
        session_id=session.session_id,
        stage=session.stage.value,
    )


@router.post("/test/task", response_model=TestSetTaskResponse)
async def test_set_task(body: TestSetTaskRequest):
    """Set task, load diagnostic sections, and log everything."""
    t0 = time.time()

    session = session_store.set_task(body.session_id, body.task)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    _log_and_snapshot(
        body.session_id,
        LogLevel.FLOW,
        "session",
        f"Task set: {body.task}",
        {"task": body.task, "stage_after": session.stage.value},
        code_file="services/session_store.py → set_task()",
    )

    # Persona doc lookup + diagnostic loading (same as agent.py but logged)
    persona_doc_name = get_doc_for_domain(session.domain or "")
    session.persona_doc_name = persona_doc_name
    session.persona_context_loaded = persona_doc_name is not None

    log_event(
        body.session_id, LogLevel.FILE, "persona",
        f"Loading persona: {persona_doc_name or 'generic'}",
        {"domain": session.domain, "persona_file": persona_doc_name},
        code_file="services/persona_doc_service.py → get_doc_for_domain()",
    )

    diagnostic = get_diagnostic_sections(
        domain=session.domain or "",
        task=session.task or "",
    )

    duration = (time.time() - t0) * 1000

    dynamic_qs = []
    task_matched = ""

    if diagnostic and diagnostic.get("sections"):
        task_matched = diagnostic.get("task_matched", "")

        log_event(
            body.session_id, LogLevel.CONTEXT, "diagnostic",
            f"Diagnostic sections loaded — task matched: {task_matched[:60]}",
            {
                "task_matched": task_matched,
                "sections_count": len(diagnostic["sections"]),
                "section_keys": [s["key"] for s in diagnostic["sections"]],
            },
            code_file="services/persona_doc_service.py → get_diagnostic_sections()",
        )

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

            log_event(
                body.session_id, LogLevel.CONTEXT, "question",
                f"Dynamic Q ({section['key']}): {section['question'][:60]}…",
                {
                    "section": section["key"],
                    "question": section["question"],
                    "options_count": len(section["items"]),
                    "options_preview": section["items"][:3],
                },
                code_file="models/session.py → DynamicQuestion",
            )
    else:
        log_event(
            body.session_id, LogLevel.WARN, "diagnostic",
            "No diagnostic sections found for task",
            {"domain": session.domain, "task": body.task},
            code_file="services/persona_doc_service.py → get_diagnostic_sections()",
        )

    session.dynamic_questions_total = len(dynamic_qs)
    session_store.update_session(session)

    _log_and_snapshot(
        body.session_id,
        LogLevel.INFO,
        "session",
        f"Task processing complete in {duration:.0f}ms",
        {"duration_ms": duration, "questions_generated": len(dynamic_qs)},
    )

    return TestSetTaskResponse(
        session_id=session.session_id,
        stage=session.stage.value,
        persona_loaded=persona_doc_name or "generic",
        task_matched=task_matched,
        questions=dynamic_qs,
    )


@router.post("/test/answer", response_model=TestAnswerResponse)
async def test_submit_answer(body: TestAnswerRequest):
    """Submit a diagnostic answer in test mode with logging."""
    session = session_store.get_session(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if body.question_index >= len(session.dynamic_questions):
        raise HTTPException(status_code=400, detail="Invalid question index")

    question_text = session.dynamic_questions[body.question_index]

    session = session_store.add_dynamic_answer(
        body.session_id, question_text, body.answer
    )
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    log_event(
        body.session_id, LogLevel.CONTEXT, "answer",
        f"Answer #{body.question_index + 1}: {body.answer[:80]}",
        {
            "question_index": body.question_index,
            "question": question_text,
            "answer": body.answer,
            "progress": f"{session.dynamic_questions_asked}/{session.dynamic_questions_total}",
        },
        code_file="services/session_store.py → add_dynamic_answer()",
    )

    next_index = body.question_index + 1
    all_answered = next_index >= session.dynamic_questions_total

    next_question = None
    if not all_answered and next_index < len(session.dynamic_questions):
        next_question = DynamicQuestion(
            question=session.dynamic_questions[next_index],
            options=[],
            allows_free_text=True,
        )

    if all_answered:
        _log_and_snapshot(
            body.session_id, LogLevel.FLOW, "session",
            "All diagnostic questions answered — ready for recommendations",
            {"total_answered": session.dynamic_questions_asked},
        )

    return TestAnswerResponse(
        session_id=body.session_id,
        all_answered=all_answered,
        next_question=next_question,
    )


@router.post("/test/recommend", response_model=TestRecommendResponse)
async def test_get_recommendations(body: TestRecommendRequest):
    """
    Get recommendations in test/sandbox mode.
    Skips payment gates. Logs the full LLM call details.
    """
    settings = get_settings()

    session = session_store.get_session(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    qa_list = [
        {"q": qa.question, "a": qa.answer, "type": qa.question_type}
        for qa in session.questions_answers
    ]

    # Log the LLM call with full context being sent
    log_event(
        body.session_id, LogLevel.LLM, "openai",
        "Generating recommendations via GPT",
        {
            "model": settings.OPENAI_MODEL_NAME,
            "outcome": session.outcome_label,
            "domain": session.domain,
            "task": session.task,
            "qa_pairs": len(qa_list),
            "qa_context": qa_list,
            "api_key_active": "primary" if settings.OPENAI_API_KEY else "secondary",
        },
        code_file="services/agent_service.py → generate_personalized_recommendations()",
    )

    if not settings.openai_api_key_active:
        log_event(
            body.session_id, LogLevel.ERROR, "openai",
            "No OpenAI API key — cannot generate recommendations",
            {},
            code_file="config.py → openai_api_key_active",
        )
        return TestRecommendResponse(
            session_id=body.session_id,
            summary="OpenAI API key not configured — recommendations unavailable in sandbox.",
        )

    t0 = time.time()

    recs = await agent_service.generate_personalized_recommendations(
        outcome=session.outcome or "",
        outcome_label=session.outcome_label or "",
        domain=session.domain or "",
        task=session.task or "",
        questions_answers=qa_list,
    )

    duration = (time.time() - t0) * 1000

    log_event(
        body.session_id, LogLevel.LLM, "openai",
        f"Recommendations received in {duration:.0f}ms",
        {
            "duration_ms": round(duration, 1),
            "extensions_count": len(recs.get("extensions", [])),
            "gpts_count": len(recs.get("gpts", [])),
            "companies_count": len(recs.get("companies", [])),
            "summary_preview": recs.get("summary", "")[:200],
        },
        code_file="services/agent_service.py → generate_personalized_recommendations()",
    )

    # Store in session
    session_store.set_recommendations(
        session.session_id,
        extensions=recs.get("extensions", []),
        gpts=recs.get("gpts", []),
        companies=recs.get("companies", []),
    )

    _log_and_snapshot(
        body.session_id, LogLevel.FLOW, "session",
        "Recommendations generated — flow complete (sandbox, no payment)",
        {"stage": "complete"},
    )

    summary_dict = session_store.get_session_summary(session.session_id) or {}

    return TestRecommendResponse(
        session_id=body.session_id,
        extensions=recs.get("extensions", []),
        gpts=recs.get("gpts", []),
        companies=recs.get("companies", []),
        summary=recs.get("summary", ""),
        session_context=summary_dict,
    )


# ══════════════════════════════════════════════════════════════
# Logger Endpoints
# ══════════════════════════════════════════════════════════════


@router.get("/logs")
async def list_all_sessions():
    """List all tracked sandbox sessions with summary."""
    sessions = get_all_sessions()
    return {
        "sessions": sessions,
        "total_sessions": len(sessions),
        "total_global_entries": 0,
    }


@router.get("/logs/export/{session_id}")
async def export_session(session_id: str):
    """Export session logs as downloadable .txt file."""
    txt = export_session_txt(session_id)
    return PlainTextResponse(
        content=txt,
        media_type="text/plain",
        headers={
            "Content-Disposition": f'attachment; filename="sandbox-log-{session_id[:8]}.txt"'
        },
    )


@router.get("/logs/{session_id}")
async def get_session_log(session_id: str):
    """Get all logs for a specific session."""
    bundle = get_session_logs(session_id)
    if not bundle:
        raise HTTPException(status_code=404, detail="No logs for this session")
    return bundle.model_dump()


@router.get("/logs/{session_id}/context")
async def get_context(session_id: str):
    """Get the live context snapshot for a session."""
    ctx = get_session_context(session_id)
    return {"session_id": session_id, "context": ctx}


@router.delete("/logs")
async def clear_all_logs():
    """Clear all sandbox logs."""
    clear_logs()
    return {"status": "cleared"}
