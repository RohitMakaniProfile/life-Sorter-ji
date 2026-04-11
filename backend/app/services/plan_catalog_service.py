"""
Read-only access to the `plans` catalog (DB is source of truth; seed via SQL + plans_seed.json).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

import structlog

from app.db import get_pool

logger = structlog.get_logger()


def _row_to_plan(row: Any) -> dict[str, Any]:
    d = dict(row)
    fid = d.get("id")
    if fid is not None:
        d["id"] = str(fid)
    pr = d.get("price_inr")
    if isinstance(pr, Decimal):
        d["price_inr"] = float(pr)
    feats = d.get("features")
    if isinstance(feats, str):
        import json

        try:
            d["features"] = json.loads(feats)
        except json.JSONDecodeError:
            d["features"] = {}
    return d


async def list_active_plans() -> list[dict[str, Any]]:
    from app.repositories import plans_repository as plans_repo
    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await plans_repo.list_active_full(conn)
    return [_row_to_plan(r) for r in rows]


async def fetch_plan_by_slug(slug: str) -> Optional[dict[str, Any]]:
    from app.repositories import plans_repository as plans_repo
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await plans_repo.find_by_slug_active(conn, slug)
    return _row_to_plan(row) if row else None


async def fetch_plan_by_id(plan_id: UUID | str) -> Optional[dict[str, Any]]:
    from app.repositories import plans_repository as plans_repo
    pid = plan_id if isinstance(plan_id, UUID) else UUID(str(plan_id))
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await plans_repo.find_by_id_full(conn, pid)
    return _row_to_plan(row) if row else None