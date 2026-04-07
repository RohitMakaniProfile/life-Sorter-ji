# Onboarding Crawl Refactor — Single-Page Playwright + RCA Questions

## Goal

Replace the heavy multi-page `crawl_service` with a focused single-page Playwright scrape inside the same background task stream. The task will:

1. Scrape one page via the `scrape-playwright` skill (stores in `skill_calls` table).
2. Build a `web_summary` text from the page data and store it on the `onboarding` row.
3. Use `web_summary` + the user's `outcome / domain / task` answers to generate **up to 3 RCA questions** and store them in `onboarding.rca_qa`.

---

## Current Flow

```
Frontend: useCrawlTaskStream.js
  └─ runResumableTaskStream('crawl', { sessionId, payload: { website_url } })
        │
        ▼
Backend: task_stream/tasks/crawl.py  (@register_task_stream("crawl"))
  └─ detect_url_type(website_url)
  └─ crawl_website(website_url)          ← crawl_service.py (1 362 lines, httpx, multi-page)
  └─ _quick_summary(crawl_raw)           ← naive bullet-point summary
  └─ persist_successful_crawl(...)
        ├─ UPSERT crawl_cache            ← normalized_url, crawl_raw, crawl_summary
        ├─ INSERT crawl_runs             ← audit / lineage
        └─ UPDATE onboarding             ← crawl_run_id, crawl_cache_key only

Returns: { crawl_raw, crawl_summary }
```

### What Is Wrong

| Problem | Detail |
|---|---|
| `crawl_service.py` is massive | 1 362 lines, recursive multi-page httpx crawler, heavy for a single onboarding signal |
| No RCA questions generated | Task ends at `crawl_summary`; questions are generated separately in a later chat turn |
| No `web_summary` on `onboarding` | There is nowhere to put a human-readable LLM-friendly page summary |
| `skill_calls` not used | The playwright skill infrastructure exists but is bypassed entirely |
| `crawl_raw` is stored raw | Large unstructured blob, mostly unused downstream |

---

## Proposed New Flow

```
Frontend: useCrawlTaskStream.js  (unchanged — task type stays 'crawl')
  └─ runResumableTaskStream('crawl', { sessionId, userId, payload: { website_url } })
        │
        ▼
Backend: task_stream/tasks/onboarding_crawl.py  (@register_task_stream("crawl"))

  STAGE 1 — scraping
  └─ call scrape-playwright skill (maxPages=1, single page)
        ├─ CREATE row in skill_calls  (onboarding_session_id column, see DB changes)
        ├─ stream events → emit stage events to frontend
        └─ page_data: { title, meta_description, elements[], tech_stack, … }

  STAGE 2 — summarizing
  └─ build_web_summary(page_data)
        └─ structured text ≤ 800 tokens:
             "Title: …  Description: …  Key content: …  Tech: …"
  └─ UPDATE onboarding SET web_summary = <text> WHERE session_id = sid

  STAGE 3 — generating_questions
  └─ load onboarding row (outcome, domain, task, web_summary)
  └─ call Claude (claude-sonnet-4-6 via ai_helper)
        system: RCA question generator prompt
        user:   { outcome, domain, task, web_summary }
  └─ parse ≤ 3 questions from response
  └─ UPDATE onboarding SET rca_qa = <questions> WHERE session_id = sid

  DONE
  └─ emit done event { web_summary, rca_questions: [...] }
```

---

## Frontend Changes

`frontend/src/components/onboarding/hooks/useCrawlTaskStream.js`

- **Task type stays `'crawl'`** — no change to the stream key or start call.
- **`onDone` payload changes**: instead of `{ crawl_raw, crawl_summary }`, the done event returns `{ web_summary, rca_questions }`.
- Update `setCrawlResult` to read the new fields:

```js
// Before
setCrawlResult({ crawl_raw: e.crawl_raw, crawl_summary: e.crawl_summary });

// After
setCrawlResult({ web_summary: e.web_summary, rca_questions: e.rca_questions ?? [] });
```

- Stage labels remain compatible (`starting`, `scraping`, `summarizing`, `generating_questions`, `done`, `error`).
- Auto-resume logic is unaffected (keyed by session/user + task type).

---

## Backend Changes

### 1. New task file: `backend/app/task_stream/tasks/onboarding_crawl.py`

Replaces `crawl.py`. Registered under the same `"crawl"` task type so no frontend change is needed.

