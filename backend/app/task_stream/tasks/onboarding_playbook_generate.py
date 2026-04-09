from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog
from pypika import Table, functions as fn
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter

from app.db import get_pool
from app.sql_builder import build_query
from app.services.instant_tool_service import get_tools_for_q1_q2_q3
from app.services.playbook_service import build_tools_toon, run_agent_a_merged, run_agent_c_stream, run_agent_e_standalone
from app.task_stream.registry import register_task_stream

logger = structlog.get_logger()
users_t = Table("users")
onboarding_t = Table("onboarding")
playbook_runs_t = Table("playbook_runs")


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



@register_task_stream("playbook/onboarding-generate")
async def onboarding_playbook_generate_task(send, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Onboarding-native playbook generator.

    Input payload:
      - onboarding_id: str (required)

    Emits:
      - stage events
      - token events from Agent C
      - done with { playbook, website_audit, context_brief, icp_card }
    """
    onboarding_id = str(payload.get("onboarding_id") or payload.get("session_id") or "").strip()
    user_id = str(payload.get("user_id") or "").strip()
    playbook_run_id = None

    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            if not onboarding_id and user_id:
                linked_sid_q = build_query(
                    PostgreSQLQuery.from_(users_t)
                    .select(users_t.onboarding_session_id)
                    .where(users_t.id.cast("TEXT") == Parameter("%s"))
                    .limit(1),
                    [user_id],
                )
                linked_sid = await conn.fetchval(linked_sid_q.sql, *linked_sid_q.params)
                onboarding_id = str(linked_sid or "").strip()
            if not onboarding_id:
                raise ValueError("onboarding_id or linked user_id is required for playbook/onboarding-generate")

            onboarding_q = build_query(
                PostgreSQLQuery.from_(onboarding_t)
                .select(
                    onboarding_t.id,
                    onboarding_t.user_id,
                    onboarding_t.outcome,
                    onboarding_t.domain,
                    onboarding_t.task,
                    onboarding_t.website_url,
                    onboarding_t.scale_answers,
                    onboarding_t.rca_qa,
                    onboarding_t.rca_summary,
                    onboarding_t.rca_handoff,
                    onboarding_t.gap_answers,
                    onboarding_t.web_summary,
                )
                .where(onboarding_t.id.cast("TEXT") == Parameter("%s"))
                .limit(1),
                [onboarding_id],
            )
            onboarding = await conn.fetchrow(onboarding_q.sql, *onboarding_q.params)
            if not onboarding:
                raise ValueError(f"Onboarding row not found for onboarding_id={onboarding_id}")

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

            web_summary = str(onboarding.get("web_summary") or "")

            # Create a playbook_runs row (running).
            onboarding_snapshot = json.dumps(
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
            )
            crawl_snapshot = json.dumps({"web_summary": web_summary})
            playbook_run_q = build_query(
                PostgreSQLQuery.into(playbook_runs_t)
                .columns(
                    playbook_runs_t.session_id,
                    playbook_runs_t.user_id,
                    playbook_runs_t.status,
                    playbook_runs_t.onboarding_snapshot,
                    playbook_runs_t.crawl_snapshot,
                )
                .insert(
                    Parameter("%s"),
                    Parameter("%s"),
                    "running",
                    Parameter("%s").cast("jsonb"),
                    Parameter("%s").cast("jsonb"),
                )
                .returning(playbook_runs_t.id),
                [onboarding_id, user_id, onboarding_snapshot, crawl_snapshot],
            )
            playbook_run = await conn.fetchrow(playbook_run_q.sql, *playbook_run_q.params)
            playbook_run_id = playbook_run.get("id")

            set_generating_q = build_query(
                PostgreSQLQuery.update(onboarding_t)
                .set(onboarding_t.playbook_status, "generating")
                .set(onboarding_t.playbook_run_id, Parameter("%s"))
                .set(onboarding_t.playbook_error, "")
                .set(onboarding_t.updated_at, fn.Now())
                .where(onboarding_t.id.cast("TEXT") == Parameter("%s")),
                [playbook_run_id, onboarding_id],
            )
            await conn.execute(set_generating_q.sql, *set_generating_q.params)

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
            set_complete_q = build_query(
                PostgreSQLQuery.update(playbook_runs_t)
                .set(playbook_runs_t.status, "complete")
                .set(playbook_runs_t.error, "")
                .set(playbook_runs_t.context_brief, Parameter("%s"))
                .set(playbook_runs_t.icp_card, Parameter("%s"))
                .set(playbook_runs_t.playbook, Parameter("%s"))
                .set(playbook_runs_t.website_audit, Parameter("%s"))
                .set(playbook_runs_t.latencies, Parameter("%s").cast("jsonb"))
                .where(playbook_runs_t.id == Parameter("%s")),
                [
                    result_payload["context_brief"],
                    result_payload["icp_card"],
                    result_payload["playbook"],
                    result_payload["website_audit"],
                    json.dumps(latencies),
                    playbook_run_id,
                ],
            )
            await conn.execute(set_complete_q.sql, *set_complete_q.params)
            set_onboarding_complete_q = build_query(
                PostgreSQLQuery.update(onboarding_t)
                .set(onboarding_t.playbook_status, "complete")
                .set(onboarding_t.playbook_completed_at, fn.Now())
                .set(onboarding_t.onboarding_completed_at, fn.Coalesce(onboarding_t.onboarding_completed_at, fn.Now()))
                .set(onboarding_t.updated_at, fn.Now())
                .where(onboarding_t.id.cast("TEXT") == Parameter("%s")),
                [onboarding_id],
            )
            await conn.execute(set_onboarding_complete_q.sql, *set_onboarding_complete_q.params)

        await asyncio.sleep(0)
        logger.info("playbook/onboarding-generate done", onboarding_id=onboarding_id, playbook_run_id=str(playbook_run_id))
        return result_payload

    except Exception as exc:
        # Update onboarding and playbook_runs to reflect error state
        error_message = str(exc)
        logger.error("playbook/onboarding-generate failed", onboarding_id=onboarding_id, error=error_message)
        try:
            async with pool.acquire() as conn:
                if playbook_run_id:
                    set_playbook_error_q = build_query(
                        PostgreSQLQuery.update(playbook_runs_t)
                        .set(playbook_runs_t.status, "error")
                        .set(playbook_runs_t.error, Parameter("%s"))
                        .where(playbook_runs_t.id == Parameter("%s")),
                        [error_message, playbook_run_id],
                    )
                    await conn.execute(set_playbook_error_q.sql, *set_playbook_error_q.params)
                if onboarding_id:
                    set_onboarding_error_q = build_query(
                        PostgreSQLQuery.update(onboarding_t)
                        .set(onboarding_t.playbook_status, "error")
                        .set(onboarding_t.playbook_error, Parameter("%s"))
                        .set(onboarding_t.updated_at, fn.Now())
                        .where(onboarding_t.id.cast("TEXT") == Parameter("%s")),
                        [error_message, onboarding_id],
                    )
                    await conn.execute(set_onboarding_error_q.sql, *set_onboarding_error_q.params)
        except Exception as db_err:
            logger.error("playbook/onboarding-generate error update failed", error=str(db_err))
        # Re-raise to let task stream service handle the error event
        raise
