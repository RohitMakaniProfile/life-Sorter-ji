from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4
import traceback
from urllib.parse import urlparse

from asyncpg import UniqueViolationError
from pypika import Order, Table, functions as fn
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter

from app.db import get_pool
from app.repositories.core_tables import (
    SQL_ADD_PLAN_RUN_ERROR_MESSAGE_COLUMN,
    SQL_ADD_PLAN_RUN_EXECUTION_MESSAGE_COLUMN,
    SQL_ADD_STREAMED_TEXT_COLUMN,
    SQL_ADVISORY_CONVERSATION_LOCK,
    SQL_APPEND_STREAMED_TEXT,
    SQL_CLAIM_PLAN_RUN_FOR_EXECUTION,
    SQL_CLEANUP_STALE_EXECUTING_PLANS,
    SQL_INSERT_AGENT,
    SQL_INSERT_AGENT_RETURNING,
    SQL_INSERT_MESSAGE,
    SQL_INSERT_PLAN_RUN_RETURNING,
    SQL_INSERT_SESSION_USER_LINK,
    SQL_INSERT_SKILL_CALL_RETURNING_ID,
    SQL_PROMOTE_SESSION_CONVERSATIONS,
    SQL_RELINK_SKILL_CALL_MESSAGE,
    SQL_RESET_SKILL_CALL_FOR_RETRY,
    SQL_SELECT_DURATION_MS_FROM_STARTED_AT,
    SQL_SELECT_FORM_MESSAGES,
    SQL_SELECT_MESSAGE_BY_MESSAGE_ID,
    SQL_SELECT_SKILL_OUTPUT_BY_ID,
    SQL_SELECT_SKILL_TIMING_AND_OUTPUT,
    SQL_UPDATE_MESSAGE_CONTENT,
    SQL_UPDATE_MESSAGE_META,
    SQL_UPDATE_SKILL_CALL_RESULT,
    SQL_UPDATE_STAGE_OUTPUTS,
)
from app.sql_builder import build_query
from app.services import form_flow_service


DEFAULT_AGENT_ID = "research-orchestrator"
agents_t = Table("agents")
conversations_t = Table("conversations")
messages_t = Table("messages")
skill_calls_t = Table("skill_calls")
plan_runs_t = Table("plan_runs")
token_usage_t = Table("token_usage")
onboarding_t = Table("onboarding")

USD_TO_INR = 94.0
MODEL_PRICING_USD_PER_TOKEN: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15 / 1_000_000, 0.60 / 1_000_000),
    "gpt-4o": (5.0 / 1_000_000, 15.0 / 1_000_000),
    "claude-3-5-sonnet-20241022": (3.0 / 1_000_000, 15.0 / 1_000_000),
    "claude-3-7-sonnet-20250219": (3.0 / 1_000_000, 15.0 / 1_000_000),
    # OpenRouter aliases seen in token_usage
    "claude-opus-4-6": (15.0 / 1_000_000, 75.0 / 1_000_000),
    "z-ai/glm-5": (0.30 / 1_000_000, 1.20 / 1_000_000),
}

DEFAULT_AGENTS = [
    {
        "id": "research-orchestrator",
        "name": "Business Research",
        "emoji": "🕵️",
        "description": "Agentic research using website scrapers, social and sentiment skills",
        "allowed_skill_ids": [
            "business-scan",
            "scrape-bs4",
            "scrape-playwright",
            "scrape-googlebusiness",
            "platform-scout",
            "web-search",
            "platform-taxonomy",
            "classify-links",
            "instagram-sentiment",
            "youtube-sentiment",
            "playstore-sentiment",
            "quora-search",
            "find-platform-handles",
        ],
        "skill_selector_context": "",
        "final_output_formatting_context": "",
    },
    {
        "id": "business_problem_identifier",
        "name": "Business Problem Identifier",
        "emoji": "🎯",
        "description": "Guided onboarding journey to identify your business problem and generate a personalised playbook",
        "allowed_skill_ids": [],
        "skill_selector_context": "",
        "final_output_formatting_context": "",
    },
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        raw = value.strip()
        if raw:
            try:
                # Support common ISO format variants (including trailing Z).
                return datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except Exception:
                pass
    return now_dt()


def _to_obj(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed
        except Exception:
            return fallback
    return fallback


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, default=_json_default)
    except Exception as exc:
        try:
            print(
                "[doable_claw_agent.stores] json-dumps-failed",
                {
                    "error": str(exc),
                    "value_type": type(value).__name__,
                    "traceback": traceback.format_exc(),
                },
            )
        except Exception:
            pass
        raise


async def ensure_default_agents() -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        now = now_dt()
        for a in DEFAULT_AGENTS:
            await conn.execute(
                SQL_INSERT_AGENT,
                a["id"],
                a["name"],
                a["emoji"],
                a["description"],
                a["allowed_skill_ids"],
                a["skill_selector_context"],
                a["final_output_formatting_context"],
                now,
                now,
            )


async def list_agents() -> list[dict[str, Any]]:
    await ensure_default_agents()
    pool = get_pool()
    async with pool.acquire() as conn:
        list_agents_q = build_query(
            PostgreSQLQuery.from_(agents_t).select("*").orderby(agents_t.updated_at, order=Order.desc)
        )
        rows = await conn.fetch(list_agents_q.sql, *list_agents_q.params)
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "id": r["id"],
                "name": r["name"],
                "emoji": r["emoji"] or "🤖",
                "description": r["description"] or "",
                "allowedSkillIds": list(r["allowed_skill_ids"] or []),
                "skillSelectorContext": r["skill_selector_context"] or "",
                "finalOutputFormattingContext": r["final_output_formatting_context"] or "",
            }
        )
    return out


async def get_agent(agent_id: str) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        get_agent_q = build_query(
            PostgreSQLQuery.from_(agents_t).select("*").where(agents_t.id == Parameter("%s")),
            [agent_id],
        )
        r = await conn.fetchrow(get_agent_q.sql, *get_agent_q.params)
    if not r:
        return None
    return {
        "id": r["id"],
        "name": r["name"],
        "emoji": r["emoji"] or "🤖",
        "description": r["description"] or "",
        "allowedSkillIds": list(r["allowed_skill_ids"] or []),
        "skillSelectorContext": r["skill_selector_context"] or "",
        "finalOutputFormattingContext": r["final_output_formatting_context"] or "",
    }


