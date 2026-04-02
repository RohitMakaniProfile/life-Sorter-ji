from __future__ import annotations

import asyncio
import structlog
from typing import Any

from app.services import session_store
from app.services.playbook_service import build_tools_toon, run_agent_a_merged, run_agent_c_stream
from app.task_stream.registry import register_task_stream

logger = structlog.get_logger()


def _build_recommended_tools_context(session) -> str:
    """Mirror playbook router's toollist shaping (TOON format)."""
    all_tools = [
        *(session.early_recommendations or []),
        *(session.recommended_extensions or []),
        *(session.recommended_gpts or []),
        *(session.recommended_companies or []),
    ]
    return build_tools_toon(all_tools)


@register_task_stream("playbook/generate")
async def playbook_generate_task(send, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Background task for generating the full playbook pipeline.

    Emits:
    - stage: {stage="generating", label="..."}
    - token: {token="..."} word-by-word from Agent C
    - done: returned payload (wrapper emits SSE done)
    - error: wrapper emits on exception
    """
    session_id = str(payload.get("session_id") or "").strip()
    if not session_id:
        raise ValueError("session_id is required for playbook/generate")

    session = session_store.get_session(session_id)
    if not session:
        raise ValueError(f"Session not found in memory for {session_id}")

    # Ensure RCA completion flag is set for downstream agent prompts.
    if not getattr(session, "rca_complete", False):
        session_store.set_rca_complete(session_id, summary="")

    gap_answers = str(payload.get("gap_answers") or getattr(session, "playbook_gap_answers", "") or "")
    agent_a_output = getattr(session, "playbook_agent1_output", "") or ""

    # Re-run Agent A if missing (edge case).
    if not agent_a_output:
        agent_a_output = (await run_agent_a_merged(
            outcome_label=session.outcome_label or "",
            domain=session.domain or "",
            task=session.task or "",
            business_profile=session.business_profile or {},
            rca_history=session.rca_history or [],
            rca_summary=session.rca_summary or "",
            crawl_summary=session.crawl_summary or {},
            gap_answers=gap_answers,
            rca_handoff=getattr(session, "rca_handoff", "") or "",
        )).get("output") or ""

    recommended_tools = _build_recommended_tools_context(session)

    await send("stage", stage="generating", label="Writing your playbook...")

    async def _on_token(token: str) -> None:
        await send("token", token=token)

    cd_result = await run_agent_c_stream(
        agent_a_output=agent_a_output,
        gap_answers=gap_answers,
        recommended_tools=recommended_tools,
        task=getattr(session, "task", "") or "",
        on_token=_on_token,
    )

    agent_e_output = getattr(session, "playbook_agent5_output", "") or ""

    # Persist results in session store (and DB, if configured).
    session_store.set_playbook_results(
        session_id=session_id,
        agent1_output=agent_a_output,
        agent2_output=getattr(session, "playbook_agent2_output", "") or "",
        agent3_output=cd_result.get("agent_c_playbook", ""),
        agent4_output="",
        agent5_output=agent_e_output,
        latencies={"agent_c": cd_result.get("agent_c_latency_ms", 0)},
    )

    await asyncio.sleep(0)  # allow other awaiting send() calls to drain

    logger.info(
        "playbook/generate task done",
        session_id=session_id,
        latency_ms=cd_result.get("agent_c_latency_ms", 0),
    )

    return {
        "playbook": cd_result.get("agent_c_playbook", ""),
        "website_audit": agent_e_output,
        "context_brief": agent_a_output,
        "icp_card": getattr(session, "playbook_agent2_output", "") or "",
    }

