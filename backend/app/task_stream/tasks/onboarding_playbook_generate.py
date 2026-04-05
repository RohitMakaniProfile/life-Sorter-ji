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


async def _load_crawl_snapshots(conn, *, crawl_run_id: Any, crawl_cache_key: str) -> tuple[dict[str, Any], dict[str, Any]]:
    crawl_summary: dict[str, Any] = {}
    crawl_raw: dict[str, Any] = {}
    try:
        row = None
        if crawl_run_id:
            row = await conn.fetchrow(
                """
                SELECT cc.crawl_summary, cc.crawl_raw
                FROM crawl_runs cr
                JOIN crawl_cache cc ON cc.id = cr.crawl_cache_id
                WHERE cr.id = $1
                """,
                crawl_run_id,
            )
        elif crawl_cache_key:
            row = await conn.fetchrow(
                """
                SELECT crawl_summary, crawl_raw
                FROM crawl_cache
                WHERE normalized_url = $1 AND crawler_version = 'v1'
                """,
                crawl_cache_key,
            )
        if row:
            for field, target in (("crawl_summary", "summary"), ("crawl_raw", "raw")):
                v = row.get(field)
                if isinstance(v, str):
                    vv = json.loads(v) if v else {}
                elif isinstance(v, dict):
                    vv = v
                else:
                    vv = {}
                if target == "summary":
                    crawl_summary = vv
                else:
                    crawl_raw = vv
    except Exception:
        crawl_summary, crawl_raw = {}, {}
    return crawl_summary, crawl_raw


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
                  crawl_run_id,
                  crawl_cache_key
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
            gap_answers = str(onboarding.get("gap_answers") or "")

            crawl_run_id = onboarding.get("crawl_run_id")
            crawl_cache_key = str(onboarding.get("crawl_cache_key") or "").strip()
            crawl_summary, crawl_raw = await _load_crawl_snapshots(conn, crawl_run_id=crawl_run_id, crawl_cache_key=crawl_cache_key)

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
                json.dumps({"crawl_summary": crawl_summary, "crawl_raw": crawl_raw}),
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
            crawl_summary=crawl_summary,
            gap_answers=gap_answers,
            rca_handoff=rca_handoff,
        )
        agent_e_task = run_agent_e_standalone(
            outcome_label=_outcome_label(outcome),
            domain=domain,
            task=task,
            business_profile=business_profile,
            rca_history=rca_history,
            crawl_summary=crawl_summary,
            crawl_raw=crawl_raw,
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