async def create_agent(payload: dict[str, Any]) -> dict[str, Any]:
    now = now_dt()
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                SQL_INSERT_AGENT_RETURNING,
                payload["id"],
                payload["name"],
                payload.get("emoji") or "🤖",
                payload.get("description") or "",
                payload.get("allowedSkillIds") or [],
                payload.get("skillSelectorContext") or "",
                payload.get("finalOutputFormattingContext") or "",
                now,
                now,
            )
    except UniqueViolationError as exc:
        raise ValueError("Agent with this id already exists") from exc

    assert row is not None
    return {
        "id": row["id"],
        "name": row["name"],
        "emoji": row["emoji"],
        "description": row["description"],
        "allowedSkillIds": list(row["allowed_skill_ids"] or []),
        "skillSelectorContext": row["skill_selector_context"] or "",
        "finalOutputFormattingContext": row["final_output_formatting_context"] or "",
    }


async def update_agent(agent_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    print("[update_agent] called", {"agent_id": agent_id, "patch_keys": sorted(list(patch.keys()))})

    fields: list[str] = []
    values: list[Any] = []

    mapping = {
        "name": "name",
        "emoji": "emoji",
        "description": "description",
        "allowedSkillIds": "allowed_skill_ids",
        "skillSelectorContext": "skill_selector_context",
        "finalOutputFormattingContext": "final_output_formatting_context",
    }

    for key, col in mapping.items():
        if key in patch:
            fields.append(f"{col} = ${len(values) + 1}")
            values.append(patch[key])

    if not fields:
        print("[update_agent] no mutable fields in patch", {"agent_id": agent_id})
        return await get_agent(agent_id)

    fields.append(f"updated_at = ${len(values) + 1}")
    values.append(now_dt())
    values.append(agent_id)

    query = f"UPDATE agents SET {', '.join(fields)} WHERE id = ${len(values)} RETURNING *"
    print(
        "[update_agent] executing update",
        {"agent_id": agent_id, "field_count": len(fields), "value_count": len(values), "query": query},
    )

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(query, *values)
    if not row:
        print("[update_agent] no row updated", {"agent_id": agent_id})
        return None
    print("[update_agent] success", {"agent_id": agent_id})
    return {
        "id": row["id"],
        "name": row["name"],
        "emoji": row["emoji"],
        "description": row["description"],
        "allowedSkillIds": list(row["allowed_skill_ids"] or []),
        "skillSelectorContext": row["skill_selector_context"] or "",
        "finalOutputFormattingContext": row["final_output_formatting_context"] or "",
    }


async def delete_agent(agent_id: str) -> bool:
    """
    Delete an agent. Conversations referencing this agent will be reassigned
    to the default agent (research-orchestrator) to avoid orphaned data.
    
    The default agent (research-orchestrator) cannot be deleted.
    """
    # Prevent deleting the default agent
    if agent_id == DEFAULT_AGENT_ID:
        raise ValueError(f"Cannot delete the default agent '{DEFAULT_AGENT_ID}'")
    
    pool = get_pool()
    async with pool.acquire() as conn:
        # First, reassign any conversations that reference this agent to the default agent
        reassign_q = build_query(
            PostgreSQLQuery.update(conversations_t)
            .set(conversations_t.agent_id, Parameter("%s"))
            .set(conversations_t.updated_at, fn.Now())
            .where(conversations_t.agent_id == Parameter("%s")),
            [DEFAULT_AGENT_ID, agent_id],
        )
        await conn.execute(reassign_q.sql, *reassign_q.params)
        # Now delete the agent
        delete_agent_q = build_query(
            PostgreSQLQuery.from_(agents_t).delete().where(agents_t.id == Parameter("%s")),
            [agent_id],
        )
        result = await conn.execute(delete_agent_q.sql, *delete_agent_q.params)
    return result.endswith("1")


async def get_or_create_conversation(
    conversation_id: str | None,
    agent_id: str | None = None,
    *,
    onboarding_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    existing = await get_conversation(conversation_id) if conversation_id else None
    if existing:
        return existing

    await ensure_default_agents()
    selected_agent = (agent_id or DEFAULT_AGENT_ID).strip() or DEFAULT_AGENT_ID
    a = await get_agent(selected_agent)
    if not a:
        all_agents = await list_agents()
        selected_agent = all_agents[0]["id"] if all_agents else DEFAULT_AGENT_ID

    oid = (onboarding_id or "").strip() or None
    uid = (user_id or "").strip() or None

    pool = get_pool()
    async with pool.acquire() as conn:
        if uid:
            existing_for_user_q = build_query(
                PostgreSQLQuery.from_(conversations_t)
                .select(conversations_t.id)
                .where(conversations_t.user_id == Parameter("%s"))
                .orderby(conversations_t.updated_at, order=Order.desc)
                .limit(1),
                [uid],
            )
            existing_for_user = await conn.fetchrow(existing_for_user_q.sql, *existing_for_user_q.params)
            if existing_for_user:
                return await get_conversation(str(existing_for_user["id"])) or {}
        elif oid:
            existing_for_onboarding_q = build_query(
                PostgreSQLQuery.from_(conversations_t)
                .select(conversations_t.id)
                .where(conversations_t.onboarding_id == Parameter("%s"))
                .where(conversations_t.user_id.isnull())
                .orderby(conversations_t.updated_at, order=Order.desc)
                .limit(1),
                [oid],
            )
            existing_for_onboarding = await conn.fetchrow(
                existing_for_onboarding_q.sql, *existing_for_onboarding_q.params
            )
            if existing_for_onboarding:
                return await get_conversation(str(existing_for_onboarding["id"])) or {}

    cid = str(uuid4())
    now = now_dt()
    async with pool.acquire() as conn:
        create_conversation_q = build_query(
            PostgreSQLQuery.into(conversations_t)
            .columns(
                conversations_t.id,
                conversations_t.agent_id,
                conversations_t.onboarding_id,
                conversations_t.user_id,
                conversations_t.created_at,
                conversations_t.updated_at,
            )
            .insert(
                Parameter("%s"),
                Parameter("%s"),
                Parameter("%s"),
                Parameter("%s"),
                Parameter("%s"),
                Parameter("%s"),
            ),
            [cid, selected_agent, oid, uid, now, now],
        )
        await conn.execute(create_conversation_q.sql, *create_conversation_q.params)

    return {
        "id": cid,
        "agentId": selected_agent,
        "onboardingId": oid,
        "messages": [],
        "createdAt": now,
        "updatedAt": now,
        "lastStageOutputs": {},
        "lastOutputFile": None,
    }


async def create_new_conversation(
    agent_id: str,
    *,
    onboarding_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
    """Always creates a brand-new conversation, never reuses an existing one."""
    selected_agent = (agent_id or "").strip()
    if not selected_agent:
        await ensure_default_agents()
        all_agents = await list_agents()
        selected_agent = all_agents[0]["id"] if all_agents else DEFAULT_AGENT_ID

    oid = (onboarding_id or "").strip() or None
    uid = (user_id or "").strip() or None
    cid = str(uuid4())
    now = now_dt()
    pool = get_pool()
    async with pool.acquire() as conn:
        create_conversation_q = build_query(
            PostgreSQLQuery.into(conversations_t)
            .columns(
                conversations_t.id,
                conversations_t.agent_id,
                conversations_t.onboarding_id,
                conversations_t.user_id,
                conversations_t.created_at,
                conversations_t.updated_at,
            )
            .insert(
                Parameter("%s"),
                Parameter("%s"),
                Parameter("%s"),
                Parameter("%s"),
                Parameter("%s"),
                Parameter("%s"),
            ),
            [cid, selected_agent, oid, uid, now, now],
        )
        await conn.execute(create_conversation_q.sql, *create_conversation_q.params)

    return {
        "id": cid,
        "agentId": selected_agent,
        "onboardingId": oid,
        "messages": [],
        "createdAt": now,
        "updatedAt": now,
        "lastStageOutputs": {},
        "lastOutputFile": None,
    }


def _message_from_row(row: Any) -> dict[str, Any]:
    payload = _to_obj(row["message"], {})
    msg = {
        "role": "assistant" if row["role"] == "assistant" else "user",
        "content": row["content"] or "",
        "createdAt": row["created_at"],
    }
    if row["output_file"]:
        msg["outputFile"] = row["output_file"]
    if isinstance(payload, dict):
        if isinstance(payload.get("messageId"), str):
            msg["messageId"] = payload["messageId"]
        if isinstance(payload.get("formId"), str):
            msg["formId"] = payload["formId"]
        if isinstance(payload.get("options"), list):
            msg["options"] = [str(x) for x in payload["options"] if isinstance(x, str)]
        if isinstance(payload.get("allowCustomAnswer"), bool):
            msg["allowCustomAnswer"] = payload["allowCustomAnswer"]
        if isinstance(payload.get("journeyStep"), str):
            msg["journeyStep"] = payload["journeyStep"]
        if isinstance(payload.get("journeySelections"), dict):
            msg["journeySelections"] = payload["journeySelections"]
        if isinstance(payload.get("skillsCount"), int):
            msg["skillsCount"] = payload["skillsCount"]
        if payload.get("kind") in ("plan", "final"):
            msg["kind"] = payload["kind"]
        if isinstance(payload.get("planId"), str):
            msg["planId"] = payload["planId"]
    return msg


async def get_conversation(conversation_id: str | None) -> dict[str, Any] | None:
    if not conversation_id:
        return None
    pool = get_pool()
    async with pool.acquire() as conn:
        conv_q = build_query(
            PostgreSQLQuery.from_(conversations_t).select("*").where(conversations_t.id == Parameter("%s")),
            [conversation_id],
        )
        conv = await conn.fetchrow(conv_q.sql, *conv_q.params)
        if not conv:
            return None
        messages_q = build_query(
            PostgreSQLQuery.from_(messages_t)
            .select("*")
            .where(messages_t.conversation_id == Parameter("%s"))
            .orderby(messages_t.message_index, order=Order.asc),
            [conversation_id],
        )
        messages = await conn.fetch(messages_q.sql, *messages_q.params)

    stage_outputs = _to_obj(conv["last_stage_outputs"], {})
    stage_outputs = stage_outputs if isinstance(stage_outputs, dict) else {}

    return {
        "id": conv["id"],
        "agentId": conv["agent_id"] or DEFAULT_AGENT_ID,
        "onboardingId": conv.get("onboarding_id"),
        "userId": conv["user_id"],
        "title": conv["title"] or None,
        "messages": [_message_from_row(m) for m in messages],
        "lastStageOutputs": {str(k): str(v) for k, v in stage_outputs.items() if isinstance(v, str)},
        "lastOutputFile": conv["last_output_file"],
        "createdAt": conv["created_at"],
        "updatedAt": conv["updated_at"],
    }


async def _insert_message(conversation_id: str, message: dict[str, Any]) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Keep raw SQL: advisory lock helper uses Postgres-specific hashtext/pg_advisory_xact_lock.
            await conn.execute(SQL_ADVISORY_CONVERSATION_LOCK, conversation_id)
            next_index_q = build_query(
                PostgreSQLQuery.from_(messages_t)
                .select(fn.Coalesce(fn.Max(messages_t.message_index), -1) + 1)
                .where(messages_t.conversation_id == Parameter("%s")),
                [conversation_id],
            )
            next_index = await conn.fetchval(next_index_q.sql, *next_index_q.params)
            await conn.execute(
                SQL_INSERT_MESSAGE,
                conversation_id,
                int(next_index),
                message["role"],
                message["content"],
                _as_datetime(message.get("createdAt")),
                message.get("outputFile"),
                _json_dumps(message),
            )
            touch_conversation_q = build_query(
                PostgreSQLQuery.update(conversations_t)
                .set(conversations_t.updated_at, Parameter("%s"))
                .where(conversations_t.id == Parameter("%s")),
                [now_dt(), conversation_id],
            )
            await conn.execute(touch_conversation_q.sql, *touch_conversation_q.params)


async def _get_active_form_id(conversation_id: str) -> str | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        active_form_q = build_query(
            PostgreSQLQuery.from_(messages_t)
            .select(messages_t.message)
            .where(messages_t.conversation_id == Parameter("%s"))
            .orderby(messages_t.message_index, order=Order.desc)
            .limit(1),
            [conversation_id],
        )
        row = await conn.fetchrow(active_form_q.sql, *active_form_q.params)
    if not row:
        return None
    payload = _to_obj(row["message"], {})
    if isinstance(payload, dict) and isinstance(payload.get("formId"), str):
        return str(payload["formId"])
    return None


async def _get_form_messages(conversation_id: str, form_id: str) -> list[dict[str, Any]]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(SQL_SELECT_FORM_MESSAGES, conversation_id, form_id)
    return [_message_from_row(r) for r in rows]


async def append_message(conversation_id: str, role: str, content: str, **extra: Any) -> str:
    message_id = str(extra.get("messageId") or uuid4())
    created_at_dt = _as_datetime(extra.get("createdAt"))
    created_at = created_at_dt.isoformat()
    provided_form_id = str(extra.get("formId") or "").strip() or None
    active_form_id = provided_form_id or await _get_active_form_id(conversation_id)
    if form_flow_service.should_start_form(
        conversation_id=conversation_id,
        role=role,
        content=content,
        active_form_id=active_form_id,
    ):
        active_form_id = form_flow_service.generate_form_id()

    message = {
        "role": "assistant" if role == "assistant" else "user",
        "content": content,
        "createdAt": created_at,
        "messageId": message_id,
    }
    if extra.get("outputFile"):
        message["outputFile"] = extra["outputFile"]
    if isinstance(extra.get("skillsCount"), int):
        message["skillsCount"] = extra["skillsCount"]
    if isinstance(extra.get("options"), list):
        message["options"] = [str(x) for x in extra["options"] if isinstance(x, str)]
    if isinstance(extra.get("allowCustomAnswer"), bool):
        message["allowCustomAnswer"] = extra["allowCustomAnswer"]
    if isinstance(extra.get("journeyStep"), str):
        message["journeyStep"] = extra["journeyStep"]
    if isinstance(extra.get("journeySelections"), dict):
        message["journeySelections"] = extra["journeySelections"]
    if extra.get("kind") in ("plan", "final"):
        message["kind"] = extra["kind"]
    if isinstance(extra.get("planId"), str):
        message["planId"] = extra["planId"]
    if active_form_id:
        message["formId"] = active_form_id

    await _insert_message(conversation_id, message)

    if role == "user":
        pool = get_pool()
        async with pool.acquire() as conn:
            title_q = build_query(
                PostgreSQLQuery.from_(conversations_t)
                .select(conversations_t.title)
                .where(conversations_t.id == Parameter("%s")),
                [conversation_id],
            )
            title = await conn.fetchval(title_q.sql, *title_q.params)
            if not title:
                update_title_q = build_query(
                    PostgreSQLQuery.update(conversations_t)
                    .set(conversations_t.title, Parameter("%s"))
                    .where(conversations_t.id == Parameter("%s")),
                    [content[:60], conversation_id],
                )
                await conn.execute(update_title_q.sql, *update_title_q.params)

    if active_form_id and form_flow_service.should_end_form(
        conversation_id=conversation_id,
        role=role,
        content=content,
        active_form_id=active_form_id,
    ):
        form_messages = await _get_form_messages(conversation_id, active_form_id)
        await form_flow_service.process_completed_form(
            conversation_id=conversation_id,
            form_id=active_form_id,
            form_messages=form_messages,
        )

    return message_id


async def append_assistant_placeholder(conversation_id: str) -> str:
    return await append_message(conversation_id, "assistant", "")


async def update_message_content(
    conversation_id: str,
    message_id: str,
    content: str,
    output_file: str | None = None,
    skills_count: int | None = None,
) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(SQL_SELECT_MESSAGE_BY_MESSAGE_ID, conversation_id, message_id)
        if not row:
            return False

        payload = _to_obj(row["message"], {})
        if not isinstance(payload, dict):
            payload = {}
        payload["content"] = content
        if output_file is not None:
            payload["outputFile"] = output_file
        if skills_count is not None:
            payload["skillsCount"] = skills_count

        await conn.execute(
            SQL_UPDATE_MESSAGE_CONTENT,
            conversation_id,
            row["message_index"],
            content,
            output_file,
            _json_dumps(payload),
        )
        touch_conversation_q = build_query(
            PostgreSQLQuery.update(conversations_t)
            .set(conversations_t.updated_at, Parameter("%s"))
            .where(conversations_t.id == Parameter("%s")),
            [now_dt(), conversation_id],
        )
        await conn.execute(touch_conversation_q.sql, *touch_conversation_q.params)
    return True


async def update_message_meta(conversation_id: str, message_id: str, kind: str | None, plan_id: str | None) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(SQL_SELECT_MESSAGE_BY_MESSAGE_ID, conversation_id, message_id)
        if not row:
            return False
        payload = _to_obj(row["message"], {})
        if not isinstance(payload, dict):
            payload = {}
        if kind in ("plan", "final"):
            payload["kind"] = kind
        if isinstance(plan_id, str):
            payload["planId"] = plan_id

        await conn.execute(
            SQL_UPDATE_MESSAGE_META,
            conversation_id,
            row["message_index"],
            _json_dumps(payload),
        )
        touch_conversation_q = build_query(
            PostgreSQLQuery.update(conversations_t)
            .set(conversations_t.updated_at, Parameter("%s"))
            .where(conversations_t.id == Parameter("%s")),
            [now_dt(), conversation_id],
        )
        await conn.execute(touch_conversation_q.sql, *touch_conversation_q.params)
    return True


async def save_stage_outputs(conversation_id: str, stage_outputs: dict[str, str], output_file: str | None) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            SQL_UPDATE_STAGE_OUTPUTS,
            conversation_id,
            _json_dumps(stage_outputs or {}),
            output_file,
            now_dt(),
        )


async def get_stage_outputs(conversation_id: str) -> dict[str, str]:
    pool = get_pool()
    async with pool.acquire() as conn:
        stage_outputs_q = build_query(
            PostgreSQLQuery.from_(conversations_t)
            .select(conversations_t.last_stage_outputs)
            .where(conversations_t.id == Parameter("%s")),
            [conversation_id],
        )
        row = await conn.fetchrow(stage_outputs_q.sql, *stage_outputs_q.params)
    if not row:
        return {}
    obj = _to_obj(row["last_stage_outputs"], {})
    if not isinstance(obj, dict):
        return {}
    return {str(k): str(v) for k, v in obj.items() if isinstance(v, str)}


async def list_conversations(
    *,
    session_id: str | None = None,
    user_id: str | None = None,
) -> list[dict[str, Any]]:
    pool = get_pool()
    sid = (session_id or "").strip()
    uid = (user_id or "").strip()
    async with pool.acquire() as conn:
        if uid:
            conversations_q = build_query(
                PostgreSQLQuery.from_(conversations_t)
                .select("*")
                .where(conversations_t.user_id == Parameter("%s"))
                .orderby(conversations_t.updated_at, order=Order.desc),
                [uid],
            )
            rows = await conn.fetch(conversations_q.sql, *conversations_q.params)
        elif sid:
            # Keep equivalent predicate shape for behavior parity.
            conversations_q = build_query(
                PostgreSQLQuery.from_(conversations_t)
                .select("*")
                .where(
                    (conversations_t.onboarding_id == Parameter("%s"))
                    | ((conversations_t.onboarding_id == Parameter("%s")) & conversations_t.user_id.isnull())
                )
                .orderby(conversations_t.updated_at, order=Order.desc),
                [sid, sid],
            )
            rows = await conn.fetch(conversations_q.sql, *conversations_q.params)
        else:
            conversations_q = build_query(
                PostgreSQLQuery.from_(conversations_t).select("*").orderby(conversations_t.updated_at, order=Order.desc)
            )
            rows = await conn.fetch(conversations_q.sql, *conversations_q.params)
    out: list[dict[str, Any]] = []
    for r in rows:
        count = 0
        async with pool.acquire() as conn:
            message_count_q = build_query(
                PostgreSQLQuery.from_(messages_t)
                .select(fn.Count("*"))
                .where(messages_t.conversation_id == Parameter("%s")),
                [r["id"]],
            )
            count = int(await conn.fetchval(message_count_q.sql, *message_count_q.params))
        out.append(
            {
                "id": r["id"],
                "agentId": r["agent_id"] or DEFAULT_AGENT_ID,
                "onboardingId": r.get("onboarding_id"),
                "userId": r["user_id"],
                "title": r["title"] or "New conversation",
                "messageCount": count,
                "createdAt": r["created_at"],
                "updatedAt": r["updated_at"],
            }
        )
    return out


async def delete_conversation(conversation_id: str) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        delete_conversation_q = build_query(
            PostgreSQLQuery.from_(conversations_t).delete().where(conversations_t.id == Parameter("%s")),
            [conversation_id],
        )
        result = await conn.execute(delete_conversation_q.sql, *delete_conversation_q.params)
    return result.endswith("1")


async def create_skill_call(
    conversation_id: str,
    message_id: str,
    skill_id: str,
    run_id: str,
    input_payload: dict[str, Any],
) -> str:
    pool = get_pool()
    started_at = now_dt()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            SQL_INSERT_SKILL_CALL_RETURNING_ID,
            conversation_id,
            message_id,
            skill_id,
            run_id,
            _json_dumps(input_payload or {}),
            _json_dumps([]),
            started_at,
        )
    return str(row["id"])


async def reset_skill_call_for_retry(
    skill_call_id: str,
    run_id: str,
    input_payload: dict[str, Any],
    new_message_id: str,
) -> str:
    """
    Reset an existing skill_call row for re-execution instead of creating a new one.
    Clears state → 'running', wipes output/error/ended_at/duration_ms,
    refreshes started_at, updates input/run_id, and re-links to new_message_id
    so the frontend can find it by the retry execution message.
    Returns the same skill_call_id.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(SQL_RESET_SKILL_CALL_FOR_RETRY, int(skill_call_id), run_id, new_message_id, _json_dumps(input_payload or {}))
    return skill_call_id


async def relink_skill_call_message(skill_call_id: str, new_message_id: str) -> None:
    """Re-point an existing skill_call row to a different message_id (e.g. retry execution message)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(SQL_RELINK_SKILL_CALL_MESSAGE, int(skill_call_id), new_message_id)


async def fetch_skill_call_output(skill_call_id: str) -> list[dict[str, Any]]:
    """Return skill_calls.output JSON array for one row (for scrape resume / checkpoint)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(SQL_SELECT_SKILL_OUTPUT_BY_ID, int(skill_call_id))
    if not row:
        return []
    out = _to_obj(row["output"], [])
    return out if isinstance(out, list) else []


def _normalize_url_for_match(url: str) -> str:
    raw = str(url or "").strip().lower()
    if not raw:
        return ""
    return raw.rstrip("/")


def _last_result_data_from_output(output: Any) -> Any:
    rows = output if isinstance(output, list) else []
    for entry in reversed(rows):
        if isinstance(entry, dict) and entry.get("type") == "result":
            return entry.get("data")
    return None


async def find_latest_scrape_cache_by_url(url: str, *, limit: int = 250) -> dict[str, Any] | None:
    """
    Return latest done scrape-playwright call for the same normalized URL with result data.
    """
    target = _normalize_url_for_match(url)
    if not target:
        return None
    pool = get_pool()
    async with pool.acquire() as conn:
        scrape_cache_q = build_query(
            PostgreSQLQuery.from_(skill_calls_t)
            .select(skill_calls_t.id, skill_calls_t.input, skill_calls_t.output, skill_calls_t.updated_at)
            .where(skill_calls_t.skill_id == "scrape-playwright")
            .where(skill_calls_t.state == "done")
            .orderby(skill_calls_t.updated_at, order=Order.desc)
            .limit(int(max(1, limit))),
        )
        rows = await conn.fetch(scrape_cache_q.sql, *scrape_cache_q.params)
    for r in rows:
        in_obj = _to_obj(r["input"], {})
        args = in_obj.get("args") if isinstance(in_obj, dict) and isinstance(in_obj.get("args"), dict) else {}
        row_url = _normalize_url_for_match(str(args.get("url") or ""))
        if row_url != target:
            continue
        out = _to_obj(r["output"], [])
        data = _last_result_data_from_output(out)
        if data is None:
            continue
        return {
            "id": str(r["id"]),
            "data": data,
            "updatedAt": r["updated_at"],
        }
    return None


def _base_origin(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlparse(raw)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
    except Exception:
        pass
    return ""


def _extract_pages_from_output(output: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    rows = output if isinstance(output, list) else []
    for entry in rows:
        if not isinstance(entry, dict):
            continue
        if entry.get("type") == "page":
            raw = entry.get("raw")
            if isinstance(raw, dict) and raw.get("url"):
                out.append(raw)
    last_data = _last_result_data_from_output(rows)
    if isinstance(last_data, dict):
        pages = last_data.get("pages")
        if isinstance(pages, list):
            for p in pages:
                if isinstance(p, dict) and p.get("url"):
                    out.append(p)
    return out


async def find_scraped_pages_for_base_url(base_url: str, *, limit_calls: int = 300) -> list[dict[str, Any]]:
    """
    Return deduped page objects scraped under the same origin across prior done calls.
    """
    base = _base_origin(base_url)
    if not base:
        return []
    pool = get_pool()
    async with pool.acquire() as conn:
        scraped_pages_q = build_query(
            PostgreSQLQuery.from_(skill_calls_t)
            .select(skill_calls_t.input, skill_calls_t.output, skill_calls_t.updated_at)
            .where(skill_calls_t.skill_id == "scrape-playwright")
            .where(skill_calls_t.state == "done")
            .orderby(skill_calls_t.updated_at, order=Order.desc)
            .limit(int(max(1, limit_calls))),
        )
        rows = await conn.fetch(scraped_pages_q.sql, *scraped_pages_q.params)
    seen: set[str] = set()
    pages: list[dict[str, Any]] = []
    for r in rows:
        in_obj = _to_obj(r["input"], {})
        args = in_obj.get("args") if isinstance(in_obj, dict) and isinstance(in_obj.get("args"), dict) else {}
        req_url = str(args.get("url") or "").strip()
        if req_url and not _normalize_url_for_match(req_url).startswith(_normalize_url_for_match(base)):
            continue
        out_obj = _to_obj(r["output"], [])
        for p in _extract_pages_from_output(out_obj):
            page_url = _normalize_url_for_match(str(p.get("url") or ""))
            if not page_url:
                continue
            if not page_url.startswith(_normalize_url_for_match(base)):
                continue
            if page_url in seen:
                continue
            seen.add(page_url)
            pages.append(p)
    return pages


async def push_skill_output(skill_call_id: str, entry: dict[str, Any]) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        skill_output_q = build_query(
            PostgreSQLQuery.from_(skill_calls_t)
            .select(skill_calls_t.output)
            .where(skill_calls_t.id == Parameter("%s")),
            [int(skill_call_id)],
        )
        row = await conn.fetchrow(skill_output_q.sql, *skill_output_q.params)
        if not row:
            return
        output = _to_obj(row["output"], [])
        if not isinstance(output, list):
            output = []
        payload = dict(entry)
        payload.setdefault("at", now_iso())
        output.append(payload)
        update_skill_output_q = build_query(
            PostgreSQLQuery.update(skill_calls_t)
            .set(skill_calls_t.output, Parameter("%s"))
            .set(skill_calls_t.updated_at, fn.Now())
            .where(skill_calls_t.id == Parameter("%s")),
            [output, int(skill_call_id)],
        )
        await conn.execute(update_skill_output_q.sql, *update_skill_output_q.params)


async def append_skill_streamed_text(skill_call_id: str, text_chunk: str) -> None:
    chunk = str(text_chunk or "")
    if not chunk:
        return
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            await conn.execute(SQL_APPEND_STREAMED_TEXT, int(skill_call_id), chunk)
        except Exception:
            await conn.execute(SQL_ADD_STREAMED_TEXT_COLUMN)
            await conn.execute(SQL_APPEND_STREAMED_TEXT, int(skill_call_id), chunk)


async def set_skill_call_result(skill_call_id: str, state: str, text: str | None, data: Any, error: str | None) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(SQL_SELECT_SKILL_TIMING_AND_OUTPUT, int(skill_call_id))
        if not row:
            return
        output = _to_obj(row["output"], [])
        if not isinstance(output, list):
            output = []
        result_data = data
        if isinstance(data, dict):
            page_entries = data.get("_pageEntries")
            if isinstance(page_entries, list):
                for item in page_entries:
                    if not isinstance(item, dict):
                        continue
                    output.append(
                        {
                            "type": "page",
                            "url": str(item.get("url") or ""),
                            "raw": item.get("raw"),
                            "text": str(item.get("text") or ""),
                            "at": now_iso(),
                        }
                    )
                result_data = {k: v for k, v in data.items() if k != "_pageEntries"}
        if text is not None or result_data is not None:
            output.append({"type": "result", "summary": text, "text": text, "data": result_data, "at": now_iso()})

        started_at = row["started_at"] or now_dt()
        try:
            started_at_dt = datetime.fromisoformat(str(started_at))
            duration_row = await conn.fetchrow(
                SQL_SELECT_DURATION_MS_FROM_STARTED_AT,
                started_at_dt,
            )
            duration_ms = int(duration_row["ms"]) if duration_row and duration_row["ms"] is not None else None
        except Exception:
            duration_ms = None

        await conn.execute(
            SQL_UPDATE_SKILL_CALL_RESULT,
            int(skill_call_id),
            state,
            error,
            now_dt(),
            duration_ms,
            _json_dumps(output),
        )


_SKILL_CALL_TIMEOUT_MINUTES = 5
_TIMEOUT_ERROR_MSG = f"Timed out: no updates received for over {_SKILL_CALL_TIMEOUT_MINUTES} minutes"

_AUTO_TIMEOUT_SQL = """
    UPDATE skill_calls
    SET state       = 'error',
        error       = '{msg}',
        ended_at    = NOW(),
        duration_ms = (EXTRACT(EPOCH FROM (NOW() - started_at)) * 1000)::integer,
        updated_at  = NOW()
    WHERE state = 'running'
      AND updated_at < NOW() - INTERVAL '{mins} minutes'
""".format(msg=_TIMEOUT_ERROR_MSG, mins=_SKILL_CALL_TIMEOUT_MINUTES)


async def auto_timeout_stale_skill_calls(
    conn,
    *,
    message_id: str | None = None,
    user_id: str | None = None,
    skill_call_id: int | None = None,
) -> None:
    """
    Transitions any 'running' skill call that hasn't been updated in the last
    SKILL_CALL_TIMEOUT_MINUTES minutes to state='error'.
    Scope: one of message_id, user_id, or skill_call_id must be supplied.
    """
    if skill_call_id is not None:
        await conn.execute(
            _AUTO_TIMEOUT_SQL + " AND id = $1",
            skill_call_id,
        )
    elif message_id:
        await conn.execute(
            _AUTO_TIMEOUT_SQL + " AND message_id = $1",
            message_id,
        )
    elif user_id:
        await conn.execute(
            _AUTO_TIMEOUT_SQL + " AND conversation_id IN (SELECT id FROM conversations WHERE user_id = $1)",
            user_id,
        )


async def get_skill_calls_by_message_id_full(message_id: str) -> list[dict[str, Any]]:
    pool = get_pool()
    async with pool.acquire() as conn:
        await auto_timeout_stale_skill_calls(conn, message_id=message_id)
        skill_calls_by_msg_q = build_query(
            PostgreSQLQuery.from_(skill_calls_t)
            .select("*")
            .where(skill_calls_t.message_id == Parameter("%s"))
            .orderby(skill_calls_t.created_at, order=Order.asc),
            [message_id],
        )
        rows = await conn.fetch(skill_calls_by_msg_q.sql, *skill_calls_by_msg_q.params)
    out: list[dict[str, Any]] = []
    for r in rows:
        output = _to_obj(r["output"], [])
        try:
            streamed_text = r["streamed_text"] or ""
        except Exception:
            streamed_text = ""
        out.append(
            {
                "id": str(r["id"]),
                "skillId": r["skill_id"],
                "runId": r["run_id"],
                "state": r["state"],
                "input": _to_obj(r["input"], {}),
                "output": output if isinstance(output, list) else [],
                "error": r["error"],
                "startedAt": r["started_at"],
                "endedAt": r["ended_at"],
                "durationMs": r["duration_ms"],
                "streamedText": streamed_text,
            }
        )
    return out


async def get_skill_calls_by_message_id(message_id: str) -> list[dict[str, Any]]:
    full = await get_skill_calls_by_message_id_full(message_id)
    out: list[dict[str, Any]] = []
    for c in full:
        last_result = None
        for e in reversed(c.get("output") or []):
            if isinstance(e, dict) and e.get("type") == "result":
                last_result = e
                break
        streamed_text = str(c.get("streamedText") or "").strip()
        result_text = (last_result or {}).get("text") if isinstance(last_result, dict) else ""
        out.append(
            {
                "id": c["id"],
                "skillId": c["skillId"],
                "status": "error" if c.get("state") == "error" else "ok",
                "input": _to_obj(c.get("input"), {}),
                "startedAt": c.get("startedAt"),
                "endedAt": c.get("endedAt"),
                "durationMs": c.get("durationMs") or 0,
                # Prefer per-page streamed NL text when available; fallback to final result text.
                "rawText": streamed_text if streamed_text else result_text,
                "rawData": (last_result or {}).get("data") if isinstance(last_result, dict) else None,
                "error": c.get("error"),
            }
        )
    return out


async def create_plan_run(
    conversation_id: str,
    user_message_id: str,
    plan_message_id: str,
    plan_markdown: str,
    plan_json: dict[str, Any],
) -> dict[str, Any]:
    pid = str(uuid4())
    now = now_dt()
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            SQL_INSERT_PLAN_RUN_RETURNING,
            pid,
            conversation_id,
            user_message_id,
            plan_message_id,
            plan_markdown,
            _json_dumps(plan_json),
            now,
            now,
        )
    assert row is not None
    return {
        "id": row["id"],
        "conversationId": row["conversation_id"],
        "userMessageId": row["user_message_id"],
        "planMessageId": row["plan_message_id"],
        "status": row["status"],
        "planMarkdown": row["plan_markdown"],
        "planJson": _to_obj(row["plan_json"], {"steps": []}),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


async def get_plan_run(plan_id: str) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        plan_run_q = build_query(
            PostgreSQLQuery.from_(plan_runs_t).select("*").where(plan_runs_t.id == Parameter("%s")),
            [plan_id],
        )
        row = await conn.fetchrow(plan_run_q.sql, *plan_run_q.params)
    if not row:
        return None
    return {
        "id": row["id"],
        "conversationId": row["conversation_id"],
        "userMessageId": row["user_message_id"],
        "planMessageId": row["plan_message_id"],
        "executionMessageId": row.get("execution_message_id") if hasattr(row, "get") else None,
        "errorMessage": row.get("error_message") if hasattr(row, "get") else None,
        "status": row["status"],
        "planMarkdown": row["plan_markdown"],
        "planJson": _to_obj(row["plan_json"], {"steps": []}),
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


async def claim_plan_run_for_execution(plan_id: str) -> bool:
    """Atomically move draft/approved → executing. Returns False if already started or invalid."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            SQL_CLAIM_PLAN_RUN_FOR_EXECUTION,
            plan_id,
            now_dt(),
        )
    return row is not None


