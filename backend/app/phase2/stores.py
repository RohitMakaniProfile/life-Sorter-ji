from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import uuid4
import traceback

from asyncpg import UniqueViolationError
from asyncpg.exceptions import UndefinedTableError

from .db import get_pool


DEFAULT_AGENT_ID = "research-orchestrator"


@lru_cache(maxsize=1)
def _load_default_phase2_contexts() -> dict[str, str]:
    """
    Keep default contexts in DB for newly-created system agents.
    (We only populate when the DB value is empty to avoid overwriting edits.)
    """
    cfg_dir = Path(__file__).resolve().parents[2] / "config"
    processing = cfg_dir / "phase2_processing.context.md"
    output = cfg_dir / "phase2_output.context.md"
    try:
        processing_text = processing.read_text(encoding="utf-8").strip()
    except Exception:
        processing_text = ""
    try:
        output_text = output.read_text(encoding="utf-8").strip()
    except Exception:
        output_text = ""
    return {"skillSelectorContext": processing_text, "finalOutputFormattingContext": output_text}

DEFAULT_AGENTS = [
    {
        "id": "research-orchestrator",
        "name": "Business Research",
        "emoji": "🕵️",
        "description": "Agentic research using website scrapers, social and sentiment skills",
        "is_locked": True,
        "visibility": "private",
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
        "id": "admin-shared-orchestrator",
        "name": "Admin Shared",
        "emoji": "🧩",
        "description": "Shared system agent; internal admins can edit, outside users can read/use",
        "is_locked": False,
        "visibility": "public",
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
    }
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
                "[phase2.stores] json-dumps-failed",
                {
                    "error": str(exc),
                    "value_type": type(value).__name__,
                    "traceback": traceback.format_exc(),
                },
            )
        except Exception:
            pass
        raise


