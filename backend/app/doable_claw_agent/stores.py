from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4
import traceback
from asyncpg import UniqueViolationError

from app.db import get_pool
from app.repositories import (
    agents_repository as agents_repo,
    conversations_repository as convs_repo,
    messages_repository as msgs_repo,
    skill_calls_repository as skill_repo,
    plan_runs_repository as plans_repo,
    token_usage_repository as token_repo,
    onboarding_repository as onboarding_repo,
    session_links_repository as session_links_repo,
)
from app.services import form_flow_service

DEFAULT_AGENT_ID = "research-orchestrator"

USD_TO_INR = 94.0
MODEL_PRICING_USD_PER_TOKEN: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15 / 1_000_000, 0.60 / 1_000_000),
    "gpt-4o": (5.0 / 1_000_000, 15.0 / 1_000_000),
    "claude-3-5-sonnet-20241022": (3.0 / 1_000_000, 15.0 / 1_000_000),
    "claude-3-7-sonnet-20250219": (3.0 / 1_000_000, 15.0 / 1_000_000),
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
            "business-scan", "scrape-bs4", "scrape-playwright", "scrape-googlebusiness",
            "platform-scout", "web-search", "platform-taxonomy", "classify-links",
            "instagram-sentiment", "youtube-sentiment", "playstore-sentiment",
            "quora-search", "find-platform-handles",
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


# ── Helpers ───────────────────────────────────────────────────────────────────

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _as_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        raw = value.strip()
        if raw:
            try:
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
            return json.loads(value)
        except Exception:
            return fallback
    return fallback


def _json_default(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else str(value)


def _json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, default=_json_default)
    except Exception as exc:
        try:
            print(
                "[doable_claw_agent.stores] json-dumps-failed",
                {"error": str(exc), "value_type": type(value).__name__, "traceback": traceback.format_exc()},
            )
        except Exception:
            pass
        raise


def _encode_token_usage_model(model: str, stage: str | None, provider: str | None) -> str:
    s = (stage or "").strip() or "unknown"
    p = (provider or "").strip() or "unknown"
    m = (model or "").strip() or "unknown"
    return f"{s}||{p}||{m}"


def _decode_token_usage_model(encoded: str) -> dict[str, str]:
    if "||" not in (encoded or ""):
        return {"stage": "unknown", "provider": "unknown", "model": (encoded or "").strip() or "unknown"}
    parts = (encoded or "").split("||", 2)
    if len(parts) != 3:
        return {"stage": "unknown", "provider": "unknown", "model": (encoded or "").strip() or "unknown"}
    return {"stage": parts[0].strip() or "unknown", "provider": parts[1].strip() or "unknown", "model": parts[2].strip() or "unknown"}


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


def _agent_from_row(r: Any) -> dict[str, Any]:
    return {
        "id": r["id"],
        "name": r["name"],
        "emoji": r["emoji"] or "🤖",
        "description": r["description"] or "",
        "allowedSkillIds": list(r["allowed_skill_ids"] or []),
        "skillSelectorContext": r["skill_selector_context"] or "",
        "finalOutputFormattingContext": r["final_output_formatting_context"] or "",
    }


def _message_from_row(row: Any) -> dict[str, Any]:
    payload = _to_obj(row["message"], {})
    msg: dict[str, Any] = {
        "role": "assistant" if row["role"] == "assistant" else "user",
        "content": row["content"] or "",
        "createdAt": row["created_at"],
    }
    if row["output_file"]:
        msg["outputFile"] = row["output_file"]
    if isinstance(payload, dict):
        for key in ("messageId", "formId", "journeyStep"):
            if isinstance(payload.get(key), str):
                msg[key] = payload[key]
        if isinstance(payload.get("options"), list):
            msg["options"] = [str(x) for x in payload["options"] if isinstance(x, str)]
        if isinstance(payload.get("allowCustomAnswer"), bool):
            msg["allowCustomAnswer"] = payload["allowCustomAnswer"]
        if isinstance(payload.get("journeySelections"), dict):
            msg["journeySelections"] = payload["journeySelections"]
        if isinstance(payload.get("skillsCount"), int):
            msg["skillsCount"] = payload["skillsCount"]
        if payload.get("kind") in ("plan", "final"):
            msg["kind"] = payload["kind"]
        if isinstance(payload.get("planId"), str):
            msg["planId"] = payload["planId"]
    return msg