async def update_plan_run(plan_id: str, patch: dict[str, Any]) -> None:
    fields: list[str] = []
    values: list[Any] = []
    if "status" in patch:
        fields.append(f"status = ${len(values) + 1}")
        values.append(patch["status"])
    if "planMarkdown" in patch:
        fields.append(f"plan_markdown = ${len(values) + 1}")
        values.append(patch["planMarkdown"])
    if "executionMessageId" in patch:
        fields.append(f"execution_message_id = ${len(values) + 1}")
        values.append(patch["executionMessageId"])
    if "planJson" in patch:
        fields.append(f"plan_json = ${len(values) + 1}::jsonb")
        values.append(_json_dumps(patch["planJson"]))
    if "errorMessage" in patch:
        fields.append(f"error_message = ${len(values) + 1}")
        values.append(patch["errorMessage"])

    fields.append(f"updated_at = ${len(values) + 1}")
    values.append(now_dt())
    values.append(plan_id)

    q = f"UPDATE plan_runs SET {', '.join(fields)} WHERE id = ${len(values)}"
    pool = get_pool()
    async with pool.acquire() as conn:
        if "executionMessageId" in patch:
            try:
                await conn.execute(SQL_ADD_PLAN_RUN_EXECUTION_MESSAGE_COLUMN)
            except Exception:
                pass
        if "errorMessage" in patch:
            try:
                await conn.execute(SQL_ADD_PLAN_RUN_ERROR_MESSAGE_COLUMN)
            except Exception:
                pass
        await conn.execute(q, *values)


