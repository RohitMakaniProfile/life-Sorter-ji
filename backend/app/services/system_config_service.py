from __future__ import annotations

import json
from typing import Literal

from app.db import get_pool

ConfigType = Literal["string", "number", "boolean", "json", "markdown"]
VALID_TYPES: set[str] = {"string", "number", "boolean", "json", "markdown"}


async def get_config_value(key: str, default: str = "") -> str:
    pool = get_pool()
    async with pool.acquire() as conn:
        v = await conn.fetchval("SELECT value FROM system_config WHERE key = $1", key)
    if v is None:
        return default
    return str(v)


async def get_config_with_type(key: str) -> tuple[str, str] | None:
    """Return (value, type) tuple or None if not found."""
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT value, type FROM system_config WHERE key = $1", key
        )
    if row is None:
        return None
    return (str(row.get("value") or ""), str(row.get("type") or "string"))


def validate_value_for_type(value: str, config_type: str) -> tuple[bool, str]:
    """
    Validate a value against its declared type.
    Returns (is_valid, error_message).
    """
    if config_type == "string" or config_type == "markdown":
        # Any string is valid
        return True, ""

    if config_type == "number":
        try:
            float(value)
            return True, ""
        except ValueError:
            return False, f"Value must be a valid number, got: {value!r}"

    if config_type == "boolean":
        lower = value.strip().lower()
        if lower in ("true", "false", "1", "0", "yes", "no", "on", "off"):
            return True, ""
        return False, f"Value must be a boolean (true/false/1/0/yes/no), got: {value!r}"

    if config_type == "json":
        try:
            json.loads(value)
            return True, ""
        except json.JSONDecodeError as e:
            return False, f"Value must be valid JSON: {e}"

    return True, ""  # Unknown type, allow anything


async def upsert_system_config_entry(
    key: str,
    value: str,
    description: str = "",
    config_type: str | None = None,
) -> None:
    """
    Insert/update a system_config row.

    Used by dev bootstrap so values in env become visible/editable in `/admin/config`.
    If config_type is None, keeps existing type or defaults to 'string'.
    """
    k = str(key or "").strip()
    v = str(value or "")
    d = str(description or "")
    if not k:
        return

    # Validate type
    t = config_type if config_type in VALID_TYPES else None

    pool = get_pool()
    async with pool.acquire() as conn:
        if t is not None:
            # Validate value against type
            is_valid, err = validate_value_for_type(v, t)
            if not is_valid:
                raise ValueError(err)

            await conn.execute(
                """
                INSERT INTO system_config (key, value, type, description)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (key)
                DO UPDATE SET
                  value = EXCLUDED.value,
                  type = EXCLUDED.type,
                  description = EXCLUDED.description
                """,
                k,
                v,
                t,
                d,
            )
        else:
            # Keep existing type, or default to 'string'
            existing = await conn.fetchval(
                "SELECT type FROM system_config WHERE key = $1", k
            )
            existing_type = str(existing or "string")

            # Validate value against existing/default type
            is_valid, err = validate_value_for_type(v, existing_type)
            if not is_valid:
                raise ValueError(err)

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