async def _ensure_insight_feedback_table(conn) -> None:
    # Safe to run multiple times.
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS insight_feedback (
            id BIGSERIAL PRIMARY KEY,
            conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
            message_id TEXT NOT NULL,
            insight_index INTEGER NOT NULL,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            rating SMALLINT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (user_id, message_id, insight_index)
        )
        """
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_insight_feedback_message_id ON insight_feedback (message_id)"
    )
    await conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_insight_feedback_conversation_id ON insight_feedback (conversation_id)"
    )


async def ensure_default_agents() -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        now = now_dt()
        default_contexts = _load_default_phase2_contexts()
        for a in DEFAULT_AGENTS:
            await conn.execute(
                """
                INSERT INTO agents (
                    id, name, emoji, description,
                    allowed_skill_ids, skill_selector_context, final_output_formatting_context,
                    created_by_user_id, visibility, is_locked,
                    created_at, updated_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                ON CONFLICT (id) DO NOTHING
                """,
                a["id"],
                a["name"],
                a["emoji"],
                a["description"],
                a["allowed_skill_ids"],
                a["skill_selector_context"],
                a["final_output_formatting_context"],
                None,
                a.get("visibility") or "private",
                bool(a.get("is_locked")),
                now,
                now,
            )

        # For already-existing rows, ensure lock/visibility match the defaults.
        # We intentionally do NOT overwrite allowed skills/contexts.
        for a in DEFAULT_AGENTS:
            desired_is_locked = bool(a.get("is_locked"))
            desired_visibility = a.get("visibility") or "private"
            try:
                await conn.execute(
                    "UPDATE agents SET is_locked = $1, visibility = $2 WHERE id = $3",
                    desired_is_locked,
                    desired_visibility,
                    a["id"],
                )
            except Exception:
                # If schema isn't ready yet, or other transient issues, don't crash startup.
                pass

            # Populate default contexts for system agents if they are empty.
            # (Do not overwrite non-empty values, so admins can edit these.)
            try:
                await conn.execute(
                    """
                    UPDATE agents
                    SET
                      skill_selector_context = CASE
                        WHEN skill_selector_context IS NULL OR skill_selector_context = '' THEN $1
                        ELSE skill_selector_context
                      END,
                      final_output_formatting_context = CASE
                        WHEN final_output_formatting_context IS NULL OR final_output_formatting_context = '' THEN $2
                        ELSE final_output_formatting_context
                      END
                    WHERE id = $3
                    AND created_by_user_id IS NULL
                    """,
                    default_contexts["skillSelectorContext"],
                    default_contexts["finalOutputFormattingContext"],
                    a["id"],
                )
            except Exception:
                pass


async def list_agents(
    *,
    user_id: str | None = None,
    is_admin: bool = False,
) -> list[dict[str, Any]]:
    await ensure_default_agents()
    pool = get_pool()
    async with pool.acquire() as conn:
        if is_admin:
            rows = await conn.fetch("SELECT * FROM agents ORDER BY updated_at DESC")
        else:
            rows = await conn.fetch(
                """
                SELECT * FROM agents
                WHERE
                    is_locked = true
                    OR visibility = 'public'
                    OR created_by_user_id = $1::uuid
                    OR created_by_user_id IS NULL
                ORDER BY updated_at DESC
                """,
                user_id,
            )

    out: list[dict[str, Any]] = []
    for r in rows:
        is_locked = bool(r["is_locked"] or False)
        can_view_secrets = bool(is_admin or not is_locked)
        out.append(
            {
                "id": r["id"],
                "name": r["name"],
                "emoji": r["emoji"] or "🤖",
                "description": r["description"] or "",
                "isLocked": is_locked,
                "visibility": (r["visibility"] or "private"),
                "createdByUserId": (str(r["created_by_user_id"]) if r["created_by_user_id"] else None),
                "allowedSkillIds": list(r["allowed_skill_ids"] or []),
                "skillSelectorContext": r["skill_selector_context"] or "",
                "finalOutputFormattingContext": r["final_output_formatting_context"] or "",
            }
        )
        if not can_view_secrets:
            out[-1]["allowedSkillIds"] = []
            out[-1]["skillSelectorContext"] = ""
            out[-1]["finalOutputFormattingContext"] = ""
    return out


async def get_agent(
    agent_id: str,
    *,
    user_id: str | None = None,
    is_admin: bool = False,
    for_execution: bool = False,
) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        if is_admin:
            r = await conn.fetchrow("SELECT * FROM agents WHERE id = $1", agent_id)
        else:
            r = await conn.fetchrow(
                """
                SELECT * FROM agents
                WHERE id = $1
                  AND (
                    is_locked = true
                    OR visibility = 'public'
                    OR created_by_user_id = $2::uuid
                    OR created_by_user_id IS NULL
                  )
                """,
                agent_id,
                user_id,
            )
    if not r:
        return None

    is_locked = bool(r["is_locked"] or False)
    can_view_secrets = bool(is_admin or for_execution or not is_locked)

    agent = {
        "id": r["id"],
        "name": r["name"],
        "emoji": r["emoji"] or "🤖",
        "description": r["description"] or "",
        "isLocked": is_locked,
        "visibility": (r["visibility"] or "private"),
        "createdByUserId": (str(r["created_by_user_id"]) if r["created_by_user_id"] else None),
        "allowedSkillIds": list(r["allowed_skill_ids"] or []),
        "skillSelectorContext": r["skill_selector_context"] or "",
        "finalOutputFormattingContext": r["final_output_formatting_context"] or "",
    }
    if not can_view_secrets:
        agent["allowedSkillIds"] = []
        agent["skillSelectorContext"] = ""
        agent["finalOutputFormattingContext"] = ""
    return agent


async def create_agent(
    payload: dict[str, Any],
    *,
    created_by_user_id: str,
    is_admin: bool,
    is_super_admin: bool,
) -> dict[str, Any]:
    now = now_dt()
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO agents (
                    id, name, emoji, description,
                    allowed_skill_ids, skill_selector_context, final_output_formatting_context,
                    created_by_user_id, visibility, is_locked,
                    created_at, updated_at
                ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
                RETURNING *
                """,
                payload["id"],
                payload["name"],
                payload.get("emoji") or "🤖",
                payload.get("description") or "",
                payload.get("allowedSkillIds") or [],
                payload.get("skillSelectorContext") or "",
                payload.get("finalOutputFormattingContext") or "",
                created_by_user_id,
                (str(payload.get("visibility") or "").strip() or "private"),
                # Only super-admins can create locked agents (case 1).
                True if (is_super_admin and bool(payload.get("isLocked"))) else False,
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
        "isLocked": bool(row["is_locked"] or False),
        "visibility": (row["visibility"] or "private"),
        "createdByUserId": (str(row["created_by_user_id"]) if row["created_by_user_id"] else None),
        "allowedSkillIds": list(row["allowed_skill_ids"] or []),
        "skillSelectorContext": row["skill_selector_context"] or "",
        "finalOutputFormattingContext": row["final_output_formatting_context"] or "",
    }


