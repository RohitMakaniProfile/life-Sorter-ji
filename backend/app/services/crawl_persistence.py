"""
Persist crawl results to `crawl_cache` + `crawl_runs` and link `onboarding`
(crawl_run_id, crawl_cache_key).
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Optional

import structlog

from app.db import get_pool
from app.utils.url_sanitize import sanitize_http_url

logger = structlog.get_logger()

CRAWLER_VERSION = "v1"


def normalized_url_for_cache(input_url: str) -> str:
    """Stable key aligned with onboarding `crawl_cache_key` lookups."""
    s = (sanitize_http_url((input_url or "").strip()) or (input_url or "").strip())
    return s


def _as_uuid(value: Optional[str]) -> Optional[uuid.UUID]:
    if not value:
        return None
    try:
        return uuid.UUID(str(value).strip())
    except ValueError:
        return None


def crawl_summary_for_storage(summary: dict[str, Any]) -> dict[str, Any]:
    """Strip internal keys before JSONB storage."""
    out = dict(summary)
    out.pop("_meta", None)
    return out


async def persist_successful_crawl(
    *,
    session_id: str,
    user_id: Optional[str],
    input_url: str,
    url_type: str,
    crawl_raw: dict[str, Any],
    crawl_summary: dict[str, Any],
) -> Optional[str]:
    """
    Upsert crawl_cache, insert a completed crawl_run, update onboarding pointers.

    Returns crawl_run id (str) or None if onboarding row missing / DB error.
    """
    sid = (session_id or "").strip()
    if not sid:
        logger.warning("persist_successful_crawl skipped: empty session_id")
        return None

    norm = normalized_url_for_cache(input_url)
    summary_clean = crawl_summary_for_storage(crawl_summary)
    uid = _as_uuid(user_id)

    raw_json = json.dumps(crawl_raw)
    sum_json = json.dumps(summary_clean)

    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            async with conn.transaction():
                cache_id = await conn.fetchval(
                    """
                    INSERT INTO crawl_cache (normalized_url, crawler_version, crawl_raw, crawl_summary)
                    VALUES ($1, $2, $3::jsonb, $4::jsonb)
                    ON CONFLICT (normalized_url, crawler_version) DO UPDATE SET
                        crawl_raw = EXCLUDED.crawl_raw,
                        crawl_summary = EXCLUDED.crawl_summary,
                        updated_at = NOW()
                    RETURNING id
                    """,
                    norm,
                    CRAWLER_VERSION,
                    raw_json,
                    sum_json,
                )

                run_id = await conn.fetchval(
                    """
                    INSERT INTO crawl_runs (
                        session_id, user_id, input_url, normalized_url, url_type,
                        status, cache_hit, crawl_cache_id, error, finished_at
                    )
                    VALUES ($1, $2, $3, $4, $5, 'complete', false, $6::uuid, '', NOW())
                    RETURNING id::text
                    """,
                    sid,
                    uid,
                    input_url,
                    norm,
                    url_type,
                    cache_id,
                )

                result = await conn.execute(
                    """
                    UPDATE onboarding
                    SET crawl_run_id = $1::uuid,
                        crawl_cache_key = $2,
                        updated_at = NOW()
                    WHERE session_id = $3
                    """,
                    run_id,
                    norm,
                    sid,
                )
                # asyncpg: result is e.g. "UPDATE 1"
                if str(result).endswith("0"):
                    logger.warning(
                        "onboarding row not updated for crawl persist",
                        session_id=sid,
                        crawl_run_id=run_id,
                    )

        logger.info(
            "crawl persisted to onboarding",
            session_id=sid,
            crawl_run_id=run_id,
            crawl_cache_key=norm,
        )
        return str(run_id) if run_id else None

    except Exception as exc:
        logger.error(
            "crawl persist failed",
            session_id=sid,
            error=str(exc),
        )
        raise
