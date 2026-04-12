from __future__ import annotations

import json
from typing import Any

import structlog

from app.db import get_pool
from app.services.instant_tool_service import get_tools_for_q1_q2_q3
from app.services.playbook_service import build_tools_toon, run_single_prompt_stream
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


def _coerce_gap_answers_text(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            parts = [f"{k}-{v}" for k, v in parsed.items()]
            return ", ".join(parts)
    except Exception:
        pass
    return raw


@register_task_stream("playbook/onboarding-generate")
async def onboarding_playbook_generate_task(send, payload: dict[str, Any]) -> dict[str, Any]:
    """
    Single-prompt playbook generator.

    Uses one streaming LLM call with the prompt from prompts table (slug: "playbook").
    Output is split server-side by section delimiters into context_brief,
    website_audit, and playbook.

    Input payload:
      - onboarding_id: str (required)

    Emits:
      - stage events
      - token events (full stream including section delimiters)
      - done with { playbook, website_audit, context_brief, icp_card }
    """
    from app.repositories import onboarding_repository as onboarding_repo
    from app.repositories import playbook_runs_repository as playbook_repo
    from app.repositories import users_repository as users_repo

    onboarding_id = str(payload.get("onboarding_id") or payload.get("session_id") or "").strip()
    user_id = str(payload.get("user_id") or "").strip()
    playbook_run_id = None

    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            if not onboarding_id and user_id:
                row = await users_repo.find_by_id(conn, user_id)
                linked_sid = str(row.get("onboarding_session_id") or "").strip() if row else ""
                onboarding_id = linked_sid
            if not onboarding_id:
                raise ValueError("onboarding_id or linked user_id is required")

            onboarding = await onboarding_repo.find_for_playbook_generation(conn, onboarding_id)
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
            gap_answers = _coerce_gap_answers_text(onboarding.get("gap_answers"))
            web_summary = str(onboarding.get("web_summary") or "")

            onboarding_snapshot = json.dumps({
                "outcome": outcome,
                "domain": domain,
                "task": task,
                "website_url": website_url,
                "scale_answers": business_profile,
                "rca_qa": rca_qa,
                "rca_summary": rca_summary,
                "rca_handoff": rca_handoff,
                "gap_answers": gap_answers,
            })
            crawl_snapshot = json.dumps({"web_summary": web_summary})

            playbook_run = await playbook_repo.insert_running(
                conn, onboarding_id, user_id, onboarding_snapshot, crawl_snapshot
            )
            playbook_run_id = playbook_run.get("id")

            await onboarding_repo.set_playbook_generating(conn, onboarding_id, playbook_run_id)

        await send("stage", stage="generating", label="Writing your playbook...")

        tools_res = get_tools_for_q1_q2_q3(outcome=outcome, domain=domain, task=task, limit=10)
        if isinstance(tools_res, str):
            try:
                tools_res = json.loads(tools_res)
            except Exception:
                logger.warning("Tool lookup returned non-JSON string; falling back to empty tools")
                tools_res = {}

        if isinstance(tools_res, dict):
            raw_tools = tools_res.get("tools")
        elif isinstance(tools_res, list):
            raw_tools = tools_res
        else:
            raw_tools = []

        if not isinstance(raw_tools, list):
            raw_tools = []

        safe_tools = [t for t in raw_tools if isinstance(t, dict)]
        recommended_tools = build_tools_toon(safe_tools)

        async def _on_token(token: str) -> None:
            await send("token", token=token)

        result = await run_single_prompt_stream(
            outcome_label=_outcome_label(outcome),
            domain=domain,
            task=task,
            business_profile=business_profile,
            rca_history=rca_history,
            rca_summary=rca_summary,
            crawl_summary=web_summary,
            recommended_tools=recommended_tools,
            gap_answers=gap_answers,
            rca_handoff=rca_handoff,
            on_token=_on_token,
            onboarding_id=onboarding_id,
        )

        result_payload = {
            "playbook": result["playbook"],
            "website_audit": result["website_audit"],
            "context_brief": result["context_brief"],
            "icp_card": "",
        }

        latencies = {"single_prompt": result["latency_ms"]}

        async with pool.acquire() as conn:
            await playbook_repo.mark_complete(
                conn,
                run_id=playbook_run_id,
                context_brief=result_payload["context_brief"],
                icp_card=result_payload["icp_card"],
                playbook=result_payload["playbook"],
                website_audit=result_payload["website_audit"],
                latencies_json=json.dumps(latencies),
            )
            await onboarding_repo.set_playbook_complete(conn, onboarding_id)

        logger.info("playbook/onboarding-generate done", onboarding_id=onboarding_id, playbook_run_id=str(playbook_run_id))
        return result_payload

    except Exception as exc:
        error_message = str(exc)
        logger.error("playbook/onboarding-generate failed", onboarding_id=onboarding_id, error=error_message)
        try:
            async with pool.acquire() as conn:
                if playbook_run_id:
                    await playbook_repo.mark_error(conn, playbook_run_id, error_message)
                if onboarding_id:
                    await onboarding_repo.set_playbook_error(conn, onboarding_id, error_message)
        except Exception as db_err:
            logger.error("playbook/onboarding-generate error update failed", error=str(db_err))
        raise