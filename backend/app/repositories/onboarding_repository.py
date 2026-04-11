from __future__ import annotations

import json
from typing import Any

from pypika import Table, functions as fn
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter

from app.sql_builder import build_query

onboarding_t = Table("onboarding")

_RETURNING_COLS = (
    "id", "user_id", "outcome", "domain", "task",
    "website_url", "gbp_url", "scale_answers", "business_profile",
    "questions_answers", "crawl_cache_key", "onboarding_completed_at",
    "created_at", "updated_at",
)

_RETURNING_TERMS = tuple(getattr(onboarding_t, c) for c in _RETURNING_COLS)

# Kept as raw SQL: DEFAULT VALUES cannot be expressed in PyPika
_SQL_INSERT_DEFAULT = (
    "INSERT INTO onboarding DEFAULT VALUES "
    "RETURNING " + ", ".join(_RETURNING_COLS)
)

# Kept as raw SQL: JSONB literal casts are safer outside PyPika parameter binding
_SQL_RESET_WEB_SUMMARY = (
    "UPDATE onboarding "
    "SET web_summary = '', business_profile = '', rca_qa = $1::jsonb, "
    "    rca_summary = '', rca_handoff = '', updated_at = NOW() "
    "WHERE id = $2 "
    "RETURNING " + ", ".join(_RETURNING_COLS)
)

_SQL_RESET_FULL = (
    "UPDATE onboarding "
    "SET outcome = NULL, domain = NULL, task = NULL, "
    "    website_url = NULL, gbp_url = NULL, "
    "    questions_answers = '[]'::jsonb, rca_qa = '[]'::jsonb, "
    "    scale_answers = '{}'::jsonb, business_profile = '', "
    "    gap_questions = '[]'::jsonb, gap_answers = '', "
    "    rca_summary = '', rca_handoff = '', "
    "    precision_questions = '[]'::jsonb, precision_answers = '[]'::jsonb, "
    "    precision_status = 'not_started', precision_completed_at = NULL, "
    "    playbook_status = 'not_started', playbook_started_at = NULL, "
    "    playbook_completed_at = NULL, playbook_error = '', "
    "    crawl_run_id = NULL, crawl_cache_key = NULL, "
    "    playbook_run_id = NULL, web_summary = '', "
    "    onboarding_completed_at = NULL, updated_at = NOW() "
    "WHERE id = $1 "
    "RETURNING " + ", ".join(_RETURNING_COLS)
)


async def insert_default(conn) -> Any:
    return await conn.fetchrow(_SQL_INSERT_DEFAULT)


async def insert_with_fields(conn, cols: list[str], vals: list[Any]) -> Any:
    terms = [getattr(onboarding_t, c) for c in cols]
    placeholders = [Parameter("%s") for _ in vals]
    q = build_query(
        PostgreSQLQuery.into(onboarding_t)
        .columns(*terms).insert(*placeholders)
        .returning(*_RETURNING_TERMS),
        vals,
    )
    return await conn.fetchrow(q.sql, *q.params)


