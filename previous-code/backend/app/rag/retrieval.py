"""
═══════════════════════════════════════════════════════════════
RAG RETRIEVAL — Semantic tool retrieval using session context
═══════════════════════════════════════════════════════════════
Takes user session context (outcome, domain, task, answers) and
produces a semantic query to search the vector store for the
most relevant tools.
"""

from __future__ import annotations

from typing import Optional

import structlog

from app.rag.embeddings import generate_query_embedding, EMBEDDING_MODEL
from app.rag.models import (
    RAGStatsResponse,
    ToolResult,
    ToolSearchResponse,
)
from app.rag.vector_store import (
    COLLECTION_NAME,
    get_collection_stats,
    search_tools,
)

logger = structlog.get_logger()


def _build_session_query(
    outcome_label: str,
    domain: str,
    task: str,
    answers: list[dict],
) -> str:
    """
    Build a rich semantic search query from the session context.

    Combines the user's growth goal, domain, task, and all diagnostic
    answers into a single query string optimized for embedding similarity.
    """
    parts = [
        f"Business goal: {outcome_label}",
        f"Domain: {domain}",
        f"Task: {task}",
    ]

    # Add diagnostic answers as context
    for i, qa in enumerate(answers, 1):
        answer_text = qa.get("a", qa.get("answer", ""))
        if answer_text:
            question_text = qa.get("q", qa.get("question", f"Question {i}"))
            parts.append(f"Q: {question_text}\nA: {answer_text}")

    return "\n".join(parts)


def _map_domain_to_persona(domain: str) -> Optional[str]:
    """
    Map a domain name to the persona key used in the JSON file.
    Returns None if no exact match (search will proceed without filter).
    """
    # The JSON keys are like "B2B Lead Generation", "Content & Social Media"
    # The domain from the session might match exactly or be close
    # For now, return the domain as-is — Qdrant payload filter is case-sensitive
    return domain if domain else None


async def search_by_query(
    query: str,
    top_k: int = 10,
    persona: Optional[str] = None,
    source: Optional[str] = None,
    category: Optional[str] = None,
) -> ToolSearchResponse:
    """
    Search for tools using a free-text query.

    Args:
        query: Natural language search query.
        top_k: Max results.
        persona: Optional persona filter.
        source: Optional source platform filter.
        category: Optional category filter.

    Returns:
        ToolSearchResponse with ranked results.
    """
    # Generate query embedding
    query_vector = await generate_query_embedding(query)

    if query_vector is None:
        logger.error("Failed to generate query embedding", query=query[:80])
        return ToolSearchResponse(query=query, results=[], total_results=0)

    # Search vector store
    raw_results = search_tools(
        query_vector=query_vector,
        top_k=top_k,
        persona=persona,
        source=source,
        category=category,
    )

    # Map to response model
    results = [
        ToolResult(
            name=r.get("name", ""),
            description=r.get("description", ""),
            source=r.get("source", ""),
            category=r.get("category", ""),
            rating=r.get("rating", ""),
            installs=r.get("installs", ""),
            url=r.get("url", ""),
            persona=r.get("persona", ""),
            relevance_score=r.get("relevance_score", 0.0),
        )
        for r in raw_results
    ]

    logger.info(
        "RAG search completed",
        query=query[:60],
        results_count=len(results),
        persona_filter=persona,
        source_filter=source,
    )

    return ToolSearchResponse(
        query=query,
        results=results,
        total_results=len(results),
    )


async def search_by_session(
    outcome_label: str,
    domain: str,
    task: str,
    answers: list[dict],
    top_k: int = 10,
    source: Optional[str] = None,
) -> ToolSearchResponse:
    """
    Search for tools using the full session context.

    Builds a semantic query from the user's outcome, domain, task,
    and all diagnostic answers, then searches the vector store.

    Args:
        outcome_label: The growth goal label.
        domain: The domain/sub-category.
        task: The specific task.
        answers: List of Q&A pairs from the session.
        top_k: Max results.
        source: Optional source platform filter.

    Returns:
        ToolSearchResponse with ranked results.
    """
    # Build query from session context
    query = _build_session_query(outcome_label, domain, task, answers)

    # Try to map domain to persona for filtering
    persona_filter = _map_domain_to_persona(domain)

    logger.info(
        "Searching by session context",
        domain=domain,
        task=task,
        persona_filter=persona_filter,
        query_length=len(query),
    )

    return await search_by_query(
        query=query,
        top_k=top_k,
        persona=persona_filter,
        source=source,
    )


def get_rag_stats() -> RAGStatsResponse:
    """Get current RAG system statistics."""
    stats = get_collection_stats()

    # Get unique personas and sources from collection info
    # (For a full list, we'd need to scan — for now return from stats)
    return RAGStatsResponse(
        total_tools_indexed=stats.get("total_points", 0),
        collection_name=COLLECTION_NAME,
        embedding_model=EMBEDDING_MODEL,
        status=stats.get("status", "not_initialized"),
    )
