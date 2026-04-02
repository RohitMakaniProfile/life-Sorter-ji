"""Normalize user-entered URLs for storage and crawling."""

from __future__ import annotations

import re
from typing import Optional

_HTTP_SCHEME = re.compile(r"^https?://", re.IGNORECASE)


def sanitize_http_url(value: Optional[str]) -> Optional[str]:
    """
    Trim whitespace; return None if empty after trim.
    If the string has no http:// or https:// prefix (case-insensitive), prepend https://.
    """
    if value is None:
        return None
    s = value.strip()
    if not s:
        return None
    if not _HTTP_SCHEME.match(s):
        s = f"https://{s}"
    return s
