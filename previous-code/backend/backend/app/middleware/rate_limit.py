"""
Rate limiting middleware using SlowAPI.
Per-endpoint rate limits configured via app settings.
"""

from __future__ import annotations

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from fastapi import FastAPI


# Global limiter instance — keyed by client IP
limiter = Limiter(key_func=get_remote_address)


def setup_rate_limiter(app: FastAPI) -> None:
    """Attach the SlowAPI limiter to the FastAPI application."""
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
