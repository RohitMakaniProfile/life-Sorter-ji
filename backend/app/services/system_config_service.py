from __future__ import annotations

import json
from typing import Literal

from pypika import Table
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter

from app.db import get_pool
from app.sql_builder import build_query

ConfigType = Literal["string", "number", "boolean", "json", "markdown"]
VALID_TYPES: set[str] = {"string", "number", "boolean", "json", "markdown"}
system_config_t = Table("system_config")


async def get_config_value(key: str, default: str = "") -> str:
    pool = get_pool()
    async with pool.acquire() as conn:
        get_value_q = build_query(
            PostgreSQLQuery.from_(system_config_t)
            .select(system_config_t.value)
            .where(system_config_t.key == Parameter("%s")),
            [key],
        )
        v = await conn.fetchval(get_value_q.sql, *get_value_q.params)
    if v is None:
        return default
    return str(v)


async def get_config_with_type(key: str) -> tuple[str, str] | None:
    """Return (value, type) tuple or None if not found."""
    pool = get_pool()
    async with pool.acquire() as conn:
        get_config_q = build_query(
            PostgreSQLQuery.from_(system_config_t)
            .select(system_config_t.value, system_config_t.type)
            .where(system_config_t.key == Parameter("%s")),
            [key],
        )
        row = await conn.fetchrow(get_config_q.sql, *get_config_q.params)
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

            upsert_typed_q = build_query(
                PostgreSQLQuery.into(system_config_t)
                .columns(
                    system_config_t.key,
                    system_config_t.value,
                    system_config_t.type,
                    system_config_t.description,
                )
                .insert(Parameter("%s"), Parameter("%s"), Parameter("%s"), Parameter("%s"))
                .on_conflict(system_config_t.key)
                .do_update(system_config_t.value)
                .do_update(system_config_t.type)
                .do_update(system_config_t.description),
                [k, v, t, d],
            )
            await conn.execute(upsert_typed_q.sql, *upsert_typed_q.params)
        else:
            # Keep existing type, or default to 'string'
            existing_type_q = build_query(
                PostgreSQLQuery.from_(system_config_t)
                .select(system_config_t.type)
                .where(system_config_t.key == Parameter("%s")),
                [k],
            )
            existing = await conn.fetchval(existing_type_q.sql, *existing_type_q.params)
            existing_type = str(existing or "string")

            # Validate value against existing/default type
            is_valid, err = validate_value_for_type(v, existing_type)
            if not is_valid:
                raise ValueError(err)

            upsert_untyped_q = build_query(
                PostgreSQLQuery.into(system_config_t)
                .columns(
                    system_config_t.key,
                    system_config_t.value,
                    system_config_t.description,
                )
                .insert(Parameter("%s"), Parameter("%s"), Parameter("%s"))
                .on_conflict(system_config_t.key)
                .do_update(system_config_t.value)
                .do_update(system_config_t.description),
                [k, v, d],
            )
            await conn.execute(upsert_untyped_q.sql, *upsert_untyped_q.params)


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    raw = str(value).strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default

