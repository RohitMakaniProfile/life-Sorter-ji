"""
═══════════════════════════════════════════════════════════════
PLAYBOOK ROUTER — AI Growth Playbook Generation Endpoints
═══════════════════════════════════════════════════════════════
Endpoints for the 5-agent playbook pipeline:
  POST /playbook/start          → Kick off Phase 0 (gap Qs) + Agent 1-2
  POST /playbook/gap-answers    → Submit gap answers → run Agent 3-5
  GET  /playbook/{session_id}   → Get playbook results
"""

import asyncio
import json
import re
import traceback
import structlog
from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Any, Optional

from app.config import get_settings
from app.middleware.rate_limit import limiter
from app.services import session_store
from app.services.playbook_service import (
    run_agent_a_merged,
    run_agent_e_standalone,
    run_agent_c,
    run_agent_c_stream,
    build_tools_toon,
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
    stage: str                    # "gap_questions" or "ready"
    gap_questions: str = ""       # gap questions raw text
    gap_questions_parsed: list[GapQuestion] = []  # structured gap questions
    agent1_output: str = ""       # Context Brief + ICP (Sonnet)
    agent2_output: str = ""       # ICP Card portion
    message: str = ""


class SubmitGapAnswersRequest(BaseModel):
    session_id: str
    answers: str                  # e.g. "Q1-A, Q2-C" or free-text


class SubmitGapAnswersResponse(BaseModel):
    session_id: str
    stage: str                    # "generating" → full pipeline running
    message: str = ""


class GenerateFullPlaybookRequest(BaseModel):
    session_id: str
    gap_answers: str = ""


class GenerateFullPlaybookResponse(BaseModel):
    session_id: str
    complete: bool
    playbook: str = ""        # Agent C — 10-step Playbook (Sonnet)
    website_audit: str = ""   # Agent E — Website Audit (Sonnet)
    context_brief: str = ""   # Agent A — Context Brief (Sonnet)
    icp_card: str = ""        # Agent A — ICP Card (Sonnet)
    latencies: dict[str, Any] = {}
    message: str = ""


# ── Background Agent E Task ────────────────────────────────────

async def _run_agent_e_background(
    session_id: str,
    outcome_label: str,
    domain: str,
    task: str,
    business_profile: dict,
    rca_history: list,
    crawl_summary: dict,
    crawl_raw: dict,
) -> None:
    """
    Fire Agent E (Website Critic) fully in parallel with Agent A.
    Stores result directly to session when done — 0s added to critical path.
    """
    try:
        result = await run_agent_e_standalone(
            outcome_label=outcome_label,
            domain=domain,
            task=task,
            business_profile=business_profile,
            rca_history=rca_history,
            crawl_summary=crawl_summary,
            crawl_raw=crawl_raw,
        )
        s = session_store.get_session(session_id)
        if s:
            s.playbook_agent5_output = result["output"]
            s.playbook_agent5_output_opus = result.get("output_opus", "")
            session_store.add_llm_call_log(
                session_id=session_id,
                service="claude_openrouter",
                model=get_settings().OPENROUTER_MODEL,
                purpose="playbook_agent_e_website_critic",
                system_prompt="[AGENT_E_STANDALONE_PROMPT]",
                user_message="[crawl + raw session data]",
                temperature=0.5,
                max_tokens=3000,
                raw_response=result["output"][:2000],
                latency_ms=result["latency_ms"],
                token_usage=result.get("usage"),
            )
            session_store.update_session(s)
            logger.info(
                "Agent E background task completed — GLM + Opus",
                session_id=session_id,
                latency_ms=result["latency_ms"],
                opus_latency_ms=result.get("opus_latency_ms", 0),
            )
    except Exception as exc:
        logger.error(
            "Agent E background task failed",
            session_id=session_id,
            error=str(exc),
        )


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

    # Auto-complete RCA if frontend reached /start without going through the Claude RCA path
    # (e.g. fallback static questions, or website-analysis path)
    if not session.rca_complete:
        logger.info(
            "rca_complete not set — auto-completing before playbook start",
            session_id=body.session_id,
        )
        session_store.set_rca_complete(body.session_id, summary="")

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
        rca_handoff = session.rca_handoff or ""
        crawl_summary = session.crawl_summary or {}
        crawl_raw = session.crawl_raw if hasattr(session, "crawl_raw") else {}

        # ── Fire Agent E in background immediately (off critical path) ──
        # Agent E needs only crawl + raw session data — no Agent A dependency.
        # It runs in parallel while Agent A executes, adding 0s to critical path.
        asyncio.create_task(
            _run_agent_e_background(
                session_id=body.session_id,
                outcome_label=outcome_label,
                domain=domain,
                task=task,
                business_profile=business_profile,
                rca_history=rca_history,
                crawl_summary=crawl_summary,
                crawl_raw=crawl_raw or {},
            )
        )
        logger.info(
            "Agent E background task fired (off critical path)",
            session_id=body.session_id,
        )

        # ── Run Agent A (merged Context Brief + ICP Card + Gap Questions) ──
        # Single LLM call replacing the sequential Agent 1 → Agent 2 flow.
        agent_a = await run_agent_a_merged(
            outcome_label=outcome_label,
            domain=domain,
            task=task,
            business_profile=business_profile,
            rca_history=rca_history,
            rca_summary=rca_summary,
            crawl_summary=crawl_summary,
            rca_handoff=rca_handoff,
        )

        # Log Agent A call
        session_store.add_llm_call_log(
            session_id=body.session_id,
            service="claude_openrouter",
            model=get_settings().OPENROUTER_MODEL,
            purpose="playbook_agent_a_merged",
            system_prompt="[AGENT_A_MERGED_PROMPT]",
            user_message="[playbook input context]",
            temperature=0.5,
            max_tokens=5000,
            raw_response=agent_a["output"][:3000],
            latency_ms=agent_a["latency_ms"],
            token_usage=agent_a.get("usage"),
        )

        # Extract GLM outputs
        agent_a_text = agent_a["output"]
        icp_portion = _extract_icp_section(agent_a_text)

        s = session_store.get_session(body.session_id)
        if s:
            s.playbook_agent1_output = agent_a_text
            s.playbook_agent2_output = icp_portion
            session_store.update_session(s)

        # Check if Agent A output contains gap questions
        has_gap_questions = _detect_gap_questions(agent_a_text)

        if has_gap_questions:
            session_store.set_playbook_gap_questions(body.session_id, agent_a_text)
            parsed_gaps = _parse_gap_questions(agent_a_text)

            logger.info(
                "Playbook pipeline paused for gap answers",
                session_id=body.session_id,
                gap_questions_count=len(parsed_gaps),
            )

            return StartPlaybookResponse(
                session_id=body.session_id,
                stage="gap_questions",
                gap_questions=agent_a_text,
                gap_questions_parsed=[GapQuestion(**g) for g in parsed_gaps],
                agent1_output=agent_a_text,
                agent2_output=icp_portion,
                message="I need a few more details before building your playbook.",
            )

        # No gap questions — ready to generate
        session_store.set_playbook_stage(body.session_id, "generating")

        return StartPlaybookResponse(
            session_id=body.session_id,
            stage="ready",
            agent1_output=agent_a_text,
            agent2_output=icp_portion,
            message="Context parsed and ICP built. Ready to generate playbook.",
        )

    except ValueError as exc:
        logger.error(
            "Playbook /start configuration error",
            session_id=body.session_id,
            error=str(exc),
        )
        raise HTTPException(status_code=503, detail=f"Playbook configuration error: {str(exc)}")
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
        session_store.set_rca_complete(body.session_id, summary="")

    try:
        session_store.set_playbook_stage(body.session_id, "generating")

        gap_answers = body.gap_answers or session.playbook_gap_answers or ""

        # Agent A output is cached from /start — contains Context Brief + ICP Card
        agent_a_output = session.playbook_agent1_output or ""

        if not agent_a_output:
            # Fallback: re-run Agent A if somehow missing
            logger.warning("Agent A output missing, re-running", session_id=body.session_id)
            from app.services.playbook_service import run_agent_a_merged as _run_a
            agent_a_result = await _run_a(
                outcome_label=session.outcome_label or "",
                domain=session.domain or "",
                task=session.task or "",
                business_profile=session.business_profile or {},
                rca_history=session.rca_history or [],
                rca_summary=session.rca_summary or "",
                crawl_summary=session.crawl_summary or {},
                gap_answers=gap_answers,
                rca_handoff=session.rca_handoff or "",
            )
            agent_a_output = agent_a_result["output"]

        # ── Build recommended tools context from session ──
        recommended_tools = _build_recommended_tools_context(session)

        # ── Run Agent C (Playbook) — GLM + Opus in parallel ──
        cd_result = await run_agent_c(
            agent_a_output=agent_a_output,
            gap_answers=gap_answers,
            recommended_tools=recommended_tools,
            task=session.task or "",
        )

        # ── Retrieve Agent E result (stored by background task from /start) ──
        agent_e_output = session.playbook_agent5_output or ""
        if not agent_e_output:
            logger.info(
                "Agent E not yet complete, waiting up to 15s",
                session_id=body.session_id,
            )
            for _ in range(15):
                await asyncio.sleep(1)
                s = session_store.get_session(body.session_id)
                if s and s.playbook_agent5_output:
                    agent_e_output = s.playbook_agent5_output
                    break

        # Log Agent C call
        settings = get_settings()
        session_store.add_llm_call_log(
            session_id=body.session_id,
            service="claude_openrouter",
            model=settings.OPENROUTER_MODEL,
            purpose="playbook_agent_c_playbook",
            system_prompt="[AGENT3_PROMPT]",
            user_message="[pipeline context]",
            temperature=0.7,
            max_tokens=10000,
            latency_ms=cd_result["agent_c_latency_ms"],
            token_usage=cd_result.get("usage"),
        )

        # Store all results
        session_store.set_playbook_results(
            session_id=body.session_id,
            agent1_output=agent_a_output,
            agent2_output=session.playbook_agent2_output or "",
            agent3_output=cd_result["agent_c_playbook"],
            agent4_output="",
            agent5_output=agent_e_output,
            latencies={
                "agent_a": 0,  # already ran in /start
                "agent_c": cd_result["agent_c_latency_ms"],
                "agent_e": 0,  # ran in parallel during /start
            },
        )

        logger.info(
            "Full playbook pipeline (v2) completed",
            session_id=body.session_id,
            total_ms=cd_result["total_latency_ms"],
            has_website_audit=bool(agent_e_output),
        )

        return GenerateFullPlaybookResponse(
            session_id=body.session_id,
            complete=True,
            playbook=cd_result["agent_c_playbook"],
            website_audit=agent_e_output,
            context_brief=agent_a_output,
            icp_card=session.playbook_agent2_output or "",
            latencies={
                "agent_c": cd_result["agent_c_latency_ms"],
                "agent_e": 0,
            },
            message="Your AI Growth Playbook is ready.",
        )

    except ValueError as exc:
        logger.error(
            "Playbook /generate configuration error",
            session_id=body.session_id,
            error=str(exc),
        )
        raise HTTPException(status_code=503, detail=f"Playbook configuration error: {str(exc)}")
    except Exception as exc:
        logger.error(
            "Playbook /generate failed",
            session_id=body.session_id,
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        raise HTTPException(status_code=500, detail=f"Playbook generation failed: {str(exc)}")


@router.post("/generate-stream")
@limiter.limit(lambda: get_settings().RATE_LIMIT_DEFAULT)
async def generate_playbook_stream(request: Request, body: GenerateFullPlaybookRequest = Body(...)):
    """
    SSE endpoint — streams Agent C tokens word-by-word as the playbook is generated.

    Event types emitted:
      data: {"type": "stage",  "stage": "generating", "label": "..."}
      data: {"type": "token",  "token": "..."}
      data: {"type": "done",   "playbook": "...", "website_audit": "...", "context_brief": "...", "icp_card": "..."}
      data: {"type": "error",  "message": "..."}
    """
    session = session_store.get_session(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not session.rca_complete:
        session_store.set_rca_complete(body.session_id, summary="")

    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def _send(obj: dict) -> None:
        await queue.put(f"data: {json.dumps(obj)}\n\n")

    async def _run() -> None:
        try:
            gap_answers = body.gap_answers or getattr(session, "playbook_gap_answers", "") or ""
            agent_a_output = getattr(session, "playbook_agent1_output", "") or ""

            # Re-run Agent A if somehow missing (edge case)
            if not agent_a_output:
                await _send({"type": "stage", "stage": "context", "label": "Building context..."})
                a_result = await run_agent_a_merged(
                    outcome_label=session.outcome_label or "",
                    domain=session.domain or "",
                    task=session.task or "",
                    business_profile=session.business_profile or {},
                    rca_history=session.rca_history or [],
                    rca_summary=session.rca_summary or "",
                    crawl_summary=session.crawl_summary or {},
                    gap_answers=gap_answers,
                    rca_handoff=session.rca_handoff or "",
                )
                agent_a_output = a_result["output"]

            recommended_tools = _build_recommended_tools_context(session)

            await _send({"type": "stage", "stage": "generating", "label": "Writing your playbook..."})

            async def on_token(token: str) -> None:
                await _send({"type": "token", "token": token})

            cd_result = await run_agent_c_stream(
                agent_a_output=agent_a_output,
                gap_answers=gap_answers,
                recommended_tools=recommended_tools,
                task=session.task or "",
                on_token=on_token,
            )

            agent_e_output = getattr(session, "playbook_agent5_output", "") or ""

            # Store results in session
            session_store.set_playbook_results(
                session_id=body.session_id,
                agent1_output=agent_a_output,
                agent2_output=getattr(session, "playbook_agent2_output", "") or "",
                agent3_output=cd_result["agent_c_playbook"],
                agent4_output="",
                agent5_output=agent_e_output,
                latencies={"agent_c": cd_result["agent_c_latency_ms"]},
            )

            await _send({
                "type": "done",
                "playbook": cd_result["agent_c_playbook"],
                "website_audit": agent_e_output,
                "context_brief": agent_a_output,
                "icp_card": getattr(session, "playbook_agent2_output", "") or "",
            })

            logger.info(
                "Playbook stream completed",
                session_id=body.session_id,
                latency_ms=cd_result["agent_c_latency_ms"],
            )

        except Exception as exc:
            logger.error(
                "Playbook stream failed",
                session_id=body.session_id,
                error=str(exc),
                traceback=traceback.format_exc(),
            )
            await _send({"type": "error", "message": str(exc)})
        finally:
            await queue.put(None)  # sentinel — close the stream

    async def event_generator():
        asyncio.create_task(_run())
        while True:
            item = await queue.get()
            if item is None:
                break
            yield item

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ── Helpers ────────────────────────────────────────────────────

def _build_recommended_tools_context(session) -> str:
    """
    Build TOON-style tabular tool list from session's recommended tools.
    ~50% fewer tokens vs the old verbose multi-line format.

    Output example:
      TOOLS[3]{name|type|price|desc|why|solves|ease}:
      HubSpot CRM|company|Free|CRM for pipeline|Early B2B traction|No lead tracking|30-min setup
      Apollo.io|company|Paid|Lead prospecting|Outbound goal match|Manual research slow|Chrome ext
    """
    all_tools = [
        *(session.early_recommendations or []),
        *(session.recommended_extensions or []),
        *(session.recommended_gpts or []),
        *(session.recommended_companies or []),
    ]
    return build_tools_toon(all_tools)


def _extract_icp_section(agent_a_output: str) -> str:
    """
    Extract the ICP CARD portion from the merged Agent A output.
    Returns just the ICP section (from '## ICP CARD' to '---' or end).
    """
    match = re.search(r'(## ICP CARD.*?)(?:\n---\n|\Z)', agent_a_output, re.DOTALL)
    if match:
        return match.group(1).strip()
    return ""


def _detect_gap_questions(agent2_output: str) -> bool:
    """
    Detect gap questions only if we can actually parse structured Q1/Q2/Q3 blocks.
    This prevents false positives from phrases like 'before the gap questions'.
    """
    return len(_parse_gap_questions(agent2_output)) > 0


def _parse_gap_questions(agent2_output: str) -> list[dict[str, Any]]:
    """
    Parse Agent A's gap questions into structured list with options.
    Line-by-line parser — handles bold markers, dash variants, inline question text.
    """
    # Q header line: Q1 — Label: question  OR  **Q1** — **Label:** question
    q_header_re = re.compile(
        r'^\*{0,2}Q(\d+)\*{0,2}\s*(?:[—–\-]\s*)?(.+?):\s*(.*)$'
    )
    opt_re = re.compile(r'^([A-E])\)\s*(.+)')

    parsed = []
    current: dict | None = None
    body_lines: list[str] = []

    # Inline option pattern: "- A) text" or "A) text" mid-line
    inline_opt_split_re = re.compile(r'\s*-?\s*([A-E]\)\s*.+?)(?=\s+-?\s*[A-E]\)|$)')

    def _flush(q: dict, lines: list[str]) -> None:
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
        # Join all question text
        question_text = ' '.join(question_parts) if question_parts else q['label']
        # If no separate-line options found, try extracting inline options
        # e.g. "Which platform? - A) Instagram - B) YouTube - C) WhatsApp - D) Other"
        if not options and question_text:
            # Check for inline options pattern: "- A) ..." or just "A) ..."
            inline_match = re.search(r'[-–]\s*A\)\s', question_text)
            if not inline_match:
                inline_match = re.search(r'\bA\)\s', question_text)
            if inline_match:
                q_part = question_text[:inline_match.start()].strip().rstrip('-–').strip()
                opt_part = question_text[inline_match.start():]
                # Split into individual options
                found_opts = inline_opt_split_re.findall(opt_part)
                if found_opts and len(found_opts) >= 2:
                    question_text = q_part
                    options = [o.strip().lstrip('- ').strip() for o in found_opts]
        if question_text and question_text != q['id']:
            parsed.append({
                "id": q['id'],
                "label": q['label'],
                "question": question_text,
                "options": options,
            })

    for raw_line in agent2_output.splitlines():
        line = raw_line.strip()
        m = q_header_re.match(line)
        if m:
            if current is not None:
                _flush(current, body_lines)
            q_num   = m.group(1)
            label   = re.sub(r'\*+', '', m.group(2)).strip()   # strip ** bold
            inline  = re.sub(r'\*+', '', m.group(3)).strip()   # text after colon
            current = {'id': f'Q{q_num}', 'label': label}
            body_lines = [inline] if inline else []
        elif current is not None:
            body_lines.append(raw_line)

    if current is not None:
        _flush(current, body_lines)

    return parsed
