from __future__ import annotations

from typing import Literal

from app.db import get_pool
from app.repositories import system_config_repository as config_repo

ConfigType = Literal["string", "number", "boolean", "json", "markdown"]
VALID_TYPES: set[str] = {"string", "number", "boolean", "json", "markdown"}


async def get_config_value(key: str, default: str = "") -> str:
    pool = get_pool()
    async with pool.acquire() as conn:
        v = await config_repo.get_value(conn, key)
    return v if v is not None else default


async def get_config_with_type(key: str) -> tuple[str, str] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await config_repo.get_value_and_type(conn, key)
    if row is None:
        return None
    return (str(row.get("value") or ""), str(row.get("type") or "string"))


def validate_value_for_type(value: str, config_type: str) -> tuple[bool, str]:
    import json
    if config_type in ("string", "markdown"):
        return True, ""
    if config_type == "number":
        try:
            float(value)
            return True, ""
        except ValueError:
            return False, f"Value must be a valid number, got: {value!r}"
    if config_type == "boolean":
        if value.strip().lower() in ("true", "false", "1", "0", "yes", "no", "on", "off"):
            return True, ""
        return False, f"Value must be a boolean (true/false/1/0/yes/no), got: {value!r}"
    if config_type == "json":
        try:
            json.loads(value)
            return True, ""
        except json.JSONDecodeError as e:
            return False, f"Value must be valid JSON: {e}"
    return True, ""


async def upsert_system_config_entry(
    key: str, value: str, description: str = "", config_type: str | None = None,
) -> None:
    k = str(key or "").strip()
    v = str(value or "")
    d = str(description or "")
    if not k:
        return

    t = config_type if config_type in VALID_TYPES else None
    pool = get_pool()
    async with pool.acquire() as conn:
        if t is not None:
            is_valid, err = validate_value_for_type(v, t)
            if not is_valid:
                raise ValueError(err)
            await config_repo.upsert_with_type(conn, k, v, t, d)
        else:
            existing_type = await config_repo.get_existing_type(conn, k)
            effective_type = existing_type or "string"
            is_valid, err = validate_value_for_type(v, effective_type)
            if not is_valid:
                raise ValueError(err)
            await config_repo.upsert_without_type(conn, k, v, d)


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    raw = str(value).strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default