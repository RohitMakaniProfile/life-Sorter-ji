from __future__ import annotations

import asyncio
import json
import os
from typing import Any

try:
    from dotenv import load_dotenv

    _BACKEND_DIR = __file__.resolve().parents[2]  # .../backend
    load_dotenv(_BACKEND_DIR / ".env", override=False)
except Exception:
    pass


_FIREBASE_APP: Any = None


def _ensure_firebase_admin() -> Any:
    """
    Initialize firebase-admin once.

    Required env vars:
      - IKSHAN_FIREBASE_SERVICE_ACCOUNT_JSON_PATH (recommended)
        or IKSHAN_FIREBASE_SERVICE_ACCOUNT_JSON (raw JSON string)
      - IKSHAN_FIREBASE_PROJECT_ID (optional but recommended)
    """
    global _FIREBASE_APP
    if _FIREBASE_APP is not None:
        return _FIREBASE_APP

    import firebase_admin  # type: ignore
    from firebase_admin import credentials  # type: ignore

    path = os.getenv("IKSHAN_FIREBASE_SERVICE_ACCOUNT_JSON_PATH", "").strip()
    raw_json = os.getenv("IKSHAN_FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
    project_id = os.getenv("IKSHAN_FIREBASE_PROJECT_ID", "").strip() or None

    if not path and not raw_json:
        raise RuntimeError(
            "Missing Firebase service account configuration. "
            "Set IKSHAN_FIREBASE_SERVICE_ACCOUNT_JSON_PATH or IKSHAN_FIREBASE_SERVICE_ACCOUNT_JSON."
        )

    if path:
        cred = credentials.Certificate(path)
    else:
        cred = credentials.Certificate(json.loads(raw_json))

    _FIREBASE_APP = firebase_admin.initialize_app(cred, {"projectId": project_id} if project_id else None)
    return _FIREBASE_APP


async def verify_firebase_id_token(id_token: str) -> dict[str, Any]:
    if not id_token or not id_token.strip():
        raise ValueError("idToken missing")

    _ensure_firebase_admin()
    from firebase_admin import auth  # type: ignore

    decoded = await asyncio.to_thread(auth.verify_id_token, id_token.strip(), True)
    if not isinstance(decoded, dict):
        raise ValueError("Invalid firebase id token payload")
    return decoded


async def verify_google_id_token(id_token: str) -> dict[str, Any]:
    """
    Verify a Google Identity Services (GSI) ID token (JWT) and return decoded claims.
    Requires IKSHAN_GOOGLE_CLIENT_ID for audience validation.
    """
    if not id_token or not id_token.strip():
        raise ValueError("idToken missing")
    aud = os.getenv("IKSHAN_GOOGLE_CLIENT_ID", "").strip()
    if not aud:
        raise RuntimeError("IKSHAN_GOOGLE_CLIENT_ID is not set")

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
    Exchange endpoint accepts either:
      - Firebase Auth ID token (verified via firebase-admin), OR
      - Google GSI ID token (verified via google-auth)
    """
    try:
        return await verify_firebase_id_token(id_token)
    except Exception:
        return await verify_google_id_token(id_token)
