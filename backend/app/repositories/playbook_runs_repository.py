from __future__ import annotations

from typing import Any

from pypika import Order, Table
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter

from app.sql_builder import build_query

playbook_runs_t = Table("playbook_runs")
_onboarding_t = Table("onboarding")

_DETAIL_COLS = (
    playbook_runs_t.playbook, playbook_runs_t.website_audit,
    playbook_runs_t.context_brief, playbook_runs_t.icp_card, playbook_runs_t.status,
)

_LIST_COLS = (
    playbook_runs_t.id, playbook_runs_t.session_id, playbook_runs_t.user_id,
    playbook_runs_t.status, playbook_runs_t.playbook, playbook_runs_t.onboarding_snapshot,
    playbook_runs_t.created_at, playbook_runs_t.updated_at,
)


async def find_latest_complete_by_session(conn, session_id: str) -> Any:
    q = build_query(
        PostgreSQLQuery.from_(playbook_runs_t)
        .select(*_DETAIL_COLS)
        .where(playbook_runs_t.session_id == Parameter("%s"))
        .orderby(playbook_runs_t.updated_at, order=Order.desc).limit(1),
        [session_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def find_latest_via_onboarding_fk(conn, onboarding_id: str) -> Any:
    """Fallback: look up playbook via onboarding.playbook_run_id FK."""
    q = build_query(
        PostgreSQLQuery.from_(_onboarding_t)
        .join(playbook_runs_t)
        .on(_onboarding_t.playbook_run_id == playbook_runs_t.id)
        .select(*_DETAIL_COLS)
        .where(_onboarding_t.id == Parameter("%s")).limit(1),
        [onboarding_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def find_by_id_and_user(conn, run_id: str, user_id: str) -> Any:
    q = build_query(
        PostgreSQLQuery.from_(playbook_runs_t)
        .select(
            playbook_runs_t.id, playbook_runs_t.session_id, playbook_runs_t.status,
            playbook_runs_t.playbook, playbook_runs_t.website_audit,
            playbook_runs_t.context_brief, playbook_runs_t.icp_card,
            playbook_runs_t.onboarding_snapshot,
        )
        .where(playbook_runs_t.id == Parameter("%s"))
        .where(playbook_runs_t.user_id == Parameter("%s"))
        .where(playbook_runs_t.status == "complete").limit(1),
        [run_id, user_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def find_distinct_sessions_by_user(conn, user_id: str) -> list[Any]:
    """Return distinct session IDs for complete playbooks owned by a user (for total count)."""
    q = build_query(
        PostgreSQLQuery.from_(playbook_runs_t)
        .select(playbook_runs_t.session_id).distinct()
        .where(playbook_runs_t.status == "complete")
        .where(playbook_runs_t.playbook != "")
        .where(playbook_runs_t.user_id == Parameter("%s")),
        [user_id],
    )
    return list(await conn.fetch(q.sql, *q.params))


async def find_paginated_by_user(conn, user_id: str, fetch_limit: int) -> list[Any]:
    """Fetch rows for pagination — caller deduplicates by session_id and slices."""
    q = build_query(
        PostgreSQLQuery.from_(playbook_runs_t)
        .select(*_LIST_COLS)
        .where(playbook_runs_t.status == "complete")
        .where(playbook_runs_t.playbook != "")
        .where(playbook_runs_t.user_id == Parameter("%s"))
        .orderby(playbook_runs_t.updated_at, order=Order.desc)
        .limit(fetch_limit),
        [user_id],
    )
    return list(await conn.fetch(q.sql, *q.params))


async def delete_by_user_id(conn, user_id: str) -> None:
    q = build_query(
        PostgreSQLQuery.from_(playbook_runs_t).delete()
        .where(playbook_runs_t.user_id == Parameter("%s")),
        [user_id],
    )
    await conn.execute(q.sql, *q.params)