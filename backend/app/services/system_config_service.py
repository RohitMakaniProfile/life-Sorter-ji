from __future__ import annotations

from app.db import get_pool


async def get_config_value(key: str, default: str = "") -> str:
    pool = get_pool()
    async with pool.acquire() as conn:
        v = await conn.fetchval("SELECT value FROM system_config WHERE key = $1", key)
    if v is None:
        return default
    return str(v)


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    raw = str(value).strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default

