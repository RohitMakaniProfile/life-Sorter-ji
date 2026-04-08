from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog

from app.db import get_pool
from app.services.instant_tool_service import get_tools_for_q1_q2_q3
from app.services.playbook_service import build_tools_toon, run_agent_a_merged, run_agent_c_stream, run_agent_e_standalone
from app.task_stream.registry import register_task_stream

logger = structlog.get_logger()


def _outcome_label(outcome_id: str) -> str:
    return {
        "lead-generation": "Lead Generation",
        "sales-retention": "Sales & Retention",
        "business-strategy": "Business Strategy",
        "save-time": "Save Time",
    }.get(outcome_id or "", "")


def _as_dict(v: Any) -> dict[str, Any]:
    if isinstance(v, str):
        try:
            vv = json.loads(v)
            return vv if isinstance(vv, dict) else {}
        except Exception:
            return {}
    return v if isinstance(v, dict) else {}


def _as_list(v: Any) -> list[dict[str, Any]]:
    if isinstance(v, str):
        try:
            vv = json.loads(v)
            return vv if isinstance(vv, list) else []
        except Exception:
            return []
    return v if isinstance(v, list) else []


def _coerce_gap_answers_text(raw: Any) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    try:
        parsed = json.loads(text)
    except Exception:
        return text
    if not isinstance(parsed, dict):
        return text
    rows: list[str] = []
    for idx in sorted(parsed.keys(), key=lambda x: int(x) if str(x).isdigit() else 10**9):
        v = parsed.get(idx)
        if not isinstance(v, dict):
            continue
        qid = str(v.get("question_id") or f"Q{int(idx) + 1 if str(idx).isdigit() else idx}").strip()
        answer_key = str(v.get("answer_key") or "").strip()
        answer_text = str(v.get("answer_text") or "").strip()
        if not answer_key:
            continue
        if answer_text:
            rows.append(f"{qid}-{answer_key}) {answer_text}")
        else:
            rows.append(f"{qid}-{answer_key}")
    return "\n".join(rows).strip()



