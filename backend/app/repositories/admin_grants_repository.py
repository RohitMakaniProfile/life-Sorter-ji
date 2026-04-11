from __future__ import annotations

from typing import Any
from uuid import UUID

from pypika import Order, Table, functions as fn
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter

from app.sql_builder import build_query

admin_grants_t = Table("admin_subscription_grants")
grant_logs_t = Table("admin_subscription_grant_logs")

# Aliased user tables for joins
_users_t = Table("users")
_u_target = _users_t.as_("u_target")
_u_granted_by = _users_t.as_("u_granted_by")
_u_revoked_by = _users_t.as_("u_revoked_by")
_u_admin = _users_t.as_("u_admin")


async def has_active_grant(conn, user_id: UUID) -> bool:
    q = build_query(
        PostgreSQLQuery.from_(admin_grants_t)
        .select(admin_grants_t.id)
        .where(admin_grants_t.user_id == Parameter("%s"))
        .where(admin_grants_t.is_active.isin([True]))
        .limit(1),
        [user_id],
    )
    return (await conn.fetchrow(q.sql, *q.params)) is not None


async def find_active_with_granter(conn, user_id: UUID) -> Any:
    """Full grant row with granted_by email — used in get_admin_subscription_grant."""
    q = build_query(
        PostgreSQLQuery.from_(admin_grants_t)
        .left_join(_u_granted_by)
        .on(_u_granted_by.id == admin_grants_t.granted_by_user_id)
        .select(
            admin_grants_t.id, admin_grants_t.user_id, admin_grants_t.granted_by_user_id,
            admin_grants_t.reason, admin_grants_t.is_active, admin_grants_t.granted_at,
            _u_granted_by.email.as_("granted_by_email"),
        )
        .where(admin_grants_t.user_id == Parameter("%s"))
        .where(admin_grants_t.is_active.isin([True]))
        .limit(1),
        [user_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def upsert_grant(conn, target_uid: UUID, admin_uid: UUID, reason: str) -> None:
    q = build_query(
        PostgreSQLQuery.into(admin_grants_t)
        .columns(
            admin_grants_t.user_id, admin_grants_t.granted_by_user_id,
            admin_grants_t.reason, admin_grants_t.is_active, admin_grants_t.granted_at,
            admin_grants_t.revoked_at, admin_grants_t.revoked_by_user_id,
        )
        .insert(Parameter("%s"), Parameter("%s"), Parameter("%s"), True, fn.Now(), None, None)
        .on_conflict(admin_grants_t.user_id)
        .do_update(admin_grants_t.granted_by_user_id)
        .do_update(admin_grants_t.reason)
        .do_update(admin_grants_t.is_active)
        .do_update(admin_grants_t.granted_at)
        .do_update(admin_grants_t.revoked_at)
        .do_update(admin_grants_t.revoked_by_user_id),
        [target_uid, admin_uid, reason],
    )
    await conn.execute(q.sql, *q.params)


async def find_active_grant_id(conn, user_id: UUID) -> Any:
    """Check for an active grant — returns row with id, or None."""
    q = build_query(
        PostgreSQLQuery.from_(admin_grants_t)
        .select(admin_grants_t.id)
        .where(admin_grants_t.user_id == Parameter("%s"))
        .where(admin_grants_t.is_active.isin([True])),
        [user_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def revoke_grant(conn, target_uid: UUID, admin_uid: UUID) -> None:
    q = build_query(
        PostgreSQLQuery.update(admin_grants_t)
        .set(admin_grants_t.is_active, False)
        .set(admin_grants_t.revoked_at, fn.Now())
        .set(admin_grants_t.revoked_by_user_id, Parameter("%s"))
        .where(admin_grants_t.user_id == Parameter("%s")),
        [admin_uid, target_uid],
    )
    await conn.execute(q.sql, *q.params)


async def find_all_with_user_details(conn) -> list[Any]:
    q = build_query(
        PostgreSQLQuery.from_(admin_grants_t)
        .join(_u_target).on(_u_target.id == admin_grants_t.user_id)
        .left_join(_u_granted_by).on(_u_granted_by.id == admin_grants_t.granted_by_user_id)
        .left_join(_u_revoked_by).on(_u_revoked_by.id == admin_grants_t.revoked_by_user_id)
        .select(
            admin_grants_t.id, admin_grants_t.user_id, admin_grants_t.granted_by_user_id,
            admin_grants_t.reason, admin_grants_t.is_active, admin_grants_t.granted_at,
            admin_grants_t.revoked_at, admin_grants_t.revoked_by_user_id,
            _u_target.email.as_("user_email"), _u_target.phone_number.as_("user_phone"),
            _u_granted_by.email.as_("granted_by_email"),
            _u_revoked_by.email.as_("revoked_by_email"),
        )
        .orderby(admin_grants_t.granted_at, order=Order.desc)
    )
    return list(await conn.fetch(q.sql, *q.params))


# ── Grant Logs ────────────────────────────────────────────────────────────────

async def insert_log(conn, target_uid: UUID, action: str, admin_uid: UUID, reason: str) -> None:
    q = build_query(
        PostgreSQLQuery.into(grant_logs_t)
        .columns(grant_logs_t.target_user_id, grant_logs_t.action,
                 grant_logs_t.admin_user_id, grant_logs_t.reason)
        .insert(Parameter("%s"), Parameter("%s"), Parameter("%s"), Parameter("%s")),
        [target_uid, action, admin_uid, reason],
    )
    await conn.execute(q.sql, *q.params)


async def find_audit_log(conn, target_user_id: UUID | None = None, limit: int = 100) -> list[Any]:
    base = (
        PostgreSQLQuery.from_(grant_logs_t)
        .join(_u_target).on(_u_target.id == grant_logs_t.target_user_id)
        .left_join(_u_admin).on(_u_admin.id == grant_logs_t.admin_user_id)
        .select(
            grant_logs_t.id, grant_logs_t.target_user_id, grant_logs_t.action,
            grant_logs_t.admin_user_id, grant_logs_t.reason, grant_logs_t.created_at,
            _u_target.email.as_("target_email"), _u_admin.email.as_("admin_email"),
        )
    )
    if target_user_id:
        q = build_query(
            base.where(grant_logs_t.target_user_id == Parameter("%s"))
            .orderby(grant_logs_t.created_at, order=Order.desc).limit(limit),
            [target_user_id],
        )
    else:
        q = build_query(
            base.orderby(grant_logs_t.created_at, order=Order.desc).limit(limit)
        )
    return list(await conn.fetch(q.sql, *q.params))