async def update_agent(
    agent_id: str,
    patch: dict[str, Any],
    *,
    user_id: str,
    is_admin: bool,
    is_super_admin: bool,
) -> dict[str, Any] | None:
    print("[update_agent] called", {"agent_id": agent_id, "patch_keys": sorted(list(patch.keys()))})

    # Ownership + locked checks
    pool = get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow(
            "SELECT created_by_user_id, is_locked FROM agents WHERE id = $1",
            agent_id,
        )
    if not r:
        return None
    owner_user_id = r["created_by_user_id"]
    is_locked = bool(r["is_locked"] or False)
    is_system_agent = owner_user_id is None

    # Permission model (3 cases):
    # 1) Super-admin locked system group: super-admin writes only, internal admins read only.
    # 2) Admin-shared system group (not locked): super-admin + internal admin writes, outside users read.
    # 3) User-created agents: only creator writes; outside users read only if agent is public.
    if is_super_admin:
        pass
    else:
        if not is_system_agent:
            # user-created: only owner can write
            if str(owner_user_id) != user_id:
                return None
        else:
            # system groups
            if is_locked:
                # case 1: locked => super-admin only writes
                return None
            # case 2: unlocked => only internal admin (non-super) can write
            if not is_admin:
                return None

    fields: list[str] = []
    values: list[Any] = []

    mapping = {
        "name": "name",
        "emoji": "emoji",
        "description": "description",
        "allowedSkillIds": "allowed_skill_ids",
        "skillSelectorContext": "skill_selector_context",
        "finalOutputFormattingContext": "final_output_formatting_context",
        "visibility": "visibility",
    }

    for key, col in mapping.items():
        if key in patch:
            fields.append(f"{col} = ${len(values) + 1}")
            values.append(patch[key])

    if not fields:
        print("[update_agent] no mutable fields in patch", {"agent_id": agent_id})
        return await get_agent(agent_id, user_id=user_id, is_admin=is_admin, for_execution=True)

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
        "isLocked": bool(row["is_locked"] or False),
        "visibility": (row["visibility"] or "private"),
        "createdByUserId": (str(row["created_by_user_id"]) if row["created_by_user_id"] else None),
        "allowedSkillIds": list(row["allowed_skill_ids"] or []),
        "skillSelectorContext": row["skill_selector_context"] or "",
        "finalOutputFormattingContext": row["final_output_formatting_context"] or "",
    }


async def delete_agent(
    agent_id: str,
    *,
    user_id: str,
    is_admin: bool,
    is_super_admin: bool,
) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        r = await conn.fetchrow("SELECT created_by_user_id, is_locked FROM agents WHERE id = $1", agent_id)
        if not r:
            return False
        owner_user_id = r["created_by_user_id"]
        is_locked = bool(r["is_locked"] or False)
        is_system_agent = owner_user_id is None

        if is_super_admin:
            pass
        else:
            if not is_system_agent:
                # user-created: only owner can delete
                if str(owner_user_id) != user_id:
                    return False
            else:
                # system groups
                if is_locked:
                    # locked system group: super-admin only
                    return False
                if not is_admin:
                    return False
        result = await conn.execute("DELETE FROM agents WHERE id = $1", agent_id)
        return result.endswith("1")


