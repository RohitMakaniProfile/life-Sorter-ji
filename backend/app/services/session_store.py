"""
═══════════════════════════════════════════════════════════════
SESSION STORE — In-memory session context management
═══════════════════════════════════════════════════════════════
Stores and manages chat session contexts in memory.
Each session preserves the full flow: Q1-Q3, dynamic questions,
answers, persona context, and recommendations.

NOTE: In production, replace this with Redis or a database.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Optional

import structlog

from app.models.session import LLMCallLog, QuestionAnswer, SessionContext, SessionStage
from app.services import user_session_service

logger = structlog.get_logger()

# In-memory session store (replace with Redis/DB in production)
_sessions: dict[str, SessionContext] = {}

# Max sessions to keep in memory (LRU eviction)
MAX_SESSIONS = 1000


def create_session() -> SessionContext:
    """Create a new session with a unique ID."""
    session_id = str(uuid.uuid4())
    session = SessionContext(session_id=session_id)

    # Evict oldest sessions if at capacity
    if len(_sessions) >= MAX_SESSIONS:
        oldest_id = min(_sessions, key=lambda k: _sessions[k].created_at)
        del _sessions[oldest_id]
        logger.info("Evicted oldest session", session_id=oldest_id)

    _sessions[session_id] = session
    logger.info("Session created", session_id=session_id)
    _persist_session(session)
    return session


def get_session(session_id: str) -> Optional[SessionContext]:
    """Retrieve a session by ID."""
    return _sessions.get(session_id)


def update_session(session: SessionContext) -> SessionContext:
    """Update a session in the store and persist to PostgreSQL."""
    session.updated_at = datetime.utcnow()
    _sessions[session.session_id] = session
    _persist_session(session)
    return session


def _persist_session(session: SessionContext) -> None:
    """Fire-and-forget upsert to PostgreSQL. Non-blocking."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(user_session_service.upsert_session(session))
    except RuntimeError:
        # No running event loop (e.g., tests) — skip persistence
        pass


def delete_session(session_id: str) -> bool:
    """Delete a session."""
    if session_id in _sessions:
        del _sessions[session_id]
        return True
    return False


def set_outcome(session_id: str, outcome: str, outcome_label: str) -> Optional[SessionContext]:
    """Set the Q1 answer (outcome/growth bucket)."""
    session = get_session(session_id)
    if not session:
        return None

    session.outcome = outcome
    session.outcome_label = outcome_label
    session.stage = SessionStage.DOMAIN
    session.questions_answers.append(
        QuestionAnswer(
            question="What matters most to you right now?",
            answer=outcome_label,
            question_type="static",
        )
    )
    return update_session(session)


def set_domain(session_id: str, domain: str) -> Optional[SessionContext]:
    """Set the Q2 answer (domain/sub-category)."""
    session = get_session(session_id)
    if not session:
        return None

    session.domain = domain
    session.stage = SessionStage.TASK
    session.questions_answers.append(
        QuestionAnswer(
            question="Which domain best matches your need?",
            answer=domain,
            question_type="static",
        )
    )
    return update_session(session)


def set_task(session_id: str, task: str) -> Optional[SessionContext]:
    """Set the Q3 answer (task). Moves to dynamic questions stage."""
    session = get_session(session_id)
    if not session:
        return None

    session.task = task
    session.stage = SessionStage.DYNAMIC_QUESTIONS
    session.questions_answers.append(
        QuestionAnswer(
            question="What task would you like help with?",
            answer=task,
            question_type="static",
        )
    )
    return update_session(session)


def add_dynamic_answer(
    session_id: str, question: str, answer: str
) -> Optional[SessionContext]:
    """Record a dynamic question answer."""
    session = get_session(session_id)
    if not session:
        return None

    session.questions_answers.append(
        QuestionAnswer(
            question=question,
            answer=answer,
            question_type="dynamic",
        )
    )
    session.dynamic_questions_asked += 1

    # If all dynamic questions answered, move to recommendation
    if session.dynamic_questions_asked >= session.dynamic_questions_total:
        session.stage = SessionStage.RECOMMENDATION

    return update_session(session)


def set_recommendations(
    session_id: str,
    extensions: list[dict],
    gpts: list[dict],
    companies: list[dict],
) -> Optional[SessionContext]:
    """Store the final recommendations in the session."""
    session = get_session(session_id)
    if not session:
        return None

    session.recommended_extensions = extensions
    session.recommended_gpts = gpts
    session.recommended_companies = companies
    session.stage = SessionStage.COMPLETE
    return update_session(session)


# ── Claude RCA helpers ─────────────────────────────────────────

def set_rca_context(
    session_id: str, diagnostic_context: dict
) -> Optional[SessionContext]:
    """Store the raw dynamic-loader output as internal RCA context."""
    session = get_session(session_id)
    if not session:
        return None
    session.rca_diagnostic_context = diagnostic_context
    return update_session(session)


