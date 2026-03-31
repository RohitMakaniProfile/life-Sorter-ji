"""
═══════════════════════════════════════════════════════════════
RAG ROUTER — API endpoints for the RAG tool retrieval pipeline
═══════════════════════════════════════════════════════════════
Endpoints:
  POST /rag/ingest          — Ingest tools from JSON into vector store
  POST /rag/search          — Free-text semantic search
  POST /rag/search/session  — Search using session context
  GET  /rag/stats           — Collection statistics
  DELETE /rag/collection    — Reset the vector store
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException

from app.rag.ingest import ingest_tools
from app.rag.models import (
    IngestResponse,
    RAGStatsResponse,
    ToolSearchBySessionRequest,
    ToolSearchRequest,
    ToolSearchResponse,
)
from app.rag.retrieval import get_rag_stats, search_by_query, search_by_session
from app.rag.vector_store import delete_collection

logger = structlog.get_logger()

router = APIRouter(prefix="/rag", tags=["RAG"])


# ── Ingest Endpoint ────────────────────────────────────────────


@router.post("/ingest", response_model=IngestResponse)
async def ingest_tools_endpoint(force: bool = False):
    """
    Ingest all tools from matched_tools_by_persona.json into the vector store.

    Args:
        force: If true, delete existing collection and re-ingest from scratch.

    This endpoint reads the JSON file, generates embeddings via OpenAI,
    and stores them in the Qdrant vector database.
    """
    logger.info("RAG ingest triggered", force=force)

    try:
        result = await ingest_tools(force=force)
        return result
    except Exception as e:
        logger.error("Ingest failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}")


# ── Search Endpoints ───────────────────────────────────────────


@router.post("/search", response_model=ToolSearchResponse)
async def search_tools_endpoint(request: ToolSearchRequest):
    """
    Search for tools using a free-text query.

    Generates an embedding for the query and performs cosine similarity
    search against all indexed tools. Supports optional filters.
    """
    try:
        result = await search_by_query(
            query=request.query,
            top_k=request.top_k,
            persona=request.persona,
            source=request.source,
            category=request.category,
        )
        return result
    except Exception as e:
        logger.error("Search failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")


@router.post("/search/session", response_model=ToolSearchResponse)
async def search_by_session_endpoint(request: ToolSearchBySessionRequest):
    """
    Search for tools using the full session context.

    Reads the session's outcome, domain, task, and all diagnostic answers,
    then builds a semantic query and searches the vector store.
    """
    from app.services.session_store import get_session

    session = get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    if not session.domain or not session.task:
        raise HTTPException(
            status_code=400,
            detail="Session must have domain and task set before searching",
        )

    # Build answers list from session
    answers = [
        {"q": qa.question, "a": qa.answer}
        for qa in session.questions_answers
    ]

    try:
        result = await search_by_session(
            outcome_label=session.outcome_label or "",
            domain=session.domain,
            task=session.task,
            answers=answers,
            top_k=request.top_k,
            source=request.source,
        )
        return result
    except Exception as e:
        logger.error("Session search failed", error=str(e), session_id=request.session_id)
        raise HTTPException(status_code=500, detail=f"Session search failed: {str(e)}")


# ── Stats & Management ────────────────────────────────────────


@router.get("/stats", response_model=RAGStatsResponse)
async def get_stats_endpoint():
    """Get statistics about the RAG vector store."""
    try:
        return get_rag_stats()
    except Exception as e:
        logger.error("Stats retrieval failed", error=str(e))
        raise HTTPException(status_code=500, detail=f"Stats failed: {str(e)}")


@router.delete("/collection")
async def delete_collection_endpoint():
    """
    Delete the entire tools collection from the vector store.
    Use this before re-ingesting to start fresh.
    """
    success = delete_collection()
    if success:
        return {"status": "deleted", "collection": "ikshan_tools"}
    raise HTTPException(status_code=500, detail="Failed to delete collection")
