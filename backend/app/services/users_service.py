from __future__ import annotations

from app.db import get_pool


async def get_or_create_user_by_phone(phone: str) -> str:
    phone_n = (phone or "").strip()
    if not phone_n:
        raise ValueError("phone is required")
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id FROM users WHERE phone = $1", phone_n)
        if row:
            return str(row["id"])
        inserted = await conn.fetchrow(
            """
            INSERT INTO users (phone, auth_provider, phone_verified_at, last_login_at)
            VALUES ($1, 'otp', NOW(), NOW())
            RETURNING id
            """,
            phone_n,
        )
        assert inserted is not None
        return str(inserted["id"])


async def set_user_last_login(user_id: str) -> None:
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET last_login_at = NOW() WHERE id = $1::uuid", user_id)

