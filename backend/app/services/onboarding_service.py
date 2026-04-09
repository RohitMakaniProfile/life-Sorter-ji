"""Persist Phase 1 onboarding selections in `onboarding` rows keyed by `id`."""

from __future__ import annotations

from typing import Any, Optional

import json
import structlog
from pypika import Table, functions as fn
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter

from app.db import get_pool
from app.repositories.onboarding_table import insert_onboarding_default_values_returning
from app.sql_builder import build_query
from app.utils.url_sanitize import sanitize_http_url

logger = structlog.get_logger()
onboarding_t = Table("onboarding")
ALLOWED_PATCH_FIELDS = frozenset(
    {
        "user_id",
        "outcome",
        "domain",
        "task",
        "website_url",
        "gbp_url",
        "scale_answers",
    }
)

# Backend-managed fields (should not be patched via onboarding upsert).
BACKEND_MANAGED_FIELDS = frozenset(
    {"questions_answers", "crawl_cache_key", "crawl_run_id", "onboarding_completed_at", "business_profile"}
)

RETURNING_COLUMNS = (
    "id",
    "user_id",
    "outcome",
    "domain",
    "task",
    "website_url",
    "gbp_url",
    "scale_answers",
    "business_profile",
    "questions_answers",
    "crawl_cache_key",
    "onboarding_completed_at",
    "created_at",
    "updated_at",
)


def _returning_terms() -> list[Any]:
    return [getattr(onboarding_t, col) for col in RETURNING_COLUMNS]


def _sanitize_onboarding_url_fields(d: dict[str, Any]) -> dict[str, Any]:
    out = dict(d)
    for key in ("website_url", "gbp_url"):
        if key not in out:
            continue
        val = out[key]
        if isinstance(val, str):
            out[key] = sanitize_http_url(val)
    return out


def _coerce_onboarding_jsonb_fields(d: dict[str, Any]) -> dict[str, Any]:
    out = dict(d)
    if "scale_answers" in out:
        v = out.get("scale_answers")
        if isinstance(v, (dict, list)):
            out["scale_answers"] = json.dumps(v)
    return out


def _allowed_updates(updates: Optional[dict[str, Any]]) -> dict[str, Any]:
    if not updates:
        return {}
    raw = {k: v for k, v in updates.items() if k in ALLOWED_PATCH_FIELDS}
    return _coerce_onboarding_jsonb_fields(_sanitize_onboarding_url_fields(raw))


def _serialize_row(row: Any) -> dict[str, Any]:
    if not row:
        return {}
    d = dict(row)
    for k, v in list(d.items()):
        if hasattr(v, "hex"):
            d[k] = str(v)
        elif k in ("created_at", "updated_at") and v is not None:
            d[k] = v.isoformat() if hasattr(v, "isoformat") else str(v)
    d["onboarding_id"] = d.get("id")
    return d


async def create_session_with_onboarding(initial: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    """Create a new onboarding row."""
    allowed = _allowed_updates(initial)

    pool = get_pool()
    async with pool.acquire() as conn:
        if not allowed:
            row = await conn.fetchrow(insert_onboarding_default_values_returning())
        else:
            cols = list(allowed.keys())
            vals: list[Any] = list(allowed.values())
            insert_terms = [getattr(onboarding_t, col) for col in cols]
            insert_placeholders = [Parameter("%s") for _ in vals]
            create_with_fields_q = build_query(
                PostgreSQLQuery.into(onboarding_t)
                .columns(*insert_terms)
                .insert(*insert_placeholders)
                .returning(*_returning_terms()),
                vals,
            )
            row = await conn.fetchrow(create_with_fields_q.sql, *create_with_fields_q.params)

    out = _serialize_row(row)
    logger.info(
        "onboarding row created",
        onboarding_id=out.get("id"),
        initial_fields=list(allowed.keys()) if allowed else [],
    )
    return out


async def upsert_onboarding_patch(
    onboarding_id: str,
    updates: dict[str, Any],
    user_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    Patch an existing onboarding row.

    If the row is already complete, create a fresh onboarding row instead.
    """
    oid = (onboarding_id or "").strip()
    if not oid:
        raise ValueError("onboarding_id is required for patch")

    allowed = _allowed_updates(updates)
    uid = (user_id or "").strip() if user_id else None

    if uid and "user_id" not in allowed:
        allowed["user_id"] = uid

    pool = get_pool()
    async with pool.acquire() as conn:
        existing_q = build_query(
            PostgreSQLQuery.from_(onboarding_t)
            .select(onboarding_t.onboarding_completed_at, onboarding_t.website_url)
            .where(onboarding_t.id == Parameter("%s")),
            [oid],
        )
        existing = await conn.fetchrow(existing_q.sql, *existing_q.params)
        if not existing:
            raise ValueError("onboarding row not found")

        website_url_changed = False
        if "website_url" in allowed:
            old_url = str(existing.get("website_url") or "").strip()
            new_url = str(allowed.get("website_url") or "").strip()
            website_url_changed = old_url != new_url

        if existing.get("onboarding_completed_at"):
            logger.info("onboarding row is complete, creating new row", onboarding_id=oid, user_id=uid)
            initial_fields = dict(allowed)
            if uid:
                initial_fields["user_id"] = uid
            return await create_session_with_onboarding(initial_fields)

        if not allowed:
            current_row_q = build_query(
                PostgreSQLQuery.from_(onboarding_t)
                .select(*_returning_terms())
                .where(onboarding_t.id == Parameter("%s")),
                [oid],
            )
            row = await conn.fetchrow(current_row_q.sql, *current_row_q.params)
        else:
            cols = list(allowed.keys())
            vals = list(allowed.values())
            update_qb = PostgreSQLQuery.update(onboarding_t)
            for col_name in cols:
                update_qb = update_qb.set(getattr(onboarding_t, col_name), Parameter("%s"))
            update_q = build_query(
                update_qb.set(onboarding_t.updated_at, fn.Now())
                .where(onboarding_t.id == Parameter("%s"))
                .returning(*_returning_terms()),
                [*vals, oid],
            )
            row = await conn.fetchrow(update_q.sql, *update_q.params)

        if website_url_changed:
            # Keep this as explicit SQL because jsonb cast on bound parameters is
            # runtime-sensitive across environments with PyPika expressions.
            reset_summary_sql = (
                "UPDATE onboarding "
                "SET web_summary = '', "
                "    business_profile = '', "
                "    rca_qa = $1::jsonb, "
                "    rca_summary = '', "
                "    rca_handoff = '', "
                "    updated_at = NOW() "
                "WHERE id = $2 "
                "RETURNING id, user_id, outcome, domain, task, "
                "          website_url, gbp_url, scale_answers, business_profile, questions_answers, crawl_cache_key, "
                "          onboarding_completed_at, created_at, updated_at"
            )
            row = await conn.fetchrow(reset_summary_sql, json.dumps([]), oid)

    out = _serialize_row(row)
    logger.debug("onboarding patched", onboarding_id=oid, fields=list(allowed.keys()))
    return out
