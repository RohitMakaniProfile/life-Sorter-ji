"""
═══════════════════════════════════════════════════════════════
RAG MODULE — Retrieval-Augmented Generation for Tool Recommendations
═══════════════════════════════════════════════════════════════
Vector-based tool retrieval pipeline:
  1. Ingest tools from matched_tools_by_persona.json
  2. Embed tool descriptions via OpenAI text-embedding-3-small
  3. Store embeddings in Qdrant (in-memory for dev)
  4. Retrieve relevant tools based on session context
"""
