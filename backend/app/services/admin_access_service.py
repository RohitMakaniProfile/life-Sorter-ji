from __future__ import annotations

import os
import json
import re
from typing import Any

from app.services.system_config_service import get_config_value


def _parse_email_list(raw: str) -> set[str]:
    """
    Parse an allowlist stored in system_config.

    Supported formats:
    - JSON array: ["a@x.com", "b@x.com"]
    - JSON object with "emails": ["..."]
    - Comma/semicolon/newline-separated list: a@x.com, b@x.com
    """
    text = (raw or "").strip()
    if not text:
        return set()

    # Try JSON first.
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            out = []
            for v in parsed:
                if isinstance(v, str) and v.strip():
                    out.append(v.strip().lower())
            return set(out)
        if isinstance(parsed, dict):
            emails = parsed.get("emails")
            if isinstance(emails, list):
                out = []
                for v in emails:
                    if isinstance(v, str) and v.strip():
                        out.append(v.strip().lower())
                return set(out)
    except Exception:
        # Fall back to delimiter parsing.
        pass

    # Delimiter parsing.
    parts = re.split(r"[,;\n]+", text)
    return {p.strip().lower() for p in parts if isinstance(p, str) and p.strip()}


async def is_super_admin_email(email: str | None) -> bool:
    e = (email or "").strip().lower()
    if not e:
        return False

    # Prefer DB-configured allowlist, but keep a safe fallback to existing
    # Cloud Run env vars so fresh DBs don't lock everyone out.
    missing_sentinel = "__IKSHAN_SUPER_ADMIN_EMAILS_MISSING__"
    allow_raw = await get_config_value("auth.super_admin_emails", missing_sentinel)
    if allow_raw == missing_sentinel:
        allow_raw = os.getenv("IKSHAN_SUPER_ADMIN_GOOGLE_EMAILS", "") or ""

    allow = _parse_email_list(allow_raw)
    # If DB is present but effectively "not configured" (empty/[]), fall back
    # to env vars to avoid locking out admin access on fresh deployments.
    if not allow and allow_raw.strip() in ("", "[]", "[ ]", "null", "{}", "None"):
        allow_raw = os.getenv("IKSHAN_SUPER_ADMIN_GOOGLE_EMAILS", "") or ""
        allow = _parse_email_list(allow_raw)
    return e in allow


async def resolve_admin_flags(email: str | None) -> dict[str, bool]:
    """
    Resolve JWT boolean flags based on configured allowlists.

    Keys:
      - "super": super-admin access
      - "admin": admin access (defaults to super-admin unless separately allowlisted)
    """
    super_flag = await is_super_admin_email(email)
    if super_flag:
        return {"super": True, "admin": True}

    missing_sentinel = "__IKSHAN_ADMIN_EMAILS_MISSING__"
    admin_raw = await get_config_value("auth.admin_emails", missing_sentinel)
    if admin_raw == missing_sentinel:
        admin_raw = os.getenv("IKSHAN_ADMIN_GOOGLE_EMAILS", "") or ""

    allow = _parse_email_list(admin_raw)
    if not allow and admin_raw.strip() in ("", "[]", "[ ]", "null", "{}", "None"):
        admin_raw = os.getenv("IKSHAN_ADMIN_GOOGLE_EMAILS", "") or ""
        allow = _parse_email_list(admin_raw)
    is_admin = bool((email or "").strip().lower() in allow) if email else False
    return {"super": False, "admin": is_admin}


def coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        raw = value.strip().lower()
        return raw in ("1", "true", "yes", "on")
    return False

