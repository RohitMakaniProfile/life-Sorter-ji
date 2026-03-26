from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from typing import Any

# Load backend/.env into os.environ so os.getenv() works in this module.
# (phase2/config.py does this elsewhere, but auth_google.py reads directly from os.environ.)
try:
    from dotenv import load_dotenv

    _BACKEND_DIR = __file__.resolve().parents[2]  # .../backend
    load_dotenv(_BACKEND_DIR / ".env", override=False)
except Exception:
    pass

import jwt


@dataclass(frozen=True)
class Phase2AuthedUser:
    user_id: str
    email: str
    # internal admin (non-super) or super admin, depending on how you define PHASE2_* lists
    is_admin: bool
    is_super_admin: bool


def _split_csv_env(name: str) -> list[str]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return []
    return [x.strip().lower() for x in raw.split(",") if x.strip()]


def get_phase2_jwt_secret() -> str:
    return os.getenv("PHASE2_JWT_SECRET", "").strip()


def get_phase2_jwt_exp_seconds() -> int:
    raw = os.getenv("PHASE2_JWT_EXPIRE_SECONDS", "").strip()
    if not raw:
        return 60 * 60 * 24  # 24h default
    try:
        return int(raw)
    except Exception:
        return 60 * 60 * 24


def get_internal_google_allowlist() -> list[str]:
    return _split_csv_env("PHASE2_ALLOWED_GOOGLE_EMAILS")


def get_internal_google_admin_emails() -> list[str]:
    return _split_csv_env("PHASE2_ADMIN_GOOGLE_EMAILS")

def get_internal_google_super_admin_emails() -> list[str]:
    return _split_csv_env("PHASE2_SUPER_ADMIN_GOOGLE_EMAILS")


def get_internal_google_controller_emails() -> list[str]:
    # Controllers can see/edit locked agents; super-admins are included.
    return sorted(set(get_internal_google_admin_emails()) | set(get_internal_google_super_admin_emails()))


_FIREBASE_APP: Any = None


def _ensure_firebase_admin() -> Any:
    """
    Initialize firebase-admin once.

    Required env vars:
      - PHASE2_FIREBASE_SERVICE_ACCOUNT_JSON_PATH (recommended)
        or PHASE2_FIREBASE_SERVICE_ACCOUNT_JSON (raw JSON string)
      - PHASE2_FIREBASE_PROJECT_ID (optional but recommended)
    """
    global _FIREBASE_APP
    if _FIREBASE_APP is not None:
        return _FIREBASE_APP

    import firebase_admin  # type: ignore
    from firebase_admin import credentials  # type: ignore

    path = os.getenv("PHASE2_FIREBASE_SERVICE_ACCOUNT_JSON_PATH", "").strip()
    raw_json = os.getenv("PHASE2_FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
    project_id = os.getenv("PHASE2_FIREBASE_PROJECT_ID", "").strip() or None

    if not path and not raw_json:
        raise RuntimeError(
            "Missing Firebase service account configuration for phase2. "
            "Set PHASE2_FIREBASE_SERVICE_ACCOUNT_JSON_PATH or PHASE2_FIREBASE_SERVICE_ACCOUNT_JSON."
        )

    if path:
        cred = credentials.Certificate(path)
    else:
        cred = credentials.Certificate(json.loads(raw_json))

    _FIREBASE_APP = firebase_admin.initialize_app(cred, {"projectId": project_id} if project_id else None)
    return _FIREBASE_APP


async def verify_firebase_id_token(id_token: str) -> dict[str, Any]:
    """
    Verify Firebase ID token and return decoded claims.
    """
    if not id_token or not id_token.strip():
        raise ValueError("idToken missing")

    _ensure_firebase_admin()

    from firebase_admin import auth  # type: ignore

    # firebase_admin.auth.verify_id_token is sync; run in thread.
    decoded = await asyncio.to_thread(auth.verify_id_token, id_token.strip(), True)
    if not isinstance(decoded, dict):
        raise ValueError("Invalid firebase id token payload")
    return decoded


async def verify_google_id_token(id_token: str) -> dict[str, Any]:
    """
    Verify a Google Identity Services (GSI) ID token (JWT) and return decoded claims.
    Requires PHASE2_GOOGLE_CLIENT_ID for audience validation.
    """
    if not id_token or not id_token.strip():
        raise ValueError("idToken missing")
    aud = os.getenv("PHASE2_GOOGLE_CLIENT_ID", "").strip()
    if not aud:
        raise RuntimeError("PHASE2_GOOGLE_CLIENT_ID is not set")

    def _verify() -> dict[str, Any]:
        from google.auth.transport import requests  # type: ignore
        from google.oauth2 import id_token as google_id_token  # type: ignore

        req = requests.Request()
        decoded = google_id_token.verify_oauth2_token(id_token.strip(), req, aud)
        if not isinstance(decoded, dict):
            raise ValueError("Invalid google id token payload")
        return decoded

    return await asyncio.to_thread(_verify)


async def verify_google_or_firebase_token(id_token: str) -> dict[str, Any]:
    """
    Phase2 exchange endpoint accepts either:
      - Firebase Auth ID token (verified via firebase-admin), OR
      - Google GSI ID token (verified via google-auth)
    """
    try:
        return await verify_firebase_id_token(id_token)
    except Exception:
        return await verify_google_id_token(id_token)


def issue_phase2_jwt(*, user_id: str, email: str, is_admin: bool, is_super_admin: bool) -> str:
    secret = get_phase2_jwt_secret()
    if not secret:
        raise RuntimeError("PHASE2_JWT_SECRET is not set")

    now = int(time.time())
    exp = now + int(get_phase2_jwt_exp_seconds())
    payload = {
        "sub": str(user_id),
        "email": str(email),
        "admin": bool(is_admin),
        "super": bool(is_super_admin),
        "iat": now,
        "exp": exp,
        "aud": "phase2",
        "iss": "ikshan-backend",
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def decode_phase2_jwt(token: str) -> Phase2AuthedUser:
    secret = get_phase2_jwt_secret()
    if not secret:
        raise RuntimeError("PHASE2_JWT_SECRET is not set")
    decoded = jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        options={"require": ["exp", "iat", "sub"], "verify_aud": False},
    )
    if not isinstance(decoded, dict):
        raise ValueError("Invalid token")
    user_id = str(decoded.get("sub") or "").strip()
    email = str(decoded.get("email") or "").strip()
    is_admin = bool(decoded.get("admin"))
    is_super_admin = bool(decoded.get("super"))
    if not user_id or not email:
        raise ValueError("Invalid token payload")
    return Phase2AuthedUser(user_id=user_id, email=email, is_admin=is_admin, is_super_admin=is_super_admin)


def is_allowed_internal_email(email: str) -> bool:
    email_l = (email or "").strip().lower()
    if not email_l:
        return False
    allow = get_internal_google_allowlist()
    # Dev/testing convenience:
    # If allowlist is not configured, don't block login (open auth).
    # In production you should set PHASE2_ALLOWED_GOOGLE_EMAILS explicitly.
    if not allow:
        return True
    return email_l in allow

