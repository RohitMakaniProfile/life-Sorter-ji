from __future__ import annotations

import os
from pathlib import Path

# backend/ directory (2 levels up from this file: phase2/ → app/ → backend/)
_BACKEND_DIR = Path(__file__).resolve().parents[2]

# Load .env into os.environ so os.getenv() picks up values from it.
# pydantic-settings reads .env but does NOT inject into os.environ.
try:
    from dotenv import load_dotenv
    load_dotenv(_BACKEND_DIR / ".env", override=False)
except ImportError:
    pass


def _getenv(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def _resolve_database_url() -> str:
    """
    Resolve DB URL with explicit switching support.

    Priority:
    1) DATABASE_URL (direct override)
    2) DATABASE_TARGET + env-specific URLs
    3) fallback local default

    DATABASE_TARGET values:
      - local | dev | prod | auto
    """
    direct = os.getenv("DATABASE_URL", "").strip()
    if direct:
        return direct

    target = os.getenv("DATABASE_TARGET", "auto").strip().lower()
    env_name = os.getenv("ENVIRONMENT", "development").strip().lower()

    url_local = os.getenv("DATABASE_URL_LOCAL", "").strip()
    url_dev = os.getenv("DATABASE_URL_DEV", "").strip()
    url_prod = os.getenv("DATABASE_URL_PROD", "").strip()

    if target == "local" and url_local:
        return url_local
    if target == "dev" and url_dev:
        return url_dev
    if target == "prod" and url_prod:
        return url_prod

    if target == "auto":
        if env_name == "production" and url_prod:
            return url_prod
        if env_name in ("development", "staging") and url_dev:
            return url_dev
        if url_local:
            return url_local

    return "postgresql://localhost:5432/ikshan"

DATABASE_URL = _resolve_database_url()
PYTHON_BIN = _getenv("PYTHON_BIN", "python3")
STORAGE_BUCKET = _getenv("STORAGE_BUCKET", str(_BACKEND_DIR / "storage-bucket"))
SKILLS_ROOT = Path(_getenv("SKILLS_ROOT", str(_BACKEND_DIR / "skills")))

# LLM — OpenAI is primary; Anthropic (Claude) preferred for large contexts
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = _getenv("OPENAI_MODEL", "gpt-4.1")
CLAUDE_API_KEY = os.getenv("CLAUDE_API_KEY", "").strip()
CLAUDE_MODEL = _getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

# Gemini — orchestration loop + platform-scout
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODELS = os.getenv("GEMINI_MODELS", os.getenv("GEMINI_MODEL", "")).strip()
GEMINI_SCOUT_MODELS = os.getenv("GEMINI_SCOUT_MODELS", "").strip()

SKILL_DEBUG_LOGS = _getenv("SKILL_DEBUG_LOGS", "false").lower() in ("true", "1", "yes")