def _encode_token_usage_model(model: str, stage: str | None, provider: str | None) -> str:
    s = (stage or "").strip() or "unknown"
    p = (provider or "").strip() or "unknown"
    m = (model or "").strip() or "unknown"
    return f"{s}||{p}||{m}"


def _decode_token_usage_model(encoded: str) -> dict[str, str]:
    if "||" not in (encoded or ""):
        m = (encoded or "").strip() or "unknown"
        return {"stage": "unknown", "provider": "unknown", "model": m}
    parts = (encoded or "").split("||", 2)
    if len(parts) != 3:
        m = (encoded or "").strip() or "unknown"
        return {"stage": "unknown", "provider": "unknown", "model": m}
    return {
        "stage": parts[0].strip() or "unknown",
        "provider": parts[1].strip() or "unknown",
        "model": parts[2].strip() or "unknown",
    }


def _pricing_for_model(model_name: str) -> tuple[float, float] | None:
    name = (model_name or "").strip().lower()
    if not name:
        return None
    if name in MODEL_PRICING_USD_PER_TOKEN:
        return MODEL_PRICING_USD_PER_TOKEN[name]
    for key, val in MODEL_PRICING_USD_PER_TOKEN.items():
        if key in name:
            return val
    return None


def _compute_cost_usd_inr(model_name: str, input_tokens: int, output_tokens: int) -> tuple[float | None, float | None]:
    pricing = _pricing_for_model(model_name)
    if not pricing:
        return None, None
    in_rate, out_rate = pricing
    usd = (max(0, int(input_tokens)) * in_rate) + (max(0, int(output_tokens)) * out_rate)
    return round(usd, 6), round(usd * USD_TO_INR, 2)


