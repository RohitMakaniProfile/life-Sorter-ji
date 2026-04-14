from __future__ import annotations

import json
from typing import Any

from pypika import Table, Order
from pypika.dialects import PostgreSQLQuery
from pypika.terms import Parameter

from app.sql_builder import build_query

scraped_pages_t = Table("scraped_pages")


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def _build_page_row(
    entry: dict[str, Any],
    *,
    skill_call_id: int | None,
    conversation_id: str | None,
    onboarding_id: str | None,
    user_id: str | None,
    message_id: str | None,
) -> tuple[str, Any] | None:
    """
    Extract and validate fields from a page dict.
    Returns (sql, params) tuple via build_query, or None if the entry is invalid.
    Internal helper shared by insert_one and bulk_insert.
    """
    if not isinstance(entry, dict):
        return None
    url = str(entry.get("url") or "").strip()
    if not url:
        return None

    raw_val = entry.get("raw")
    markdown_val = entry.get("text") or entry.get("markdown") or ""

    raw_text = _to_text(raw_val)
    markdown_text = str(markdown_val or "")

    page_dict = raw_val if isinstance(raw_val, dict) else {}
    page_title = str(page_dict.get("title") or entry.get("title") or "")
    status_code_raw = page_dict.get("status_code") or page_dict.get("statusCode") or entry.get("status_code")
    status_code = int(status_code_raw) if status_code_raw is not None else None
    crawl_depth_raw = page_dict.get("depth") or entry.get("depth")
    crawl_depth = int(crawl_depth_raw) if crawl_depth_raw is not None else None
    content_type = str(page_dict.get("content_type") or page_dict.get("contentType") or "")

    q = build_query(
        PostgreSQLQuery.into(scraped_pages_t)
        .columns(
            scraped_pages_t.url,
            scraped_pages_t.raw,
            scraped_pages_t.markdown,
            scraped_pages_t.skill_call_id,
            scraped_pages_t.conversation_id,
            scraped_pages_t.onboarding_id,
            scraped_pages_t.user_id,
            scraped_pages_t.message_id,
            scraped_pages_t.page_title,
            scraped_pages_t.status_code,
            scraped_pages_t.crawl_depth,
            scraped_pages_t.content_type,
        )
        .insert(
            Parameter("%s"), Parameter("%s"), Parameter("%s"),
            Parameter("%s"), Parameter("%s"), Parameter("%s"),
            Parameter("%s"), Parameter("%s"), Parameter("%s"),
            Parameter("%s"), Parameter("%s"), Parameter("%s"),
        ),
        [
            url, raw_text, markdown_text,
            skill_call_id, conversation_id, onboarding_id,
            user_id, message_id,
            page_title, status_code, crawl_depth, content_type,
        ],
    )
    return q


async def insert_one(
    conn,
    entry: dict[str, Any],
    *,
    skill_call_id: int | None = None,
    conversation_id: str | None = None,
    onboarding_id: str | None = None,
    user_id: str | None = None,
    message_id: str | None = None,
) -> bool:
    """Insert a single scraped page row. Returns True if inserted, False if skipped."""
    q = _build_page_row(
        entry,
        skill_call_id=skill_call_id,
        conversation_id=conversation_id,
        onboarding_id=onboarding_id,
        user_id=user_id,
        message_id=message_id,
    )
    if q is None:
        return False
    await conn.execute(q.sql, *q.params)
    return True


async def bulk_insert(
    conn,
    page_entries: list[dict[str, Any]],
    *,
    skill_call_id: int | None = None,
    conversation_id: str | None = None,
    onboarding_id: str | None = None,
    user_id: str | None = None,
    message_id: str | None = None,
) -> int:
    """Insert one row per scraped page.  Returns number of rows inserted."""
    if not page_entries:
        return 0

    count = 0
    for entry in page_entries:
        inserted = await insert_one(
            conn, entry,
            skill_call_id=skill_call_id,
            conversation_id=conversation_id,
            onboarding_id=onboarding_id,
            user_id=user_id,
            message_id=message_id,
        )
        if inserted:
            count += 1

    return count


async def find_by_base_url(conn, base_url: str, *, limit: int = 500) -> list[Any]:
    """Return all scraped_pages rows whose url starts with the same origin."""
    from urllib.parse import urlparse
    try:
        parsed = urlparse(str(base_url or "").strip())
        if parsed.scheme and parsed.netloc:
            origin_prefix = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
        else:
            origin_prefix = str(base_url or "").strip().rstrip("/")
    except Exception:
        origin_prefix = str(base_url or "").strip().rstrip("/")

    if not origin_prefix:
        return []

    # Use LIKE for prefix match — pypika doesn't expose LIKE natively so raw SQL.
    rows = await conn.fetch(
        "SELECT id, url, raw, markdown, skill_call_id, conversation_id, "
        "onboarding_id, user_id, message_id, page_title, status_code, "
        "crawl_depth, content_type, created_at "
        "FROM scraped_pages "
        "WHERE url LIKE $1 "
        "ORDER BY created_at DESC "
        "LIMIT $2",
        origin_prefix + "%",
        limit,
    )
    return list(rows)


async def find_latest_by_exact_url(conn, url: str) -> Any | None:
    """Return the most recently inserted row for an exact URL (normalised)."""
    normalised = str(url or "").strip().rstrip("/").lower()
    if not normalised:
        return None
    rows = await conn.fetch(
        "SELECT id, url, raw, markdown, skill_call_id, conversation_id, "
        "onboarding_id, user_id, message_id, created_at "
        "FROM scraped_pages "
        "WHERE lower(rtrim(url, '/')) = $1 "
        "ORDER BY created_at DESC LIMIT 1",
        normalised,
    )
    return rows[0] if rows else None


async def find_by_skill_call_id(conn, skill_call_id: int) -> list[Any]:
    q = build_query(
        PostgreSQLQuery.from_(scraped_pages_t)
        .select("*")
        .where(scraped_pages_t.skill_call_id == Parameter("%s"))
        .orderby(scraped_pages_t.id, order=Order.asc),
        [skill_call_id],
    )
    return list(await conn.fetch(q.sql, *q.params))

