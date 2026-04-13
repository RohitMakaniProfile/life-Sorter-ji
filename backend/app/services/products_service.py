from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from asyncpg import UniqueViolationError

from app.db import get_pool
from app.repositories import products_repository as products_repo

PRODUCT_MUTABLE_FIELDS = [
    "name",
    "emoji",
    "description",
    "color",
    "outcome",
    "domain",
    "task",
    "isActive",
    "sortOrder",
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_product_row(r: Any) -> dict[str, Any]:
    return {
        "id": r["id"],
        "name": r["name"],
        "emoji": r["emoji"] or "🧩",
        "description": r["description"] or "",
        "color": r["color"] or "#857BFF",
        "outcome": r["outcome"] or "",
        "domain": r["domain"] or "",
        "task": r["task"] or "",
        "isActive": bool(r["is_active"]),
        "sortOrder": int(r["sort_order"] or 0),
        "createdAt": r["created_at"],
        "updatedAt": r["updated_at"],
    }


def _validate_required_fields(payload: dict[str, Any]) -> None:
    for field in ("id", "name", "outcome", "domain", "task"):
        value = str(payload.get(field) or "").strip()
        if not value:
            raise ValueError(f"{field} is required")


async def list_products(active_only: bool = True) -> list[dict[str, Any]]:
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await products_repo.find_all(conn, active_only=active_only)
    return [_normalize_product_row(r) for r in rows]


async def get_product(product_id: str) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await products_repo.find_by_id(conn, product_id)
    return _normalize_product_row(row) if row else None


async def create_product(payload: dict[str, Any]) -> dict[str, Any]:
    _validate_required_fields(payload)
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            row = await products_repo.insert_returning(
                conn,
                str(payload["id"]).strip(),
                str(payload["name"]).strip(),
                str(payload.get("emoji") or "🧩").strip(),
                str(payload.get("description") or "").strip(),
                str(payload.get("color") or "#857BFF").strip(),
                str(payload["outcome"]).strip(),
                str(payload["domain"]).strip(),
                str(payload["task"]).strip(),
                bool(payload.get("isActive", True)),
                int(payload.get("sortOrder", 0) or 0),
                _now(),
            )
    except UniqueViolationError as exc:
        raise ValueError("Product with this id already exists") from exc

    assert row is not None
    return _normalize_product_row(row)


async def patch_product(product_id: str, body: dict[str, Any]) -> dict[str, Any] | None:
    patch: dict[str, Any] = {k: body[k] for k in PRODUCT_MUTABLE_FIELDS if k in body}
    if not patch:
        return await get_product(product_id)
    for field in ("outcome", "domain", "task"):
        if field in patch and not str(patch[field] or "").strip():
            raise ValueError(f"{field} cannot be empty")

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await products_repo.update_fields(conn, product_id, patch, _now())
    if row is None:
        return await get_product(product_id)
    return _normalize_product_row(row) if row else None


async def remove_product(product_id: str) -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        return await products_repo.delete_by_id(conn, product_id)