async def get_or_create_conversation(
    conversation_id: str | None,
    agent_id: str | None = None,
    *,
    user_id: str,
    is_admin: bool,
) -> dict[str, Any] | None:
    existing = (
        await get_conversation(conversation_id, user_id=user_id, is_admin=is_admin)
        if conversation_id
        else None
    )
    if existing:
        return existing
    if conversation_id and not existing:
        # Prevent cross-user conversation access.
        return None

    await ensure_default_agents()
    selected_agent = (agent_id or DEFAULT_AGENT_ID).strip() or DEFAULT_AGENT_ID
    a = await get_agent(selected_agent, user_id=user_id, is_admin=is_admin, for_execution=True)
    if not a:
        all_agents = await list_agents(user_id=user_id, is_admin=is_admin)
        selected_agent = all_agents[0]["id"] if all_agents else DEFAULT_AGENT_ID

    cid = str(uuid4())
    now = now_dt()
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO conversations (id, agent_id, user_id, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5)
            """,
            cid,
            selected_agent,
            user_id,
            now,
            now,
        )

    return {
        "id": cid,
        "agentId": selected_agent,
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
        if isinstance(payload.get("skillsCount"), int):
            msg["skillsCount"] = payload["skillsCount"]
        if payload.get("kind") in ("plan", "final"):
            msg["kind"] = payload["kind"]
        if isinstance(payload.get("planId"), str):
            msg["planId"] = payload["planId"]
    return msg


async def get_conversation(
    conversation_id: str | None,
    *,
    user_id: str | None = None,
    is_admin: bool = False,
) -> dict[str, Any] | None:
    if not conversation_id:
        return None
    pool = get_pool()
    async with pool.acquire() as conn:
        if is_admin:
            conv = await conn.fetchrow("SELECT * FROM conversations WHERE id = $1", conversation_id)
        else:
            conv = await conn.fetchrow(
                "SELECT * FROM conversations WHERE id = $1 AND user_id = $2",
                conversation_id,
                user_id,
            )
        if not conv:
            return None
        messages = await conn.fetch(
            "SELECT * FROM messages WHERE conversation_id = $1 ORDER BY message_index ASC",
            conversation_id,
        )

    stage_outputs = _to_obj(conv["last_stage_outputs"], {})
    stage_outputs = stage_outputs if isinstance(stage_outputs, dict) else {}

    return {
        "id": conv["id"],
        "agentId": conv["agent_id"] or DEFAULT_AGENT_ID,
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
            await conn.execute("SELECT pg_advisory_xact_lock(hashtext($1))", conversation_id)
            next_index = await conn.fetchval(
                "SELECT COALESCE(MAX(message_index), -1) + 1 FROM messages WHERE conversation_id = $1",
                conversation_id,
            )
            await conn.execute(
                """
                INSERT INTO messages (
                    conversation_id, message_index, role, content, created_at, output_file, message
                ) VALUES ($1,$2,$3,$4,$5,$6,$7::jsonb)
                """,
                conversation_id,
                int(next_index),
                message["role"],
                message["content"],
                _as_datetime(message.get("createdAt")),
                message.get("outputFile"),
                _json_dumps(message),
            )
            await conn.execute(
                "UPDATE conversations SET updated_at = $2 WHERE id = $1",
                conversation_id,
                now_dt(),
            )


async def append_message(conversation_id: str, role: str, content: str, **extra: Any) -> str:
    message_id = str(extra.get("messageId") or uuid4())
    created_at_dt = _as_datetime(extra.get("createdAt"))
    created_at = created_at_dt.isoformat()
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
    if extra.get("kind") in ("plan", "final"):
        message["kind"] = extra["kind"]
    if isinstance(extra.get("planId"), str):
        message["planId"] = extra["planId"]

    await _insert_message(conversation_id, message)

    if role == "user":
        pool = get_pool()
        async with pool.acquire() as conn:
            title = await conn.fetchval("SELECT title FROM conversations WHERE id = $1", conversation_id)
            if not title:
                await conn.execute(
                    "UPDATE conversations SET title = $2 WHERE id = $1",
                    conversation_id,
                    content[:60],
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
        row = await conn.fetchrow(
            """
            SELECT message_index, message
            FROM messages
            WHERE conversation_id = $1 AND (message->>'messageId') = $2
            LIMIT 1
            """,
            conversation_id,
            message_id,
        )
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
            """
            UPDATE messages
            SET content = $3,
                output_file = COALESCE($4, output_file),
                message = $5::jsonb
            WHERE conversation_id = $1 AND message_index = $2
            """,
            conversation_id,
            row["message_index"],
            content,
            output_file,
            _json_dumps(payload),
        )
        await conn.execute("UPDATE conversations SET updated_at = $2 WHERE id = $1", conversation_id, now_dt())
    return True


async def update_message_meta(conversation_id: str, message_id: str, kind: str | None, plan_id: str | None) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT message_index, message FROM messages WHERE conversation_id = $1 AND (message->>'messageId') = $2 LIMIT 1",
            conversation_id,
            message_id,
        )
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
            "UPDATE messages SET message = $3::jsonb WHERE conversation_id = $1 AND message_index = $2",
            conversation_id,
            row["message_index"],
            _json_dumps(payload),
        )
        await conn.execute("UPDATE conversations SET updated_at = $2 WHERE id = $1", conversation_id, now_dt())
    return True


async def save_stage_outputs(conversation_id: str, stage_outputs: dict[str, str], output_file: str | None) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE conversations SET last_stage_outputs = $2::jsonb, last_output_file = $3, updated_at = $4 WHERE id = $1",
            conversation_id,
            _json_dumps(stage_outputs or {}),
            output_file,
            now_dt(),
        )


async def get_stage_outputs(conversation_id: str) -> dict[str, str]:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT last_stage_outputs FROM conversations WHERE id = $1", conversation_id)
    if not row:
        return {}
    obj = _to_obj(row["last_stage_outputs"], {})
    if not isinstance(obj, dict):
        return {}
    return {str(k): str(v) for k, v in obj.items() if isinstance(v, str)}


async def list_conversations(*, user_id: str, is_admin: bool) -> list[dict[str, Any]]:
    pool = get_pool()
    async with pool.acquire() as conn:
        if is_admin:
            rows = await conn.fetch("SELECT * FROM conversations ORDER BY updated_at DESC")
        else:
            rows = await conn.fetch(
                "SELECT * FROM conversations WHERE user_id = $1 ORDER BY updated_at DESC",
                user_id,
            )
    out: list[dict[str, Any]] = []
    for r in rows:
        count = 0
        async with pool.acquire() as conn:
            count = int(await conn.fetchval("SELECT COUNT(*) FROM messages WHERE conversation_id = $1", r["id"]))
        out.append(
            {
                "id": r["id"],
                "agentId": r["agent_id"] or DEFAULT_AGENT_ID,
                "title": r["title"] or "New conversation",
                "messageCount": count,
                "createdAt": r["created_at"],
                "updatedAt": r["updated_at"],
            }
        )
    return out


async def delete_conversation(conversation_id: str, *, user_id: str, is_admin: bool) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        if is_admin:
            result = await conn.execute("DELETE FROM conversations WHERE id = $1", conversation_id)
        else:
            result = await conn.execute(
                "DELETE FROM conversations WHERE id = $1 AND user_id = $2",
                conversation_id,
                user_id,
            )
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
            """
            INSERT INTO skill_calls (
                conversation_id, message_id, skill_id, run_id,
                input, state, output, started_at, created_at, updated_at
            ) VALUES ($1,$2,$3,$4,$5::jsonb,'running',$6::jsonb,$7,NOW(),NOW())
            RETURNING id
            """,
            conversation_id,
            message_id,
            skill_id,
            run_id,
            _json_dumps(input_payload or {}),
            _json_dumps([]),
            started_at,
        )
    return str(row["id"])


async def push_skill_output(skill_call_id: str, entry: dict[str, Any]) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT output FROM skill_calls WHERE id = $1::bigint", int(skill_call_id))
        if not row:
            return
        output = _to_obj(row["output"], [])
        if not isinstance(output, list):
            output = []
        payload = dict(entry)
        payload.setdefault("at", now_iso())
        output.append(payload)
        await conn.execute(
            "UPDATE skill_calls SET output = $2::jsonb, updated_at = NOW() WHERE id = $1::bigint",
            int(skill_call_id),
            _json_dumps(output),
        )


async def append_skill_streamed_text(skill_call_id: str, text_chunk: str) -> None:
    chunk = str(text_chunk or "")
    if not chunk:
        return
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                """
                UPDATE skill_calls
                SET streamed_text = COALESCE(streamed_text, '') || $2,
                    updated_at = NOW()
                WHERE id = $1::bigint
                """,
                int(skill_call_id),
                chunk,
            )
        except Exception:
            await conn.execute(
                "ALTER TABLE skill_calls ADD COLUMN IF NOT EXISTS streamed_text TEXT NOT NULL DEFAULT ''"
            )
            await conn.execute(
                """
                UPDATE skill_calls
                SET streamed_text = COALESCE(streamed_text, '') || $2,
                    updated_at = NOW()
                WHERE id = $1::bigint
                """,
                int(skill_call_id),
                chunk,
            )


async def set_skill_call_result(skill_call_id: str, state: str, text: str | None, data: Any, error: str | None) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT started_at, output FROM skill_calls WHERE id = $1::bigint",
            int(skill_call_id),
        )
        if not row:
            return
        output = _to_obj(row["output"], [])
        if not isinstance(output, list):
            output = []
        if text is not None or data is not None:
            output.append({"type": "result", "summary": text, "text": text, "data": data, "at": now_iso()})

        started_at = row["started_at"] or now_dt()
        try:
            started_at_dt = datetime.fromisoformat(str(started_at))
            duration_row = await conn.fetchrow(
                "SELECT (EXTRACT(EPOCH FROM (NOW() - $1)) * 1000)::int AS ms",
                started_at_dt,
            )
            duration_ms = int(duration_row["ms"]) if duration_row and duration_row["ms"] is not None else None
        except Exception:
            duration_ms = None

        await conn.execute(
            """
            UPDATE skill_calls
            SET state = $2,
                error = $3,
                ended_at = $4,
                duration_ms = $5,
                output = $6::jsonb,
                updated_at = NOW()
            WHERE id = $1::bigint
            """,
            int(skill_call_id),
            state,
            error,
            now_dt(),
            duration_ms,
            _json_dumps(output),
        )


async def get_skill_calls_by_message_id_full(
    message_id: str,
    *,
    user_id: str,
    is_admin: bool,
) -> list[dict[str, Any]]:
    pool = get_pool()
    async with pool.acquire() as conn:
        if is_admin:
            rows = await conn.fetch(
                "SELECT * FROM skill_calls WHERE message_id = $1 ORDER BY created_at ASC",
                message_id,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT sc.* FROM skill_calls sc
                JOIN conversations c ON c.id = sc.conversation_id
                WHERE sc.message_id = $1 AND c.user_id = $2
                ORDER BY sc.created_at ASC
                """,
                message_id,
                user_id,
            )
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


