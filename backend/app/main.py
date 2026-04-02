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
from app.middleware.rate_limit import setup_rate_limiter

from app.db import connect_db as p2_connect_db
from app.skills.service import load_skills as p2_load_skills
from app.phase2.stores import ensure_default_agents as p2_ensure_agents
from app.db import close_db as p2_close_db

# ── Structured Logging ─────────────────────────────────────────
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer() if not get_settings().is_production
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
    if not settings.openai_api_key_active:
        logger.warning("⚠️  No OpenAI API key configured — chat/TTS endpoints will fail")
    if not settings.JUSPAY_API_KEY:
        logger.warning("⚠️  No JusPay API key configured — payment endpoints will fail")

    # Pre-load all persona documents so task lookups are instant
    from app.services.persona_doc_service import preload_all_docs
    preload_all_docs()

    # Pre-load RCA decision tree for instant question serving
    from app.services.rca_tree_service import load_tree
    load_tree()

    # Auto-ingest RAG tools if API key is available
    if settings.openai_api_key_active:
        try:
            from app.rag.ingest import ingest_tools
            result = await ingest_tools()
            logger.info(
                "🔍 RAG tools auto-ingested",
                total=result.tools_ingested,
                errors=len(result.errors),
                status=result.status,
            )
        except Exception as e:
            logger.warning("⚠️  RAG auto-ingest failed (tools won't be available)", error=str(e))
    else:
        logger.warning("⚠️  Skipping RAG ingest — no OpenAI API key for embeddings")

    # ── Phase 2: Research Agent startup ───────────────────────────────────────
    try:
        await p2_connect_db()
        p2_load_skills()
        await p2_ensure_agents()
        logger.info("✅ Phase 2 (Research Agent) started")
    except Exception as e:
        logger.warning("⚠️  Phase 2 startup failed — research agent routes unavailable", error=str(e))

    yield

    # ── Phase 2 shutdown ───────────────────────────────────────────────────────
    try:
        await p2_close_db()
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
        companies,
        payments,
        legacy,
        agent,
        playbook,
        onboarding,
    )

    # CRITICAL: Rebuild models here after routers are loaded
    from app.models.chat import ChatRequest, ChatResponse
    ChatRequest.model_rebuild()
    ChatResponse.model_rebuild()

    app.include_router(auth.router, prefix="/api/v1", tags=["Authentication"])
    app.include_router(onboarding.router, prefix="/api/v1", tags=["Onboarding"])
    app.include_router(ai_chat.router, prefix="/api/v1")
    app.include_router(chat.router, prefix="/api/v1", tags=["Chat"])
    app.include_router(companies.router, prefix="/api/v1", tags=["Companies"])
    app.include_router(payments.router, prefix="/api/v1", tags=["Payments"])
    app.include_router(agent.router, prefix="/api/v1")
    app.include_router(playbook.router, tags=["Playbook"])

    # ── Task stream (Redis-backed re-attach after refresh) ───────────────
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

    # ── Phase 2: Research Agent routes (/api/chat/*, /api/agents, /api/skills) ─
    from app.phase2.router import router as phase2_router
    app.include_router(phase2_router, tags=["Phase2-ResearchAgent"])

    @app.get("/health", tags=["System"])
    async def health_check():
        return {"status": "healthy", "version": settings.APP_VERSION}

    return app

app = create_app()

if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.is_development)