# ── Agents ────────────────────────────────────────────────────────────────────

async def ensure_default_agents() -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        now = now_dt()
        for a in DEFAULT_AGENTS:
            await agents_repo.insert_ignore(
                conn, a["id"], a["name"], a["emoji"], a["description"],
                a["allowed_skill_ids"], a["skill_selector_context"],
                a["final_output_formatting_context"], now,
            )


async def list_agents() -> list[dict[str, Any]]:
    await ensure_default_agents()
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await agents_repo.find_all(conn)
    return [_agent_from_row(r) for r in rows]


async def get_agent(agent_id: str) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        r = await agents_repo.find_by_id(conn, agent_id)
    return _agent_from_row(r) if r else None


async def create_agent(payload: dict[str, Any]) -> dict[str, Any]:
    now = now_dt()
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            row = await agents_repo.insert_returning(
                conn, payload["id"], payload["name"],
                payload.get("emoji") or "🤖", payload.get("description") or "",
                payload.get("allowedSkillIds") or [],
                payload.get("skillSelectorContext") or "",
                payload.get("finalOutputFormattingContext") or "",
                now,
            )
    except UniqueViolationError as exc:
        raise ValueError("Agent with this id already exists") from exc
    assert row is not None
    return _agent_from_row(row)


async def update_agent(agent_id: str, patch: dict[str, Any]) -> dict[str, Any] | None:
    print("[update_agent] called", {"agent_id": agent_id, "patch_keys": sorted(list(patch.keys()))})
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await agents_repo.update_fields(conn, agent_id, patch, now_dt())
    if row is None:
        return await get_agent(agent_id)
    if not row:
        print("[update_agent] no row updated", {"agent_id": agent_id})
        return None
    print("[update_agent] success", {"agent_id": agent_id})
    return _agent_from_row(row)


async def delete_agent(agent_id: str) -> bool:
    if agent_id == DEFAULT_AGENT_ID:
        raise ValueError(f"Cannot delete the default agent '{DEFAULT_AGENT_ID}'")
    pool = get_pool()
    async with pool.acquire() as conn:
        await agents_repo.reassign_conversations_agent(conn, agent_id, DEFAULT_AGENT_ID)
        return await agents_repo.delete_by_id(conn, agent_id)


# ── Conversations ─────────────────────────────────────────────────────────────

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
    if not await get_agent(selected_agent):
        all_agents = await list_agents()
        selected_agent = all_agents[0]["id"] if all_agents else DEFAULT_AGENT_ID

    oid = (onboarding_id or "").strip() or None
    uid = (user_id or "").strip() or None

    pool = get_pool()
    async with pool.acquire() as conn:
        if uid:
            existing_row = await convs_repo.find_latest_by_user(conn, uid)
            if existing_row:
                return await get_conversation(str(existing_row["id"])) or {}
        elif oid:
            existing_row = await convs_repo.find_latest_by_onboarding(conn, oid)
            if existing_row:
                return await get_conversation(str(existing_row["id"])) or {}

    cid = str(uuid4())
    now = now_dt()
    async with pool.acquire() as conn:
        await convs_repo.insert(conn, cid, selected_agent, oid, uid, now)

    return {
        "id": cid, "agentId": selected_agent, "onboardingId": oid,
        "messages": [], "createdAt": now, "updatedAt": now,
        "lastStageOutputs": {}, "lastOutputFile": None,
    }


async def create_new_conversation(
    agent_id: str,
    *,
    onboarding_id: str | None = None,
    user_id: str | None = None,
) -> dict[str, Any]:
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
        await convs_repo.insert(conn, cid, selected_agent, oid, uid, now)

    return {
        "id": cid, "agentId": selected_agent, "onboardingId": oid,
        "messages": [], "createdAt": now, "updatedAt": now,
        "lastStageOutputs": {}, "lastOutputFile": None,
    }


