"""
═══════════════════════════════════════════════════════════════
PLAYBOOK ROUTER — AI Growth Playbook Generation Endpoints
═══════════════════════════════════════════════════════════════
Endpoints for the 5-agent playbook pipeline:
  POST /playbook/start          → Kick off Phase 0 (gap Qs) + Agent 1-2
  POST /playbook/gap-answers    → Submit gap answers → run Agent 3-5
  GET  /playbook/{session_id}   → Get playbook results
"""

import re
import traceback
import structlog
from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import BaseModel
from typing import Any, Optional

from app.config import get_settings
from app.middleware.rate_limit import limiter
from app.services import session_store
from app.services.playbook_service import (
    run_phase0_gap_questions,
    run_agent1_context_parser,
    run_agent2_icp_analyst,
    run_full_playbook_pipeline,
)

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/playbook", tags=["Playbook"])


# ── Request / Response Models ──────────────────────────────────

class StartPlaybookRequest(BaseModel):
    session_id: str


class GapQuestion(BaseModel):
    id: str = ""                  # e.g. "Q1"
    label: str = ""               # e.g. "Founder Background"
    question: str = ""            # full question text
    options: list[str] = []       # ["A) ...", "B) ...", ...]


class StartPlaybookResponse(BaseModel):
    session_id: str
    stage: str                    # "gap_questions" or "generating"
    gap_questions: str = ""       # raw gap questions text
    gap_questions_parsed: list[GapQuestion] = []  # structured gap questions with options
    agent1_output: str = ""       # Context Brief (always generated)
    agent2_output: str = ""       # ICP Card (always generated)
    message: str = ""


class SubmitGapAnswersRequest(BaseModel):
    session_id: str
    answers: str                  # e.g. "Q1-A, Q2-C" or free-text


class SubmitGapAnswersResponse(BaseModel):
    session_id: str
    stage: str                    # "generating" → full pipeline running
    message: str = ""


class PlaybookResultResponse(BaseModel):
    session_id: str
    complete: bool
    stage: str
    playbook: str = ""            # Agent 3 output — the 10-step playbook
    tool_matrix: str = ""         # Agent 4 output
    website_audit: str = ""       # Agent 5 output
    context_brief: str = ""       # Agent 1 output
    icp_card: str = ""            # Agent 2 output
    latencies: dict[str, Any] = {}


class GenerateFullPlaybookRequest(BaseModel):
    session_id: str
    gap_answers: str = ""


class GenerateFullPlaybookResponse(BaseModel):
    session_id: str
    complete: bool
    playbook: str = ""
    tool_matrix: str = ""
    website_audit: str = ""
    context_brief: str = ""
    icp_card: str = ""
    latencies: dict[str, Any] = {}
    message: str = ""


# ── Endpoints ──────────────────────────────────────────────────