```python
@register_task_stream("crawl")
async def onboarding_crawl_task(send, payload: dict) -> dict:
    # 1. Validate inputs
    website_url = sanitize_http_url(payload["website_url"])
    session_id  = payload["session_id"]
    user_id     = payload.get("user_id")

    await send("stage", stage="scraping", label="Scraping page with Playwright")

    # 2. Run scrape-playwright skill (single page)
    skill_call_id = await create_onboarding_skill_call(
        session_id=session_id,
        skill_id="scrape-playwright",
        input={"url": website_url, "maxPages": 1},
    )
    page_data = await run_playwright_single_page(
        url=website_url,
        on_progress=lambda e: send("stage", stage="scraping", **e),
    )
    await finish_onboarding_skill_call(skill_call_id, output=page_data)

    await send("stage", stage="summarizing", label="Building web summary")

    # 3. Build web_summary
    web_summary = build_web_summary(page_data, website_url)
    await update_onboarding_web_summary(session_id, web_summary)

    await send("stage", stage="generating_questions", label="Generating RCA questions")

    # 4. Load onboarding context and generate questions
    onboarding = await fetch_onboarding_row(session_id)
    rca_questions = await generate_rca_questions(
        outcome=onboarding["outcome"],
        domain=onboarding["domain"],
        task=onboarding["task"],
        web_summary=web_summary,
        max_questions=3,
    )
    await update_onboarding_rca_questions(session_id, rca_questions)

    return {"web_summary": web_summary, "rca_questions": rca_questions}
```

#### Sub-functions to implement in the same file or a new `onboarding_crawl_service.py`:

| Function | Responsibility |
|---|---|
| `create_onboarding_skill_call(session_id, skill_id, input)` | INSERT into `skill_calls` using `onboarding_session_id` (see DB changes); return `id` |
| `run_playwright_single_page(url, on_progress)` | Call `SCRAPER_BASE_URL/v1/scrape-playwright/stream` with `maxPages=1`; parse SSE; return page dict |
| `finish_onboarding_skill_call(id, output)` | UPDATE skill_calls SET state='done', output=…, ended_at=NOW() |
| `build_web_summary(page_data, url)` | Pure function → structured text ≤ 800 tokens |
| `update_onboarding_web_summary(session_id, text)` | UPDATE onboarding SET web_summary = $1 WHERE session_id = $2 |
| `fetch_onboarding_row(session_id)` | SELECT outcome, domain, task, web_summary FROM onboarding WHERE session_id = $1 |
| `generate_rca_questions(...)` | LLM call → list[str] of ≤ 3 questions |
| `update_onboarding_rca_questions(session_id, questions)` | UPDATE onboarding SET rca_qa = $1 WHERE session_id = $2 |

### 2. `build_web_summary` — format spec

```
Website: {url}
Title: {title}
Description: {meta_description}
Tech stack: {tech_stack.detected joined by ", "}
Key content:
{top 10 elements rendered as "- {type}: {content}"}
```

Total length capped at 800 tokens (~3 200 chars). Sufficient context for RCA question generation without storing the full crawl blob.

### 3. `generate_rca_questions` — prompt spec

**System prompt:**
```
You are an expert business diagnostician. Given what you know about a business's
website and their stated goal, generate up to 3 concise, specific, layman-friendly
diagnostic questions that will help identify the root cause of their challenge.

Rules:
- Maximum 3 questions.
- Each question must be answerable in 1-3 sentences by a non-technical business owner.
- Questions must be directly motivated by the website evidence and the user's goal.
- Output ONLY a JSON array of question strings: ["Q1", "Q2", "Q3"]
```

**User message:**
```json
{
  "outcome": "...",
  "domain": "...",
  "task": "...",
  "web_summary": "..."
}
```

Parse the JSON array response; fall back to `[]` on parse error (do not block the task).

---

## Database Schema Changes

### `onboarding` table — add `web_summary`

```sql
ALTER TABLE onboarding
    ADD COLUMN IF NOT EXISTS web_summary TEXT NOT NULL DEFAULT '';
```

`web_summary` stores the LLM-friendly page summary built from the single-page Playwright scrape.

---

### `skill_calls` table — support onboarding context

The existing `skill_calls` schema has `conversation_id TEXT NOT NULL REFERENCES conversations(id)`. Onboarding tasks have no conversation, so we need one of the following approaches:

**Option A (recommended) — add nullable `onboarding_session_id`, make `conversation_id` nullable**

