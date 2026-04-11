from __future__ import annotations

from typing import Any

from pypika import Order, Table
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter

from app.sql_builder import build_query

token_usage_t = Table("token_usage")


async def insert(
    conn,
    message_id: str,
    session_id: str | None,
    conversation_id: str | None,
    user_id: str | None,
    model_encoded: str,
    stage: str,
    provider: str,
    model_name: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float | None,
    cost_inr: float | None,
) -> None:
    q = build_query(
        PostgreSQLQuery.into(token_usage_t)
        .columns(
            token_usage_t.message_id, token_usage_t.session_id,
            token_usage_t.conversation_id, token_usage_t.user_id,
            token_usage_t.model, token_usage_t.stage, token_usage_t.provider,
            token_usage_t.model_name, token_usage_t.input_tokens,
            token_usage_t.output_tokens, token_usage_t.cost_usd, token_usage_t.cost_inr,
        )
        .insert(
            Parameter("%s"), Parameter("%s"), Parameter("%s"), Parameter("%s"),
            Parameter("%s"), Parameter("%s"), Parameter("%s"), Parameter("%s"),
            Parameter("%s"), Parameter("%s"), Parameter("%s"), Parameter("%s"),
        ),
        [message_id, session_id, conversation_id, user_id, model_encoded, stage,
         provider, model_name, input_tokens, output_tokens, cost_usd, cost_inr],
    )
    await conn.execute(q.sql, *q.params)


async def find_by_message_id(conn, message_id: str) -> list[Any]:
    q = build_query(
        PostgreSQLQuery.from_(token_usage_t)
        .select(
            token_usage_t.model, token_usage_t.stage, token_usage_t.provider,
            token_usage_t.model_name, token_usage_t.input_tokens, token_usage_t.output_tokens,
            token_usage_t.cost_usd, token_usage_t.cost_inr, token_usage_t.created_at,
        )
        .where(token_usage_t.message_id == Parameter("%s"))
        .orderby(token_usage_t.created_at, order=Order.asc),
        [message_id],
    )
    return list(await conn.fetch(q.sql, *q.params))


async def fetch_summary(conn) -> Any:
    """Admin: aggregate token usage summary across all users."""
    return await conn.fetchrow(
        "SELECT "
        "COALESCE(SUM(t.cost_inr), 0) AS spend_inr, "
        "COALESCE(SUM(t.input_tokens), 0) AS input_tokens, "
        "COALESCE(SUM(t.output_tokens), 0) AS output_tokens, "
        "COUNT(*) AS calls_count, "
        "COUNT(*) FILTER (WHERE t.cost_inr IS NULL) AS unknown_priced_calls, "
        "COUNT(DISTINCT t.user_id) AS users_count, "
        "(SELECT COALESCE(SUM(cost_inr), 0) FROM token_usage) AS overall_spend_inr, "
        "(SELECT COALESCE(SUM(input_tokens), 0) FROM token_usage) AS overall_input_tokens, "
        "(SELECT COALESCE(SUM(output_tokens), 0) FROM token_usage) AS overall_output_tokens, "
        "(SELECT COUNT(*) FROM token_usage) AS overall_calls_count, "
        "(SELECT COALESCE(SUM(cost_inr), 0) FROM token_usage WHERE user_id IS NULL) AS unlinked_spend_inr, "
        "(SELECT COUNT(*) FROM token_usage WHERE user_id IS NULL) AS unlinked_calls_count "
        "FROM token_usage t "
        "JOIN users u ON u.id::text = t.user_id "
        "WHERE t.user_id IS NOT NULL"
    )


async def fetch_users(conn, needle: str, limit: int, offset: int) -> list[Any]:
    """Admin: per-user token usage aggregates, filterable by email/phone."""
    return list(await conn.fetch(
        "SELECT u.id::text AS user_id, u.email, u.phone_number, "
        "COALESCE(SUM(t.cost_inr), 0) AS spend_inr, "
        "COALESCE(SUM(t.input_tokens), 0) AS input_tokens, "
        "COALESCE(SUM(t.output_tokens), 0) AS output_tokens, "
        "COUNT(*) AS calls_count "
        "FROM token_usage t "
        "JOIN users u ON u.id::text = t.user_id "
        "WHERE t.user_id IS NOT NULL "
        "AND ($1 = '%%' OR u.email ILIKE $1 OR u.phone_number ILIKE $1) "
        "GROUP BY u.id, u.email, u.phone_number "
        "ORDER BY spend_inr DESC, calls_count DESC "
        "LIMIT $2 OFFSET $3",
        needle, limit, offset,
    ))


async def fetch_user_conversations(conn, user_id: str, limit: int, offset: int) -> list[Any]:
    """Admin: per-conversation token usage for a user."""
    return list(await conn.fetch(
        "SELECT conversation_id, "
        "COALESCE(SUM(cost_inr), 0) AS spend_inr, "
        "COALESCE(SUM(input_tokens), 0) AS input_tokens, "
        "COALESCE(SUM(output_tokens), 0) AS output_tokens, "
        "COUNT(*) AS calls_count, "
        "MAX(created_at) AS last_used_at "
        "FROM token_usage "
        "WHERE user_id = $1 AND conversation_id IS NOT NULL "
        "GROUP BY conversation_id "
        "ORDER BY last_used_at DESC "
        "LIMIT $2 OFFSET $3",
        user_id, limit, offset,
    ))


async def fetch_conversation_calls(conn, conversation_id: str, limit: int, offset: int) -> list[Any]:
    """Admin: individual token usage rows for a conversation."""
    return list(await conn.fetch(
        "SELECT message_id, stage, provider, model_name, input_tokens, output_tokens, cost_inr, created_at "
        "FROM token_usage WHERE conversation_id = $1 "
        "ORDER BY created_at DESC LIMIT $2 OFFSET $3",
        conversation_id, limit, offset,
    ))