@router.post("/start", response_model=StartPlaybookResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def start_playbook(request: Request, body: StartPlaybookRequest = Body(...)):
    """
    Start the playbook pipeline.

    1. Runs Agent 1 (Context Parser) and Agent 2 (ICP Analyst + Gap Questions).
    2. If Agent 2 produces gap questions, returns them for the user to answer.
    3. If no gaps, proceeds directly to full pipeline.
    """
    session = session_store.get_session(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not session.rca_complete:
        raise HTTPException(status_code=400, detail="RCA diagnostic must be completed before generating playbook")

    try:
        # Mark playbook as starting
        session_store.set_playbook_stage(body.session_id, "generating_context")

        # Gather session data
        outcome_label = session.outcome_label or ""
        domain = session.domain or ""
        task = session.task or ""
        business_profile = session.business_profile or {}
        rca_history = session.rca_history or []
        rca_summary = session.rca_summary or ""
        crawl_summary = session.crawl_summary or {}

        # ── Run Agent 1 (Context Parser) ──────────────────────────
        agent1 = await run_agent1_context_parser(
            outcome_label=outcome_label,
            domain=domain,
            task=task,
            business_profile=business_profile,
            rca_history=rca_history,
            rca_summary=rca_summary,
            crawl_summary=crawl_summary,
        )

        # Log Agent 1 call
        session_store.add_llm_call_log(
            session_id=body.session_id,
            service="claude_openrouter",
            model=get_settings().OPENROUTER_MODEL,
            purpose="playbook_agent1_context_parser",
            system_prompt="[AGENT1_PROMPT]",
            user_message="[playbook input context]",
            temperature=0.4,
            max_tokens=3000,
            raw_response=agent1["output"][:3000],
            latency_ms=agent1["latency_ms"],
            token_usage=agent1.get("usage"),
        )

        # Store Agent 1 output
        s = session_store.get_session(body.session_id)
        if s:
            s.playbook_agent1_output = agent1["output"]
            session_store.update_session(s)

        # ── Run Agent 2 (ICP Analyst + Gap Questions) ─────────────
        agent2 = await run_agent2_icp_analyst(agent1_output=agent1["output"])

        # Log Agent 2 call
        session_store.add_llm_call_log(
            session_id=body.session_id,
            service="claude_openrouter",
            model=get_settings().OPENROUTER_MODEL,
            purpose="playbook_agent2_icp_analyst",
            system_prompt="[AGENT2_PROMPT]",
            user_message="[agent1 output]",
            temperature=0.6,
            max_tokens=4000,
            raw_response=agent2["output"][:3000],
            latency_ms=agent2["latency_ms"],
            token_usage=agent2.get("usage"),
        )

        # Store Agent 2 output
        s = session_store.get_session(body.session_id)
        if s:
            s.playbook_agent2_output = agent2["output"]
            session_store.update_session(s)

        # Check if Agent 2 output contains gap questions
        agent2_text = agent2["output"]
        has_gap_questions = _detect_gap_questions(agent2_text)

        if has_gap_questions:
            # Extract gap questions portion and return to user
            session_store.set_playbook_gap_questions(body.session_id, agent2_text)

            # Parse gap questions into structured format with options
            parsed_gaps = _parse_gap_questions(agent2_text)

            logger.info(
                "Playbook pipeline paused for gap answers",
                session_id=body.session_id,
                gap_questions_count=len(parsed_gaps),
            )

            return StartPlaybookResponse(
                session_id=body.session_id,
                stage="gap_questions",
                gap_questions=agent2_text,
                gap_questions_parsed=[
                    GapQuestion(**g) for g in parsed_gaps
                ],
                agent1_output=agent1["output"],
                agent2_output=agent2["output"],
                message="I need a few more details before building your playbook.",
            )

        # No gap questions — proceed to full pipeline
        session_store.set_playbook_stage(body.session_id, "generating")

        return StartPlaybookResponse(
            session_id=body.session_id,
            stage="ready",
            agent1_output=agent1["output"],
            agent2_output=agent2["output"],
            message="Context parsed and ICP built. Ready to generate playbook.",
        )

    except Exception as exc:
        logger.error(
            "Playbook /start failed",
            session_id=body.session_id,
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        raise HTTPException(status_code=500, detail=f"Playbook generation failed: {str(exc)}")


@router.post("/gap-answers", response_model=SubmitGapAnswersResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def submit_gap_answers(request: Request, body: SubmitGapAnswersRequest = Body(...)):
    """
    Submit gap question answers. Stores them for the full pipeline run.
    """
    session = session_store.get_session(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session_store.set_playbook_gap_answers(body.session_id, body.answers)
    session_store.set_playbook_stage(body.session_id, "ready")

    logger.info(
        "Gap answers received",
        session_id=body.session_id,
        answers_length=len(body.answers),
    )

    return SubmitGapAnswersResponse(
        session_id=body.session_id,
        stage="ready",
        message="Got it. Generating your playbook now.",
    )


@router.post("/generate", response_model=GenerateFullPlaybookResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def generate_full_playbook(request: Request, body: GenerateFullPlaybookRequest = Body(...)):
    """
    Run the full 5-agent playbook pipeline.

    Call this AFTER /start (and /gap-answers if needed).
    Runs Agent 1 → 2 → 3 → 4+5 (parallel) and returns all outputs.
    """
    session = session_store.get_session(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not session.rca_complete:
        raise HTTPException(status_code=400, detail="RCA diagnostic must be completed first")

    try:
        session_store.set_playbook_stage(body.session_id, "generating")

        # Gather session data
        outcome_label = session.outcome_label or ""
        domain = session.domain or ""
        task = session.task or ""
        business_profile = session.business_profile or {}
        rca_history = session.rca_history or []
        rca_summary = session.rca_summary or ""
        crawl_summary = session.crawl_summary or {}
        gap_answers = body.gap_answers or session.playbook_gap_answers or ""

        # Run the full pipeline
        result = await run_full_playbook_pipeline(
            outcome_label=outcome_label,
            domain=domain,
            task=task,
            business_profile=business_profile,
            rca_history=rca_history,
            rca_summary=rca_summary,
            crawl_summary=crawl_summary,
            gap_answers=gap_answers,
        )

        # Store all results in session
        session_store.set_playbook_results(
            session_id=body.session_id,
            agent1_output=result["agent1_context_brief"],
            agent2_output=result["agent2_icp_card"],
            agent3_output=result["agent3_playbook"],
            agent4_output=result["agent4_tool_matrix"],
            agent5_output=result["agent5_website_audit"],
            latencies=result["agent_latencies"],
        )

        # Log each agent call
        settings = get_settings()
        for agent_name in ["agent1", "agent2", "agent3", "agent4", "agent5"]:
            session_store.add_llm_call_log(
                session_id=body.session_id,
                service="claude_openrouter",
                model=settings.OPENROUTER_MODEL,
                purpose=f"playbook_{agent_name}",
                system_prompt=f"[{agent_name.upper()}_PROMPT]",
                user_message="[pipeline context]",
                temperature=0.5,
                max_tokens=4000,
                latency_ms=result["agent_latencies"].get(agent_name, 0),
                token_usage=result.get("total_usage"),
            )

        logger.info(
            "Full playbook pipeline completed",
            session_id=body.session_id,
            total_latency_ms=result["total_latency_ms"],
        )

        return GenerateFullPlaybookResponse(
            session_id=body.session_id,
            complete=True,
            playbook=result["agent3_playbook"],
            tool_matrix=result["agent4_tool_matrix"],
            website_audit=result["agent5_website_audit"],
            context_brief=result["agent1_context_brief"],
            icp_card=result["agent2_icp_card"],
            latencies=result["agent_latencies"],
            message="Your AI Growth Playbook is ready.",
        )

    except Exception as exc:
        logger.error(
            "Playbook /generate failed",
            session_id=body.session_id,
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        raise HTTPException(status_code=500, detail=f"Playbook generation failed: {str(exc)}")


@router.get("/{session_id}", response_model=PlaybookResultResponse)
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def get_playbook(request: Request, session_id: str):
    """
    Get the playbook results for a session.
    Returns whatever has been generated so far.
    """
    session = session_store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    return PlaybookResultResponse(
        session_id=session_id,
        complete=session.playbook_complete,
        stage=session.playbook_stage or "not_started",
        playbook=session.playbook_agent3_output,
        tool_matrix=session.playbook_agent4_output,
        website_audit=session.playbook_agent5_output,
        context_brief=session.playbook_agent1_output,
        icp_card=session.playbook_agent2_output,
        latencies=session.playbook_latencies,
    )


# ── Helpers ────────────────────────────────────────────────────

def _detect_gap_questions(agent2_output: str) -> bool:
    """
    Detect whether Agent 2's output contains gap questions.
    """
    markers = [
        "Q1 —",
        "Q1 —",
        "GAP QUESTIONS",
        "Before I build your playbook",
        "I need clarity on",
        "things the data didn't tell me",
    ]
    return any(marker in agent2_output for marker in markers)


def _parse_gap_questions(agent2_output: str) -> list[dict[str, Any]]:
    """
    Parse Agent 2's gap questions into structured list with options.
    Expected format:
        Q1 — Label: Question text
          A) option text
          B) option text
          ...
    """
    parsed = []
    # Match Q1/Q2/Q3 blocks: capture id, label, question, then options
    q_pattern = re.compile(
        r'Q(\d+)\s*[—–-]\s*\**([^:*]+?)\**\s*:\s*(.+?)(?=\nQ\d+\s*[—–-]|\Z)',
        re.DOTALL
    )

    for match in q_pattern.finditer(agent2_output):
        q_id = f"Q{match.group(1)}"
        label = match.group(2).strip().strip('*')
        body = match.group(3).strip()

        # Split body into question text and options
        lines = body.split('\n')
        question_parts = []
        options = []

        for line in lines:
            stripped = line.strip()
            # Match option lines: A) ..., B) ..., etc.
            opt_match = re.match(r'^([A-E])\)\s*(.+)', stripped)
            if opt_match:
                options.append(stripped)
            elif stripped and not options:
                # Still part of question text (before options start)
                question_parts.append(stripped)

        question_text = ' '.join(question_parts) if question_parts else label

        parsed.append({
            "id": q_id,
            "label": label,
            "question": question_text,
            "options": options,
        })

    return parsed
