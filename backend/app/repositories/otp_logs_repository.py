from __future__ import annotations

from typing import Any

from pypika import Order, Table
from pypika.dialects import PostgreSQLQuery

from app.sql_builder import build_query

otp_logs_t = Table("otp_provider_logs")


async def find_recent_failures(conn, limit: int = 20) -> list[Any]:
    q = build_query(
        PostgreSQLQuery.from_(otp_logs_t)
        .select(
            otp_logs_t.action, otp_logs_t.provider,
            otp_logs_t.phone_masked, otp_logs_t.error, otp_logs_t.created_at,
        )
        .where(otp_logs_t.success == False)  # noqa: E712
        .orderby(otp_logs_t.created_at, order=Order.desc)
        .limit(limit)
    )
    return list(await conn.fetch(q.sql, *q.params))