# Ikshan Session Analysis — 16 March 2026

## Objective
Audit the complete Ikshan chatbot session to understand time taken at every phase and question, and identify why a single chat takes **20+ minutes** in reality.

---

## Complete Flow (Step-by-Step)

```
outcome → domain → task → url-input → scale-questions
    → diagnostic (start + 3-4 RCA Qs) → precision-questions
    → auth-gate → playbook (5 agents) → complete
```

---

## Phase-by-Phase Time Breakdown

### Phase 1: Q1 — Outcome Selection
- **Type:** User click (4 buttons)
- **LLM Call:** None — stores selection
- **API:** `POST /session` + `POST /session/outcome`
- **User Time:** ~5s
- **LLM Wait:** 0s

### Phase 2: Q2 — Domain Selection
- **Type:** User click (4-5 options per outcome)
- **LLM Call:** None — stores selection
- **API:** `POST /session/domain`
- **User Time:** ~5s
- **LLM Wait:** 0s

### Phase 3: Q3 — Task Selection
- **Type:** User click + triggers 3 parallel backend calls
- **API:** `POST /session/task`
- **What fires:**
  - (a) **Instant tool lookup** — JSON dictionary, <1ms
  - (b) **LLM #1:** `generate_next_rca_question` → GLM-5 via OpenRouter, 90s timeout, 3 retries with exponential backoff (2s, 3s, 5s sleep on 429)
  - (c) Persona doc loading (local, fast)
- **User Time:** ~5s (click)
- **LLM Wait:** **5-30s** (blocking — user sees loading spinner)

### Phase 4: Early Tool Recommendations
- **Type:** Auto-displayed (from instant JSON lookup at Q3)
- **LLM Call:** None (pre-mapped JSON)
- **User Time:** ~10s (reading)
- **LLM Wait:** 0s

### Phase 5: URL Input
- **Type:** User types website URL
- **API:** `POST /session/url` → returns immediately, fires async background crawl
- **User Time:** ~10-15s
- **LLM Wait:** 0s (non-blocking)

### Phase 5b: Background Crawl (runs in parallel while user does Scale Questions)
- **What happens:**
  - Fetch homepage (15s timeout)
  - Crawl up to **15 internal pages** in batches of 5 (15s timeout per page)
  - **LLM #2:** `generate_crawl_summary` → GPT-4o-mini, max_tokens 300
- **User Time:** 0s (hidden)
- **Background Time:** **15-45s**
- **Polled by frontend:** Every 3 seconds

### Phase 6: Scale Questions
- **Type:** User form — **4 business profile questions**
  1. Business Stage
  2. Current Stack
  3. Primary Channel
  4. Biggest Constraint
- **API:** `GET /scale-questions` + `POST /scale-answers` (no LLM)
- **User Time:** **30-90s**
- **LLM Wait:** 0s

### Phase 7: Start Diagnostic (Context-Aware)
- **Type:** Transition screen (loading)
- **LLM #3:** `generate_next_rca_question` → GLM-5 via OpenRouter, 90s timeout, 3 retries
- **Context sent:** Q1 + Q2 + Q3 + scale answers + crawl data + persona doc
- **User Time:** 0s
- **LLM Wait:** **5-20s** (blocking)

### Phase 8-11: RCA Diagnostic Questions (3-4 adaptive questions)
Each question follows this loop:
1. User reads insight + picks option → **15-30s**
2. Answer submitted → LLM generates next question → **5-20s** (blocking)

| Step | Action | User Time | LLM Wait |
|------|--------|-----------|----------|
| RCA Q1 | Read + answer | 15-30s | 0s |
| Q1 → Q2 | LLM #4: next question | 0s | **5-20s** |
| RCA Q2 | Read + answer | 15-30s | 0s |
| Q2 → Q3 | LLM #5: next question | 0s | **5-20s** |
| RCA Q3 | Read + answer | 15-30s | 0s |
| Q3 → Q4 | LLM #6: next question (optional) | 0s | **0-20s** |
| RCA Q4 | Read + answer (optional) | 0-30s | 0s |

- **Model:** GLM-5 via OpenRouter
- **Timeout:** 90s per call
- **Max Tokens:** 4000
- **Retry:** 3 attempts with `2^attempt + 1` sec backoff

