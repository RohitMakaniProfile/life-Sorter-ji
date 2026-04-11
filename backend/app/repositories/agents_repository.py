from __future__ import annotations

from datetime import datetime
from typing import Any

from pypika import Order, Table
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter

from app.sql_builder import build_query

agents_t = Table("agents")

# Kept as raw SQL: asyncpg list binding for text[] is straightforward this way
SQL_INSERT_AGENT_IGNORE = """
    INSERT INTO agents (
        id, name, emoji, description,
        allowed_skill_ids, skill_selector_context, final_output_formatting_context,
        created_at, updated_at
    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
    ON CONFLICT (id) DO NOTHING
"""

SQL_INSERT_AGENT_RETURNING = """
    INSERT INTO agents (
        id, name, emoji, description,
        allowed_skill_ids, skill_selector_context, final_output_formatting_context,
        created_at, updated_at
    ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
    RETURNING *
"""


async def insert_ignore(
    conn, agent_id: str, name: str, emoji: str, description: str,
    allowed_skill_ids: list[str], skill_selector_context: str,
    final_output_formatting_context: str, now: datetime,
) -> None:
    await conn.execute(
        SQL_INSERT_AGENT_IGNORE,
        agent_id, name, emoji, description,
        allowed_skill_ids, skill_selector_context, final_output_formatting_context,
        now, now,
    )


async def insert_returning(
    conn, agent_id: str, name: str, emoji: str, description: str,
    allowed_skill_ids: list[str], skill_selector_context: str,
    final_output_formatting_context: str, now: datetime,
) -> Any:
    return await conn.fetchrow(
        SQL_INSERT_AGENT_RETURNING,
        agent_id, name, emoji, description,
        allowed_skill_ids, skill_selector_context, final_output_formatting_context,
        now, now,
    )


async def find_all(conn) -> list[Any]:
    q = build_query(
        PostgreSQLQuery.from_(agents_t).select("*")
        .orderby(agents_t.updated_at, order=Order.desc)
    )
    return list(await conn.fetch(q.sql, *q.params))


async def find_by_id(conn, agent_id: str) -> Any:
    q = build_query(
        PostgreSQLQuery.from_(agents_t).select("*")
        .where(agents_t.id == Parameter("%s")),
        [agent_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def update_fields(conn, agent_id: str, fields: dict[str, Any], now: datetime) -> Any:
    """Dynamic UPDATE — only sets columns present in `fields`. Returns updated row or None."""
    col_map = {
        "name": "name",
        "emoji": "emoji",
        "description": "description",
        "allowedSkillIds": "allowed_skill_ids",
        "skillSelectorContext": "skill_selector_context",
        "finalOutputFormattingContext": "final_output_formatting_context",
    }
    set_parts: list[str] = []
    values: list[Any] = []
    for key, col in col_map.items():
        if key in fields:
            set_parts.append(f"{col} = ${len(values) + 1}")
            values.append(fields[key])
    if not set_parts:
        return None  # Nothing to update — caller should return current row unchanged
    set_parts.append(f"updated_at = ${len(values) + 1}")
    values.append(now)
    values.append(agent_id)
    sql = f"UPDATE agents SET {', '.join(set_parts)} WHERE id = ${len(values)} RETURNING *"
    return await conn.fetchrow(sql, *values)


async def reassign_conversations_agent(conn, old_agent_id: str, new_agent_id: str) -> None:
    """Point all conversations off the deleted agent to the default agent."""
    from app.repositories.conversations_repository import conversations_t
    q = build_query(
        PostgreSQLQuery.update(conversations_t)
        .set(conversations_t.agent_id, Parameter("%s"))
        .set(conversations_t.updated_at, Parameter("%s"))
        .where(conversations_t.agent_id == Parameter("%s")),
        [new_agent_id, None, old_agent_id],  # updated_at uses fn.Now() below
    )
    # Use raw update to get fn.Now() behavior
    from pypika import functions as fn
    q2 = build_query(
        PostgreSQLQuery.update(conversations_t)
        .set(conversations_t.agent_id, Parameter("%s"))
        .set(conversations_t.updated_at, fn.Now())
        .where(conversations_t.agent_id == Parameter("%s")),
        [new_agent_id, old_agent_id],
    )
    await conn.execute(q2.sql, *q2.params)


async def delete_by_id(conn, agent_id: str) -> bool:
    q = build_query(
        PostgreSQLQuery.from_(agents_t).delete()
        .where(agents_t.id == Parameter("%s")),
        [agent_id],
    )
    result = await conn.execute(q.sql, *q.params)
    return result.endswith("1")