## Goal

Make Phase 1 onboarding independent of `user_sessions`, `session_store`, and `agent.py`.

- **Onboarding source of truth**: `onboarding` table holds journey state + answers.
- **Auth source of truth**: `users` holds identity; links to onboarding via `onboarding_session_id` (or history table).
- **Crawl source of truth**: separate crawl tables with cache + runs; executed via Task Stream and streamed to UI.
- **Static lookups**: deterministic recommendations/tools loaded from JSON using `onboarding` fields (e.g. `task`).

## Guiding principles

- **Strangler migration**: dual-write/dual-read where needed, cut over, then delete.
- **No hidden coupling**: onboarding APIs must not write to `session_store` or `user_sessions`.
- **Background work via Task Stream**: crawl and other heavy jobs should be resumable and stream progress.

## Phase 0 — Inventory & invariants (prep)

- [ ] Document what Phase 1 screens require at runtime (fields needed for UI + playbook context + diagnostics).
- [ ] List which endpoints still call `agent/session/*` from onboarding frontend and why.
- [ ] Decide canonical shapes for:
  - [ ] `onboarding.scale_answers` (dict keyed by question id)
  - [ ] `onboarding.rca_qa` (array of `{question, answer}`)
  - [ ] optional `onboarding.questions_answers` (unified log) vs keeping separate columns

## Phase 1 — Database: remove hard dependency on `user_sessions`

- [x] Migration: drop FK constraint `onboarding.session_id -> user_sessions(session_id)` (keep `session_id` as `TEXT NOT NULL`).
- [x] Ensure indexes remain: `idx_onboarding_session_id`, `idx_onboarding_user_id`.
- [ ] If you want “1 row per session”: add unique constraint on `onboarding.session_id` (or keep “latest row wins” and be explicit).
  - [ ] **Decision**: pick one and document it here:
    - [x] **Option A (chosen)**: **1 row per session**. Add `UNIQUE (session_id)` and update `upsert_onboarding_patch` to update that row (no “latest row” semantics).
    - [ ] **Option B**: **latest row wins**. Keep allowing multiple rows per `session_id` and always read/write the latest `created_at DESC` row (be explicit in all queries and APIs).
  - [ ] **If Option A**: add migration (idempotent):
    - [x] `ALTER TABLE onboarding ADD CONSTRAINT onboarding_session_id_unique UNIQUE (session_id);`

## Phase 2 — Onboarding table completeness (store what you need)

- [ ] Verify onboarding contains required state:
  - [x] `outcome`, `domain`, `task`
  - [x] `website_url`, `gbp_url`
  - [x] `scale_answers` (JSONB)
  - [x] `rca_qa` (JSONB)
- [ ] Add missing columns (only if needed):
  - [x] `questions_answers` JSONB (if you want a unified Q&A log for replay/debug)
  - [x] `onboarding_completed_at` (optional)
  - [x] `crawl_run_id` or `crawl_cache_key` (optional pointer to crawl subsystem)

## Phase 3 — Onboarding API cutover (remove session_store/user_sessions writes)

- [x] `POST /api/v1/onboarding` upsert:
  - [x] Remove any `session_store.*` updates.
  - [x] Ensure JSONB fields are stored correctly (use JSON dumps or asyncpg JSON codec).
  - [x] Keep URL sanitization in one place.
- [x] `POST /api/v1/onboarding/rca-next-question`:
  - [x] Read `outcome/domain/task`, `scale_answers`, `rca_qa` from onboarding only.
  - [x] Ensure JSONB normalization on read (asyncpg may return strings without codecs).
  - [x] Persist transcript back to `onboarding.rca_qa`.
- [ ] Add a small “health”/debug endpoint (optional):
  - [ ] `GET /api/v1/onboarding/{session_id}` to inspect stored state during migration.

## Phase 4 — Auth linkage (users table owns identity)

- [ ] DB: extend `users`:
  - [ ] `onboarding_session_id`
  - [ ] `onboarding_completed_at`.
- [ ] Auth flow:
  - [ ] On OTP/Google verification: create/lookup user row.
  - [ ] Link onboarding session to user:
    - [ ] set `users.onboarding_session_id = sid`
    - [ ] set `onboarding.user_id = users.id`
- [ ] Remove any need for onboarding APIs to “ensure user_sessions exists”.

## Phase 5 — Crawling subsystem (reusable + task-stream powered)

- [ ] DB tables:
  - [ ] `crawl_cache` (keyed by normalized URL + version; stores summary/raw outputs)
  - [ ] `crawl_runs` (tracks per-request run status, timestamps, errors, cache_hit)
- [ ] Task Stream task:
  - [x] `task-stream/start/crawl` starts crawl in background
  - [x] emits progress events (queued/running/parsing/summarizing/done/error)
  - [ ] writes to `crawl_cache` and `crawl_runs`
- [ ] Onboarding integration:
  - [x] URL submit: onboarding upsert stores URL(s)
  - [x] then starts crawl task-stream and UI subscribes to events
  - [ ] onboarding row stores pointer to latest `crawl_run` / `crawl_cache` if needed

## Phase 6 — Playbook & recommendations: read from onboarding + crawl, not agent session

- [ ] Refactor playbook inputs to build context from:
  - [x] `onboarding` fields (`outcome/domain/task`, `scale_answers`, `rca_qa`, urls)
  - [ ] crawl summary from `crawl_cache`
  - [x] static JSON lookups using `task` (and possibly `domain/outcome`)
- [ ] If recommendations are static:
  - [x] create/confirm deterministic JSON datasets + lookup functions
  - [x] add endpoint(s) for frontend to fetch derived recommendations by `task`

## Phase 7 — Frontend cleanup (no agent endpoints in onboarding)

- [ ] Remove onboarding usage of:
  - [x] `POST /api/v1/agent/session/:sid/advance`
  - [x] `PATCH /api/v1/agent/session/:sid` (url/skip/scale answers)
- [ ] Ensure onboarding UI relies only on:
  - [x] `POST /api/v1/onboarding` (selections, urls, scale answers)
  - [x] `POST /api/v1/onboarding/rca-next-question`
  - [x] Task Stream crawl events
  - [x] playbook endpoints (refactored to onboarding source)

## Phase 8 — Decommission (last)

- [ ] Confirm no runtime code reads/writes `user_sessions` for Phase 1.
- [ ] Remove:
  - [ ] `session_store.py` usage
  - [ ] `user_session_service.py` usage
  - [ ] `agent.py` router (Phase 1 flow portions)
- [ ] DB cleanup:
  - [ ] drop `user_sessions` table (or archive) once fully unused
  - [ ] remove any remaining foreign keys/indexes referencing it

## Acceptance checklist

- [ ] Onboarding journey works end-to-end without `agent/session/*`.
- [x] RCA questions work and persist via onboarding (`rca_qa`) and use onboarding `scale_answers`.
- [ ] Crawl runs in background via Task Stream and results are reusable via `crawl_cache`.
- [ ] Auth creates/links user and ties onboarding session to that user.