async def get_skill_calls_by_message_id(
    message_id: str,
    *,
    user_id: str,
    is_admin: bool,
) -> list[dict[str, Any]]:
    full = await get_skill_calls_by_message_id_full(message_id, user_id=user_id, is_admin=is_admin)
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
            """
            INSERT INTO plan_runs (
                id, conversation_id, user_message_id, plan_message_id,
                status, plan_markdown, plan_json, created_at, updated_at
            ) VALUES ($1,$2,$3,$4,'draft',$5,$6::jsonb,$7,$8)
            RETURNING *
            """,
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


async def get_plan_run(
    plan_id: str,
    *,
    user_id: str,
    is_admin: bool,
) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        if is_admin:
            row = await conn.fetchrow("SELECT * FROM plan_runs WHERE id = $1", plan_id)
        else:
            row = await conn.fetchrow(
                """
                SELECT pr.* FROM plan_runs pr
                JOIN conversations c ON c.id = pr.conversation_id
                WHERE pr.id = $1 AND c.user_id = $2
                """,
                plan_id,
                user_id,
            )
    if not row:
        return None
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


async def update_plan_run(
    plan_id: str,
    patch: dict[str, Any],
    *,
    user_id: str,
    is_admin: bool,
) -> None:
    fields: list[str] = []
    values: list[Any] = []
    if "status" in patch:
        fields.append(f"status = ${len(values) + 1}")
        values.append(patch["status"])
    if "planMarkdown" in patch:
        fields.append(f"plan_markdown = ${len(values) + 1}")
        values.append(patch["planMarkdown"])
    if "planJson" in patch:
        fields.append(f"plan_json = ${len(values) + 1}::jsonb")
        values.append(_json_dumps(patch["planJson"]))

    fields.append(f"updated_at = ${len(values) + 1}")
    values.append(now_dt())
    values.append(plan_id)

    if is_admin:
        q = f"UPDATE plan_runs SET {', '.join(fields)} WHERE id = ${len(values)}"
    else:
        plan_param_idx = len(values)
        user_param_idx = len(values) + 1
        q = f"""
        UPDATE plan_runs SET {', '.join(fields)}
        WHERE id = ${plan_param_idx}
          AND EXISTS (
            SELECT 1 FROM conversations c
            WHERE c.id = plan_runs.conversation_id AND c.user_id = ${user_param_idx}
          )
        """
        values.append(user_id)
    pool = get_pool()
    async with pool.acquire() as conn:
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


