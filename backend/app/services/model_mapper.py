from __future__ import annotations

import os


def _normalize_prefix(prefix: str) -> str:
    p = (prefix or "").strip()
    if not p:
        return "google/"
    # Ensure exactly one trailing slash.
    return p.rstrip("/") + "/"


def model_to_openrouter_candidates(model_id: str, prefix_env: str = "OPENROUTER_MODEL_PREFIX") -> list[str]:
    """
    Map a logical model id (e.g. "gemini-2.5-flash-lite") to OpenRouter model ids.

    OpenRouter model ids are typically namespaced (e.g. "google/gemini-2.5-flash-lite").
    We try a best-effort prefix mapping first, then the original id as a fallback.
    """
    raw = (model_id or "").strip()
    if not raw:
        return []

    # If it's already namespaced, treat as an OpenRouter id candidate.
    if "/" in raw:
        return [raw]

    # Backward-compatible fallback to legacy env name.
    prefix_raw = os.getenv(prefix_env)
    if prefix_raw is None and prefix_env == "OPENROUTER_MODEL_PREFIX":
        prefix_raw = os.getenv("OPENROUTER_GEMINI_MODEL_PREFIX")
    prefix = _normalize_prefix(prefix_raw or "google/")
    candidate = f"{prefix}{raw}"
    if candidate == raw:
        return [raw]
    return [candidate, raw]


def gemini_model_to_openrouter_candidates(gemini_model_id: str) -> list[str]:
    """
    Backward-compatible alias for legacy callsites.
    """
    return model_to_openrouter_candidates(gemini_model_id, prefix_env="OPENROUTER_MODEL_PREFIX")

