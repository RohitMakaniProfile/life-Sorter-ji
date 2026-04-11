from __future__ import annotations

from typing import Any

from pypika import Order, Table, functions as fn
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter

from app.sql_builder import build_query

prompts_t = Table("prompts")

_FULL_COLS = (
    prompts_t.slug,
    prompts_t.name,
    prompts_t.content,
    prompts_t.description,
    prompts_t.category,
    prompts_t.created_at,
    prompts_t.updated_at,
)


async def get_content(conn, slug: str) -> str | None:
    """Return prompt content by slug, or None if not found."""
    q = build_query(
        PostgreSQLQuery.from_(prompts_t).select(prompts_t.content)
        .where(prompts_t.slug == Parameter("%s")),
        [slug],
    )
    row = await conn.fetchrow(q.sql, *q.params)
    return str(row["content"]) if row else None


async def get_full(conn, slug: str) -> Any:
    """Return full prompt record by slug."""
    q = build_query(
        PostgreSQLQuery.from_(prompts_t).select(*_FULL_COLS)
        .where(prompts_t.slug == Parameter("%s")),
        [slug],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def list_all(conn) -> list[Any]:
    """List all prompts ordered by category then name."""
    q = build_query(
        PostgreSQLQuery.from_(prompts_t).select(*_FULL_COLS)
        .orderby(prompts_t.category, order=Order.asc)
        .orderby(prompts_t.name, order=Order.asc)
    )
    return list(await conn.fetch(q.sql, *q.params))


async def list_by_category(conn, category: str) -> list[Any]:
    """List prompts filtered by category."""
    q = build_query(
        PostgreSQLQuery.from_(prompts_t).select(*_FULL_COLS)
        .where(prompts_t.category == Parameter("%s"))
        .orderby(prompts_t.name),
        [category],
    )
    return list(await conn.fetch(q.sql, *q.params))


async def upsert(
    conn, slug: str, name: str, content: str, description: str, category: str,
) -> Any:
    """Create or update a prompt. Returns the updated row."""
    q = build_query(
        PostgreSQLQuery.into(prompts_t)
        .columns(
            prompts_t.slug, prompts_t.name, prompts_t.content,
            prompts_t.description, prompts_t.category, prompts_t.updated_at,
        )
        .insert(Parameter("%s"), Parameter("%s"), Parameter("%s"),
                Parameter("%s"), Parameter("%s"), fn.Now())
        .on_conflict(prompts_t.slug)
        .do_update(prompts_t.name)
        .do_update(prompts_t.content)
        .do_update(prompts_t.description)
        .do_update(prompts_t.category)
        .do_update(prompts_t.updated_at)
        .returning(*_FULL_COLS),
        [slug, name, content, description, category],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def delete(conn, slug: str) -> bool:
    """Delete a prompt by slug. Returns True if deleted."""
    q = build_query(
        PostgreSQLQuery.from_(prompts_t).delete()
        .where(prompts_t.slug == Parameter("%s")),
        [slug],
    )
    result = await conn.execute(q.sql, *q.params)
    return result == "DELETE 1"