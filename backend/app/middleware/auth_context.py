from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException, Request

from app.db import get_pool
from app.services.jwt_service import decode_and_verify_access_token
from app.task_stream.redis_client import get_redis

_AUTH_CACHE_PREFIX = "ikshan:auth:user"
_AUTH_CACHE_TTL_SECONDS = 300


def _extract_bearer_token(authorization: str | None) -> str:
    raw = (authorization or "").strip()
    if not raw.lower().startswith("bearer "):
        return ""
    return raw[7:].strip()


async def _load_user_from_db(user_id: str) -> dict[str, Any] | None:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT id, email, phone_number, name, auth_provider, onboarding_session_id, last_login_at
            FROM users
            WHERE id::text = $1
            LIMIT 1
            """,
            user_id,
        )
    if not row:
        return None
    return {
        "id": str(row.get("id") or ""),
        "email": row.get("email"),
        "phone_number": row.get("phone_number"),
        "name": row.get("name"),
        "auth_provider": row.get("auth_provider"),
        "onboarding_session_id": row.get("onboarding_session_id"),
        "last_login_at": str(row.get("last_login_at") or ""),
    }


async def _load_user_with_cache(user_id: str) -> dict[str, Any] | None:
    cache_key = f"{_AUTH_CACHE_PREFIX}:{user_id}"
    try:
        redis = await get_redis()
        if redis:
            cached = await redis.get(cache_key)
            if cached:
                parsed = json.loads(cached)
                if isinstance(parsed, dict):
                    return parsed
    except Exception:
        pass

    user = await _load_user_from_db(user_id)
    if not user:
        return None
    try:
        redis = await get_redis()
        if redis:
            await redis.set(cache_key, json.dumps(user), ex=_AUTH_CACHE_TTL_SECONDS)
    except Exception:
        pass
    return user


async def attach_request_auth_context(request: Request) -> None:
    """
    Best-effort global auth context resolver.
    Always sets:
      - request.state.auth_claims: dict | None
      - request.state.user: dict | None
    """
    request.state.auth_claims = None
    request.state.user = None

    token = _extract_bearer_token(request.headers.get("authorization"))
    if not token:
        return
    try:
        claims = decode_and_verify_access_token(token)
    except Exception:
        return

    request.state.auth_claims = claims
    sub = str(claims.get("sub") or "").strip()
    if not sub:
        return

    user = await _load_user_with_cache(sub)
    if user:
        request.state.user = user
        return

    # Fallback with token claims even when users row not found.
    request.state.user = {
        "id": sub,
        "email": claims.get("email"),
        "phone_number": claims.get("phone_number"),
        "name": claims.get("name"),
        "auth_provider": claims.get("provider"),
        "onboarding_session_id": claims.get("onboarding_session_id"),
    }


def get_request_user(request: Request) -> dict[str, Any] | None:
    return getattr(request.state, "user", None)


def require_request_user(request: Request) -> dict[str, Any]:
    user = get_request_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user

