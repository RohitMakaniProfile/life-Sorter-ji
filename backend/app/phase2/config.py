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

DATABASE_URL = _getenv("DATABASE_URL", "postgresql://localhost:5432/ikshan")
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
