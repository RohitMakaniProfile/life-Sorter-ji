from __future__ import annotations

from typing import Any

from pypika import Case, Order, Table, functions as fn
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter

from app.sql_builder import build_query

users_t = Table("users")

_SELECT_COLS = (
    users_t.id.as_("id"),
    users_t.phone_number,
    users_t.email,
    users_t.name,
    users_t.auth_provider,
    users_t.onboarding_session_id,
    users_t.last_login_at,
)

_SELECT_ADMIN_COLS = (
    users_t.id,
    users_t.email,
    users_t.phone_number,
    users_t.name,
    users_t.auth_provider,
    users_t.created_at,
    users_t.last_login_at,
)


async def find_by_id(conn, user_id: Any) -> Any:
    q = build_query(
        PostgreSQLQuery.from_(users_t).select(*_SELECT_COLS)
        .where(users_t.id == Parameter("%s")).limit(1),
        [user_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def find_by_phone(conn, phone: str) -> Any:
    q = build_query(
        PostgreSQLQuery.from_(users_t).select(*_SELECT_COLS)
        .where(users_t.phone_number == Parameter("%s")).limit(1),
        [phone],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def find_by_email(conn, email: str) -> Any:
    q = build_query(
        PostgreSQLQuery.from_(users_t).select(*_SELECT_COLS)
        .where(users_t.email == Parameter("%s")).limit(1),
        [email],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def phone_used_by_other(conn, phone: str, exclude_user_id: Any) -> Any:
    """Return row if this phone is already claimed by a different user."""
    q = build_query(
        PostgreSQLQuery.from_(users_t).select(users_t.id.as_("id"))
        .where(users_t.phone_number == Parameter("%s"))
        .where(users_t.id != Parameter("%s")).limit(1),
        [phone, exclude_user_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def email_used_by_other(conn, email: str, exclude_user_id: Any) -> Any:
    """Return row if this email is already claimed by a different user."""
    q = build_query(
        PostgreSQLQuery.from_(users_t).select(users_t.id.as_("id"))
        .where(users_t.email == Parameter("%s"))
        .where(users_t.id != Parameter("%s")).limit(1),
        [email, exclude_user_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def exists_by_id(conn, user_id: Any) -> bool:
    q = build_query(
        PostgreSQLQuery.from_(users_t).select(1)
        .where(users_t.id == Parameter("%s")).limit(1),
        [user_id],
    )
    return bool(await conn.fetchval(q.sql, *q.params))


async def exists_by_email(conn, email: str) -> bool:
    q = build_query(
        PostgreSQLQuery.from_(users_t).select(1)
        .where(users_t.email == Parameter("%s")).limit(1),
        [email],
    )
    return bool(await conn.fetchval(q.sql, *q.params))


async def insert_otp_user(conn, phone: str, onboarding_session_id: str | None) -> Any:
    q = build_query(
        PostgreSQLQuery.into(users_t)
        .columns(users_t.phone_number, users_t.name, users_t.auth_provider,
                 users_t.onboarding_session_id, users_t.last_login_at)
        .insert(Parameter("%s"), "", "otp", Parameter("%s"), fn.Now())
        .returning(*_SELECT_COLS),
        [phone, onboarding_session_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def insert_google_user(conn, email: str, name: str, onboarding_session_id: str | None) -> Any:
    q = build_query(
        PostgreSQLQuery.into(users_t)
        .columns(users_t.email, users_t.name, users_t.auth_provider,
                 users_t.onboarding_session_id, users_t.last_login_at)
        .insert(Parameter("%s"), Parameter("%s"), "google", Parameter("%s"), fn.Now())
        .returning(*_SELECT_COLS),
        [email, name, onboarding_session_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def update_on_otp_login(conn, user_id: Any, provider: str, onboarding_session_id: str | None) -> Any:
    q = build_query(
        PostgreSQLQuery.update(users_t)
        .set(users_t.last_login_at, fn.Now())
        .set(users_t.auth_provider, Parameter("%s"))
        .set(users_t.onboarding_session_id, fn.Coalesce(Parameter("%s"), users_t.onboarding_session_id))
        .set(users_t.updated_at, fn.Now())
        .where(users_t.id == Parameter("%s"))
        .returning(*_SELECT_COLS),
        [provider, onboarding_session_id, user_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def update_on_google_login(conn, user_id: Any, name: str, provider: str, onboarding_session_id: str | None) -> Any:
    q = build_query(
        PostgreSQLQuery.update(users_t)
        .set(users_t.name, fn.Coalesce(Parameter("%s"), users_t.name))
        .set(users_t.auth_provider, Parameter("%s"))
        .set(users_t.onboarding_session_id, fn.Coalesce(Parameter("%s"), users_t.onboarding_session_id))
        .set(users_t.last_login_at, fn.Now())
        .set(users_t.updated_at, fn.Now())
        .where(users_t.id == Parameter("%s"))
        .returning(*_SELECT_COLS),
        [name, provider, onboarding_session_id, user_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def link_phone(conn, user_id: Any, phone: str) -> Any:
    q = build_query(
        PostgreSQLQuery.update(users_t)
        .set(users_t.phone_number, Parameter("%s"))
        .set(
            users_t.auth_provider,
            Case().when(users_t.auth_provider == "google", "both").else_(users_t.auth_provider),
        )
        .set(users_t.updated_at, fn.Now())
        .where(users_t.id == Parameter("%s"))
        .returning(*_SELECT_COLS),
        [phone, user_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def link_email(conn, user_id: Any, email: str, name: str | None) -> Any:
    q = build_query(
        PostgreSQLQuery.update(users_t)
        .set(users_t.email, Parameter("%s"))
        .set(users_t.name, fn.Coalesce(Parameter("%s"), users_t.name))
        .set(
            users_t.auth_provider,
            Case().when(users_t.auth_provider == "otp", "both").else_(users_t.auth_provider),
        )
        .set(users_t.updated_at, fn.Now())
        .where(users_t.id == Parameter("%s"))
        .returning(*_SELECT_COLS),
        [email, name, user_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def delete_by_id(conn, user_id: Any) -> None:
    q = build_query(
        PostgreSQLQuery.from_(users_t).delete().where(users_t.id == Parameter("%s")),
        [user_id],
    )
    await conn.execute(q.sql, *q.params)


async def list_admin(conn, search: str | None, limit: int, offset: int) -> tuple[list[Any], int]:
    """Return (rows, total) for admin user listing. Search matches email/phone/name."""
    base = PostgreSQLQuery.from_(users_t)
    if search:
        pattern = f"%{search}%"
        filter_cond = (
            users_t.email.ilike(Parameter("%s"))
            | users_t.phone_number.ilike(Parameter("%s"))
            | users_t.name.ilike(Parameter("%s"))
        )
        rows_q = build_query(
            base.select(*_SELECT_ADMIN_COLS).where(filter_cond)
            .orderby(users_t.created_at, order=Order.desc)
            .limit(Parameter("%s")).offset(Parameter("%s")),
            [pattern, pattern, pattern, limit, offset],
        )
        count_q = build_query(
            base.select(fn.Count(1)).where(filter_cond),
            [pattern, pattern, pattern],
        )
    else:
        rows_q = build_query(
            base.select(*_SELECT_ADMIN_COLS)
            .orderby(users_t.created_at, order=Order.desc)
            .limit(Parameter("%s")).offset(Parameter("%s")),
            [limit, offset],
        )
        count_q = build_query(base.select(fn.Count(1)))

    rows = await conn.fetch(rows_q.sql, *rows_q.params)
    total = await conn.fetchval(count_q.sql, *count_q.params)
    return list(rows), int(total or 0)


async def search_for_grant(conn, query: str, limit: int = 20) -> list[Any]:
    """Search users by email/phone for admin grant UI; includes active_grant_id via LEFT JOIN."""
    from app.repositories.admin_grants_repository import admin_grants_t
    asg = admin_grants_t.as_("asg_search")
    q = build_query(
        PostgreSQLQuery.from_(users_t)
        .left_join(asg)
        .on((asg.user_id == users_t.id) & (asg.is_active.isin([True])))
        .select(
            users_t.id, users_t.email, users_t.phone_number, users_t.created_at,
            asg.id.as_("active_grant_id"),
        )
        .where(users_t.email.ilike(Parameter("%s")) | users_t.phone_number.ilike(Parameter("%s")))
        .orderby(users_t.created_at, order=Order.desc)
        .limit(limit),
        [f"%{query}%", f"%{query}%"],
    )
    return list(await conn.fetch(q.sql, *q.params))


async def find_with_onboarding_session(conn, user_id: Any) -> Any:
    """Fetch user with onboarding_session_id — used for user deletion and auth/me."""
    q = build_query(
        PostgreSQLQuery.from_(users_t)
        .select(users_t.id, users_t.email, users_t.phone_number, users_t.onboarding_session_id)
        .where(users_t.id == Parameter("%s")).limit(1),
        [user_id],
    )
    return await conn.fetchrow(q.sql, *q.params)


async def find_phone_by_id(conn, user_id: Any) -> str | None:
    """Return phone_number for a user (used for SMS sending)."""
    q = build_query(
        PostgreSQLQuery.from_(users_t).select(users_t.phone_number)
        .where(users_t.id == Parameter("%s")).limit(1),
        [user_id],
    )
    v = await conn.fetchval(q.sql, *q.params)
    return str(v).strip() if v else None