async def save_token_usage(
    message_id: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    *,
    stage: str | None = None,
    provider: str | None = None,
    session_id: str | None = None,
) -> None:
    pool = get_pool()
    decoded = _decode_token_usage_model(_encode_token_usage_model(model, stage, provider))
    stage_name = (stage or decoded["stage"] or "unknown").strip()
    provider_name = (provider or decoded["provider"] or "unknown").strip()
    model_name = (model or decoded["model"] or "unknown").strip()
    encoded_model = _encode_token_usage_model(model_name, stage_name, provider_name)
    cost_usd, cost_inr = _compute_cost_usd_inr(model_name, input_tokens, output_tokens)
    async with pool.acquire() as conn:
        sid = (session_id or "").strip() or None
        conversation_id: str | None = None
        linked_user_id: str | None = None

        link_q = build_query(
            PostgreSQLQuery.from_(messages_t)
            .join(conversations_t)
            .on(conversations_t.id == messages_t.conversation_id)
            .select(messages_t.conversation_id, conversations_t.user_id)
            .where(messages_t.message.get_text_value("messageId") == Parameter("%s"))
            .limit(1),
            [message_id],
        )
        found = await conn.fetchrow(link_q.sql, *link_q.params)
        if found:
            conversation_id = str(found.get("conversation_id") or "").strip() or None
            linked_user_id = str(found.get("user_id") or "").strip() or None

        if sid and not linked_user_id:
            onboarding_user_q = build_query(
                PostgreSQLQuery.from_(onboarding_t)
                .select(onboarding_t.user_id)
                .where(onboarding_t.id == Parameter("%s"))
                .limit(1),
                [sid],
            )
            onboarding_user = await conn.fetchval(onboarding_user_q.sql, *onboarding_user_q.params)
            linked_user_id = str(onboarding_user or "").strip() or None

        insert_token_usage_q = build_query(
            PostgreSQLQuery.into(token_usage_t)
            .columns(
                token_usage_t.message_id,
                token_usage_t.session_id,
                token_usage_t.conversation_id,
                token_usage_t.user_id,
                token_usage_t.model,
                token_usage_t.stage,
                token_usage_t.provider,
                token_usage_t.model_name,
                token_usage_t.input_tokens,
                token_usage_t.output_tokens,
                token_usage_t.cost_usd,
                token_usage_t.cost_inr,
            )
            .insert(
                Parameter("%s"),
                Parameter("%s"),
                Parameter("%s"),
                Parameter("%s"),
                Parameter("%s"),
                Parameter("%s"),
                Parameter("%s"),
                Parameter("%s"),
                Parameter("%s"),
                Parameter("%s"),
                Parameter("%s"),
            ),
            [
                message_id,
                sid,
                conversation_id,
                linked_user_id,
                encoded_model,
                stage_name,
                provider_name,
                model_name,
                input_tokens,
                output_tokens,
                cost_usd,
                cost_inr,
            ],
        )
        await conn.execute(insert_token_usage_q.sql, *insert_token_usage_q.params)


