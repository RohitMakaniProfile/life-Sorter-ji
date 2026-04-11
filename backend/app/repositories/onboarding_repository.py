from __future__ import annotations

import json
from typing import Any

from pypika import Order, Table, functions as fn
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter, LiteralValue

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


# ── Columns used for full state reads (router / journey) ──────────────────────

_STATE_COLS = (
    onboarding_t.id,
    onboarding_t.outcome,
    onboarding_t.domain,
    onboarding_t.task,
    onboarding_t.website_url,
    onboarding_t.gbp_url,
    onboarding_t.business_profile,
    onboarding_t.scale_answers,
    onboarding_t.rca_qa,
    onboarding_t.rca_summary,
    onboarding_t.rca_handoff,
    onboarding_t.precision_questions,
    onboarding_t.precision_answers,
    onboarding_t.precision_status,
    onboarding_t.playbook_status,
    onboarding_t.playbook_error,
    onboarding_t.gap_questions,
    onboarding_t.gap_answers,
    onboarding_t.onboarding_completed_at,
)


def _cast_jsonb(param: Parameter) -> LiteralValue:
    """Cast a parameter to jsonb type."""
    return LiteralValue(f"{param}::jsonb")


# ── State reads ───────────────────────────────────────────────────────────────

async def find_full_state(conn, onboarding_id: str) -> Any:
    """Fetch full onboarding state for router status endpoints (by id)."""
    q = build_query(
        PostgreSQLQuery.from_(onboarding_t)
        .select(*_STATE_COLS)
        .where(onboarding_t.id == Parameter("%s")),
        [onboarding_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def find_latest_incomplete_by_user(conn, user_id: str) -> Any:
    """Fetch latest non-complete onboarding row for a user (router status fallback)."""
    q = build_query(
        PostgreSQLQuery.from_(onboarding_t)
        .select(*_STATE_COLS)
        .where(onboarding_t.user_id == Parameter("%s"))
        .where(onboarding_t.onboarding_completed_at.isnull())
        .where(onboarding_t.playbook_status != Parameter("%s"))
        .orderby(onboarding_t.created_at, order=Order.desc)
        .limit(1),
        [user_id, "complete"],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def find_latest_id_by_user(conn, user_id: str) -> str | None:
    """Return latest onboarding id for authenticated user."""
    q = build_query(
        PostgreSQLQuery.from_(onboarding_t)
        .select(onboarding_t.id)
        .where(onboarding_t.user_id == Parameter("%s"))
        .orderby(onboarding_t.created_at, order=Order.desc)
        .limit(1),
        [user_id],
    )
    v = await conn.fetchval(q.sql, *q.params)
    return str(v) if v else None


# ── Playbook launch helpers ───────────────────────────────────────────────────

async def find_gap_launch_state(conn, onboarding_id: str) -> Any:
    """Fetch gap_questions, gap_answers, playbook_status for playbook launch."""
    q = build_query(
        PostgreSQLQuery.from_(onboarding_t)
        .select(onboarding_t.id, onboarding_t.gap_questions,
                onboarding_t.gap_answers, onboarding_t.playbook_status)
        .where(onboarding_t.id == Parameter("%s")),
        [onboarding_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def set_playbook_starting(conn, onboarding_id: str) -> None:
    """Mark onboarding playbook as starting."""
    q = build_query(
        PostgreSQLQuery.update(onboarding_t)
        .set(onboarding_t.playbook_status, "starting")
        .set(onboarding_t.playbook_started_at,
             fn.Coalesce(onboarding_t.playbook_started_at, fn.Now()))
        .set(onboarding_t.playbook_error, "")
        .set(onboarding_t.updated_at, fn.Now())
        .where(onboarding_t.id == Parameter("%s")),
        [onboarding_id],
    )
    await conn.execute(q.sql, *q.params)


async def set_conversation_id(conn, onboarding_id: str, conversation_id: str) -> None:
    """Link a conversation_id to the onboarding row."""
    q = build_query(
        PostgreSQLQuery.update(onboarding_t)
        .set(onboarding_t.conversation_id, Parameter("%s"))
        .set(onboarding_t.updated_at, fn.Now())
        .where(onboarding_t.id == Parameter("%s")),
        [conversation_id, onboarding_id],
    )
    await conn.execute(q.sql, *q.params)


# ── Gap answers ───────────────────────────────────────────────────────────────

async def set_gap_answers_ready(conn, onboarding_id: str, answers: str) -> None:
    """Persist gap answers and mark onboarding as ready for playbook."""
    q = build_query(
        PostgreSQLQuery.update(onboarding_t)
        .set(onboarding_t.gap_answers, Parameter("%s"))
        .set(onboarding_t.playbook_status, "ready")
        .set(onboarding_t.updated_at, fn.Now())
        .where(onboarding_t.id == Parameter("%s")),
        [answers, onboarding_id],
    )
    await conn.execute(q.sql, *q.params)


async def find_mcq_gap_state(conn, onboarding_id: str) -> Any:
    """Fetch gap_questions and gap_answers for MCQ answer endpoint."""
    q = build_query(
        PostgreSQLQuery.from_(onboarding_t)
        .select(onboarding_t.id, onboarding_t.gap_questions, onboarding_t.gap_answers)
        .where(onboarding_t.id == Parameter("%s")).limit(1),
        [onboarding_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def update_gap_answers(conn, onboarding_id: str, answers: str, status: str) -> None:
    """Update gap_answers and playbook_status (MCQ answer endpoint)."""
    q = build_query(
        PostgreSQLQuery.update(onboarding_t)
        .set(onboarding_t.gap_answers, Parameter("%s"))
        .set(onboarding_t.playbook_status, Parameter("%s"))
        .set(onboarding_t.updated_at, fn.Now())
        .where(onboarding_t.id == Parameter("%s")),
        [answers, status, onboarding_id],
    )
    await conn.execute(q.sql, *q.params)


# ── Precision questions ───────────────────────────────────────────────────────

async def find_precision_context(conn, onboarding_id: str) -> Any:
    """Fetch context needed for precision question generation."""
    q = build_query(
        PostgreSQLQuery.from_(onboarding_t)
        .select(
            onboarding_t.outcome, onboarding_t.domain, onboarding_t.task,
            onboarding_t.scale_answers, onboarding_t.rca_qa,
            onboarding_t.web_summary, onboarding_t.business_profile,
        )
        .where(onboarding_t.id == Parameter("%s")),
        [onboarding_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def mark_precision_empty(conn, onboarding_id: str) -> None:
    """Mark precision as complete with empty questions (no questions generated)."""
    q = build_query(
        PostgreSQLQuery.update(onboarding_t)
        .set(onboarding_t.precision_questions, _cast_jsonb(Parameter("%s")))
        .set(onboarding_t.precision_answers, _cast_jsonb(Parameter("%s")))
        .set(onboarding_t.precision_status, "complete")
        .set(onboarding_t.precision_completed_at, fn.Now())
        .set(onboarding_t.updated_at, fn.Now())
        .where(onboarding_t.id == Parameter("%s")),
        [json.dumps([]), json.dumps([]), onboarding_id],
    )
    await conn.execute(q.sql, *q.params)


async def save_precision_questions(conn, onboarding_id: str, questions_json: str) -> None:
    """Persist generated precision questions and set status to awaiting_answers."""
    q = build_query(
        PostgreSQLQuery.update(onboarding_t)
        .set(onboarding_t.precision_questions, _cast_jsonb(Parameter("%s")))
        .set(onboarding_t.precision_answers, _cast_jsonb(Parameter("%s")))
        .set(onboarding_t.precision_status, "awaiting_answers")
        .set(onboarding_t.precision_completed_at, None)
        .set(onboarding_t.updated_at, fn.Now())
        .where(onboarding_t.id == Parameter("%s")),
        [questions_json, json.dumps([]), onboarding_id],
    )
    await conn.execute(q.sql, *q.params)


async def find_precision_state(conn, onboarding_id: str) -> Any:
    """Fetch precision_questions, precision_answers, questions_answers for answer endpoint."""
    q = build_query(
        PostgreSQLQuery.from_(onboarding_t)
        .select(
            onboarding_t.id, onboarding_t.precision_questions,
            onboarding_t.precision_answers, onboarding_t.questions_answers,
        )
        .where(onboarding_t.id == Parameter("%s")),
        [onboarding_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def mark_precision_complete(conn, onboarding_id: str, answers_json: str, qa_json: str) -> None:
    """Mark precision questions as fully answered."""
    q = build_query(
        PostgreSQLQuery.update(onboarding_t)
        .set(onboarding_t.precision_answers, _cast_jsonb(Parameter("%s")))
        .set(onboarding_t.precision_status, "complete")
        .set(onboarding_t.precision_completed_at, fn.Now())
        .set(onboarding_t.questions_answers, _cast_jsonb(Parameter("%s")))
        .set(onboarding_t.updated_at, fn.Now())
        .where(onboarding_t.id == Parameter("%s")),
        [answers_json, qa_json, onboarding_id],
    )
    await conn.execute(q.sql, *q.params)


async def update_precision_progress(conn, onboarding_id: str, answers_json: str, qa_json: str) -> None:
    """Save partial precision answers (more questions remaining)."""
    q = build_query(
        PostgreSQLQuery.update(onboarding_t)
        .set(onboarding_t.precision_answers, _cast_jsonb(Parameter("%s")))
        .set(onboarding_t.precision_status, "awaiting_answers")
        .set(onboarding_t.questions_answers, _cast_jsonb(Parameter("%s")))
        .set(onboarding_t.updated_at, fn.Now())
        .where(onboarding_t.id == Parameter("%s")),
        [answers_json, qa_json, onboarding_id],
    )
    await conn.execute(q.sql, *q.params)


# ── Gap questions generation ──────────────────────────────────────────────────

async def find_gap_questions_context(conn, onboarding_id: str) -> Any:
    """Fetch context for gap question generation."""
    q = build_query(
        PostgreSQLQuery.from_(onboarding_t)
        .select(
            onboarding_t.outcome, onboarding_t.domain, onboarding_t.task,
            onboarding_t.scale_answers, onboarding_t.rca_qa,
            onboarding_t.rca_summary, onboarding_t.rca_handoff,
            onboarding_t.web_summary, onboarding_t.precision_questions,
            onboarding_t.precision_answers,
        )
        .where(onboarding_t.id == Parameter("%s")),
        [onboarding_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def set_gap_questions_ready(conn, onboarding_id: str) -> None:
    """Persist empty gap questions and mark onboarding as ready for playbook."""
    q = build_query(
        PostgreSQLQuery.update(onboarding_t)
        .set(onboarding_t.gap_questions, _cast_jsonb(Parameter("%s")))
        .set(onboarding_t.playbook_status, "ready")
        .set(onboarding_t.updated_at, fn.Now())
        .where(onboarding_t.id == Parameter("%s")),
        [json.dumps([]), onboarding_id],
    )
    await conn.execute(q.sql, *q.params)


async def set_gap_questions_awaiting(conn, onboarding_id: str, questions_json: str) -> None:
    """Persist gap questions and mark onboarding as awaiting gap answers."""
    q = build_query(
        PostgreSQLQuery.update(onboarding_t)
        .set(onboarding_t.gap_questions, _cast_jsonb(Parameter("%s")))
        .set(onboarding_t.playbook_status, "awaiting_gap_answers")
        .set(onboarding_t.updated_at, fn.Now())
        .where(onboarding_t.id == Parameter("%s")),
        [questions_json, onboarding_id],
    )
    await conn.execute(q.sql, *q.params)


# ── Playbook generation task ──────────────────────────────────────────────────

async def find_for_playbook_generation(conn, onboarding_id: str) -> Any:
    """Fetch all fields needed for playbook generation task."""
    q = build_query(
        PostgreSQLQuery.from_(onboarding_t)
        .select(
            onboarding_t.id, onboarding_t.user_id,
            onboarding_t.outcome, onboarding_t.domain, onboarding_t.task,
            onboarding_t.website_url, onboarding_t.scale_answers,
            onboarding_t.rca_qa, onboarding_t.rca_summary, onboarding_t.rca_handoff,
            onboarding_t.gap_answers, onboarding_t.web_summary,
        )
        .where(onboarding_t.id == Parameter("%s")).limit(1),
        [onboarding_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def set_playbook_generating(conn, onboarding_id: str, playbook_run_id: Any) -> None:
    """Mark onboarding as generating a playbook, link the playbook_run_id."""
    q = build_query(
        PostgreSQLQuery.update(onboarding_t)
        .set(onboarding_t.playbook_status, "generating")
        .set(onboarding_t.playbook_run_id, Parameter("%s"))
        .set(onboarding_t.playbook_error, "")
        .set(onboarding_t.updated_at, fn.Now())
        .where(onboarding_t.id == Parameter("%s")),
        [playbook_run_id, onboarding_id],
    )
    await conn.execute(q.sql, *q.params)


async def set_playbook_complete(conn, onboarding_id: str) -> None:
    """Mark onboarding as playbook complete, set completion timestamps."""
    q = build_query(
        PostgreSQLQuery.update(onboarding_t)
        .set(onboarding_t.playbook_status, "complete")
        .set(onboarding_t.playbook_completed_at, fn.Now())
        .set(onboarding_t.onboarding_completed_at,
             fn.Coalesce(onboarding_t.onboarding_completed_at, fn.Now()))
        .set(onboarding_t.updated_at, fn.Now())
        .where(onboarding_t.id == Parameter("%s")),
        [onboarding_id],
    )
    await conn.execute(q.sql, *q.params)


async def set_playbook_error(conn, onboarding_id: str, error_message: str) -> None:
    """Mark onboarding playbook generation as errored."""
    q = build_query(
        PostgreSQLQuery.update(onboarding_t)
        .set(onboarding_t.playbook_status, "error")
        .set(onboarding_t.playbook_error, Parameter("%s"))
        .set(onboarding_t.updated_at, fn.Now())
        .where(onboarding_t.id == Parameter("%s")),
        [error_message, onboarding_id],
    )
    await conn.execute(q.sql, *q.params)


# ── Crawl service helpers ─────────────────────────────────────────────────────

async def find_crawl_context(conn, onboarding_id: str) -> Any:
    """Fetch context fields needed for crawl operations."""
    q = build_query(
        PostgreSQLQuery.from_(onboarding_t)
        .select(
            onboarding_t.outcome, onboarding_t.domain, onboarding_t.task,
            onboarding_t.scale_answers, onboarding_t.web_summary,
            onboarding_t.business_profile,
        )
        .where(onboarding_t.id == Parameter("%s")),
        [onboarding_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def update_crawl_outputs(conn, onboarding_id: str, web_summary: str, business_profile: str) -> None:
    """Persist web_summary and business_profile from crawl."""
    q = build_query(
        PostgreSQLQuery.update(onboarding_t)
        .set(onboarding_t.web_summary, Parameter("%s"))
        .set(onboarding_t.business_profile, Parameter("%s"))
        .set(onboarding_t.updated_at, fn.Now())
        .where(onboarding_t.id == Parameter("%s")),
        [web_summary, business_profile, onboarding_id],
    )
    await conn.execute(q.sql, *q.params)