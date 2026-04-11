from __future__ import annotations

from pypika import Table, functions as fn
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter

from app.sql_builder import build_query

report_link_sms_logs_t = Table("report_link_sms_logs")


async def check_sent(conn, conversation_id: str) -> bool:
    """Return True if an SMS was already sent for this conversation."""
    q = build_query(
        PostgreSQLQuery.from_(report_link_sms_logs_t).select(1)
        .where(report_link_sms_logs_t.conversation_id == Parameter("%s"))
        .where(report_link_sms_logs_t.status == "sent")
        .limit(1),
        [conversation_id],
    )
    return bool(await conn.fetchval(q.sql, *q.params))


async def upsert_log(
    conn,
    conversation_id: str,
    user_id: str,
    status: str,
    provider_message_id: str = "",
    error: str = "",
) -> None:
    """Upsert an SMS delivery log (conflict on conversation_id)."""
    q = build_query(
        PostgreSQLQuery.into(report_link_sms_logs_t)
        .columns(
            report_link_sms_logs_t.conversation_id,
            report_link_sms_logs_t.user_id,
            report_link_sms_logs_t.status,
            report_link_sms_logs_t.provider_message_id,
            report_link_sms_logs_t.error,
            report_link_sms_logs_t.updated_at,
        )
        .insert(
            Parameter("%s"), Parameter("%s"), Parameter("%s"),
            Parameter("%s"), Parameter("%s"), fn.Now(),
        )
        .on_conflict(report_link_sms_logs_t.conversation_id)
        .do_update(report_link_sms_logs_t.status)
        .do_update(report_link_sms_logs_t.provider_message_id)
        .do_update(report_link_sms_logs_t.error)
        .do_update(report_link_sms_logs_t.updated_at),
        [conversation_id, user_id, status, provider_message_id, error],
    )
    await conn.execute(q.sql, *q.params)