async def save_token_usage(
    message_id: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    *,
    stage: str | None = None,
    provider: str | None = None,
) -> None:
    pool = get_pool()
    encoded_model = _encode_token_usage_model(model, stage, provider)
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO token_usage (message_id, model, input_tokens, output_tokens)
            VALUES ($1, $2, $3, $4)
            """,
            message_id,
            encoded_model,
            input_tokens,
            output_tokens,
        )


async def get_token_usage(
    message_id: str,
    *,
    user_id: str,
    is_admin: bool,
) -> dict[str, Any]:
    pool = get_pool()
    async with pool.acquire() as conn:
        if is_admin:
            rows = await conn.fetch(
                "SELECT model, input_tokens, output_tokens, created_at FROM token_usage WHERE message_id = $1 ORDER BY created_at ASC",
                message_id,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT tu.model, tu.input_tokens, tu.output_tokens, tu.created_at
                FROM token_usage tu
                JOIN messages m
                  ON (m.message->>'messageId') = tu.message_id
                JOIN conversations c
                  ON c.id = m.conversation_id
                WHERE tu.message_id = $1 AND c.user_id = $2
                ORDER BY tu.created_at ASC
                """,
                message_id,
                user_id,
            )
    entries = [
        (
            lambda decoded: {
                "stage": decoded["stage"],
                "provider": decoded["provider"],
                "model": decoded["model"],
                "inputTokens": r["input_tokens"],
                "outputTokens": r["output_tokens"],
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


async def list_insight_feedback(
    message_id: str,
    *,
    user_id: str,
    is_admin: bool,
) -> list[dict[str, Any]]:
    """
    Returns feedback entries for this message that the current user is allowed to view.
    For now, we return only the current user's feedback (and for admins, still only their own),
    so the UI can show selected thumbs state per insight.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        try:
            if is_admin:
                rows = await conn.fetch(
                    """
                    SELECT insight_index, rating, updated_at
                    FROM insight_feedback
                    WHERE message_id = $1 AND user_id = $2
                    ORDER BY insight_index ASC
                    """,
                    message_id,
                    user_id,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT f.insight_index, f.rating, f.updated_at
                    FROM insight_feedback f
                    JOIN messages m
                      ON (m.message->>'messageId') = f.message_id
                    JOIN conversations c
                      ON c.id = m.conversation_id
                    WHERE f.message_id = $1 AND f.user_id = $2 AND c.user_id = $2
                    ORDER BY f.insight_index ASC
                    """,
                    message_id,
                    user_id,
                )
        except UndefinedTableError:
            await _ensure_insight_feedback_table(conn)
            return await list_insight_feedback(message_id, user_id=user_id, is_admin=is_admin)
    return [
        {"insightIndex": int(r["insight_index"]), "rating": int(r["rating"]), "updatedAt": str(r["updated_at"])}
        for r in rows
    ]


async def set_insight_feedback(
    message_id: str,
    *,
    insight_index: int,
    rating: int,
    user_id: str,
    is_admin: bool,
) -> dict[str, Any]:
    """
    Upsert thumbs feedback for a specific insight within a specific output message.
    rating: 1 (up) or -1 (down)
    """
    idx = int(insight_index)
    r = int(rating)
    if idx <= 0:
        raise ValueError("insightIndex must be >= 1")
    if r not in (-1, 1):
        raise ValueError("rating must be 1 or -1")

    pool = get_pool()
    async with pool.acquire() as conn:
        # Resolve conversation_id for messageId and enforce access (non-admin: must own conversation)
        row = await conn.fetchrow(
            """
            SELECT m.conversation_id AS conversation_id, c.user_id AS owner_user_id
            FROM messages m
            JOIN conversations c ON c.id = m.conversation_id
            WHERE (m.message->>'messageId') = $1
            LIMIT 1
            """,
            message_id,
        )
        if not row:
            raise ValueError("message not found")
        if not is_admin and str(row["owner_user_id"]) != str(user_id):
            raise ValueError("message not accessible")
        conversation_id = str(row["conversation_id"])

        try:
            saved = await conn.fetchrow(
                """
                INSERT INTO insight_feedback (conversation_id, message_id, insight_index, user_id, rating, created_at, updated_at)
                VALUES ($1, $2, $3, $4::uuid, $5, NOW(), NOW())
                ON CONFLICT (user_id, message_id, insight_index)
                DO UPDATE SET rating = EXCLUDED.rating, updated_at = NOW()
                RETURNING insight_index, rating, updated_at
                """,
                conversation_id,
                message_id,
                idx,
                user_id,
                r,
            )
        except UndefinedTableError:
            await _ensure_insight_feedback_table(conn)
            saved = await conn.fetchrow(
                """
                INSERT INTO insight_feedback (conversation_id, message_id, insight_index, user_id, rating, created_at, updated_at)
                VALUES ($1, $2, $3, $4::uuid, $5, NOW(), NOW())
                ON CONFLICT (user_id, message_id, insight_index)
                DO UPDATE SET rating = EXCLUDED.rating, updated_at = NOW()
                RETURNING insight_index, rating, updated_at
                """,
                conversation_id,
                message_id,
                idx,
                user_id,
                r,
            )
    assert saved is not None
    return {"insightIndex": int(saved["insight_index"]), "rating": int(saved["rating"]), "updatedAt": str(saved["updated_at"])}
