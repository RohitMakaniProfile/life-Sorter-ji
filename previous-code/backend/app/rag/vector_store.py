"""
═══════════════════════════════════════════════════════════════
RAG VECTOR STORE — Qdrant vector database management
═══════════════════════════════════════════════════════════════
Manages the Qdrant collection for tool embeddings.
Uses in-memory storage by default (no external server needed).
Can switch to a Qdrant server via QDRANT_URL env var.
"""

from __future__ import annotations

import os
from typing import Optional

import structlog
from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointStruct,
    VectorParams,
)

from app.rag.embeddings import EMBEDDING_DIMENSION

logger = structlog.get_logger()

# ── Constants ──────────────────────────────────────────────────
COLLECTION_NAME = "ikshan_tools"
BATCH_UPSERT_SIZE = 100


# ── Singleton Client ───────────────────────────────────────────
_client: Optional[QdrantClient] = None


def get_qdrant_client() -> QdrantClient:
    """
    Get or create the Qdrant client singleton.
    Uses QDRANT_URL env var if set, otherwise in-memory.
    """
    global _client
    if _client is None:
        qdrant_url = os.getenv("QDRANT_URL")
        if qdrant_url:
            logger.info("Connecting to Qdrant server", url=qdrant_url)
            _client = QdrantClient(url=qdrant_url)
        else:
            logger.info("Using in-memory Qdrant (no QDRANT_URL set)")
            _client = QdrantClient(":memory:")
    return _client


def ensure_collection() -> None:
    """
    Create the tools collection if it doesn't exist.
    Idempotent — safe to call multiple times.
    """
    client = get_qdrant_client()
    collections = client.get_collections().collections
    existing_names = [c.name for c in collections]

    if COLLECTION_NAME not in existing_names:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(
                size=EMBEDDING_DIMENSION,
                distance=Distance.COSINE,
            ),
        )
        logger.info("Created Qdrant collection", name=COLLECTION_NAME, dim=EMBEDDING_DIMENSION)
    else:
        logger.info("Qdrant collection already exists", name=COLLECTION_NAME)


def upsert_tools(
    ids: list[int],
    vectors: list[list[float]],
    payloads: list[dict],
) -> int:
    """
    Upsert tool vectors + metadata into Qdrant in batches.

    Args:
        ids: Numeric IDs for each point.
        vectors: Embedding vectors.
        payloads: Metadata dicts (name, description, source, etc.)

    Returns:
        Number of points successfully upserted.
    """
    client = get_qdrant_client()
    total_upserted = 0

    for batch_start in range(0, len(ids), BATCH_UPSERT_SIZE):
        batch_end = min(batch_start + BATCH_UPSERT_SIZE, len(ids))

        points = [
            PointStruct(
                id=ids[i],
                vector=vectors[i],
                payload=payloads[i],
            )
            for i in range(batch_start, batch_end)
        ]

        client.upsert(
            collection_name=COLLECTION_NAME,
            points=points,
        )

        batch_count = batch_end - batch_start
        total_upserted += batch_count
        logger.info(
            "Upserted batch to Qdrant",
            batch_start=batch_start,
            batch_count=batch_count,
            total_so_far=total_upserted,
        )

    return total_upserted


def search_tools(
    query_vector: list[float],
    top_k: int = 10,
    persona: Optional[str] = None,
    source: Optional[str] = None,
    category: Optional[str] = None,
) -> list[dict]:
    """
    Search for similar tools using a query embedding vector.

    Args:
        query_vector: The embedding vector for the search query.
        top_k: Number of results to return.
        persona: Optional persona filter (e.g., "B2B Lead Generation").
        source: Optional source filter (e.g., "Google Workspace").
        category: Optional category filter.

    Returns:
        List of dicts with tool metadata + relevance score.
    """
    client = get_qdrant_client()

    # Build filters
    must_conditions = []
    if persona:
        must_conditions.append(
            FieldCondition(key="persona", match=MatchValue(value=persona))
        )
    if source:
        must_conditions.append(
            FieldCondition(key="source", match=MatchValue(value=source))
        )
    if category:
        must_conditions.append(
            FieldCondition(key="category", match=MatchValue(value=category))
        )

    query_filter = Filter(must=must_conditions) if must_conditions else None

    results = client.search(
        collection_name=COLLECTION_NAME,
        query_vector=query_vector,
        limit=top_k,
        query_filter=query_filter,
    )

    return [
        {
            **hit.payload,
            "relevance_score": hit.score,
        }
        for hit in results
    ]


def get_collection_stats() -> dict:
    """Get statistics about the tools collection."""
    client = get_qdrant_client()

    try:
        info = client.get_collection(collection_name=COLLECTION_NAME)
        return {
            "total_points": info.points_count,
            "vectors_count": info.vectors_count,
            "status": info.status.value if info.status else "unknown",
            "collection_name": COLLECTION_NAME,
        }
    except Exception:
        return {
            "total_points": 0,
            "vectors_count": 0,
            "status": "not_initialized",
            "collection_name": COLLECTION_NAME,
        }


def delete_collection() -> bool:
    """Delete the tools collection (for re-ingestion)."""
    client = get_qdrant_client()
    try:
        client.delete_collection(collection_name=COLLECTION_NAME)
        logger.info("Deleted Qdrant collection", name=COLLECTION_NAME)
        return True
    except Exception as e:
        logger.error("Failed to delete collection", error=str(e))
        return False