```sql
ALTER TABLE skill_calls
    ALTER COLUMN conversation_id DROP NOT NULL;

ALTER TABLE skill_calls
    ADD COLUMN IF NOT EXISTS onboarding_session_id TEXT;

CREATE INDEX IF NOT EXISTS idx_skill_calls_onboarding_session_id
    ON skill_calls (onboarding_session_id)
    WHERE onboarding_session_id IS NOT NULL;

-- Constraint: exactly one context must be set
ALTER TABLE skill_calls
    ADD CONSTRAINT skill_calls_context_check
    CHECK (
        (conversation_id IS NOT NULL AND onboarding_session_id IS NULL) OR
        (conversation_id IS NULL     AND onboarding_session_id IS NOT NULL)
    );
```

**Option B — separate `onboarding_skill_calls` table**

A simpler, less invasive alternative: add a dedicated table with the same columns but without the `conversations` FK, and without touching the existing `skill_calls` table. Only choose this if you want to avoid schema changes on the shared table.

```sql
CREATE TABLE IF NOT EXISTS onboarding_skill_calls (
    id                  BIGSERIAL   PRIMARY KEY,
    onboarding_session_id TEXT      NOT NULL,
    skill_id            TEXT        NOT NULL,
    input               JSONB       NOT NULL DEFAULT '{}'::JSONB,
    state               TEXT        NOT NULL DEFAULT 'running'
                                    CHECK (state IN ('running', 'done', 'error')),
    output              JSONB       NOT NULL DEFAULT '[]'::JSONB,
    error               TEXT,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ended_at            TIMESTAMPTZ,
    duration_ms         INTEGER,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_onboarding_skill_calls_session_id
    ON onboarding_skill_calls (onboarding_session_id);
```

> **Recommendation: use Option B** to avoid breaking the existing `skill_calls` constraint and keep agent and onboarding concerns separate. The new task code references `onboarding_skill_calls`.

---

## Files to Delete / Deprecate

| File | Action |
|---|---|
| `backend/app/task_stream/tasks/crawl.py` | **Delete** — replaced by `onboarding_crawl.py` |
| `backend/app/services/crawl_service.py` | **Delete** — no longer called from any task stream |
| `backend/app/services/crawl_persistence.py` | **Delete** — `crawl_cache` and `crawl_runs` tables become unused |

> Verify no other code imports from `crawl_service.py` or `crawl_persistence.py` before deleting. A `grep -r "crawl_service\|crawl_persistence"` across `app/` will confirm.

### Tables that become unused (optional cleanup)

| Table | Action |
|---|---|
| `crawl_cache` | Can be dropped once the old flow is removed |
| `crawl_runs` | Can be dropped once the old flow is removed |
| `onboarding.crawl_run_id` | Column can be dropped |
| `onboarding.crawl_cache_key` | Column can be dropped |

---

## Files to Create

| File | Purpose |
|---|---|
| `backend/app/task_stream/tasks/onboarding_crawl.py` | New `@register_task_stream("crawl")` task entry point |
| `backend/app/services/onboarding_crawl_service.py` | `run_playwright_single_page`, `build_web_summary`, `generate_rca_questions`, all DB helpers |

---

## Event Sequence (SSE to Frontend)

| Event type | `stage` | `label` | Extra fields |
|---|---|---|---|
| `stage` | `starting` | Starting | `url` |
| `stage` | `scraping` | Scraping page | `url`, `current_page` |
| `stage` | `summarizing` | Building web summary | — |
| `stage` | `generating_questions` | Generating RCA questions | — |
| `done` | — | — | `web_summary`, `rca_questions: string[]` |
| `error` | — | — | `message` |

The frontend `useCrawlTaskStream.js` currently handles `type === 'stage'` for progress and `onDone`/`onError`. The only required frontend change is reading `e.web_summary` and `e.rca_questions` in `onDone` instead of `e.crawl_raw` / `e.crawl_summary`.

---

## Implementation Order

1. **DB migration** — add `web_summary` to `onboarding`; add `onboarding_skill_calls` table.
2. **`onboarding_crawl_service.py`** — implement all helper functions and test individually.
3. **`onboarding_crawl.py`** — wire task, keep same `"crawl"` registration key.
4. **Delete `crawl.py`** — remove old task registration so new file is the only `"crawl"` handler.
5. **Frontend `onDone`** — update result field names.
6. **Smoke test** — submit a URL, verify: skill_call row created, `onboarding.web_summary` set, `onboarding.rca_qa` contains ≤ 3 questions.
7. **Cleanup** — drop `crawl_service.py`, `crawl_persistence.py`, old DB columns/tables after verifying nothing references them.