async def get_conversation(conversation_id: str | None, include_messages: bool = True) -> dict[str, Any] | None:
    if not conversation_id:
        return None
    pool = get_pool()
    messages: list[Any] = []
    async with pool.acquire() as conn:
        conv = await convs_repo.find_by_id(conn, conversation_id)
        if not conv:
            return None
        if include_messages:
            messages = await msgs_repo.find_by_conversation(conn, conversation_id)

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


async def get_last_assistant_message(conversation_id: str) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await msgs_repo.get_last_assistant_message(conn, conversation_id)
    if not row:
        return None
    return _message_from_row(row)


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
            rows = await convs_repo.list_by_user(conn, uid)
        elif sid:
            rows = await convs_repo.list_by_session(conn, sid)
        else:
            rows = []

    out: list[dict[str, Any]] = []
    for r in rows:
        async with pool.acquire() as conn:
            count = await msgs_repo.count_by_conversation(conn, r["id"])
        out.append({
            "id": r["id"],
            "agentId": r["agent_id"] or DEFAULT_AGENT_ID,
            "onboardingId": r.get("onboarding_id"),
            "userId": r["user_id"],
            "title": r["title"] or "New conversation",
            "messageCount": count,
            "createdAt": r["created_at"],
            "updatedAt": r["updated_at"],
        })
    return out


async def delete_conversation(conversation_id: str) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        return await convs_repo.delete_by_id(conn, conversation_id)


# ── Messages ──────────────────────────────────────────────────────────────────

async def _get_active_form_id(conversation_id: str) -> str | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await msgs_repo.get_last_message(conn, conversation_id)
    if not row:
        return None
    payload = _to_obj(row["message"], {})
    if isinstance(payload, dict) and isinstance(payload.get("formId"), str):
        return str(payload["formId"])
    return None


async def _get_form_messages(conversation_id: str, form_id: str) -> list[dict[str, Any]]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await msgs_repo.find_by_form_id(conn, conversation_id, form_id)
    return [_message_from_row(r) for r in rows]


async def _insert_message(conversation_id: str, message: dict[str, Any]) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await msgs_repo.insert_atomic(
            conn, conversation_id,
            message["role"], message["content"],
            _as_datetime(message.get("createdAt")),
            message.get("outputFile"),
            _json_dumps(message),
        )
        await convs_repo.touch(conn, conversation_id, now_dt())