### Phase 12: Crawl Wait (if still running)
- **Type:** Blocking spinner
- **Polls:** `GET /crawl-status` every 2 seconds
- **User Time:** 0s
- **Wait:** **0-30s** (depends on crawl speed)

### Phase 13: Precision Questions Generation
- **LLM #7:** `generate_precision_questions` → GLM-5 via OpenRouter
- **Timeout:** 90s, 3 retries
- **Max Tokens:** 4000
- **Generates:** 3 cross-reference questions (contradiction, blind spot, unlock)
- **User Time:** 0s (loading)
- **LLM Wait:** **5-20s** (blocking)

### Phase 14: Precision Questions — User Answers
- **Type:** User answers 3 questions one-by-one
- **User Time:** **60-90s**
- **LLM Wait:** 0s

### Phase 15: Auth Gate
- **Type:** Google OAuth or email sign-in
- **User Time:** **15-30s**
- **LLM Wait:** 0s

### Phase 16: Playbook — Agent 1 (Context Parser)
- **LLM #8:** GLM-5 via OpenRouter
- **Timeout:** 120s, 3 retries
- **Max Tokens:** 3000
- **User Time:** 0s (loading screen)
- **LLM Wait:** **10-30s** (blocking)

### Phase 17: Playbook — Agent 2 (ICP Analyst)
- **LLM #9:** GLM-5 via OpenRouter
- **Timeout:** 120s, 3 retries
- **Max Tokens:** 4000
- **User Time:** 0s (loading screen)
- **LLM Wait:** **10-30s** (blocking)

### Phase 18: Gap Questions (optional)
- **Type:** 0-3 follow-up questions if Agent 2 finds gaps
- **User Time:** **0-45s**
- **LLM Wait:** 0s

### Phase 19: Playbook — Agent 3 (Playbook Architect)
- **LLM #10:** GLM-5 via OpenRouter
- **Timeout:** 120s, 3 retries
- **Max Tokens:** **10,000** ← biggest single generation
- **User Time:** 0s (loading screen)
- **LLM Wait:** **15-45s** (blocking)

### Phase 20: Playbook — Agents 4+5 (parallel)
- **LLM #11:** Agent 4 (Tool Intelligence) → GLM-5, 120s timeout, 4000 tokens
- **LLM #12:** Agent 5 (Website Critic) → GLM-5, 120s timeout, 4000 tokens
- **Run in parallel** — wait = max of the two
- **User Time:** 0s
- **LLM Wait:** **10-30s** (blocking)

### Phase 21: Final Report Display
- **Type:** Reading the playbook
- **LLM Wait:** 0s

---

## Summary Totals

### User Interactions
| Count | What |
|-------|------|
| 3 | Static selections (Q1, Q2, Q3) |
| 1 | URL input |
| 4 | Scale questions |
| 3-4 | RCA diagnostic questions |
| 3 | Precision questions |
| 1 | Auth gate |
| 0-3 | Gap questions |
| **15-19** | **Total user-facing interactions** |

### LLM Calls
| Provider | Calls | Timeout | Purpose |
|----------|-------|---------|---------|
| GLM-5 (OpenRouter) | **9-11** | 90-120s each | First RCA Q, Start Diagnostic, 3-4 RCA Qs, Precision Qs, 5 Playbook Agents |
| GPT-4o-mini (OpenAI) | **1-2** | — | Crawl summary, early recs (if RAG path used) |
| **TOTAL** | **10-12** | — | — |

### Every OpenRouter call has:
- **3 retries** on 429 rate limits
- **Exponential backoff:** sleep 2s, 3s, 5s between retries
- **Worst case per call:** 90-120s timeout + 10s retry sleep = **up to 130s**

---

## Time Budget (Wall Clock)

