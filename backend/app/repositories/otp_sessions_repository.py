from __future__ import annotations

from datetime import datetime
from typing import Any

from pypika import Table, functions as fn
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter

from app.sql_builder import build_query

otp_sessions_t = Table("otp_sessions")
otp_provider_logs_t = Table("otp_provider_logs")


async def upsert_otp(conn, phone_key: str, payload_json: str, expires_at: datetime) -> None:
    """Upsert an OTP session (keyed on phone_number)."""
    q = build_query(
        PostgreSQLQuery.into(otp_sessions_t)
        .columns(otp_sessions_t.phone_number, otp_sessions_t.payload, otp_sessions_t.expires_at)
        .insert(Parameter("%s"), Parameter("%s"), Parameter("%s"))
        .on_conflict(otp_sessions_t.phone_number)
        .do_update(otp_sessions_t.payload)
        .do_update(otp_sessions_t.expires_at),
        [phone_key, payload_json, expires_at],
    )
    await conn.execute(q.sql, *q.params)


async def find_active_by_phone(conn, phone_key: str) -> Any:
    """Return payload for a non-expired OTP session."""
    q = build_query(
        PostgreSQLQuery.from_(otp_sessions_t)
        .select(otp_sessions_t.payload)
        .where(otp_sessions_t.phone_number == Parameter("%s"))
        .where(otp_sessions_t.expires_at > fn.Now()),
        [phone_key],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def delete_by_phone(conn, phone_key: str) -> None:
    """Delete OTP session for a phone number."""
    q = build_query(
        PostgreSQLQuery.from_(otp_sessions_t).delete()
        .where(otp_sessions_t.phone_number == Parameter("%s")),
        [phone_key],
    )
    await conn.execute(q.sql, *q.params)


async def insert_provider_log(
    conn,
    action: str,
    phone_masked: str,
    request_url: str,
    response_payload_json: str,
    provider_session_id: str,
    success: bool,
    error: str,
) -> None:
    """Log a 2Factor.in API call."""
    q = build_query(
        PostgreSQLQuery.into(otp_provider_logs_t)
        .columns(
            otp_provider_logs_t.action,
            otp_provider_logs_t.provider,
            otp_provider_logs_t.phone_masked,
            otp_provider_logs_t.request_url,
            otp_provider_logs_t.response_payload,
            otp_provider_logs_t.provider_session_id,
            otp_provider_logs_t.success,
            otp_provider_logs_t.error,
        )
        .insert(
            Parameter("%s"), Parameter("%s"), Parameter("%s"), Parameter("%s"),
            Parameter("%s"), Parameter("%s"), Parameter("%s"), Parameter("%s"),
        ),
        [
            action, "2factor", phone_masked, request_url,
            response_payload_json, provider_session_id, success, error,
        ],
    )
    await conn.execute(q.sql, *q.params)