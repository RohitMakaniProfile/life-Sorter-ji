from __future__ import annotations

from typing import Any

from pypika import Order, Table
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter, LiteralValue

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


def _cast_jsonb(param: Parameter) -> LiteralValue:
    return LiteralValue(f"{param}::jsonb")


async def insert_running(
    conn, session_id: str, user_id: Any,
    onboarding_snapshot_json: str, crawl_snapshot_json: str,
) -> Any:
    """INSERT a new playbook_run in 'running' state. Returns the row."""
    q = build_query(
        PostgreSQLQuery.into(playbook_runs_t)
        .columns(
            playbook_runs_t.session_id, playbook_runs_t.user_id,
            playbook_runs_t.status, playbook_runs_t.onboarding_snapshot,
            playbook_runs_t.crawl_snapshot,
        )
        .insert(
            Parameter("%s"), Parameter("%s"), "running",
            _cast_jsonb(Parameter("%s")), _cast_jsonb(Parameter("%s")),
        )
        .returning(playbook_runs_t.id),
        [session_id, user_id, onboarding_snapshot_json, crawl_snapshot_json],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def mark_complete(
    conn, run_id: Any, context_brief: str, icp_card: str,
    playbook: str, website_audit: str, latencies_json: str,
) -> None:
    """Mark a playbook_run as complete with results."""
    q = build_query(
        PostgreSQLQuery.update(playbook_runs_t)
        .set(playbook_runs_t.status, "complete")
        .set(playbook_runs_t.error, "")
        .set(playbook_runs_t.context_brief, Parameter("%s"))
        .set(playbook_runs_t.icp_card, Parameter("%s"))
        .set(playbook_runs_t.playbook, Parameter("%s"))
        .set(playbook_runs_t.website_audit, Parameter("%s"))
        .set(playbook_runs_t.latencies, _cast_jsonb(Parameter("%s")))
        .where(playbook_runs_t.id == Parameter("%s")),
        [context_brief, icp_card, playbook, website_audit, latencies_json, run_id],
    )
    await conn.execute(q.sql, *q.params)


async def mark_error(conn, run_id: Any, error_message: str) -> None:
    """Mark a playbook_run as errored."""
    q = build_query(
        PostgreSQLQuery.update(playbook_runs_t)
        .set(playbook_runs_t.status, "error")
        .set(playbook_runs_t.error, Parameter("%s"))
        .where(playbook_runs_t.id == Parameter("%s")),
        [error_message, run_id],
    )
    await conn.execute(q.sql, *q.params)