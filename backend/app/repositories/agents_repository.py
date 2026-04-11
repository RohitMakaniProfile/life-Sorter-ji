from __future__ import annotations

from datetime import datetime
from typing import Any

from pypika import Order, Table, functions as fn
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter

from app.sql_builder import build_query

agents_t = Table("agents")

_INSERT_COLS = (
    agents_t.id, agents_t.name, agents_t.emoji, agents_t.description,
    agents_t.allowed_skill_ids, agents_t.skill_selector_context,
    agents_t.final_output_formatting_context, agents_t.created_at, agents_t.updated_at,
)


async def insert_ignore(
    conn, agent_id: str, name: str, emoji: str, description: str,
    allowed_skill_ids: list[str], skill_selector_context: str,
    final_output_formatting_context: str, now: datetime,
) -> None:
    q = build_query(
        PostgreSQLQuery.into(agents_t)
        .columns(*_INSERT_COLS)
        .insert(
            Parameter("%s"), Parameter("%s"), Parameter("%s"), Parameter("%s"),
            Parameter("%s"), Parameter("%s"), Parameter("%s"), Parameter("%s"), Parameter("%s"),
        )
        .on_conflict(agents_t.id).do_nothing(),
        [agent_id, name, emoji, description, allowed_skill_ids,
         skill_selector_context, final_output_formatting_context, now, now],
    )
    await conn.execute(q.sql, *q.params)


async def insert_returning(
    conn, agent_id: str, name: str, emoji: str, description: str,
    allowed_skill_ids: list[str], skill_selector_context: str,
    final_output_formatting_context: str, now: datetime,
) -> Any:
    q = build_query(
        PostgreSQLQuery.into(agents_t)
        .columns(*_INSERT_COLS)
        .insert(
            Parameter("%s"), Parameter("%s"), Parameter("%s"), Parameter("%s"),
            Parameter("%s"), Parameter("%s"), Parameter("%s"), Parameter("%s"), Parameter("%s"),
        )
        .returning("*"),
        [agent_id, name, emoji, description, allowed_skill_ids,
         skill_selector_context, final_output_formatting_context, now, now],
    )
    return await conn.fetchrow(q.sql, *q.params)


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
        "name": agents_t.name,
        "emoji": agents_t.emoji,
        "description": agents_t.description,
        "allowedSkillIds": agents_t.allowed_skill_ids,
        "skillSelectorContext": agents_t.skill_selector_context,
        "finalOutputFormattingContext": agents_t.final_output_formatting_context,
    }
    qb = PostgreSQLQuery.update(agents_t)
    vals: list[Any] = []
    for key, col in col_map.items():
        if key in fields:
            qb = qb.set(col, Parameter("%s"))
            vals.append(fields[key])
    if not vals:
        return None  # Nothing to update — caller should return current row unchanged
    qb = qb.set(agents_t.updated_at, Parameter("%s"))
    vals.append(now)
    vals.append(agent_id)
    q = build_query(
        qb.where(agents_t.id == Parameter("%s")).returning("*"),
        vals,
    )
    return await conn.fetchrow(q.sql, *q.params)


async def reassign_conversations_agent(conn, old_agent_id: str, new_agent_id: str) -> None:
    """Point all conversations off the deleted agent to the default agent."""
    from app.repositories.conversations_repository import conversations_t
    q = build_query(
        PostgreSQLQuery.update(conversations_t)
        .set(conversations_t.agent_id, Parameter("%s"))
        .set(conversations_t.updated_at, fn.Now())
        .where(conversations_t.agent_id == Parameter("%s")),
        [new_agent_id, old_agent_id],
    )
    await conn.execute(q.sql, *q.params)


async def delete_by_id(conn, agent_id: str) -> bool:
    q = build_query(
        PostgreSQLQuery.from_(agents_t).delete()
        .where(agents_t.id == Parameter("%s")),
        [agent_id],
    )
    result = await conn.execute(q.sql, *q.params)
    return result.endswith("1")