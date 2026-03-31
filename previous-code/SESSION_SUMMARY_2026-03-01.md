# Session Summary — March 1, 2026

## Overview
Continued multi-day development session (started Feb 28). Today's focus was building the **Claude RCA (Root Cause Analysis) diagnostic engine** and **enriching its question quality** to impress users.

---

## What Was Built Today

### 1. Claude RCA Diagnostic Engine ✅
**Files created:**
- `backend/app/services/claude_rca_service.py` — Core service calling Claude Sonnet via OpenRouter API
- `backend/app/config.py` — Added `OPENROUTER_API_KEY` and `OPENROUTER_MODEL` settings

**How it works:**
- After the user answers Q1 (outcome), Q2 (domain), Q3 (task), the system silently loads rich diagnostic context from persona docs (problems, RCA bridge symptoms, opportunities, strategies)
- This context is sent to Claude Sonnet via OpenRouter along with conversation history
- Claude generates adaptive, one-at-a-time diagnostic questions with multiple-choice options
- Each question builds on previous answers — progressive depth from visible symptom → root behavior → systemic gap
- After 4-5 questions, Claude signals completion with a diagnostic summary
- Fallback: if Claude is unreachable, the old static dynamic-loader questions are served

**Files modified for RCA integration:**
- `backend/app/routers/agent.py` — `/session/task` now calls Claude for first RCA question; `/session/answer` handles adaptive RCA Q&A loop
- `backend/app/models/session.py` — Added `rca_diagnostic_context`, `rca_history`, `rca_complete`, `rca_summary`, `rca_fallback_active` fields; extended `SubmitDynamicAnswerResponse` with `rca_mode`, `acknowledgment`, `rca_summary`
- `backend/app/services/session_store.py` — Added `set_rca_context()`, `add_rca_answer()`, `set_rca_complete()`, `set_rca_fallback()` functions
- `frontend/src/components/ChatBotNew.jsx` — Added `rcaMode` state; `handleTaskClick()` detects RCA mode; `handleDynamicAnswer()` handles adaptive Claude questions with typing indicator
- `frontend/src/components/ChatBotNewMobile.jsx` — Same RCA mode support added

### 2. Enriched RCA Question Quality ✅
**Problem:** Initial Claude questions were too generic ("What's not working with your social media?") and Claude was completing after only 1-2 questions.

**Solution — System Prompt Overhaul:**
- Rewrote Claude's persona as "Ikshan — world-class business diagnostic advisor"
- Added 7 detailed question-crafting rules with BAD/GOOD examples
- Instructed Claude to weave in industry metrics/KPIs from RCA bridge data
- Added micro-insight acknowledgments (not just empathy)
- Progressive depth model: RCA-Q1 (symptom) → RCA-Q2 (root behavior) → RCA-Q3 (systemic gap) → RCA-Q4-Q5 (validate & confirm)
- "Power move" ending rule for aha-moment final question

**Solution — Context Builder Enrichment:**
- Now passes structured RCA bridge data (symptom → KPI/metric → root-cause area)
- Includes task variants for vocabulary depth
- Strategies bumped to 2000 chars with instruction to reference frameworks naturally
- Clear section labels: "REAL-WORLD PROBLEM PATTERNS", "DIAGNOSTIC SIGNALS", "GROWTH OPPORTUNITIES"

**Solution — Question Count Fix:**
- Minimum 4 diagnostic questions enforced (was completing after 1-2)
- Explicit instruction that user's Q1/Q2/Q3 don't count toward Claude's quota
- Context builder now tells Claude exactly how many more questions it must ask
- Renamed Q1-Q5 to RCA-Q1 through RCA-Q5 to avoid confusion
- `max_tokens` bumped from 600 → 900 for richer responses

### 3. Previously Completed (Feb 28 - Mar 1)
- **RAG Pipeline** — 360 tools indexed in Qdrant (in-memory), auto-ingests on startup
- **RAG → Recommendations** — Rewired `generate_personalized_recommendations()` to query RAG first, feed real tools to GPT
- **Sandbox/Developer Panel** — Login (ikshan/123), Test Flow panel, Logger with real-time logs, export to .txt
- **Developer Button in Header** — Moved from floating FAB to header bar (desktop + mobile)

---

## Architecture Snapshot

```
User Flow:
Q1 (Outcome) → Q2 (Domain) → Q3 (Task)
    → [Dynamic Loader silently loads persona doc context]
    → Claude RCA Q1-Q5 (adaptive, one at a time)
    → Auth Gate (login/signup)
    → GPT Recommendations (RAG-powered, real tools)
    → Complete

Tech Stack:
- Backend: FastAPI + uvicorn (port 8000, --reload)
- Frontend: React 19 + Vite 7.2.6 (port 5173)
- RAG: Qdrant (in-memory) + OpenAI text-embedding-3-small
- RCA: Claude Sonnet via OpenRouter API
- Recommendations: GPT-4o-mini via OpenAI API
```

---

## Key Files Changed (22 files)

### Backend — Modified
| File | Change |
|------|--------|
| `app/config.py` | Added OpenRouter API key + model config |
| `app/main.py` | RAG auto-ingest on startup |
| `app/models/session.py` | RCA fields + response models |
| `app/routers/agent.py` | Claude RCA integration in task/answer endpoints |
| `app/services/agent_service.py` | RAG integration for recommendations |
| `app/services/session_store.py` | RCA state management functions |
| `requirements.txt` | Added qdrant-client, docx dependencies |

### Backend — New
| File | Purpose |
|------|---------|
| `app/services/claude_rca_service.py` | Claude RCA engine (OpenRouter) |
| `app/services/sandbox_logger.py` | Sandbox logging service |
| `app/routers/sandbox.py` | Sandbox API endpoints |
| `app/routers/rag.py` | RAG API endpoints |
| `app/rag/` | RAG pipeline (ingest, query, vectorstore) |

### Frontend — Modified
| File | Change |
|------|--------|
| `src/App.jsx` | Sandbox panel routing + developer button |
| `src/App.css` | Sandbox panel styles |
| `src/components/ChatBotNew.jsx` | RCA mode + developer button in header |
| `src/components/ChatBotNew.css` | RCA + developer button styles |
| `src/components/ChatBotNewMobile.jsx` | RCA mode (mobile) |

### Frontend — New
| File | Purpose |
|------|---------|
| `src/components/SandboxLogin.jsx` | Developer login component |
| `src/components/SandboxLogin.css` | Login styles |
| `src/components/SandboxPanel.jsx` | Developer panel (test flow + logger) |
| `src/components/SandboxPanel.css` | Panel styles |

---

## What's Next (Future Sessions)
- [ ] Frontend polish for RCA questions (display micro-insights distinctly)
- [ ] Add `insight` field to RCA response for frontend to render separately
- [ ] Payment flow completion (Juspay integration)
- [ ] End-to-end testing of full user journey
- [ ] Deploy to production (Docker + Vercel)
