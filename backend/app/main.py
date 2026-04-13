"""
IKSHAN BACKEND — FastAPI Application Entry Point
"""

from __future__ import annotations

import traceback
from contextlib import asynccontextmanager
import structlog
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse, JSONResponse

from app.config import get_settings
from app.middleware.auth_context import attach_request_auth_context
from app.middleware.rate_limit import setup_rate_limiter

from app.db import connect_db, close_db
from app.skills.service import load_skills
from app.doable_claw_agent.stores import ensure_default_agents
from app.services.system_config_service import upsert_system_config_entry

# ── Structured Logging ─────────────────────────────────────────
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer() if get_settings().is_development
        else structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(0),
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info(
        "🚀 Ikshan Backend starting",
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT.value,
        host=settings.HOST,
        port=settings.PORT,
    )

    # Verify critical configuration
    if not settings.JUSPAY_API_KEY:
        logger.warning("⚠️  No JusPay API key configured — payment endpoints will fail")

    # Pre-load all persona documents so task lookups are instant
    from app.services.persona_doc_service import preload_all_docs
    preload_all_docs()

    # Pre-load RCA decision tree for instant question serving
    from app.services.rca_tree_service import load_tree
    load_tree()

    # Load skills from disk — independent of DB, must run unconditionally.
    load_skills()

    # ── DoableClaw Agent startup ───────────────────────────────────────────────
    try:
        await connect_db()

        # Clean up any plans that were executing when the backend was last shut down
        from app.doable_claw_agent.stores import cleanup_stale_executing_plans
        stale_count = await cleanup_stale_executing_plans()
        if stale_count > 0:
            logger.info(f"✅ Cleaned up {stale_count} stale executing plan(s) from previous session")

        # Clean up stale task streams (running for more than 30 minutes)
        from app.task_stream.store_factory import get_task_stream_store
        store = get_task_stream_store()
        if hasattr(store, 'cleanup_stale_running_streams'):
            stream_cleanup_count = await store.cleanup_stale_running_streams(max_age_minutes=30)
            if stream_cleanup_count > 0:
                logger.info(f"✅ Cleaned up {stream_cleanup_count} stale task stream(s)")

        # Dev bootstrap: make JusPay sandbox test-card details visible/editable
        # in `/admin/config` via the `system_config` table.
        try:
            if settings.is_development:
                card_number = (settings.JUSPAY_TEST_CARD_NUMBER or "").strip()
                card_expiry = (settings.JUSPAY_TEST_CARD_EXPIRY or "").strip()
                card_cvv = (settings.JUSPAY_TEST_CARD_CVV or "").strip()
                card_otp = (settings.JUSPAY_TEST_CARD_OTP or "").strip()

                # Only bootstrap if at least one field is configured.
                if card_number or card_expiry or card_cvv or card_otp:
                    await upsert_system_config_entry(
                        "JUSPAY_TEST_CARD_NUMBER",
                        card_number,
                        "JusPay sandbox test card number (development only)",
                    )
                    await upsert_system_config_entry(
                        "JUSPAY_TEST_CARD_EXPIRY",
                        card_expiry,
                        "JusPay sandbox test card expiry (development only)",
                    )
                    await upsert_system_config_entry(
                        "JUSPAY_TEST_CARD_CVV",
                        card_cvv,
                        "JusPay sandbox test card CVV (development only)",
                    )
                    await upsert_system_config_entry(
                        "JUSPAY_TEST_CARD_OTP",
                        card_otp,
                        "JusPay sandbox test card OTP (development only)",
                    )
                    logger.info("✅ Bootstrapped JusPay test card into system_config")
        except Exception as e:
            logger.warning("⚠️ JusPay test-card bootstrap failed", error=str(e))

        await ensure_default_agents()
        logger.info("✅ DoableClaw Agent started")
    except Exception as e:
        logger.warning("⚠️  DoableClaw Agent startup failed — research agent routes unavailable", error=str(e))

    yield

    # ── DoableClaw Agent shutdown ──────────────────────────────────────────────
    try:
        await close_db()
    except Exception:
        pass

    logger.info("🛑 Ikshan Backend shutting down")

def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        openapi_url="/openapi.json",
        default_response_class=ORJSONResponse,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    setup_rate_limiter(app)

    @app.middleware("http")
    async def auth_context_middleware(request: Request, call_next):
        await attach_request_auth_context(request)
        return await call_next(request)

    # ── Global exception handler for debugging ─────────────────
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(
            "Unhandled exception",
            path=str(request.url),
            method=request.method,
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        return JSONResponse(
            status_code=500,
            content={"detail": f"Internal server error: {str(exc)}"},
        )

    # ── Routers ────────────────────────────────────────────────
    from app.routers import (
        auth,
        ai_chat,
        chat,
        admin_management,
        admin_subscription_grants,
        agents,
        products,
        payments,
        plans,
        legacy,
        onboarding,
    )

    # CRITICAL: Rebuild models here after routers are loaded
    from app.models.chat import ChatRequest, ChatResponse
    ChatRequest.model_rebuild()
    ChatResponse.model_rebuild()

    app.include_router(agents.router, prefix="/api", tags=["Agents"])
    app.include_router(products.router, prefix="/api/v1", tags=["Products"])
    app.include_router(auth.router, prefix="/api/v1", tags=["Authentication"])
    app.include_router(onboarding.router, prefix="/api/v1", tags=["Onboarding"])
    app.include_router(ai_chat.router, prefix="/api/v1")
    app.include_router(chat.router, prefix="/api/v1", tags=["Chat"])
    app.include_router(payments.router, prefix="/api/v1", tags=["Payments"])
    app.include_router(plans.router, prefix="/api/v1", tags=["Plans"])
    app.include_router(admin_management.router, prefix="/api/v1", tags=["Admin"])
    app.include_router(admin_subscription_grants.router, prefix="/api/v1", tags=["Admin-Subscription-Grants"])

    # ── Task stream (Redis or Postgres; TASKSTREAM_BACKEND) ──────────────
    from app.task_stream.router import create_task_stream_router
    from app.task_stream.service import TaskStreamService
    from app.task_stream.registry import TASK_STREAM_REGISTRY

    # Import task implementations so their @register_task_stream decorators run.
    from app.task_stream import tasks as _task_stream_tasks  # noqa: F401

    task_stream_service = TaskStreamService()
    app.include_router(
        create_task_stream_router(
            service=task_stream_service,
            task_registry=TASK_STREAM_REGISTRY,
        )
    )

    # Legacy routes for frontend compatibility (/api/chat, /api/companies, etc.)
    app.include_router(legacy.router, prefix="/api", tags=["Legacy"])

    # ── DoableClaw Agent routes (/api/chat/*, /api/agents, /api/skills) ─────────
    from app.doable_claw_agent.router import router as doable_claw_router
    app.include_router(doable_claw_router, tags=["DoableClaw-ResearchAgent"])

    @app.get("/health", tags=["System"])
    async def health_check():
        return {"status": "healthy", "version": settings.APP_VERSION}

    return app

app = create_app()

if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.is_development)