from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from pypika import Order, Table
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter

from app.db import get_pool
from app.doable_claw_agent.stores import (
    delete_conversation,
    get_or_create_conversation,
    get_skill_calls_by_message_id_full,
    get_token_usage,
    list_conversations,
    now_iso,
)
from app.sql_builder import build_query
from app.skills.service import list_skills

playbook_runs_t = Table("playbook_runs")
onboarding_t = Table("onboarding")


def _extract_company_name(website_url: str) -> str:
    raw = str(website_url or "").strip()
    if not raw:
        return ""
    candidate = raw if "://" in raw else f"https://{raw}"
    try:
        host = (urlparse(candidate).hostname or "").lower().strip(".")
    except Exception:
        return ""
    if not host:
        return ""
    if host.startswith("www."):
        host = host[4:]
    base = host.split(".")[0].replace("-", " ").replace("_", " ").strip()
    if not base:
        return ""
    return " ".join(part.capitalize() for part in base.split())


def _as_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return [x for x in parsed if isinstance(x, dict)] if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def _has_onboarding_markers(messages: list[dict[str, Any]]) -> bool:
    for msg in messages:
        step = str(msg.get("journeyStep") or "")
        mid = str(msg.get("messageId") or "")
        if step.startswith("onboarding_") or mid.startswith("onboarding:"):
            return True
    return False


async def _attach_onboarding_transcript(
    messages: list[dict[str, Any]],
    *,
    onboarding_session_id: str | None,
) -> list[dict[str, Any]]:
    sid = str(onboarding_session_id or "").strip()
    if not sid:
        return messages
    if _has_onboarding_markers(messages):
        return messages

    pool = get_pool()
    async with pool.acquire() as conn:
        row_q = build_query(
            PostgreSQLQuery.from_(onboarding_t)
            .select(
                onboarding_t.outcome,
                onboarding_t.domain,
                onboarding_t.task,
                onboarding_t.website_url,
                onboarding_t.gbp_url,
                onboarding_t.questions_answers,
            )
            .where(onboarding_t.id == Parameter("%s"))
            .limit(1),
            [sid],
        )
        row = await conn.fetchrow(row_q.sql, *row_q.params)

    if not row:
        return messages

    summary = {
        "role": "assistant",
        "content": "Onboarding selections and Q&A imported into this conversation.",
        "createdAt": now_iso(),
        "journeyStep": "onboarding_summary",
        "messageId": f"onboarding:summary:{sid}",
        "journeySelections": {
            "onboardingSessionId": sid,
            "outcome": str(row.get("outcome") or ""),
            "domain": str(row.get("domain") or ""),
            "task": str(row.get("task") or ""),
            "websiteUrl": str(row.get("website_url") or ""),
            "gbpUrl": str(row.get("gbp_url") or ""),
        },
    }
    onboarding_msgs: list[dict[str, Any]] = [summary]
    qa = _as_list(row.get("questions_answers"))
    for idx, item in enumerate(qa):
        q = str(item.get("question") or "").strip()
        a = str(item.get("answer") or "").strip()
        if q:
            onboarding_msgs.append(
                {
                    "role": "assistant",
                    "content": q,
                    "createdAt": now_iso(),
                    "journeyStep": "onboarding_question",
                    "messageId": f"onboarding:q:{sid}:{idx}",
                }
            )
        if a:
            onboarding_msgs.append(
                {
                    "role": "user",
                    "content": a,
                    "createdAt": now_iso(),
                    "journeyStep": "onboarding_answer",
                    "messageId": f"onboarding:a:{sid}:{idx}",
                }
            )
    return onboarding_msgs + messages