async def promote_session_conversations(session_id: str, user_id: str) -> dict[str, Any]:
    sid = (session_id or "").strip()
    uid = (user_id or "").strip()
    if not sid or not uid:
        return {"updatedConversations": 0}

    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Do not use `user_id = ''`: if user_id is UUID, Postgres coerces '' and raises
            # InvalidTextRepresentationError. Treat "unset" via text cast + NULLIF.
            updated = await conn.execute(SQL_PROMOTE_SESSION_CONVERSATIONS, sid, uid)
            await conn.execute(SQL_INSERT_SESSION_USER_LINK, sid, uid)
    try:
        count = int((updated or "UPDATE 0").split()[-1])
    except Exception:
        count = 0
    return {"updatedConversations": count}


async def get_token_usage(message_id: str) -> dict[str, Any]:
    pool = get_pool()
    async with pool.acquire() as conn:
        token_usage_q = build_query(
            PostgreSQLQuery.from_(token_usage_t)
            .select(
                token_usage_t.model,
                token_usage_t.stage,
                token_usage_t.provider,
                token_usage_t.model_name,
                token_usage_t.input_tokens,
                token_usage_t.output_tokens,
                token_usage_t.cost_usd,
                token_usage_t.cost_inr,
                token_usage_t.created_at,
            )
            .where(token_usage_t.message_id == Parameter("%s"))
            .orderby(token_usage_t.created_at, order=Order.asc),
            [message_id],
        )
        rows = await conn.fetch(token_usage_q.sql, *token_usage_q.params)
    entries = [
        (
            lambda decoded: {
                "stage": str(r.get("stage") or decoded["stage"]),
                "provider": str(r.get("provider") or decoded["provider"]),
                "model": str(r.get("model_name") or decoded["model"]),
                "inputTokens": r["input_tokens"],
                "outputTokens": r["output_tokens"],
                "costUsd": float(r["cost_usd"]) if r.get("cost_usd") is not None else None,
                "costInr": float(r["cost_inr"]) if r.get("cost_inr") is not None else None,
                "createdAt": str(r["created_at"]),
            }
        )(_decode_token_usage_model(str(r["model"])))
        for r in rows
    ]
    return {
        "entries": entries,
        "totalInputTokens": sum(e["inputTokens"] for e in entries),
        "totalOutputTokens": sum(e["outputTokens"] for e in entries),
    }