| Category | Optimistic | Realistic | Pessimistic |
|----------|-----------|-----------|-------------|
| User interaction (reading + answering 15-19 Qs) | 3 min | 5 min | 8 min |
| Q3 first RCA question (LLM #1) | 5s | 15s | 30s |
| Start diagnostic (LLM #3) | 5s | 15s | 30s |
| RCA chain (3-4 sequential LLM calls) | 15s | 1.5 min | 4 min |
| Precision Qs generation (LLM #7) | 5s | 15s | 30s |
| Playbook pipeline (5 agents: 3 sequential + 2 parallel) | 45s | 2.5 min | 6 min |
| Crawl pipeline (15 pages + GPT summary) | 15s | 30s | 1.5 min |
| Auth gate | 10s | 20s | 1 min |
| Network overhead + retries | 5s | 30s | 2 min |
| **TOTAL** | **~5 min** | **~10-12 min** | **~22+ min** |

---

## Top 3 Time Killers

### 1. Playbook Pipeline (Phases 16-20)
- **5 LLM calls** with 120s timeouts
- Agent 3 alone generates **10,000 tokens** (takes 15-45s)
- 3 sequential + 2 parallel = minimum **4 round-trips**
- **Adds 2-6 min** of pure waiting

### 2. Sequential RCA Chain (Phases 7-11)
- Each user answer triggers a new GLM-5 call (90s timeout)
- 3-4 iterations × (5-20s LLM wait + 15-30s user time)
- **Adds 2-5 min** total

### 3. User Reading Time
- 15-19 interactions with insight-rich questions
- Each takes 15-30s to read and understand
- **Adds 5-8 min**

---

## Technical Details

### Models Used
| Model | Via | Used For |
|-------|-----|----------|
| `z-ai/glm-5` | OpenRouter | All RCA questions, precision Qs, all 5 playbook agents |
| `gpt-4o-mini` | OpenAI direct | Crawl summary, early recommendations |

### System Prompt Sizes (contribute to latency)
- RCA system prompt: **~3000+ words** (includes diagnostic rules, persona context, crawl data, business profile)
- Playbook Agent 3: Largest — generates full playbook with 10,000 max_tokens

### Retry Logic (on ALL OpenRouter calls)
```python
for _attempt in range(3):
    resp = await client.post(url, json=payload, headers=headers)
    if resp.status_code == 429 and _attempt < 2:
        await asyncio.sleep(2 ** _attempt + 1)  # 2s, 3s, 5s
        continue
    resp.raise_for_status()
    break
```

### Crawl Config
- `CRAWL_TIMEOUT = 15.0` seconds per page
- `MAX_INTERNAL_PAGES = 15`
- Batches of 5 concurrent page fetches
- Frontend polls every 2-3 seconds

---

## Dormant/Disabled Features (not in current critical path)
1. **Task Alignment Filter** — additional LLM call exists in code but `filtered_context` is always `None`
2. **Business Intel Verdict** — LLM call exists (GPT-4o-mini, 2000 tokens) but commented out / disabled in frontend
3. **Website Audience Analysis** — code exists in `agent_service.py` (GPT-4o-mini, 1000 tokens), separate from crawl summary

---

## Optimization Plan

> Reference: [Claude chat](https://claude.ai/share/83d738c4-f6bc-47c7-92c2-8d1bf7a72ee7)

---

### SPRINT 1: SSE Streaming — Playbook Delivery

Stream Agent 3 output token-by-token via SSE instead of waiting for the full 10K response.

| Dimension | Detail |
|-----------|--------|
| **What to do** | Backend: Add streaming variant of `_call_claude()` (`payload["stream"] = True`, async iterator). New SSE endpoint `/playbook/stream`. Frontend: Replace `fetch()` → `await response.json()` in `startPlaybook()` with `ReadableStream` consumer + progressive markdown renderer. |
| **Files** | `playbook_service.py`, `playbook.py`, `ChatBotNew.jsx`, `ChatBotNewMobile.jsx`, `ChatBotNew.css` |
| **Time saved** | Perceived wait: 30-45s → 2-3s |
| **Verdict** | ✅ **Highest-ROI change.** Same output, just delivered sooner. |

---

### SPRINT 2: Model Router — Tiered Model Selection

Route cheap calls (Agent 1, crawl summary, first RCA) to GPT-4o-mini/Haiku. Keep premium calls (RCA chain, Agents 2-3) on GLM-5.

| Dimension | Detail |
|-----------|--------|
| **What to do** | Create `model_router.py` with `MODEL_CONFIG` dict. Modify `_call_claude()` to accept model/provider params. Update `config.py` with per-tier env vars. |
| **Files** | New: `model_router.py`. Modified: `playbook_service.py`, `claude_rca_service.py`, `agent_service.py`, `config.py`, `.env` |
| **Cost savings** | ~50-60% per session (₹25-40 → ₹8-16) |
| **Verdict** | ✅ **Major cost reduction.** Add output validation on Agent 1 to ensure format consistency across models. |

---

### SPRINT 3b: Parallelize Agent 5 with Agent 3

Fire Agent 5 (Website Critic) alongside Agent 3 instead of after it. Agent 5 only needs crawl data + Agent 2 output — both available before Agent 3 starts.

| Dimension | Detail |
|-----------|--------|
| **What to do** | In `run_full_playbook_pipeline()`, restructure `asyncio.gather()` — run Agent 5 in parallel with Agent 3 instead of with Agent 4. ~10 lines changed. |
| **Files** | `playbook_service.py` |
| **Time saved** | 10-20s (Agent 5 hidden behind Agent 3's longer execution) |
| **Verdict** | ✅ **10-line change, instant win.** |

---

### SPRINT 3a: Merge Phase 0 into Agent 1

Absorb gap question detection into Agent 1's prompt, eliminating a full LLM round-trip.

| Dimension | Detail |
|-----------|--------|
| **What to do** | Rewrite `AGENT1_PROMPT` to include gap question generation. Modify `/start` endpoint flow from Agent 1 → Agent 2 → detect gaps to Agent 1 (with gaps) → show gaps → Agent 2. Update `_detect_gap_questions()` and `_parse_gap_questions()`. |
| **Files** | `playbook_service.py`, `playbook.py`, `ChatBotNew.jsx` |
| **Time saved** | ~10-30s (one fewer LLM call) |
| **Verdict** | ✅ **Saves a full round-trip.** Test that Agent 1 produces both clean structured output AND quality gap questions in one pass. |

---

### SPRINT 4: Two-Pass Playbook (Skeleton + Enrichment)

Split Agent 3 into Pass 1 (skeleton, ~2K tokens) streamed immediately, then Pass 2 (full enrichment) streamed after.

| Dimension | Detail |
|-----------|--------|
| **What to do** | Split `AGENT3_PROMPT` into two prompts. Modify `run_agent3_playbook_architect()` for two sequential calls. Fire Agent 4 after Pass 1. Frontend handles two-phase rendering. |
| **Files** | `playbook_service.py`, `playbook.py`, `ChatBotNew.jsx`, `ChatBotNewMobile.jsx` |
| **Time saved** | Time-to-first-content: 30s → 5-8s (combined with streaming) |
| **Verdict** | ✅ **Build after Sprint 1.** Streaming alone covers 80% of the perceived speed gain; two-pass adds the remaining 20%. |

---

### SPRINT 5: Caching + Prompt Compression

(a) Cache enrichment blocks by industry × task. (b) Compress system prompts by 40-50%.

| Dimension | Detail |
|-----------|--------|
| **What to do** | Add Redis cache layer with cache key generation from session data. Audit and compress ALL system prompts across `claude_rca_service.py`, `playbook_service.py`, `agent_service.py`. |
| **Files** | New: caching service. Modified: all service files, `docker-compose.yml` (Redis), `requirements.txt` |
| **Time saved** | Caching: variable (depends on cache hit rate). Compression: ~1-2s per LLM call. |
| **Verdict** | ✅ **Build after observability (Sprint 6c) provides data on which prompts to compress and which responses to cache.** |

---

### SPRINT 6: Crawl Optimization + Auth Move + Observability

(a) Reduce crawl from 15 to 8 pages. (b) Move auth to overlap with scale questions. (c) Build per-session logging.

| Dimension | Detail |
|-----------|--------|
| **6a** | Change `MAX_INTERNAL_PAGES = 15` to `8` in `crawl_service.py`. One line. |
| **6b** | Move Google OAuth trigger from `auth-gate` stage to `url-input` or `scale-questions`. Frontend flow state machine change. |
| **6c** | Add cost estimate per call, drop-off tracking, aggregate dashboard. Plumbing already exists in `user_session_service.py`. |
| **Files** | 6a: `crawl_service.py`. 6b: `ChatBotNew.jsx` + mobile. 6c: `user_session_service.py` + new endpoint. |
| **Verdict** | ✅ **All quick wins.** 6a is 1 line. 6b saves 15-30s. 6c gives data for every future decision. |

---

### Other Proposals

| Proposal | What to do | Time saved | Verdict |
|----------|-----------|------------|---------|
| **Collapse Q1+Q2+Q3** | Redesign frontend selection from 3-step funnel to single screen | ~10s | ✅ Do after UX research — current funnel is only 15s |
| **Reduce RCA to 2 Qs** | Change `total_questions` logic in `claude_rca_service.py` | ~30-60s | ✅ A/B test first to validate diagnostic depth |
| **Speculative pre-gen** | Pre-generate responses for likely answers during user thinking time | ~5-10s per Q | ✅ Build after model router (Sprint 2) reduces per-call cost |
| **API failover** | Per-provider keys + try/except fallback in model router | N/A (reliability) | ✅ Trivial add-on after Sprint 2 |

---

### Implementation Order

```
WEEK 1: Sprint 6a (crawl 15→8) + Sprint 3b (parallelize Agent 5)
         → 20-50s saved. Minimal code changes.

WEEK 2: Sprint 1 (SSE streaming for playbook)
         → Perceived wait 30s → 3s.

WEEK 3: Sprint 2 (Model router with tiered models)
         → 50-60% cost reduction.

WEEK 4: Sprint 6b (auth move) + Sprint 6c (observability)
         → 15-30s saved + data for all future decisions.

WEEK 5+: Sprint 3a (merge Phase 0) + Sprint 4 (two-pass) + Sprint 5 (caching)
         → Informed by observability data.
```

### Net Impact After Weeks 1-4

| Metric | Current | After |
|--------|---------|-------|
| Perceived playbook wait | 30-45s spinner | 2-3s (streaming) |
| Playbook pipeline wall-clock | 60-180s | 45-120s |
| Total session wall-clock | 10-22 min | 7-15 min |
| Cost per session | ₹25-40 | ₹8-16 |
| Playbook quality | Current | **Identical** (no prompt changes in Weeks 1-4) |
| Reliability | Single provider | Failover-ready |

---

## Time Savings Breakdown

### Actual Wall-Clock Savings (per sprint)

| Change | What it removes | Seconds saved |
|--------|----------------|---------------|
| Sprint 6a (crawl 15→8) | Fewer pages to fetch; Phase 12 wait drops | **5-20s** |
| Sprint 3b (Agent 5 ‖ Agent 3) | Agent 5 hidden behind Agent 3's longer execution | **10-20s** |
| **Bug fix: Agent 1+2 double-execution** | `/generate` re-runs Agent 1+2 that `/start` already ran | **20-60s** |
| Sprint 1 (SSE streaming) | Perceived spinner wait eliminated (same clock time, zero dead stare) | **30-45s perceived** |
| Sprint 2 (model router — faster models for Agent 1, first RCA) | GPT-4o-mini responds faster than GLM-5 | **10-20s** |
| Sprint 6b (auth during scale questions) | Auth wait overlaps with existing user activity | **15-30s** |
| Sprint 3a (merge Phase 0 into Agent 1) | One fewer LLM round-trip | **10-30s** |
| Sprint 5 (prompt compression) | Fewer input tokens per call × 10-12 calls | **10-24s** |
| **Total actual clock savings** | | **~80-200s (1.5-3.5 min)** |

### Perceived vs Actual

| Type | Savings |
|------|---------|
| **Actual clock time removed** | 1.5-3.5 min of real LLM/network wait eliminated |
| **Perceived wait eliminated** | Additional 30-45s (streaming makes playbook generation feel instant) |
| **Dead spinner time reduced** | From ~3-5 min total → ~1-2 min |

### Before vs After (combined)

| Metric | Current | After all sprints |
|--------|---------|-------------------|
| Actual session clock | 10-22 min | **7-15 min** (~3-7 min saved) |
| Perceived playbook wait | 30-45s spinner | **2-3s** (streaming) |
| Cost per session | ₹25-40 | **₹8-16** (50-60% cut) |
| Dead time (user staring at spinners) | ~3-5 min | **~1-2 min** |
| Number of wasted LLM calls | 2 (Agent 1+2 re-run) | **0** (bug fixed) |

### Key Insight

The session goes from **"20+ minutes that feels painful"** to **"12-15 minutes that feels fast"** because:
1. 1.5-3.5 min of actual clock time is removed
2. The remaining wait is hidden behind user activity (reading, answering) rather than exposed as spinners
3. The worst single wait (30-45s playbook spinner) is replaced by progressive streaming

The biggest free win — **fixing the Agent 1+2 double-execution** — is not in the original Claude chat plan but saves 20-60s and 2 wasted LLM calls every single session.

---

*Session documented: 16 March 2026*