def set_filtered_context(
    session_id: str,
    filtered_items: dict,
    deferred_items: list,
    task_execution_summary: str = "",
    validation: dict | None = None,
) -> Optional[SessionContext]:
    """Store the task-aligned filtered context and deferred items."""
    session = get_session(session_id)
    if not session:
        return None
    session.rca_filtered_context = filtered_items
    session.rca_deferred_context = deferred_items
    session.rca_task_execution_summary = task_execution_summary
    return update_session(session)


def expand_rca_context(session_id: str) -> Optional[SessionContext]:
    """Pull deferred context items into the filtered context for scope expansion."""
    session = get_session(session_id)
    if not session:
        return None
    if session.rca_context_expanded:
        return session  # Already expanded

    # Merge deferred items into filtered context
    deferred = session.rca_deferred_context
    filtered = session.rca_filtered_context
    if deferred and filtered:
        # Add deferred items as a new "expanded" category
        filtered["expanded"] = deferred
        session.rca_filtered_context = filtered
        session.rca_context_expanded = True
        logger.info(
            "RCA context expanded with deferred items",
            session_id=session_id,
            deferred_count=len(deferred),
        )
    return update_session(session)


def add_rca_answer(
    session_id: str, question: str, answer: str
) -> Optional[SessionContext]:
    """Append a Claude RCA question-answer pair."""
    session = get_session(session_id)
    if not session:
        return None
    session.rca_history.append({"question": question, "answer": answer})
    session.questions_answers.append(
        QuestionAnswer(question=question, answer=answer, question_type="rca")
    )
    return update_session(session)


def set_rca_running_summary(
    session_id: str, running_summary: str
) -> Optional[SessionContext]:
    """Update the compressed running summary of RCA findings."""
    session = get_session(session_id)
    if not session:
        return None
    session.rca_running_summary = running_summary
    return update_session(session)


def set_rca_complete(
    session_id: str, summary: str = "", handoff: str = ""
) -> Optional[SessionContext]:
    """Mark the RCA diagnostic as complete and store structured handoff."""
    session = get_session(session_id)
    if not session:
        return None
    session.rca_complete = True
    session.rca_summary = summary
    if handoff:
        session.rca_handoff = handoff
    session.stage = SessionStage.RECOMMENDATION
    return update_session(session)


def set_rca_fallback(session_id: str) -> Optional[SessionContext]:
    """Activate fallback mode (use static dynamic-loader questions)."""
    session = get_session(session_id)
    if not session:
        return None
    session.rca_fallback_active = True
    return update_session(session)


# ── LLM Call Log helpers ───────────────────────────────────────

def add_llm_call_log(
    session_id: str,
    service: str,
    model: str,
    purpose: str,
    system_prompt: str,
    user_message: str,
    temperature: float,
    max_tokens: int,
    raw_response: str = "",
    latency_ms: int = 0,
    token_usage: dict | None = None,
    error: str = "",
) -> Optional[SessionContext]:
    """Append an LLM call record to the session's context pool log."""
    session = get_session(session_id)
    if not session:
        return None
    entry = LLMCallLog(
        timestamp=datetime.utcnow().isoformat() + "Z",
        service=service,
        model=model,
        purpose=purpose,
        system_prompt=system_prompt[:3000],    # Truncate for memory
        user_message=user_message[:3000],
        temperature=temperature,
        max_tokens=max_tokens,
        raw_response=raw_response[:5000],
        latency_ms=latency_ms,
        token_usage=token_usage or {},
        error=error,
    )
    session.llm_call_log.append(entry)

    # Auto-accumulate token counts
    if token_usage:
        p_tok = token_usage.get("prompt_tokens", 0)
        c_tok = token_usage.get("completion_tokens", 0)
        session.total_llm_tokens["prompt_tokens"] += p_tok
        session.total_llm_tokens["completion_tokens"] += c_tok

    return update_session(session)


# ── Early Recommendations helpers ──────────────────────────────

def set_early_recommendations(
    session_id: str,
    tools: list[dict],
    message: str = "",
) -> Optional[SessionContext]:
    """Store early tool recommendations generated after Q3."""
    session = get_session(session_id)
    if not session:
        return None
    session.early_recommendations = tools
    session.early_recommendations_message = message
    return update_session(session)


# ── Website & Audience Insights helpers ────────────────────────

def set_website_url(
    session_id: str, website_url: str, url_type: str = "website"
) -> Optional[SessionContext]:
    """Store the user's business website URL with metadata."""
    session = get_session(session_id)
    if not session:
        return None
    session.website_url = website_url
    session.url_type = url_type
    session.url_submitted_at = datetime.utcnow().isoformat() + "Z"
    return update_session(session)


def set_audience_insights(
    session_id: str, insights: dict
) -> Optional[SessionContext]:
    """Store audience analysis insights from website review."""
    session = get_session(session_id)
    if not session:
        return None
    session.audience_insights = insights
    return update_session(session)


