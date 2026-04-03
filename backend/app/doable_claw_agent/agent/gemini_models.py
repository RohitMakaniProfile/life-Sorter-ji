from __future__ import annotations

from app.config import GEMINI_MODELS

_DEFAULT_GEMINI_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
]


def get_planner_models() -> list[str]:
    """
    Return ordered list of planning model IDs to try on OpenRouter.
    On 503/429/404 the caller tries the next until one succeeds or the list is exhausted.
    Set GEMINI_MODELS (comma-separated) or GEMINI_MODEL (single) to override.
    """
    env = GEMINI_MODELS
    if not env:
        return list(_DEFAULT_GEMINI_MODELS)
    lst = [s.strip() for s in env.split(",") if s.strip()]
    if not lst:
        return list(_DEFAULT_GEMINI_MODELS)
    if len(lst) == 1:
        rest = [m for m in _DEFAULT_GEMINI_MODELS if m != lst[0]]
        return lst + rest
    return lst


def get_gemini_models() -> list[str]:
    """
    Backward-compatible alias for legacy imports.
    """
    return get_planner_models()
