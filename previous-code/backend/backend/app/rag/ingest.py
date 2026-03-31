"""
═══════════════════════════════════════════════════════════════
RAG INGEST — Load & embed tools from matched_tools_by_persona.json
═══════════════════════════════════════════════════════════════
Reads the JSON file, normalizes each tool record, generates
embeddings, and stores everything in Qdrant.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import structlog

from app.rag.embeddings import generate_embeddings_batch
from app.rag.models import IngestResponse, ToolRecord
from app.rag.vector_store import (
    delete_collection,
    ensure_collection,
    upsert_tools,
)

logger = structlog.get_logger()

# ── File Location ──────────────────────────────────────────────
# The JSON file is at the project root (one level above backend/)
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_JSON_PATH = _PROJECT_ROOT / "matched_tools_by_persona.json"


def _clean_persona_name(raw: str) -> str:
    """
    Convert persona key like 'B2B Lead Generation.docx'
    to a clean persona name: 'B2B Lead Generation'.
    """
    return raw.replace(".docx", "").replace(".DOCX", "").strip()


def _build_embedding_text(tool: ToolRecord) -> str:
    """
    Build the text to embed for a tool.
    Combines name, description, category, and persona for rich context.
    Falls back to search_text if description is sparse.
    """
    parts = []

    # Always include the tool name
    parts.append(f"Tool: {tool.name}")

    # Include persona context for domain relevance
    if tool.persona:
        parts.append(f"Domain: {tool.persona}")

    # Category adds semantic signal
    if tool.category:
        parts.append(f"Category: {tool.category}")

    # Source platform
    if tool.source:
        parts.append(f"Platform: {tool.source}")

    # Use description first, but if it's very short, supplement with search_text
    if tool.description and len(tool.description) > 50:
        parts.append(f"Description: {tool.description}")
    elif tool.search_text and len(tool.search_text) > 50:
        # search_text is often very long — take first 2000 chars
        parts.append(f"Description: {tool.search_text[:2000]}")
    elif tool.description:
        parts.append(f"Description: {tool.description}")

    return "\n".join(parts)


def load_tools_from_json(
    json_path: Optional[Path] = None,
) -> list[ToolRecord]:
    """
    Load and normalize all tools from the JSON file.

    Args:
        json_path: Path to the JSON file. Defaults to project root.

    Returns:
        List of ToolRecord objects.
    """
    path = json_path or DEFAULT_JSON_PATH

    if not path.exists():
        logger.error("JSON file not found", path=str(path))
        raise FileNotFoundError(f"Tool data file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    tools: list[ToolRecord] = []
    seen_keys: set[str] = set()

    for persona_key, tool_list in raw_data.items():
        persona_name = _clean_persona_name(persona_key)

        if not isinstance(tool_list, list):
            logger.warning("Skipping non-list persona entry", persona=persona_key)
            continue

        for raw_tool in tool_list:
            if not isinstance(raw_tool, dict):
                continue

            name = raw_tool.get("name", "").strip()
            if not name:
                continue

            # Deduplicate by (name, source, persona)
            dedup_key = f"{name}|{raw_tool.get('source', '')}|{persona_name}"
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            tool = ToolRecord(
                name=name,
                description=raw_tool.get("description", ""),
                source=raw_tool.get("source", ""),
                category=raw_tool.get("category", ""),
                rating=raw_tool.get("rating", ""),
                installs=raw_tool.get("installs", ""),
                url=raw_tool.get("url", ""),
                search_text=raw_tool.get("search_text", ""),
                score=raw_tool.get("score", 0),
                persona=persona_name,
            )
            tools.append(tool)

    logger.info(
        "Loaded tools from JSON",
        total_tools=len(tools),
        personas=len(raw_data),
        path=str(path),
    )
    return tools


async def ingest_tools(
    json_path: Optional[Path] = None,
    force: bool = False,
) -> IngestResponse:
    """
    Full ingestion pipeline:
      1. Load tools from JSON
      2. Generate embeddings for each tool
      3. Store in Qdrant

    Args:
        json_path: Optional custom path to JSON file.
        force: If True, delete existing collection and re-ingest.

    Returns:
        IngestResponse with stats.
    """
    errors: list[str] = []

    # Step 1: Load tools
    try:
        tools = load_tools_from_json(json_path)
    except FileNotFoundError as e:
        return IngestResponse(
            status="error",
            errors=[str(e)],
        )

    if not tools:
        return IngestResponse(
            status="error",
            errors=["No tools found in JSON file"],
        )

    logger.info("Starting tool ingestion", tool_count=len(tools))

    # Step 2: Delete old collection if force re-ingest
    if force:
        delete_collection()

    # Create collection
    ensure_collection()

    # Step 3: Build embedding texts
    embedding_texts = [_build_embedding_text(t) for t in tools]

    # Step 4: Generate embeddings in batches
    logger.info("Generating embeddings", count=len(embedding_texts))
    embeddings = await generate_embeddings_batch(embedding_texts)

    # Step 5: Filter out tools where embedding failed
    valid_ids: list[int] = []
    valid_vectors: list[list[float]] = []
    valid_payloads: list[dict] = []

    for i, (tool, embedding) in enumerate(zip(tools, embeddings)):
        if embedding is None:
            errors.append(f"Embedding failed for tool: {tool.name}")
            continue

        valid_ids.append(i)
        valid_vectors.append(embedding)
        valid_payloads.append({
            "name": tool.name,
            "description": tool.description,
            "source": tool.source,
            "category": tool.category,
            "rating": tool.rating,
            "installs": tool.installs,
            "url": tool.url,
            "persona": tool.persona,
            "score": tool.score,
        })

    # Step 6: Upsert into Qdrant
    if valid_ids:
        upserted = upsert_tools(valid_ids, valid_vectors, valid_payloads)
        logger.info("Ingestion complete", upserted=upserted, errors=len(errors))
    else:
        errors.append("No valid embeddings generated — nothing to index")

    # Collect personas processed
    personas = sorted(set(t.persona for t in tools))

    return IngestResponse(
        status="success" if valid_ids else "error",
        tools_ingested=len(valid_ids),
        personas_processed=personas,
        errors=errors,
    )
