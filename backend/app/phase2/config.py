from __future__ import annotations

import os
import shutil
import sys
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


def _resolve_python_bin() -> str:
    """
    Interpreter used to run phase2 skill subprocesses.

    Prefer PYTHON_BIN from env when it exists or resolves via PATH; otherwise
    use sys.executable so skills run with the same interpreter as the API (avoids
    FileNotFoundError when python3 is missing on PATH or PYTHON_BIN points at a
    deleted venv).
    """
    raw = os.getenv("PYTHON_BIN", "").strip()
    if raw:
        candidate = Path(raw)
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate.resolve())
        found = shutil.which(raw)
        if found:
            return found
    return sys.executable


DATABASE_URL = _resolve_database_url()
PYTHON_BIN = _resolve_python_bin()
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
