"""DataImpulse proxy configuration for Playwright.

Loads proxy credentials from environment variables (set via .env).
Each Playwright browser context is launched with this proxy so that
outbound requests are routed through DataImpulse's rotating proxy
network and avoid 403 / bot-detection blocks.
"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).parent.parent / ".env"
    load_dotenv(_env_path)
except ImportError:
    pass  # dotenv not installed; rely on env vars already being set


def get_playwright_proxy() -> dict | None:
    """Return a Playwright-compatible proxy dict, or None if not configured.

    Playwright proxy format::

        {
            "server": "http://<host>:<port>",
            "username": "...",
            "password": "...",
        }
    """
    host = os.getenv("PROXY_HOST", "").strip()
    port = os.getenv("PROXY_PORT", "").strip()
    username = os.getenv("PROXY_USERNAME", "").strip()
    password = os.getenv("PROXY_PASSWORD", "").strip()

    if not host or not port:
        return None

    proxy: dict = {"server": f"http://{host}:{port}"}
    if username:
        proxy["username"] = username
    if password:
        proxy["password"] = password

    return proxy