async def find_by_id(conn, onboarding_id: str) -> Any:
    """Lightweight fetch: just onboarding_completed_at and website_url (for patch guard)."""
    q = build_query(
        PostgreSQLQuery.from_(onboarding_t)
        .select(onboarding_t.onboarding_completed_at, onboarding_t.website_url,
                onboarding_t.playbook_status)
        .where(onboarding_t.id == Parameter("%s")),
        [onboarding_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def find_full_by_id(conn, onboarding_id: str) -> Any:
    q = build_query(
        PostgreSQLQuery.from_(onboarding_t)
        .select(*_RETURNING_TERMS)
        .where(onboarding_t.id == Parameter("%s")),
        [onboarding_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def find_transcript_fields(conn, onboarding_id: str) -> Any:
    """Fetch fields needed for onboarding transcript reconstruction."""
    q = build_query(
        PostgreSQLQuery.from_(onboarding_t)
        .select(
            onboarding_t.outcome, onboarding_t.domain, onboarding_t.task,
            onboarding_t.website_url, onboarding_t.gbp_url, onboarding_t.scale_answers,
            onboarding_t.rca_qa, onboarding_t.precision_questions,
            onboarding_t.precision_answers, onboarding_t.gap_questions,
            onboarding_t.gap_answers,
        )
        .where(onboarding_t.id == Parameter("%s")).limit(1),
        [onboarding_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def find_user_id(conn, onboarding_id: str) -> Any:
    """Return user_id for onboarding row (used in token usage attribution)."""
    q = build_query(
        PostgreSQLQuery.from_(onboarding_t)
        .select(onboarding_t.user_id)
        .where(onboarding_t.id == Parameter("%s")).limit(1),
        [onboarding_id],
    )
    return await conn.fetchval(q.sql, *q.params)


async def update_fields(conn, onboarding_id: str, fields: dict[str, Any]) -> Any:
    """Dynamic UPDATE for allowed patch fields. Returns updated row."""
    qb = PostgreSQLQuery.update(onboarding_t)
    vals: list[Any] = []
    for col_name, val in fields.items():
        qb = qb.set(getattr(onboarding_t, col_name), Parameter("%s"))
        vals.append(val)
    q = build_query(
        qb.set(onboarding_t.updated_at, fn.Now())
        .where(onboarding_t.id == Parameter("%s"))
        .returning(*_RETURNING_TERMS),
        [*vals, onboarding_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def update_rca_qa(conn, onboarding_id: str, rca_qa_json: str) -> None:
    q = build_query(
        PostgreSQLQuery.update(onboarding_t)
        .set(onboarding_t.rca_qa, Parameter("%s"))
        .where(onboarding_t.id == Parameter("%s")),
        [rca_qa_json, onboarding_id],
    )
    await conn.execute(q.sql, *q.params)


async def update_questions_answers(conn, onboarding_id: str, qa_json: str) -> None:
    q = build_query(
        PostgreSQLQuery.update(onboarding_t)
        .set(onboarding_t.questions_answers, Parameter("%s"))
        .set(onboarding_t.updated_at, fn.Now())
        .where(onboarding_t.id == Parameter("%s")),
        [qa_json, onboarding_id],
    )
    await conn.execute(q.sql, *q.params)


async def reset_web_summary(conn, onboarding_id: str) -> Any:
    return await conn.fetchrow(_SQL_RESET_WEB_SUMMARY, json.dumps([]), onboarding_id)


async def reset_full(conn, onboarding_id: str) -> Any:
    return await conn.fetchrow(_SQL_RESET_FULL, onboarding_id)


async def link_user(conn, user_id: str, onboarding_id: str) -> None:
    """Attach user_id to an onboarding row that is still unowned (or already owned by the same user)."""
    q = build_query(
        PostgreSQLQuery.update(onboarding_t)
        .set(onboarding_t.user_id, Parameter("%s"))
        .set(onboarding_t.updated_at, fn.Now())
        .where(onboarding_t.id == Parameter("%s"))
        .where(
            onboarding_t.user_id.isnull()
            | (onboarding_t.user_id == Parameter("%s"))
        ),
        [user_id, onboarding_id, user_id],
    )
    await conn.execute(q.sql, *q.params)


async def delete_by_user_id(conn, user_id: str) -> None:
    q = build_query(
        PostgreSQLQuery.from_(onboarding_t).delete()
        .where(onboarding_t.user_id == Parameter("%s")),
        [user_id],
    )
    await conn.execute(q.sql, *q.params)


async def delete_by_session_id(conn, session_id: str) -> None:
    q = build_query(
        PostgreSQLQuery.from_(onboarding_t).delete()
        .where(onboarding_t.session_id == Parameter("%s")),
        [session_id],
    )
    await conn.execute(q.sql, *q.params)