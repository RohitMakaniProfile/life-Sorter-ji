"""
═══════════════════════════════════════════════════════════════
IKSHAN BACKEND — Application Configuration
═══════════════════════════════════════════════════════════════
Pydantic BaseSettings for type-safe, validated environment
variable management. All secrets loaded from .env file.
"""

from __future__ import annotations

from enum import Enum
from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(str, Enum):
    """Application environment."""
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class JuspayEnvironment(str, Enum):
    """JusPay environment — determines API base URL."""
    SANDBOX = "sandbox"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables / .env file.
    All fields use UPPER_CASE env var names by default.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ────────────────────────────────────────────
    APP_NAME: str = "Ikshan Backend"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: Environment = Environment.DEVELOPMENT
    LOG_LEVEL: str = "INFO"
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # ── CORS ───────────────────────────────────────────────────
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://localhost:3001",
        "https://ikshan.in",
        "https://www.ikshan.in",
        "https://dev.ikshan.in",
        "https://admin.ikshan.in",
        "https://ikshan-fe-dev.web.app",
        "https://ikshan-fe-prod.web.app",
        "https://ikshan-fe-dev.firebaseapp.com",
        "https://ikshan-fe-prod.firebaseapp.com",
    ]

    # ── OpenAI ─────────────────────────────────────────────────
    OPENAI_API_KEY: str = ""
    OPENAI_API_KEY_2: str = ""
    OPENAI_MODEL_NAME: str = "gpt-4o-mini"

    # ── OpenRouter (GLM-5 RCA) ──────────────────────────────────
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_MODEL: str = "z-ai/glm-5"
    OPENROUTER_CLAUDE_MODEL: str = "anthropic/claude-sonnet-4-6"  # Used only for playbook Agent C comparison

    # ── SERP API ───────────────────────────────────────────────
    SERP_API_KEY: str = ""

    # ── JusPay ─────────────────────────────────────────────────
    JUSPAY_MERCHANT_ID: str = ""
    JUSPAY_API_KEY: str = ""
    JUSPAY_RESPONSE_KEY: str = ""
    JUSPAY_PAYMENT_PAGE_CLIENT_ID: str = ""
    JUSPAY_BASE_URL: str = ""  # Override base URL (e.g., HDFC SmartGateway)
    JUSPAY_ENVIRONMENT: JuspayEnvironment = JuspayEnvironment.SANDBOX

    # ── Frontend ───────────────────────────────────────────────
    FRONTEND_URL: str = "https://ikshan.in"

    # ── JWT Auth ───────────────────────────────────────────────
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ACCESS_TOKEN_EXPIRES_HOURS: int = 168

    # ── 2Factor.in OTP ─────────────────────────────────────────
    TWO_FACTOR_API_KEY: str = ""

    # ── Google Sheets ──────────────────────────────────────────
    GOOGLE_SHEETS_WEBHOOK_URL: str = ""

    # ── Rate Limiting ──────────────────────────────────────────
    RATE_LIMIT_CHAT: str = "10/minute"
    RATE_LIMIT_COMPANIES: str = "30/minute"
    RATE_LIMIT_SPEAK: str = "5/minute"
    RATE_LIMIT_DEFAULT: str = "60/minute"

    # ── Computed Properties ────────────────────────────────────

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == Environment.PRODUCTION

    @property
    def is_development(self) -> bool:
        return self.ENVIRONMENT == Environment.DEVELOPMENT

    @property
    def juspay_base_url(self) -> str:
        # Use explicit base URL if configured (e.g., HDFC SmartGateway)
        if self.JUSPAY_BASE_URL:
            return self.JUSPAY_BASE_URL.rstrip("/")
        if self.JUSPAY_ENVIRONMENT == JuspayEnvironment.PRODUCTION:
            return "https://api.juspay.in"
        return "https://sandbox.juspay.in"

    @property
    def openai_api_key_active(self) -> str:
        """Return the primary key, fallback to secondary."""
        return self.OPENAI_API_KEY or self.OPENAI_API_KEY_2


@lru_cache
def get_settings() -> Settings:
    """
    Cached singleton for application settings.
    Called once at startup; subsequent calls return the same instance.
    """
    return Settings()