async def cleanup_stale_executing_plans() -> int:
    """
    Mark any 'executing' plans as 'interrupted' on backend startup.

    This handles the case where the backend was restarted while plans were
    running. The in-memory task references are lost, so we mark them as
    interrupted so the frontend can offer a retry option.

    Returns the number of plans that were cleaned up.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            await conn.execute(SQL_ADD_PLAN_RUN_ERROR_MESSAGE_COLUMN)
        except Exception:
            pass
        result = await conn.execute(SQL_CLEANUP_STALE_EXECUTING_PLANS)
        # Result format: "UPDATE N"
        count = int(result.split()[-1]) if result else 0
        return count


async def mark_plan_as_interrupted(plan_id: str, error_message: str = "Process interrupted") -> None:
    """Mark a specific plan as interrupted (e.g., when detecting a stale task)."""
    pool = get_pool()
    async with pool.acquire() as conn:
        mark_interrupted_q = build_query(
            PostgreSQLQuery.update(plan_runs_t)
            .set(plan_runs_t.status, "interrupted")
            .set(plan_runs_t.error_message, Parameter("%s"))
            .set(plan_runs_t.updated_at, fn.Now())
            .where(plan_runs_t.id == Parameter("%s"))
            .where(plan_runs_t.status == "executing"),
            [error_message, plan_id],
        )
        await conn.execute(mark_interrupted_q.sql, *mark_interrupted_q.params)
