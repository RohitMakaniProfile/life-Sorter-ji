"""
Prompts repository service.

Provides functions to read and manage system prompts stored in the database.
Includes Redis caching with 1-hour TTL for performance.
"""
from __future__ import annotations

from typing import Any
from app.db import get_pool
from app.task_stream.redis_client import get_redis

CACHE_TTL_SECONDS = 3600  # 1 hour
CACHE_KEY_PREFIX = "prompt:"


async def get_prompt(slug: str, default: str = "") -> str:
    """
    Get prompt content by slug.
    First checks Redis cache, falls back to DB if not cached.
    """
    slug = (slug or "").strip()
    if not slug:
        return default

    # Try cache first
    redis = await get_redis()
    if redis:
        cached = await redis.get(f"{CACHE_KEY_PREFIX}{slug}")
        if cached is not None:
            return cached.decode() if isinstance(cached, bytes) else str(cached)

    # Fetch from DB
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT content FROM prompts WHERE slug = $1", slug
        )

    if row is None:
        return default

    content = str(row.get("content") or "")

    # Cache the result
    if redis:
        await redis.setex(f"{CACHE_KEY_PREFIX}{slug}", CACHE_TTL_SECONDS, content)

    return content


async def get_prompt_full(slug: str) -> dict[str, Any] | None:
    """
    Get full prompt record by slug (for admin UI).
    """
    slug = (slug or "").strip()
    if not slug:
        return None

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT slug, name, content, description, category, created_at, updated_at
            FROM prompts WHERE slug = $1
            """,
            slug,
        )

    if row is None:
        return None

    return {
        "slug": row["slug"],
        "name": row["name"],
        "content": row["content"],
        "description": row["description"],
        "category": row["category"],
        "createdAt": row["created_at"].isoformat() if row["created_at"] else "",
        "updatedAt": row["updated_at"].isoformat() if row["updated_at"] else "",
    }


async def list_prompts(category: str | None = None) -> list[dict[str, Any]]:
    """
    List all prompts, optionally filtered by category.
    """
    pool = get_pool()
    async with pool.acquire() as conn:
        if category:
            rows = await conn.fetch(
                """
                SELECT slug, name, content, description, category, created_at, updated_at
                FROM prompts WHERE category = $1 ORDER BY name
                """,
                category,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT slug, name, content, description, category, created_at, updated_at
                FROM prompts ORDER BY category, name
                """
            )

    return [
        {
            "slug": r["slug"],
            "name": r["name"],
            "content": r["content"],
            "description": r["description"],
            "category": r["category"],
            "createdAt": r["created_at"].isoformat() if r["created_at"] else "",
            "updatedAt": r["updated_at"].isoformat() if r["updated_at"] else "",
        }
        for r in rows
    ]


async def upsert_prompt(
    slug: str,
    name: str,
    content: str,
    description: str = "",
    category: str = "general",
) -> dict[str, Any]:
    """
    Create or update a prompt.
    Invalidates cache on update.
    """
    slug = (slug or "").strip()
    name = (name or "").strip()
    content = content or ""
    description = (description or "").strip()
    category = (category or "general").strip()

    if not slug:
        raise ValueError("slug is required")
    if not name:
        raise ValueError("name is required")

    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO prompts (slug, name, content, description, category)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (slug)
            DO UPDATE SET
                name = EXCLUDED.name,
                content = EXCLUDED.content,
                description = EXCLUDED.description,
                category = EXCLUDED.category,
                updated_at = NOW()
            RETURNING slug, name, content, description, category, created_at, updated_at
            """,
            slug,
            name,
            content,
            description,
            category,
        )

    # Invalidate cache
    redis = await get_redis()
    if redis:
        await redis.delete(f"{CACHE_KEY_PREFIX}{slug}")

    return {
        "slug": row["slug"],
        "name": row["name"],
        "content": row["content"],
        "description": row["description"],
        "category": row["category"],
        "createdAt": row["created_at"].isoformat() if row["created_at"] else "",
        "updatedAt": row["updated_at"].isoformat() if row["updated_at"] else "",
    }


async def delete_prompt(slug: str) -> bool:
    """
    Delete a prompt by slug.
    Returns True if deleted, False if not found.
    """
    slug = (slug or "").strip()
    if not slug:
        return False

    pool = get_pool()
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM prompts WHERE slug = $1", slug
        )

    deleted = result == "DELETE 1"

    # Invalidate cache
    if deleted:
        redis = await get_redis()
        if redis:
            await redis.delete(f"{CACHE_KEY_PREFIX}{slug}")

    return deleted


async def invalidate_prompt_cache(slug: str | None = None) -> None:
    """
    Invalidate prompt cache.
    If slug is provided, only that prompt is invalidated.
    If slug is None, all prompts are invalidated (by pattern).
    """
    redis = await get_redis()
    if not redis:
        return

    if slug:
        await redis.delete(f"{CACHE_KEY_PREFIX}{slug}")
    else:
        # Delete all prompt keys (use scan for safety)
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor, match=f"{CACHE_KEY_PREFIX}*", count=100)
            if keys:
                await redis.delete(*keys)
            if cursor == 0:
                break