def set_crawl_status(
    session_id: str, status: str
) -> Optional[SessionContext]:
    """Update the crawl status flag (in_progress, complete, failed)."""
    session = get_session(session_id)
    if not session:
        return None
    session.crawl_status = status
    return update_session(session)


def set_crawl_data(
    session_id: str,
    crawl_raw: dict,
    crawl_summary: dict,
) -> Optional[SessionContext]:
    """Store both raw crawl data and the compressed summary."""
    session = get_session(session_id)
    if not session:
        return None
    session.crawl_raw = crawl_raw
    session.crawl_summary = crawl_summary
    session.crawl_status = crawl_summary.get("crawl_status", "complete")
    return update_session(session)


# ── Business Profile / Scale Questions helpers ─────────────────

def set_business_profile(
    session_id: str, profile: dict
) -> Optional[SessionContext]:
    """Store the business profile from scale questions."""
    session = get_session(session_id)
    if not session:
        return None
    session.business_profile = profile
    session.scale_questions_complete = True
    session.stage = SessionStage.DYNAMIC_QUESTIONS
    # Also record each scale answer in the main Q&A list for traceability
    for key, value in profile.items():
        session.questions_answers.append(
            QuestionAnswer(
                question=f"Scale: {key}",
                answer=str(value),
                question_type="scale",
            )
        )
    return update_session(session)


def get_session_summary(session_id: str) -> Optional[dict]:
    """Get a summary of the full session context."""
    session = get_session(session_id)
    if not session:
        return None

    return {
        "session_id": session.session_id,
        "created_at": session.created_at.isoformat(),
        "stage": session.stage.value,
        "outcome": session.outcome_label,
        "domain": session.domain,
        "task": session.task,
        "persona_doc": session.persona_doc_name,
        "questions_answers": [
            {"q": qa.question, "a": qa.answer, "type": qa.question_type}
            for qa in session.questions_answers
        ],
        "dynamic_questions_progress": f"{session.dynamic_questions_asked}/{session.dynamic_questions_total}",
        "recommendations": {
            "extensions": len(session.recommended_extensions),
            "gpts": len(session.recommended_gpts),
            "companies": len(session.recommended_companies),
        },
        "website_url": session.website_url,
        "url_type": session.url_type,
        "audience_insights": session.audience_insights if session.audience_insights else None,
        "crawl_status": session.crawl_status or None,
        "crawl_summary": session.crawl_summary if session.crawl_summary else None,
        "business_profile": session.business_profile if session.business_profile else None,
        "playbook_stage": session.playbook_stage or None,
        "playbook_complete": session.playbook_complete,
    }


# ── Playbook Pipeline helpers ──────────────────────────────────

def set_playbook_stage(
    session_id: str, stage: str
) -> Optional[SessionContext]:
    """Update the playbook pipeline stage."""
    session = get_session(session_id)
    if not session:
        return None
    session.playbook_stage = stage
    return update_session(session)


def set_playbook_gap_questions(
    session_id: str, gap_questions_text: str
) -> Optional[SessionContext]:
    """Store gap questions from Phase 0 / Agent 2."""
    session = get_session(session_id)
    if not session:
        return None
    session.playbook_gap_questions = gap_questions_text
    session.playbook_stage = "waiting_gap_answers"
    return update_session(session)


def set_playbook_gap_answers(
    session_id: str, gap_answers: str
) -> Optional[SessionContext]:
    """Store user's gap question answers."""
    session = get_session(session_id)
    if not session:
        return None
    session.playbook_gap_answers = gap_answers
    return update_session(session)


def set_playbook_results(
    session_id: str,
    agent1_output: str,
    agent2_output: str,
    agent3_output: str,
    agent4_output: str,
    agent5_output: str,
    latencies: dict,
) -> Optional[SessionContext]:
    """Store all 5 agent outputs after pipeline completion."""
    session = get_session(session_id)
    if not session:
        return None
    session.playbook_agent1_output = agent1_output
    session.playbook_agent2_output = agent2_output
    session.playbook_agent3_output = agent3_output
    session.playbook_agent4_output = agent4_output
    session.playbook_agent5_output = agent5_output
    session.playbook_complete = True
    session.playbook_stage = "complete"
    session.playbook_latencies = latencies
    session.stage = SessionStage.PLAYBOOK
    return update_session(session)


def log_phase_timing(session_id: str, phase: str, duration_ms: int) -> None:
    """Record a phase's duration (e.g. crawl_ms, rca_total_ms, playbook_total_ms)."""
    session = get_session(session_id)
    if not session:
        return
    session.phase_timings[phase] = duration_ms
    update_session(session)


def add_cost_and_tokens(session_id: str, cost_inr: float, prompt_tokens: int, completion_tokens: int) -> None:
    """Accumulate cost and token counts for the session."""
    session = get_session(session_id)
    if not session:
        return
    session.estimated_cost_inr += cost_inr
    session.total_llm_tokens["prompt_tokens"] += prompt_tokens
    session.total_llm_tokens["completion_tokens"] += completion_tokens
    update_session(session)