async def _attach_playbook_content(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Post-processor: if the last assistant message is the playbook placeholder
    (journeyStep == "playbook"), look up the completed playbook from
    playbook_runs and inject it as an additional assistant message.
    """
    if not messages:
        return messages

    # Find the playbook placeholder message (scan from end)
    playbook_msg_idx: int | None = None
    session_id: str = ""
    for i in range(len(messages) - 1, -1, -1):
        msg = messages[i]
        if (
            msg.get("role") == "assistant"
            and msg.get("journeyStep") == "playbook"
        ):
            selections = msg.get("journeySelections") or {}
            sid = str(selections.get("onboardingSessionId") or "").strip()
            if sid:
                playbook_msg_idx = i
                session_id = sid
            break

    if playbook_msg_idx is None or not session_id:
        return messages

    # Check if playbook content already exists as a subsequent message
    for j in range(playbook_msg_idx + 1, len(messages)):
        subsequent = messages[j]
        if (
            subsequent.get("role") == "assistant"
            and subsequent.get("journeyStep") == "playbook_content"
        ):
            # Already attached in a prior call or stored — nothing to do
            return messages

    # Look up completed playbook from playbook_runs
    pool = get_pool()
    async with pool.acquire() as conn:
        fetch_playbook_q = build_query(
            PostgreSQLQuery.from_(playbook_runs_t)
            .select(
                playbook_runs_t.playbook,
                playbook_runs_t.website_audit,
                playbook_runs_t.context_brief,
                playbook_runs_t.icp_card,
                playbook_runs_t.status,
            )
            .where(playbook_runs_t.session_id == Parameter("%s"))
            .orderby(playbook_runs_t.updated_at, order=Order.desc)
            .limit(1),
            [session_id],
        )
        row = await conn.fetchrow(fetch_playbook_q.sql, *fetch_playbook_q.params)

    if not row or row["status"] != "complete":
        return messages

    playbook_text = str(row["playbook"] or "").strip()
    if not playbook_text:
        return messages

    # Build the playbookData object matching the frontend PlaybookData interface
    playbook_data: dict[str, str] = {
        "playbook": playbook_text,
        "websiteAudit": str(row["website_audit"] or "").strip(),
        "contextBrief": str(row["context_brief"] or "").strip(),
        "icpCard": str(row["icp_card"] or "").strip(),
    }

    # Extract websiteUrl from the placeholder message's journeySelections
    placeholder_selections = messages[playbook_msg_idx].get("journeySelections") or {}
    website_url = str(placeholder_selections.get("websiteUrl") or "").strip()

    # Build cross-agent actions (e.g. "Do Deep Analysis" → research-orchestrator)
    cross_agent_actions: list[dict[str, str]] = []
    if website_url:
        cross_agent_actions.append({
            "label": "Do Deep Analysis",
            "icon": "🔬",
            "agentId": "research-orchestrator",
            "initialMessage": f"Do deep analysis of {website_url}",
        })

    # Inject the playbook as an additional assistant message right after the placeholder
    playbook_content_msg: dict[str, Any] = {
        "role": "assistant",
        "content": playbook_text,
        "createdAt": now_iso(),
        "journeyStep": "playbook_content",
        "playbookData": playbook_data,
    }
    if cross_agent_actions:
        playbook_content_msg["crossAgentActions"] = cross_agent_actions

    result = list(messages)
    result.insert(playbook_msg_idx + 1, playbook_content_msg)
    return result


async def get_messages(
    conversation_id: str | None = None,
    session_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    conv = await get_or_create_conversation(
        conversation_id,
        session_id=session_id,
        user_id=user_id,
    )
    messages = conv.get("messages") or []
    onboarding_sid = str(conv.get("onboardingSessionId") or session_id or "").strip() or None
    messages = await _attach_onboarding_transcript(messages, onboarding_session_id=onboarding_sid)
    messages = await _attach_playbook_content(messages)
    return {
        "messages": messages,
        "conversationId": conv["id"],
        "agentId": conv.get("agentId"),
        "lastStageOutputs": conv.get("lastStageOutputs") or {},
        "lastOutputFile": conv.get("lastOutputFile"),
    }


async def get_conversations(
    session_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    return {
        "conversations": await list_conversations(
            session_id=session_id,
            user_id=user_id,
        )
    }


async def get_playbook_history(
    session_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    sid = str(session_id or "").strip()
    uid = str(user_id or "").strip()

    pool = get_pool()
    async with pool.acquire() as conn:
        q = (
            PostgreSQLQuery.from_(playbook_runs_t)
            .select(
                playbook_runs_t.id,
                playbook_runs_t.session_id,
                playbook_runs_t.user_id,
                playbook_runs_t.status,
                playbook_runs_t.playbook,
                playbook_runs_t.onboarding_snapshot,
                playbook_runs_t.created_at,
                playbook_runs_t.updated_at,
            )
            .where(playbook_runs_t.status == "complete")
            .where(playbook_runs_t.playbook != "")
            .orderby(playbook_runs_t.updated_at, order=Order.desc)
            .limit(200)
        )

        params: list[Any] = []
        if uid:
            q = q.where(playbook_runs_t.user_id == Parameter("%s"))
            params.append(uid)
        elif sid:
            q = q.where(playbook_runs_t.session_id == Parameter("%s"))
            params.append(sid)

        built = build_query(q, params)
        rows = await conn.fetch(built.sql, *built.params)

    # One row per onboarding journey (`session_id` == onboarding.id): latest complete playbook only.
    seen_sessions: set[str] = set()
    items: list[dict[str, Any]] = []
    for row in rows:
        data = dict(row)
        run_session_id = str(data.get("session_id") or "").strip()
        if not run_session_id or run_session_id in seen_sessions:
            continue
        seen_sessions.add(run_session_id)

        snapshot = data.get("onboarding_snapshot")
        if isinstance(snapshot, str):
            try:
                snapshot = json.loads(snapshot)
            except Exception:
                snapshot = {}
        if not isinstance(snapshot, dict):
            snapshot = {}

        outcome = str(snapshot.get("outcome") or "").strip()
        domain = str(snapshot.get("domain") or "").strip()
        task = str(snapshot.get("task") or "").strip()
        website_url = str(snapshot.get("website_url") or "").strip()
        company_name = _extract_company_name(website_url)
        title = company_name or task or domain or outcome or "Generated playbook"

        items.append(
            {
                "runId": str(data.get("id") or ""),
                "sessionId": run_session_id,
                "title": title,
                "companyName": company_name,
                "outcome": outcome,
                "domain": domain,
                "task": task,
                "updatedAt": data.get("updated_at"),
                "createdAt": data.get("created_at"),
            }
        )

    return {"playbooks": items}


async def get_playbook_run_for_user(run_id: str, user_id: str) -> dict[str, Any] | None:
    """Return one completed playbook row if it belongs to the authenticated user."""
    rid = str(run_id or "").strip()
    uid = str(user_id or "").strip()
    if not rid or not uid:
        return None

    pool = get_pool()
    async with pool.acquire() as conn:
        row_q = build_query(
            PostgreSQLQuery.from_(playbook_runs_t)
            .select(
                playbook_runs_t.id,
                playbook_runs_t.session_id,
                playbook_runs_t.status,
                playbook_runs_t.playbook,
                playbook_runs_t.website_audit,
                playbook_runs_t.context_brief,
                playbook_runs_t.icp_card,
                playbook_runs_t.onboarding_snapshot,
            )
            .where(playbook_runs_t.id == Parameter("%s"))
            .where(playbook_runs_t.user_id == Parameter("%s"))
            .where(playbook_runs_t.status == "complete")
            .limit(1),
            [rid, uid],
        )
        row = await conn.fetchrow(row_q.sql, *row_q.params)

    if not row:
        return None

    data = dict(row)
    playbook_text = str(data.get("playbook") or "").strip()
    if not playbook_text:
        return None

    snapshot = data.get("onboarding_snapshot")
    if isinstance(snapshot, str):
        try:
            snapshot = json.loads(snapshot)
        except Exception:
            snapshot = {}
    if not isinstance(snapshot, dict):
        snapshot = {}

    outcome = str(snapshot.get("outcome") or "").strip()
    domain = str(snapshot.get("domain") or "").strip()
    task = str(snapshot.get("task") or "").strip()
    website_url = str(snapshot.get("website_url") or "").strip()
    title = task or domain or outcome or "Generated playbook"

    playbook_data: dict[str, str] = {
        "playbook": playbook_text,
        "websiteAudit": str(data.get("website_audit") or "").strip(),
        "contextBrief": str(data.get("context_brief") or "").strip(),
        "icpCard": str(data.get("icp_card") or "").strip(),
    }

    cross_agent_actions: list[dict[str, str]] = []
    if website_url:
        cross_agent_actions.append(
            {
                "label": "Do Deep Analysis",
                "icon": "🔬",
                "agentId": "research-orchestrator",
                "initialMessage": f"Do deep analysis of {website_url}",
            }
        )

    return {
        "runId": str(data.get("id") or ""),
        "sessionId": str(data.get("session_id") or ""),
        "title": title,
        "outcome": outcome,
        "domain": domain,
        "task": task,
        "playbookData": playbook_data,
        "crossAgentActions": cross_agent_actions,
    }


async def get_skills() -> list[dict[str, Any]]:
    return list_skills()


async def get_skill_calls(message_id: str | None) -> dict[str, Any]:
    if not message_id or not message_id.strip():
        raise ValueError("messageId is required")
    return {"skillCalls": await get_skill_calls_by_message_id_full(message_id.strip())}


async def get_token_usage_by_message(message_id: str | None) -> dict[str, Any]:
    if not message_id or not message_id.strip():
        raise ValueError("messageId is required")
    return await get_token_usage(message_id.strip())


async def delete_conversation_by_id(conversation_id: str) -> dict[str, bool]:
    return {"ok": await delete_conversation(conversation_id)}

