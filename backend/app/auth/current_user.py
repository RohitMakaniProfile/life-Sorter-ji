from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Any

from fastapi import Depends, HTTPException, Request

from app.db import get_pool
from app.phase2.auth_google import (
    Phase2AuthedUser,
    decode_phase2_jwt,
    get_internal_google_admin_emails,
    get_internal_google_super_admin_emails,
)


AuthKind = Literal["otp", "admin_jwt"]


@dataclass(frozen=True)
class AuthedUser:
    user_id: str
    auth_kind: AuthKind
    is_admin: bool
    is_super_admin: bool
    session_id: str | None = None
    email: str | None = None
    phone: str | None = None


def _bearer_token(req: Request) -> str | None:
    raw = req.headers.get("Authorization") or ""
    if not raw:
        return None
    parts = raw.split()
    if len(parts) != 2:
        return None
    if parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


async def require_user(req: Request) -> AuthedUser:
    """
    Unified auth:
    - Admin Google login: Bearer JWT (Phase2 JWT) -> grants is_admin/is_super_admin for agent write controls.
    - OTP users: also receive Bearer JWT (non-admin) from OTP verify endpoint.
    """
    token = _bearer_token(req)
    if token:
        try:
            decoded: Phase2AuthedUser = decode_phase2_jwt(token)
            email = decoded.email.lower()
            is_super_admin = email in get_internal_google_super_admin_emails()
            is_internal_admin = email in get_internal_google_admin_emails()
            is_admin = is_super_admin or is_internal_admin

            pool = get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow("SELECT id, email FROM users WHERE id = $1::uuid", decoded.user_id)
                if not row:
                    raise HTTPException(status_code=401, detail="User not found for token; please login again")
                db_email = str(row["email"] or "").strip().lower()
                if db_email and db_email != email:
                    raise HTTPException(status_code=401, detail="Token/user mismatch; please login again")

            return AuthedUser(
                user_id=decoded.user_id,
                auth_kind="admin_jwt",
                is_admin=is_admin,
                is_super_admin=is_super_admin,
                email=decoded.email,
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=401, detail=f"Invalid auth token: {str(exc)}") from exc

    raise HTTPException(status_code=401, detail="Missing Authorization Bearer token")


def require_user_dep() -> Any:
    return Depends(require_user)

