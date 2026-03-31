"""
═══════════════════════════════════════════════════════════════
RAG MODELS — Pydantic models for the RAG pipeline
═══════════════════════════════════════════════════════════════
"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


# ── Tool Data Models ───────────────────────────────────────────


class ToolRecord(BaseModel):
    """
    A single tool record extracted from matched_tools_by_persona.json.
    Represents a Chrome extension, Play Store app, GPT, Zapier integration, etc.
    """
    name: str
    description: str
    source: str                          # e.g. "Google Workspace", "Play Store"
    category: str = ""
    rating: str = ""
    installs: str = ""
    url: str = ""
    search_text: str = ""                # Full description text for embedding
    score: int = 0                       # Original relevance score from scraping
    persona: str = ""                    # Which persona doc this belongs to


class ToolSearchRequest(BaseModel):
    """Request to search for tools via the RAG pipeline."""
    query: str = Field(..., min_length=1, description="Free-text search query")
    persona: Optional[str] = Field(None, description="Filter by persona (domain)")
    source: Optional[str] = Field(None, description="Filter by source platform")
    category: Optional[str] = Field(None, description="Filter by tool category")
    top_k: int = Field(10, ge=1, le=50, description="Number of results")


class ToolSearchBySessionRequest(BaseModel):
    """Request to search for tools using session context."""
    session_id: str = Field(..., description="Session ID from the agent flow")
    top_k: int = Field(10, ge=1, le=50, description="Number of results")
    source: Optional[str] = Field(None, description="Filter by source platform")


class ToolResult(BaseModel):
    """A single tool result from RAG retrieval."""
    name: str
    description: str
    source: str
    category: str = ""
    rating: str = ""
    installs: str = ""
    url: str = ""
    persona: str = ""
    relevance_score: float = 0.0        # Cosine similarity score


class ToolSearchResponse(BaseModel):
    """Response from RAG tool search."""
    query: str
    results: list[ToolResult] = []
    total_results: int = 0


class RAGStatsResponse(BaseModel):
    """Response for RAG system statistics."""
    total_tools_indexed: int = 0
    personas: list[str] = []
    sources: list[str] = []
    collection_name: str = ""
    embedding_model: str = ""
    status: str = "not_initialized"


class IngestResponse(BaseModel):
    """Response after ingesting tools."""
    status: str
    tools_ingested: int = 0
    personas_processed: list[str] = []
    errors: list[str] = []
