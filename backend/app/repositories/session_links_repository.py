from __future__ import annotations

from pypika import Table
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter

from app.sql_builder import build_query

session_links_t = Table("session_user_links")

_SQL_INSERT_LINK = """
    INSERT INTO session_user_links (session_id, user_id, linked_at)
    VALUES ($1, $2, NOW())
    ON CONFLICT (session_id, user_id) DO NOTHING
"""


async def insert(conn, session_id: str, user_id: str) -> None:
    await conn.execute(_SQL_INSERT_LINK, session_id, user_id)


async def exists_by_user(conn, user_id: str) -> bool:
    q = build_query(
        PostgreSQLQuery.from_(session_links_t).select(1)
        .where(session_links_t.user_id == Parameter("%s")).limit(1),
        [user_id],
    )
    return bool(await conn.fetchval(q.sql, *q.params))


async def delete_by_user(conn, user_id: str) -> None:
    q = build_query(
        PostgreSQLQuery.from_(session_links_t).delete()
        .where(session_links_t.user_id == Parameter("%s")),
        [user_id],
    )
    await conn.execute(q.sql, *q.params)