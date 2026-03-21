# Pre-Merge Backend Comparison

## life-Sorter-ji/backend (Ikshan)

**What it is:** A business growth advisor — a structured **onboarding funnel** that guides users through a multi-stage diagnostic to recommend tools and generate AI growth playbooks.

**Architecture pattern: Linear session flow**

```
User → Q1 (growth goal) → Q2 (domain) → Q3 (task)
     → Dynamic AI Questions (Claude RCA)
     → Website Crawl Analysis
     → Tool Recommendations (RAG/Qdrant)
     → 5-Agent Playbook Pipeline (Premium, payment-gated)
```

**AI stack:**

| Component | Model | Purpose |
|---|---|---|
| Dynamic Q generation | OpenAI gpt-4o-mini | Task-specific follow-up questions |
| RCA diagnostics | Claude Sonnet via OpenRouter | Adaptive root-cause analysis |
| 5-agent playbook | GLM-5/Claude via OpenRouter | Context brief → playbook → website audit |
| Tool ranking | OpenAI embeddings + Qdrant | Semantic RAG search |
| TTS | OpenAI tts-1 | Hindi/English audio |

**Key technical traits:**
- **In-memory sessions** (`session_store.py`) — no persistent DB for session state
- **Supabase** for leads/conversations only
- **Qdrant** vector store for 2MB tool knowledge base
- **JusPay** payment gating for Stage 2 (premium chat)
- **No SSE streaming** — all responses are synchronous JSON
- **Static data** driving most of the logic (categories.csv, personas_docs/, tools_by_q1_q2_q3.json)

---

## ikshan-ai/fastapi (Research Agent)

**What it is:** A general-purpose **AI research agent** — users ask open-ended questions and the system orchestrates multiple data-collection skills in parallel to produce a synthesized answer.

**Architecture pattern: Dynamic multi-skill orchestration**

```
User message → Gemini orchestrator → picks N skills in parallel
             → skill extraction → subprocess execution
             → result synthesis (Claude/OpenAI final formatter)
             → SSE stream to frontend
```

**AI stack:**

| Component | Model | Purpose |
|---|---|---|
| Orchestrator | Gemini 2.5 Flash/Pro | Decides which skills to call + args |
| Skill arg extraction | Gemini JSON mode | Structured input for each skill |
| Final formatter | Claude (prefers large ctx) | Synthesizes all skill outputs |
| Platform scout | Gemini | Identifies platforms to research |
| Skills | Python subprocesses | Actual data collection |

**Key technical traits:**
- **SSE streaming** throughout — tokens, stages, progress all streamed live
- **asyncpg raw SQL** for conversation/message/token persistence
- **Skills as subprocesses** with stdin/stdout JSON + `PROGRESS:` protocol
- **15-round Gemini loop** with dedup and parallel execution
- **No payment gating** — open access
- **Dynamic agents** — each `UiAgent` defines allowed skills + formatting context

---

## Side-by-Side Comparison

| Dimension | life-Sorter-ji/backend | ikshan-ai/fastapi |
|---|---|---|
| **Purpose** | Structured funnel → playbook | Open-ended research agent |
| **Session model** | Linear stages (Q1→Q2→Q3→RCA→playbook) | Free-form conversation history |
| **AI orchestration** | Fixed 5-agent pipeline | Dynamic Gemini-directed N-skill loop |
| **Data sources** | Static CSVs + Supabase + Qdrant | Live web/social scraping via skills |
| **Streaming** | None (sync JSON) | Full SSE (tokens, stages, progress) |
| **DB** | Supabase (cloud PostgreSQL) | asyncpg (self-hosted PostgreSQL) |
| **Vector store** | Qdrant for tool RAG | None |
| **Payment** | JusPay gating | None |
| **Session state** | In-memory dict | Persisted to DB (messages table) |
| **Skills/tools** | Hardcoded services | 13 dynamic subprocess skills |
| **Complexity** | Domain-specific, deep persona docs | General-purpose, breadth-first research |

---

## Summary

**Ikshan (life-Sorter-ji)** is a product with a fixed journey — every user walks the same funnel.

**ikshan-ai/fastapi** is an agentic research platform — Gemini dynamically decides what to research based on the question, making it architecturally more complex and general-purpose.
