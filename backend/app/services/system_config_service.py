from __future__ import annotations

from app.db import get_pool


async def get_config_value(key: str, default: str = "") -> str:
    pool = get_pool()
    async with pool.acquire() as conn:
        v = await conn.fetchval("SELECT value FROM system_config WHERE key = $1", key)
    if v is None:
        return default
    return str(v)


async def upsert_system_config_entry(key: str, value: str, description: str = "") -> None:
    """
    Insert/update a system_config row.

    Used by dev bootstrap so values in env become visible/editable in `/admin/config`.
    """
    k = str(key or "").strip()
    v = str(value or "")
    d = str(description or "")
    if not k:
        return

    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO system_config (key, value, description)
            VALUES ($1, $2, $3)
            ON CONFLICT (key)
            DO UPDATE SET
              value = EXCLUDED.value,
              description = EXCLUDED.description
            """,
            k,
            v,
            d,
        )


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    raw = str(value).strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default