@register_task_stream("playbook/onboarding-generate")
async def onboarding_playbook_generate_task(send, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Onboarding-native playbook generator.

    Input payload:
      - session_id: str (required)

    Emits:
      - stage events
      - token events from Agent C
      - done with { playbook, website_audit, context_brief, icp_card }
    """
    session_id = str(payload.get("session_id") or "").strip()
    user_id = str(payload.get("user_id") or "").strip()
    onboarding_id = None
    playbook_run_id = None

    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            if not session_id and user_id:
                linked_sid = await conn.fetchval(
                    "SELECT onboarding_session_id FROM users WHERE id::text = $1 LIMIT 1",
                    user_id,
                )
                session_id = str(linked_sid or "").strip()
            if not session_id:
                raise ValueError("session_id or linked user_id is required for playbook/onboarding-generate")

            onboarding = await conn.fetchrow(
                """
                SELECT
                  id, session_id, user_id,
                  outcome, domain, task,
                  website_url,
                  scale_answers, rca_qa, rca_summary, rca_handoff,
                  gap_answers,
                  web_summary
                FROM onboarding
                WHERE session_id = $1
                """,
                session_id,
            )
            if not onboarding:
                raise ValueError(f"Onboarding row not found for session_id={session_id}")

            onboarding_id = onboarding.get("id")
            user_id = onboarding.get("user_id")
            outcome = str(onboarding.get("outcome") or "")
            domain = str(onboarding.get("domain") or "")
            task = str(onboarding.get("task") or "")
            website_url = str(onboarding.get("website_url") or "")

            business_profile = _as_dict(onboarding.get("scale_answers"))
            rca_qa = _as_list(onboarding.get("rca_qa"))
            rca_history = [
                {"question": str(it.get("question") or ""), "answer": str(it.get("answer") or "")}
                for it in rca_qa
                if isinstance(it, dict) and it.get("answer") not in (None, "")
            ]
            rca_summary = str(onboarding.get("rca_summary") or "")
            rca_handoff = str(onboarding.get("rca_handoff") or "")
            gap_answers = _coerce_gap_answers_text(onboarding.get("gap_answers"))

            web_summary = str(onboarding.get("web_summary") or "")

            # Create a playbook_runs row (running).
            playbook_run = await conn.fetchrow(
                """
                INSERT INTO playbook_runs (session_id, user_id, status, onboarding_snapshot, crawl_snapshot)
                VALUES ($1, $2, 'running', $3::jsonb, $4::jsonb)
                RETURNING id
                """,
                session_id,
                user_id,
                json.dumps(
                    {
                        "outcome": outcome,
                        "domain": domain,
                        "task": task,
                        "website_url": website_url,
                        "scale_answers": business_profile,
                        "rca_qa": rca_qa,
                        "rca_summary": rca_summary,
                        "rca_handoff": rca_handoff,
                        "gap_answers": gap_answers,
                    }
                ),
                json.dumps({"web_summary": web_summary}),
            )
            playbook_run_id = playbook_run.get("id")

            await conn.execute(
                """
                UPDATE onboarding
                SET playbook_status = 'generating',
                    playbook_run_id = $1,
                    playbook_error = '',
                    updated_at = NOW()
                WHERE id = $2
                """,
                playbook_run_id,
                onboarding_id,
            )

        await send("stage", stage="generating", label="Writing your playbook...")

        tools_res = get_tools_for_q1_q2_q3(outcome=outcome, domain=domain, task=task, limit=10)
        recommended_tools = build_tools_toon((tools_res.get("tools") or []))

        # Run Agent A and Agent E in parallel (E is best-effort).
        agent_a_task = run_agent_a_merged(
            outcome_label=_outcome_label(outcome),
            domain=domain,
            task=task,
            business_profile=business_profile,
            rca_history=rca_history,
            rca_summary=rca_summary,
            crawl_summary=web_summary,
            gap_answers=gap_answers,
            rca_handoff=rca_handoff,
        )
        agent_e_task = run_agent_e_standalone(
            outcome_label=_outcome_label(outcome),
            domain=domain,
            task=task,
            business_profile=business_profile,
            rca_history=rca_history,
            crawl_summary=web_summary,
            crawl_raw={},
        )

        agent_a, agent_e = await asyncio.gather(agent_a_task, agent_e_task, return_exceptions=True)
        agent_a_output = "" if isinstance(agent_a, Exception) else (agent_a.get("output") or "")
        agent_e_output = "" if isinstance(agent_e, Exception) else (agent_e.get("output") or "")

        async def _on_token(token: str) -> None:
            await send("token", token=token)

        cd_result = await run_agent_c_stream(
            agent_a_output=agent_a_output,
            gap_answers=gap_answers,
            recommended_tools=recommended_tools,
            task=task,
            on_token=_on_token,
        )

        result_payload = {
            "playbook": cd_result.get("agent_c_playbook", ""),
            "website_audit": agent_e_output,
            "context_brief": agent_a_output,
            "icp_card": "",
        }

        latencies = {
            "agent_a": 0 if isinstance(agent_a, Exception) else int(agent_a.get("latency_ms") or 0),
            "agent_c": int(cd_result.get("agent_c_latency_ms") or 0),
            "agent_e": 0 if isinstance(agent_e, Exception) else int(agent_e.get("latency_ms") or 0),
        }

        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE playbook_runs
                SET status = 'complete',
                    error = '',
                    context_brief = $1,
                    icp_card = $2,
                    playbook = $3,
                    website_audit = $4,
                    latencies = $5::jsonb
                WHERE id = $6
                """,
                result_payload["context_brief"],
                result_payload["icp_card"],
                result_payload["playbook"],
                result_payload["website_audit"],
                json.dumps(latencies),
                playbook_run_id,
            )
            await conn.execute(
                """
                UPDATE onboarding
                SET playbook_status = 'complete',
                    playbook_completed_at = NOW(),
                    onboarding_completed_at = COALESCE(onboarding_completed_at, NOW()),
                    updated_at = NOW()
                WHERE session_id = $1
                """,
                session_id,
            )

        await asyncio.sleep(0)
        logger.info("playbook/onboarding-generate done", session_id=session_id, playbook_run_id=str(playbook_run_id))
        return result_payload

    except Exception as exc:
        # Update onboarding and playbook_runs to reflect error state
        error_message = str(exc)
        logger.error("playbook/onboarding-generate failed", session_id=session_id, error=error_message)
        try:
            async with pool.acquire() as conn:
                if playbook_run_id:
                    await conn.execute(
                        """
                        UPDATE playbook_runs
                        SET status = 'error',
                            error = $1
                        WHERE id = $2
                        """,
                        error_message,
                        playbook_run_id,
                    )
                if onboarding_id:
                    await conn.execute(
                        """
                        UPDATE onboarding
                        SET playbook_status = 'error',
                            playbook_error = $1,
                            updated_at = NOW()
                        WHERE id = $2
                        """,
                        error_message,
                        onboarding_id,
                    )
        except Exception as db_err:
            logger.error("playbook/onboarding-generate error update failed", error=str(db_err))
        # Re-raise to let task stream service handle the error event
        raise

