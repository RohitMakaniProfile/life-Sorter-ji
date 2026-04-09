"""
Read-only access to the `plans` catalog (DB is source of truth; seed via SQL + plans_seed.json).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

import structlog
from pypika import Table
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter

from app.db import get_pool
from app.sql_builder import build_query

logger = structlog.get_logger()
plans_t = Table("plans")


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
    pool = get_pool()
    async with pool.acquire() as conn:
        list_active_q = build_query(
            PostgreSQLQuery.from_(plans_t)
            .select(
                plans_t.id,
                plans_t.slug,
                plans_t.name,
                plans_t.description,
                plans_t.price_inr,
                plans_t.credits_allocation,
                plans_t.features,
                plans_t.display_order,
                plans_t.active,
            )
            .where(plans_t.active.isin([True]))
            .orderby(plans_t.display_order)
            .orderby(plans_t.name)
        )
        rows = await conn.fetch(list_active_q.sql, *list_active_q.params)
    return [_row_to_plan(r) for r in rows]


async def fetch_plan_by_slug(slug: str) -> Optional[dict[str, Any]]:
    pool = get_pool()
    async with pool.acquire() as conn:
        fetch_by_slug_q = build_query(
            PostgreSQLQuery.from_(plans_t)
            .select(
                plans_t.id,
                plans_t.slug,
                plans_t.name,
                plans_t.description,
                plans_t.price_inr,
                plans_t.credits_allocation,
                plans_t.features,
                plans_t.display_order,
                plans_t.active,
            )
            .where(plans_t.slug == Parameter("%s"))
            .where(plans_t.active.isin([True])),
            [slug.strip()],
        )
        row = await conn.fetchrow(fetch_by_slug_q.sql, *fetch_by_slug_q.params)
    return _row_to_plan(row) if row else None


async def fetch_plan_by_id(plan_id: UUID | str) -> Optional[dict[str, Any]]:
    pool = get_pool()
    async with pool.acquire() as conn:
        fetch_by_id_q = build_query(
            PostgreSQLQuery.from_(plans_t)
            .select(
                plans_t.id,
                plans_t.slug,
                plans_t.name,
                plans_t.description,
                plans_t.price_inr,
                plans_t.credits_allocation,
                plans_t.features,
                plans_t.display_order,
                plans_t.active,
            )
            .where(plans_t.id == Parameter("%s")),
            [plan_id if isinstance(plan_id, UUID) else UUID(str(plan_id))],
        )
        row = await conn.fetchrow(fetch_by_id_q.sql, *fetch_by_id_q.params)
    return _row_to_plan(row) if row else None
