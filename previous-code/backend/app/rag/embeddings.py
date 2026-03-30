"""
═══════════════════════════════════════════════════════════════
RAG EMBEDDINGS — OpenAI embedding generation service
═══════════════════════════════════════════════════════════════
Generates embeddings using OpenAI text-embedding-3-small model.
Handles batching to stay within API limits.
"""

from __future__ import annotations

import asyncio
from typing import Optional

import structlog
from openai import AsyncOpenAI

from app.config import get_settings

logger = structlog.get_logger()

# ── Constants ──────────────────────────────────────────────────
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSION = 1536
MAX_BATCH_SIZE = 100          # OpenAI allows up to 2048, but 100 is safe
MAX_TEXT_LENGTH = 8000         # Truncate texts longer than this (token-safe)


def _get_client() -> AsyncOpenAI:
    """Get an async OpenAI client with the active API key."""
    settings = get_settings()
    return AsyncOpenAI(api_key=settings.openai_api_key_active)


def _prepare_text(text: str, max_length: int = MAX_TEXT_LENGTH) -> str:
    """Truncate text to stay within token limits."""
    if len(text) > max_length:
        return text[:max_length]
    return text


async def generate_embedding(text: str) -> Optional[list[float]]:
    """
    Generate a single embedding vector for the given text.

    Returns:
        List of floats (1536-dimensional vector) or None on failure.
    """
    client = _get_client()
    cleaned = _prepare_text(text)

    if not cleaned.strip():
        logger.warning("Empty text provided for embedding")
        return None

    try:
        response = await client.embeddings.create(
            model=EMBEDDING_MODEL,
            input=cleaned,
        )
        return response.data[0].embedding
    except Exception as e:
        logger.error("Failed to generate embedding", error=str(e), text_preview=cleaned[:80])
        return None


async def generate_embeddings_batch(
    texts: list[str],
    batch_size: int = MAX_BATCH_SIZE,
) -> list[Optional[list[float]]]:
    """
    Generate embeddings for a batch of texts with automatic chunking.

    Args:
        texts: List of texts to embed.
        batch_size: Number of texts per API call.

    Returns:
        List of embedding vectors (or None for failed items),
        in the same order as the input texts.
    """
    client = _get_client()
    results: list[Optional[list[float]]] = [None] * len(texts)

    # Prepare texts
    prepared = [_prepare_text(t) for t in texts]

    # Process in batches
    for batch_start in range(0, len(prepared), batch_size):
        batch_end = min(batch_start + batch_size, len(prepared))
        batch = prepared[batch_start:batch_end]

        # Filter out empty texts in this batch
        non_empty_indices = []
        non_empty_texts = []
        for i, text in enumerate(batch):
            if text.strip():
                non_empty_indices.append(batch_start + i)
                non_empty_texts.append(text)

        if not non_empty_texts:
            continue

        try:
            response = await client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=non_empty_texts,
            )

            for j, embedding_data in enumerate(response.data):
                original_index = non_empty_indices[j]
                results[original_index] = embedding_data.embedding

            logger.info(
                "Embedding batch completed",
                batch_start=batch_start,
                batch_size=len(non_empty_texts),
                total=len(texts),
            )

        except Exception as e:
            logger.error(
                "Embedding batch failed",
                error=str(e),
                batch_start=batch_start,
                batch_size=len(non_empty_texts),
            )
            # Leave results as None for this batch — partial success

        # Rate-limit safety: small delay between batches
        if batch_end < len(prepared):
            await asyncio.sleep(0.5)

    successful = sum(1 for r in results if r is not None)
    logger.info(
        "Embedding generation complete",
        total=len(texts),
        successful=successful,
        failed=len(texts) - successful,
    )

    return results


async def generate_query_embedding(query: str) -> Optional[list[float]]:
    """
    Generate an embedding for a search query.
    Identical to generate_embedding but named separately for clarity.
    """
    return await generate_embedding(query)