async def append_message(conversation_id: str, role: str, content: str, **extra: Any) -> str:
    message_id = str(extra.get("messageId") or uuid4())
    created_at_dt = _as_datetime(extra.get("createdAt"))
    created_at = created_at_dt.isoformat()
    provided_form_id = str(extra.get("formId") or "").strip() or None
    active_form_id = provided_form_id or await _get_active_form_id(conversation_id)
    if form_flow_service.should_start_form(
        conversation_id=conversation_id, role=role, content=content, active_form_id=active_form_id,
    ):
        active_form_id = form_flow_service.generate_form_id()

    message: dict[str, Any] = {
        "role": "assistant" if role == "assistant" else "user",
        "content": content, "createdAt": created_at, "messageId": message_id,
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
            title = await convs_repo.get_title(conn, conversation_id)
            if not title:
                await convs_repo.set_title(conn, conversation_id, content[:60])

    if active_form_id and form_flow_service.should_end_form(
        conversation_id=conversation_id, role=role, content=content, active_form_id=active_form_id,
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
    conversation_id: str, message_id: str, content: str,
    output_file: str | None = None, skills_count: int | None = None,
) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await msgs_repo.find_by_message_id(conn, conversation_id, message_id)
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
        await msgs_repo.update_content(
            conn, conversation_id, row["message_index"],
            content, output_file, _json_dumps(payload),
        )
        await convs_repo.touch(conn, conversation_id, now_dt())
    return True


async def update_message_meta(conversation_id: str, message_id: str, kind: str | None, plan_id: str | None) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await msgs_repo.find_by_message_id(conn, conversation_id, message_id)
        if not row:
            return False
        payload = _to_obj(row["message"], {})
        if not isinstance(payload, dict):
            payload = {}
        if kind in ("plan", "final"):
            payload["kind"] = kind
        if isinstance(plan_id, str):
            payload["planId"] = plan_id
        await msgs_repo.update_meta(conn, conversation_id, row["message_index"], _json_dumps(payload))
        await convs_repo.touch(conn, conversation_id, now_dt())
    return True


async def save_stage_outputs(conversation_id: str, stage_outputs: dict[str, str], output_file: str | None) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await convs_repo.update_stage_outputs(
            conn, conversation_id, _json_dumps(stage_outputs or {}), output_file, now_dt(),
        )


async def get_stage_outputs(conversation_id: str) -> dict[str, str]:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await convs_repo.get_stage_outputs(conn, conversation_id)
    if not row:
        return {}
    obj = _to_obj(row["last_stage_outputs"], {})
    if not isinstance(obj, dict):
        return {}
    return {str(k): str(v) for k, v in obj.items() if isinstance(v, str)}


# ── Skill Calls ───────────────────────────────────────────────────────────────

async def create_skill_call(
    conversation_id: str, message_id: str, skill_id: str,
    run_id: str, input_payload: dict[str, Any],
) -> str:
    pool = get_pool()
    async with pool.acquire() as conn:
        return await skill_repo.insert_returning_id(
            conn, conversation_id, message_id, skill_id, run_id,
            _json_dumps(input_payload or {}), now_dt(),
        )


async def reset_skill_call_for_retry(
    skill_call_id: str, run_id: str,
    input_payload: dict[str, Any], new_message_id: str,
) -> str:
    pool = get_pool()
    async with pool.acquire() as conn:
        await skill_repo.reset_for_retry(
            conn, int(skill_call_id), run_id, new_message_id, _json_dumps(input_payload or {}),
        )
    return skill_call_id


async def relink_skill_call_message(skill_call_id: str, new_message_id: str) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await skill_repo.relink_message(conn, int(skill_call_id), new_message_id)


async def fetch_skill_call_output(skill_call_id: str) -> list[dict[str, Any]]:
    pool = get_pool()
    async with pool.acquire() as conn:
        output = await skill_repo.get_output(conn, int(skill_call_id))
    if output is None:
        return []
    out = _to_obj(output, [])
    return out if isinstance(out, list) else []


async def push_skill_output(skill_call_id: str, entry: dict[str, Any]) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        output = await skill_repo.get_output(conn, int(skill_call_id))
        if output is None:
            return
        current = _to_obj(output, [])
        if not isinstance(current, list):
            current = []
        payload = dict(entry)
        payload.setdefault("at", now_iso())
        current.append(payload)
        await skill_repo.update_output(conn, int(skill_call_id), _json_dumps(current))


async def append_skill_streamed_text(skill_call_id: str, text_chunk: str) -> None:
    chunk = str(text_chunk or "")
    if not chunk:
        return
    pool = get_pool()
    async with pool.acquire() as conn:
        await skill_repo.append_streamed_text(conn, int(skill_call_id), chunk)


async def set_skill_call_result(skill_call_id: str, state: str, text: str | None, data: Any, error: str | None) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await skill_repo.get_timing_and_output(conn, int(skill_call_id))
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
                    output.append({
                        "type": "page", "url": str(item.get("url") or ""),
                        "raw": item.get("raw"), "text": str(item.get("text") or ""), "at": now_iso(),
                    })
                result_data = {k: v for k, v in data.items() if k != "_pageEntries"}
        if text is not None or result_data is not None:
            output.append({"type": "result", "summary": text, "text": text, "data": result_data, "at": now_iso()})

        started_at = row["started_at"] or now_dt()
        try:
            started_at_dt = datetime.fromisoformat(str(started_at))
            duration_ms = await skill_repo.compute_duration_ms(conn, started_at_dt)
        except Exception:
            duration_ms = None

        await skill_repo.update_result(
            conn, int(skill_call_id), state, error, now_dt(), duration_ms, _json_dumps(output),
        )


async def auto_timeout_stale_skill_calls(
    conn, *, message_id: str | None = None,
    user_id: str | None = None, skill_call_id: int | None = None,
) -> None:
    await skill_repo.auto_timeout_stale(
        conn, message_id=message_id, user_id=user_id, skill_call_id=skill_call_id,
    )


async def get_skill_calls_by_message_id_full(message_id: str) -> list[dict[str, Any]]:
    pool = get_pool()
    async with pool.acquire() as conn:
        await skill_repo.auto_timeout_stale(conn, message_id=message_id)
        rows = await skill_repo.find_by_message_id(conn, message_id)
    out: list[dict[str, Any]] = []
    for r in rows:
        output = _to_obj(r["output"], [])
        try:
            streamed_text = r["streamed_text"] or ""
        except Exception:
            streamed_text = ""
        out.append({
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
        })
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
        out.append({
            "id": c["id"], "skillId": c["skillId"],
            "status": "error" if c.get("state") == "error" else "ok",
            "input": _to_obj(c.get("input"), {}),
            "startedAt": c.get("startedAt"), "endedAt": c.get("endedAt"),
            "durationMs": c.get("durationMs") or 0,
            "rawText": streamed_text if streamed_text else result_text,
            "rawData": (last_result or {}).get("data") if isinstance(last_result, dict) else None,
            "error": c.get("error"),
        })
    return out


# ── Scrape cache ──────────────────────────────────────────────────────────────

def _normalize_url_for_match(url: str) -> str:
    return str(url or "").strip().lower().rstrip("/")


def _last_result_data_from_output(output: Any) -> Any:
    for entry in reversed(output if isinstance(output, list) else []):
        if isinstance(entry, dict) and entry.get("type") == "result":
            return entry.get("data")
    return None


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


async def find_latest_scrape_cache_by_url(url: str, *, limit: int = 250) -> dict[str, Any] | None:
    target = _normalize_url_for_match(url)
    if not target:
        return None
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await skill_repo.find_recent_playwright_done(conn, limit)
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
        return {"id": str(r["id"]), "data": data, "updatedAt": r["updated_at"]}
    return None


def _base_origin(url: str) -> str:
    from urllib.parse import urlparse
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


async def find_scraped_pages_for_base_url(base_url: str, *, limit_calls: int = 300) -> list[dict[str, Any]]:
    base = _base_origin(base_url)
    if not base:
        return []
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await skill_repo.find_recent_playwright_done(conn, limit_calls)
    seen: set[str] = set()
    pages: list[dict[str, Any]] = []
    for r in rows:
        in_obj = _to_obj(r["input"], {})
        args = in_obj.get("args") if isinstance(in_obj, dict) and isinstance(in_obj.get("args"), dict) else {}
        req_url = str(args.get("url") or "").strip()
        if req_url and not _normalize_url_for_match(req_url).startswith(_normalize_url_for_match(base)):
            continue
        for p in _extract_pages_from_output(_to_obj(r["output"], [])):
            page_url = _normalize_url_for_match(str(p.get("url") or ""))
            if not page_url or not page_url.startswith(_normalize_url_for_match(base)):
                continue
            if page_url in seen:
                continue
            seen.add(page_url)
            pages.append(p)
    return pages


# ── Plan Runs ─────────────────────────────────────────────────────────────────

async def create_plan_run(
    conversation_id: str, user_message_id: str, plan_message_id: str,
    plan_markdown: str, plan_json: dict[str, Any],
) -> dict[str, Any]:
    pid = str(uuid4())
    now = now_dt()
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await plans_repo.insert_returning(
            conn, pid, conversation_id, user_message_id, plan_message_id,
            plan_markdown, _json_dumps(plan_json), now,
        )
    assert row is not None
    return {
        "id": row["id"], "conversationId": row["conversation_id"],
        "userMessageId": row["user_message_id"], "planMessageId": row["plan_message_id"],
        "status": row["status"], "planMarkdown": row["plan_markdown"],
        "planJson": _to_obj(row["plan_json"], {"steps": []}),
        "createdAt": row["created_at"], "updatedAt": row["updated_at"],
    }


async def get_plan_run(plan_id: str) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await plans_repo.find_by_id(conn, plan_id)
    if not row:
        return None
    return {
        "id": row["id"], "conversationId": row["conversation_id"],
        "userMessageId": row["user_message_id"], "planMessageId": row["plan_message_id"],
        "executionMessageId": row.get("execution_message_id") if hasattr(row, "get") else None,
        "errorMessage": row.get("error_message") if hasattr(row, "get") else None,
        "status": row["status"], "planMarkdown": row["plan_markdown"],
        "planJson": _to_obj(row["plan_json"], {"steps": []}),
        "createdAt": row["created_at"], "updatedAt": row["updated_at"],
    }


async def claim_plan_run_for_execution(plan_id: str) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await plans_repo.claim_for_execution(conn, plan_id, now_dt())
    return row is not None


async def update_plan_run(plan_id: str, patch: dict[str, Any]) -> None:
    if "planJson" in patch:
        patch = dict(patch)
        patch["planJson"] = _json_dumps(patch["planJson"])
    pool = get_pool()
    async with pool.acquire() as conn:
        await plans_repo.update_fields(conn, plan_id, patch)


async def cleanup_stale_executing_plans() -> int:
    pool = get_pool()
    async with pool.acquire() as conn:
        await plans_repo.ensure_columns(conn)
        result = await plans_repo.cleanup_stale_executing(conn)
        try:
            return int(result.split()[-1]) if result else 0
        except Exception:
            return 0


async def mark_plan_as_interrupted(plan_id: str, error_message: str = "Process interrupted") -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await plans_repo.mark_as_interrupted(conn, plan_id, error_message)


# ── Token Usage ───────────────────────────────────────────────────────────────

async def save_token_usage(
    message_id: str, model: str, input_tokens: int, output_tokens: int,
    *, stage: str | None = None, provider: str | None = None, session_id: str | None = None,
) -> None:
    stage_name = (stage or "unknown").strip()
    provider_name = (provider or "unknown").strip()
    model_name = (model or "unknown").strip()
    encoded_model = _encode_token_usage_model(model_name, stage_name, provider_name)
    cost_usd, cost_inr = _compute_cost_usd_inr(model_name, input_tokens, output_tokens)

    pool = get_pool()
    async with pool.acquire() as conn:
        sid = (session_id or "").strip() or None
        conversation_id: str | None = None
        linked_user_id: str | None = None

        found = await msgs_repo.find_conversation_and_user_by_message_id(conn, message_id)
        if found:
            conversation_id = str(found.get("conversation_id") or "").strip() or None
            linked_user_id = str(found.get("user_id") or "").strip() or None

        if sid and not linked_user_id:
            user_id_val = await onboarding_repo.find_user_id(conn, sid)
            linked_user_id = str(user_id_val or "").strip() or None

        await token_repo.insert(
            conn, message_id, sid, conversation_id, linked_user_id,
            encoded_model, stage_name, provider_name, model_name,
            input_tokens, output_tokens, cost_usd, cost_inr,
        )


async def get_token_usage(message_id: str) -> dict[str, Any]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await token_repo.find_by_message_id(conn, message_id)
    entries = []
    for r in rows:
        decoded = _decode_token_usage_model(str(r["model"]))
        entries.append({
            "stage": str(r.get("stage") or decoded["stage"]),
            "provider": str(r.get("provider") or decoded["provider"]),
            "model": str(r.get("model_name") or decoded["model"]),
            "inputTokens": r["input_tokens"],
            "outputTokens": r["output_tokens"],
            "costUsd": float(r["cost_usd"]) if r.get("cost_usd") is not None else None,
            "costInr": float(r["cost_inr"]) if r.get("cost_inr") is not None else None,
            "createdAt": str(r["created_at"]),
        })
    return {
        "entries": entries,
        "totalInputTokens": sum(e["inputTokens"] for e in entries),
        "totalOutputTokens": sum(e["outputTokens"] for e in entries),
    }


# ── Session promotion ─────────────────────────────────────────────────────────

async def promote_session_conversations(session_id: str, user_id: str) -> dict[str, Any]:
    sid = (session_id or "").strip()
    uid = (user_id or "").strip()
    if not sid or not uid:
        return {"updatedConversations": 0}
    pool = get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            updated = await convs_repo.promote_session_to_user(conn, sid, uid)
            await session_links_repo.insert(conn, sid, uid)
    try:
        count = int((updated or "UPDATE 0").split()[-1])
    except Exception:
        count = 0
    return {"updatedConversations": count}