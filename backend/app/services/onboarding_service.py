"""Persist Phase 1 onboarding selections in `onboarding` rows keyed by `id`."""

from __future__ import annotations

import json
import uuid as _uuid
from typing import Any, Optional

import structlog

from app.db import get_pool
from app.repositories import onboarding_repository as onboarding_repo
from app.utils.url_sanitize import sanitize_http_url

logger = structlog.get_logger()


def _validate_uuid(value: str, label: str = "onboarding_id") -> str:
    """Validate that a string is a valid UUID. Raises ValueError if not."""
    try:
        _uuid.UUID(value)
    except ValueError:
        raise ValueError(f"{label} must be a valid UUID, got '{value}'")
    return value

ALLOWED_PATCH_FIELDS = frozenset({
    "user_id", "outcome", "domain", "task", "website_url", "gbp_url", "scale_answers",
})

BACKEND_MANAGED_FIELDS = frozenset({
    "questions_answers", "crawl_cache_key", "crawl_run_id",
    "onboarding_completed_at", "business_profile",
})


def _sanitize_url_fields(d: dict[str, Any]) -> dict[str, Any]:
    out = dict(d)
    for key in ("website_url", "gbp_url"):
        if key in out and isinstance(out[key], str):
            out[key] = sanitize_http_url(out[key])
    return out


def _coerce_jsonb_fields(d: dict[str, Any]) -> dict[str, Any]:
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
    return _coerce_jsonb_fields(_sanitize_url_fields(raw))


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
    allowed = _allowed_updates(initial)
    pool = get_pool()
    async with pool.acquire() as conn:
        if not allowed:
            row = await onboarding_repo.insert_default(conn)
        else:
            row = await onboarding_repo.insert_with_fields(conn, list(allowed.keys()), list(allowed.values()))

    out = _serialize_row(row)
    logger.info("onboarding row created", onboarding_id=out.get("id"),
                initial_fields=list(allowed.keys()) if allowed else [])
    return out


async def upsert_onboarding_patch(
    onboarding_id: str, updates: dict[str, Any], user_id: Optional[str] = None,
) -> dict[str, Any]:
    oid = (onboarding_id or "").strip()
    if not oid:
        raise ValueError("onboarding_id is required for patch")
    _validate_uuid(oid)

    allowed = _allowed_updates(updates)
    uid = (user_id or "").strip() if user_id else None
    if uid and "user_id" not in allowed:
        allowed["user_id"] = uid

    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await onboarding_repo.find_by_id(conn, oid)
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
            row = await onboarding_repo.find_full_by_id(conn, oid)
        else:
            row = await onboarding_repo.update_fields(conn, oid, allowed)

        if website_url_changed:
            row = await onboarding_repo.reset_web_summary(conn, oid)

    out = _serialize_row(row)
    logger.debug("onboarding patched", onboarding_id=oid, fields=list(allowed.keys()))
    return out


async def reset_onboarding(onboarding_id: str) -> dict[str, Any]:
    oid = (onboarding_id or "").strip()
    if not oid:
        raise ValueError("onboarding_id is required for reset")
    _validate_uuid(oid)

    pool = get_pool()
    async with pool.acquire() as conn:
        existing = await onboarding_repo.find_by_id(conn, oid)
        if not existing:
            raise ValueError("onboarding row not found")
        if existing.get("onboarding_completed_at") or str(existing.get("playbook_status") or "") == "complete":
            raise PermissionError("cannot reset a completed onboarding row")
        row = await onboarding_repo.reset_full(conn, oid)
        if not row:
            raise ValueError("onboarding row not found")

    out = _serialize_row(row)
    logger.info("onboarding row reset", onboarding_id=oid)
    return out