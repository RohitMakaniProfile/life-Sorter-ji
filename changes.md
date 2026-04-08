# Changes Log

This file tracks **every engineering change** we make in this repo, with:
- what changed (exact behavior)
- where it changed (files + functions)
- why we changed it (reason / bug)
- how to verify (manual / API calls)

---

## 2026-04-08 — Attach onboarding row to conversation + unified history

### Goal (from `docs/TODO.md`)
- Show **Phase-1 onboarding** + **Phase-2 chat** in the **same chat UI history** so the user doesn’t feel they are two separate experiences.

### Problem (what was happening before)
- Onboarding data is stored in the `onboarding` table (`questions_answers`, `rca_qa`, selections like outcome/domain/task/urls).
- Phase-2 chat history is stored as `conversations` + ordered `messages`.
- The `/api/v1/ai-chat/messages` endpoint returned only the conversation’s `messages`.
- Result: the UI history would show only stage-2 messages; onboarding context/history wouldn’t show up in the unified “chat history” experience.

### Chosen implementation (best for current DB + code)
We chose **virtual merge (no backfill)**:
- Convert `onboarding.questions_answers` into chat-like messages **on the fly**.
- **Prepend** those messages to the response of `GET /api/v1/ai-chat/messages`.
- Do **not** insert/backfill onboarding rows into the `messages` table (avoids duplication + ordering edge cases).

### Database / schema alignment
- Schema already has `onboarding.session_id` as the canonical key for an onboarding journey.
- There is a migration that links conversations back to onboarding:
  - `backend/migrations/20260408_conversations_add_onboarding_session_id.sql`
  - Adds: `conversations.onboarding_session_id TEXT REFERENCES onboarding(session_id)`.

### Backend changes (exact)

#### 1) Ensure conversation always carries `onboarding_session_id`

**File:** `backend/app/routers/ai_chat.py`
- **Route:** `POST /api/v1/ai-chat/conversations`
- **Change:** if request body does not include `onboardingSessionId`, we set:
  - `onboardingSessionId = sessionId`
- Why: In this app, we treat `sessionId` as the canonical onboarding session id actor key (confirmed in discussion).

**File:** `backend/app/doable_claw_agent/stores.py`
- **Function:** `get_or_create_conversation(...)`
  - **Change:** when creating a new conversation, we now insert with `onboarding_session_id = session_id`.
  - Exact behavior: conversation insert now includes the `onboarding_session_id` column so it’s stored immediately.
- **Function:** `get_conversation(...)`
  - **Change:** the returned conversation payload now includes:
    - `onboardingSessionId: conv["onboarding_session_id"]`
  - Why: downstream APIs (like `get_messages`) can reliably fetch and merge onboarding transcript.

#### 2) Merge onboarding transcript into `/api/v1/ai-chat/messages`

**File:** `backend/app/repositories/chat_repository.py`
- **Function:** `get_messages(...)`
  - **Change:** after loading conversation messages, we compute:
    - `onboarding_session_id = conv.onboardingSessionId OR session_id`
  - Then we call a new helper to prepend onboarding transcript.

- **Helper added:** `_attach_onboarding_transcript(messages, onboarding_session_id=...)`
  - **Fetches** the onboarding row by `session_id`:
    - `outcome, domain, task, website_url, gbp_url, questions_answers`
  - **Builds** virtual chat messages:
    1) A compact assistant summary message:
       - `journeyStep = "onboarding_summary"`
       - `messageId = "onboarding:summary:<sid>"`
       - includes `journeySelections` with `onboardingSessionId`, outcome/domain/task/urls.
    2) For every Q&A entry in `questions_answers`:
       - assistant message:
         - `journeyStep = "onboarding_question"`
         - `messageId = "onboarding:q:<sid>:<i>"`
       - user message:
         - `journeyStep = "onboarding_answer"`
         - `messageId = "onboarding:a:<sid>:<i>"`
  - **Prepends** onboarding messages:
    - `return onboarding_msgs + conversation_messages`

- **Dedupe guard added:** `_has_onboarding_markers(messages)`
  - If the existing message list already contains onboarding markers, we skip prepend to avoid double-adding:
    - `journeyStep` starts with `"onboarding_"` OR
    - `messageId` starts with `"onboarding:"`

##### Bug found during verification (and fixed)
- Initially, Q&A prepend was not working reliably because `questions_answers` sometimes came back as a **JSON string**, not a Python list.
- Fix:
  - `_as_list(...)` now supports `str` by doing `json.loads(...)` safely and returning `[]` on parse failure.

### What did NOT change (explicitly)
- We did **not** backfill onboarding Q&A into `messages` table.
- We did **not** alter frontend rendering logic in this step (backend now provides unified stream; UI can render it as normal chat messages).
- We did **not** edit the plan file (per instruction).

### How to verify (repeatable)

#### A) Verify backend is up
- `GET /health` → should be 200

#### B) Pick a session id that has onboarding Q&A
Run a quick script (example) to find a recent onboarding row with non-empty `questions_answers`:
- Query: `SELECT session_id FROM onboarding ... WHERE questions_answers not empty`

#### C) Call unified messages endpoint
- `GET /api/v1/ai-chat/messages?sessionId=<sid>`
Expected:
- First message has `journeyStep = "onboarding_summary"`
- Next messages alternate:
  - `"onboarding_question"` (assistant) then `"onboarding_answer"` (user)
- After those, normal conversation messages appear (if any exist).

### Files touched (for quick diff)
- `backend/app/doable_claw_agent/stores.py`
- `backend/app/routers/ai_chat.py`
- `backend/app/repositories/chat_repository.py`

---

## 2026-04-08 — Frontend playbook restoration + reset logic

### Goal (from `docs/TODO.md`)
- Reset flow works for both **session-based (guest)** and **JWT-based** users.
- If playbook is **generating**: refresh should **resume stream** (not get stuck).
- If playbook is **completed**: show full playbook and a **Start New Journey** button.
- Reset action should call `clearSession()` and navigate back to **outcome selection**.

### Context (what existed already)
- Onboarding flow UI is driven by `frontend/src/components/onboarding/OnboardingApp.jsx`.
- Onboarding session id is stored client-side via `useOnboardingSession()`:
  - localStorage keys:
    - `life-sorter-onboarding-session-id`
    - `life-sorter-onboarding-row-id`
- Playbook generation uses task streams via `usePlaybookTaskStream()` (task type `playbook/onboarding-generate`).
- On mount, onboarding has a restoration effect that restores state from backend; it skips restoration if URL has `?reset=1`.

### Problem (what was wrong / missing)
1) **Generating → refresh → resume** could fail because the stored taskStream id lookup used the wrong actor key.\n
2) Completed state had “Go to Homepage”, but requirement was a proper **Start New Journey** flow that clears onboarding session and returns to outcome selection without “restoring” old state.

### Changes (exact)

#### 1) Fix playbook stream resume key (generating restore)
**File:** `frontend/src/components/onboarding/hooks/usePlaybookTaskStream.js`
- Auto-resume now reads stored stream id using the **session actor key**:\n
  - `getStoredTaskStreamId('playbook/onboarding-generate', { sessionId: sid, userId: null })`\n
- Why: `runResumableTaskStream(...)` stores stream id under `{ sessionId: sid, userId: null }`, so resume must match the same key.

#### 2) Add proper reset (“Start New Journey”) wiring
**File:** `frontend/src/components/onboarding/OnboardingApp.jsx`
- Destructure `clearSession` from `useOnboardingSession()`.
- Added `startNewJourney()` callback that:\n
  - clears playbook resume flag: `clearStepReached()`\n
  - clears onboarding session storage: `clearSession()`\n
  - clears localStorage keys prefixed with `life-sorter` and `ikshan-taskstream` (keeps auth token)\n
  - navigates to: `/?reset=1` (so restore effect doesn’t bring old state back)\n
- `PlaybookStage` props wiring:\n
  - `onGoHome={startNewJourney}`\n
  - `onCancel={startNewJourney}`

#### 3) Completed CTA label update
**File:** `frontend/src/components/onboarding/stages/PlaybookStage.jsx`
- Button label changed:\n
  - “Go to Homepage” → **“Start New Journey”**

### What did NOT change (explicitly)
- No backend API changes were needed for this step.
- No changes to playbook content rendering; only restore/reset behavior.

### How to verify (manual)
1) **Generating resume**:\n
   - Start playbook generation.\n
   - Refresh page.\n
   - Expect: playbook stream continues (auto-resume attaches using stored stream id).\n
2) **Completed reset**:\n
   - After playbook completes, click **Start New Journey**.\n
   - Expect: onboarding session cleared and you land on outcome selection at `/?reset=1`.\n
   - Expect: no old state is restored automatically.

### Files touched (for quick diff)
- `frontend/src/components/onboarding/hooks/usePlaybookTaskStream.js`
- `frontend/src/components/onboarding/OnboardingApp.jsx`
- `frontend/src/components/onboarding/stages/PlaybookStage.jsx`

---

## 2026-04-08 — Admin config: markdown type + interactive editor

### Goal (from `docs/TODO.md`)
- Add an interactive editor for **markdown config values**.
- Reuse existing editor UX from Agents.
- Show the editor in Admin System Config page when config `type` is `markdown`.

### Problem (what was happening before)
- `system_config` table had only: `key, value, description, updated_at`.
- Admin APIs (`/admin/management/config`) returned only: `key, value, description, updatedAt`.
- Frontend Admin Config UI only had a plain textarea for the value, with no ability to:
  - distinguish markdown vs non-markdown values
  - render markdown preview
  - open a full-screen editor

### Changes (end-to-end)

#### 1) Database: add `system_config.type`
**File:** `backend/migrations/20260408_system_config_add_type.sql`
- Adds:
  - `type TEXT NOT NULL DEFAULT 'string'`
- Adds index:
  - `idx_system_config_type`

#### 2) Backend: return + upsert `type` in admin config APIs
**File:** `backend/app/routers/admin_management.py`
- `SystemConfigEntry` response model now includes `type`.
- `UpsertSystemConfigRequest` now accepts:
  - `type` (default `'string'`)
- SQL changes:
  - `list_system_config`: `SELECT key, value, type, description, updated_at ...`
  - `get_system_config_entry`: `SELECT key, value, type, description, updated_at ...`
  - `upsert_system_config_entry`:
    - Insert includes `(key, value, type, description)`
    - On conflict, updates `type` as well

#### 3) Frontend: extract Agents editor into a reusable component
**New file:** `frontend/src/components/FullScreenMarkdownEditor.tsx`
- Provides full-screen editor with:
  - Edit / Preview toggle (markdown render)
  - Save + Close
  - Cmd+S / Ctrl+S support

**File:** `frontend/src/pages/ai/AgentContextsPage.tsx`
- Replaced inlined full-screen editor with `FullScreenMarkdownEditor` so the same UX can be reused elsewhere.

#### 4) Frontend: Admin Config page now supports types + markdown editor
**File:** `frontend/src/pages/AdminSystemConfigPage.tsx`
- Added `Type` selector for both:
  - editing existing entry
  - adding a new entry
- When `type === 'markdown'`:
  - shows “Open full-screen editor”
  - uses `FullScreenMarkdownEditor` for edit/preview
- Save payload now includes `type`.

**File:** `frontend/src/api/types.ts`
- `SystemConfigEntry` now includes optional `type`.

### Admin access note
- Verified DB allowlist already includes `rohitmakani564@gmail.com` in `auth.super_admin_emails`.\n
  This email should be able to access Admin config once logged in and token is set.

### How to verify (manual)
1) Navigate to Admin Config page.\n
2) Select a config key.\n
3) Set `Type = markdown`.\n
4) Click “Open full-screen editor”.\n
5) Edit markdown → switch to Preview → Save.\n
6) Refresh page; confirm the entry still shows `type: markdown` and value persists.

### Files touched (for quick diff)
- `backend/migrations/20260408_system_config_add_type.sql`
- `backend/app/routers/admin_management.py`
- `frontend/src/components/FullScreenMarkdownEditor.tsx`
- `frontend/src/pages/ai/AgentContextsPage.tsx`
- `frontend/src/pages/AdminSystemConfigPage.tsx`
- `frontend/src/api/types.ts`

---

## 2026-04-08 — Token usage tracking (Backend + Frontend admin spend)

### Goal (from `docs/TODO.md`)
- Backend stores token metadata in `token_usage` with fields:
  - `conversation_id`, `user_id`, `model`, `input_tokens`, `output_tokens`, `cost`
- Admin APIs:
  - overall spend
  - users list
  - user conversations
  - conversation LLM calls
- Frontend Admin page:
  - spend summary + users list → user detail → conversation side panel

### Baseline (what already existed)
- DB already had `token_usage` table storing per-message token rows keyed by `message_id`.
- Backend already had:
  - `save_token_usage(...)` and `get_token_usage(message_id)` in `backend/app/doable_claw_agent/stores.py`
  - `GET /api/v1/ai-chat/token-usage?messageId=...` wired via `backend/app/routers/ai_chat.py` → `backend/app/repositories/chat_repository.py`.
- Frontend chat already showed per-message token usage in the side panel:
  - `frontend/src/components/ai/chat/TokenUsagePanel.tsx`

### Decisions implemented
- **Backend authoritative cost**:\n
  - store `cost_usd` and `cost_inr` in DB using server-side pricing map.\n
  - unknown models => cost NULL (excluded from spend totals).\n
- **Spend dashboards scope**: authenticated users only (`user_id` not null).
- **Primary currency**: INR.

### Database changes
**New migration:** `backend/migrations/20260408_token_usage_add_cost_and_links.sql`
- Extends `token_usage` with:
  - `conversation_id TEXT`
  - `user_id TEXT`
  - `stage TEXT NOT NULL DEFAULT ''`
  - `provider TEXT NOT NULL DEFAULT ''`
  - `model_name TEXT NOT NULL DEFAULT ''`
  - `cost_usd NUMERIC(12,6)` NULL
  - `cost_inr NUMERIC(12,2)` NULL
- Backfills:
  - `stage/provider/model_name` from legacy encoded `model = stage||provider||model` (or uses raw model as `model_name`).\n
  - `conversation_id` by joining `messages` via `(messages.message->>'messageId') = token_usage.message_id`.\n
  - `user_id` by joining `conversations` via `conversation_id`.\n
- Adds indexes:
  - `idx_token_usage_user_id_created_at` (filtered)\n
  - `idx_token_usage_conversation_id_created_at` (filtered)\n

**Fresh schema alignment:** `backend/migrations/cloud_sql_full_setup.sql`\n
`token_usage` table definition updated to include the new columns + indexes for new environments.

### Backend changes
**File:** `backend/app/doable_claw_agent/stores.py`
- Added server-side pricing + INR conversion:\n
  - `MODEL_PRICING_USD_PER_TOKEN` + `USD_TO_INR`.\n
  - `_compute_cost_usd_inr(...)`.\n
- Updated `save_token_usage(...)`:\n
  - Computes `stage/provider/model_name`.\n
  - Computes `cost_usd/cost_inr` when pricing is known.\n
  - Best-effort attaches `conversation_id` + `user_id` by looking up the messageId in `messages.message->>'messageId'` and joining `conversations`.\n
  - Inserts into the extended columns.\n
- Updated `get_token_usage(message_id)`:\n
  - Selects new columns and prefers `stage/provider/model_name` when present, falling back to decoding legacy `model` string.\n

**File:** `backend/app/routers/admin_management.py`
- Added super-admin endpoints for spend analytics:\n
  - `GET /api/v1/admin/management/token-usage/summary`\n
  - `GET /api/v1/admin/management/token-usage/users`\n
  - `GET /api/v1/admin/management/token-usage/users/{user_id}/conversations`\n
  - `GET /api/v1/admin/management/token-usage/conversations/{conversation_id}/calls`\n

### Frontend changes
**Routes + API client**\n
- `frontend/src/api/routes.ts`: added routes for the new admin token usage endpoints.\n
- `frontend/src/api/types.ts`: added DTO types for summary/users/conversations/calls.\n
- `frontend/src/api/services/admin.ts`: added API wrapper functions.\n

**Admin UI page**\n
- New page: `frontend/src/pages/AdminTokenUsagePage.tsx`\n
  - Summary cards (INR spend, tokens, users, unknown-priced calls)\n
  - Users list with search + pagination\n
  - Drill-down: user → conversations\n
  - Drill-down: conversation → LLM call rows table\n
- Navigation + routing:\n
  - `frontend/src/components/ai/Layout.tsx`: added Admin nav item “Token Usage” → `/admin/token-usage`.\n
  - `frontend/src/App.tsx`: added route under `/admin`.\n

### How to verify (manual)
1) Generate some chat activity (so new `token_usage` rows are created).\n
2) Open a chat message context panel and confirm `/api/v1/ai-chat/token-usage` still returns token totals.\n
3) As super-admin, open `/admin/token-usage`.\n
4) Confirm:\n
   - summary cards show priced INR totals\n
   - users list loads\n
   - selecting a user loads conversations\n
   - selecting a conversation loads call rows\n
   - rows with unknown model pricing show `—` in INR and are excluded from priced totals.\n

### Files touched (for quick diff)
- `backend/migrations/20260408_token_usage_add_cost_and_links.sql`
- `backend/migrations/cloud_sql_full_setup.sql`
- `backend/app/doable_claw_agent/stores.py`
- `backend/app/routers/admin_management.py`
- `frontend/src/api/routes.ts`
- `frontend/src/api/types.ts`
- `frontend/src/api/services/admin.ts`
- `frontend/src/pages/AdminTokenUsagePage.tsx`
- `frontend/src/components/ai/Layout.tsx`
- `frontend/src/App.tsx`

## 2026-04-08 — Send research report link via SMS (post-completion)

Implemented `docs/TODO.md` (54-57): send the deep-analysis conversation link via SMS only after report completion, only for users with a phone number, and behind a system-config toggle.

### What changed

**Reliable completion hook (backend):**
- Wired post-completion SMS trigger in `backend/app/services/agent_checklist_service.py`.
- Hook runs only when:
  - plan execution is marked `done`, and
  - agent is `research-orchestrator`.
- SMS send is best-effort and never blocks/fails report completion.

**New SMS service:**
- Added `backend/app/services/report_sms_service.py` with:
  - `send_report_link_sms_if_enabled(conversation_id, user_id)`
  - Toggle gate via `system_config` key `sms.report_link_enabled` (default `false`)
  - User phone lookup (`users.phone_number`) and skip-if-missing logic
  - Conversation URL generation: `${FRONTEND_URL}/chat/{conversation_id}`
  - 2Factor transactional template API call:
    - `POST /API/V1/{api_key}/ADDON_SERVICES/SEND/TSMS`
    - payload uses `From`, `To`, `TemplateName`, `VAR1` (report URL)
  - Fail-safe behavior if migration/table is not yet present (no crash)

**Duplicate-send guard + audit log:**
- Added migration `backend/migrations/20260408_report_link_sms_logs.sql`:
  - New table `report_link_sms_logs` (unique `conversation_id`) to prevent repeated successful sends
  - status tracking: `pending|sent|skipped|error`
  - provider message id / error metadata
  - supporting indexes + updated_at trigger
  - inserts new `system_config` keys if missing

**Base schema updates:**
- Updated `backend/migrations/cloud_sql_full_setup.sql`:
  - Added `report_link_sms_logs` table definition and indexes
  - Added system config defaults:
    - `sms.report_link_enabled = false`
    - `sms.report_link_sender_id = ''`
    - `sms.report_link_template_name = ''`

### Verification performed
- Applied migration SQL and verified keys exist in `system_config`.
- Ran service smoke test:
  - with default toggle `false`, function returns `{'sent': False, 'reason': 'disabled'}`.
  - confirms safe no-send default.

### Files touched
- `backend/app/services/agent_checklist_service.py`
- `backend/app/services/report_sms_service.py`
- `backend/migrations/20260408_report_link_sms_logs.sql`
- `backend/migrations/cloud_sql_full_setup.sql`
- `changes.md`

## 2026-04-08 — AI-generated MCQ playbook intake (incremental save + auto-generate)

Implemented the new playbook intake experience to replace long free-text prompting with 3-4 AI-generated MCQs, save each answer immediately, and auto-start playbook generation once all MCQs are answered.

### Backend changes

- Updated `backend/app/routers/onboarding.py`:
  - Added strict MCQ normalization and fallback logic:
    - `_normalize_mcq_questions(...)` enforces structured MCQs with options.
    - `_fallback_mcq_questions(...)` provides safe defaults when AI output is malformed/insufficient.
  - Added incremental-answer API:
    - `POST /api/v1/onboarding/playbook/mcq-answer`
    - accepts `session_id`, `question_index`, `answer_key`, `answer_text`
    - updates onboarding row immediately on every answer
    - updates `playbook_status` to:
      - `awaiting_gap_answers` while incomplete
      - `ready` when all MCQs answered
  - Added answer parsing/serialization helpers:
    - `_parse_gap_answers_map(...)`
    - `_serialize_gap_answers_text(...)`
  - Improved launch flow to avoid re-generating MCQs repeatedly:
    - reuses existing unanswered MCQs from DB
    - returns `ready` when all are answered
  - `playbook/launch` now returns `gap_answers_parsed` to support UI restore.
  - `GET /api/v1/onboarding/state` now includes `gap_answers_parsed` for session recovery.

- Updated `backend/app/task_stream/tasks/onboarding_playbook_generate.py`:
  - Added `_coerce_gap_answers_text(...)` to support JSON-stored incremental answers and convert them into text fed to playbook agents.
  - Preserves compatibility with legacy plain-text `gap_answers`.

### Frontend changes

- Updated `frontend/src/components/onboarding/OnboardingApp.jsx`:
  - Added MCQ progression state:
    - `gapCurrentIndex`
    - `gapSavingIndex`
  - Replaced all-at-once submit with per-answer save flow:
    - new `handleGapAnswer(...)`
    - saves each selection immediately via new API
    - auto-advances to next MCQ
    - auto-starts playbook stream after final answer (no extra submit button)
  - On restore/start, preloads saved answers and resumes at next unanswered MCQ using `gap_answers_parsed`.

- Updated `frontend/src/components/onboarding/stages/PlaybookStage.jsx`:
  - Reworked pre-playbook UI into strict MCQ-only interaction.
  - Shows one active MCQ at a time with progress indicator.
  - Removed textarea fallback and removed manual “Generate Playbook” dependency.

- Updated API client wiring:
  - `frontend/src/api/routes.ts`: added `playbookMcqAnswer` route.
  - `frontend/src/api/services/core.ts`: added `onboardingPlaybookMcqAnswer(...)`.

### Verification

- Python compile checks passed:
  - `backend/app/routers/onboarding.py`
  - `backend/app/task_stream/tasks/onboarding_playbook_generate.py`
- Frontend production build passed (`vite build`).
- No linter diagnostics in edited files.

### Files touched

- `backend/app/routers/onboarding.py`
- `backend/app/task_stream/tasks/onboarding_playbook_generate.py`
- `frontend/src/components/onboarding/OnboardingApp.jsx`
- `frontend/src/components/onboarding/stages/PlaybookStage.jsx`
- `frontend/src/api/routes.ts`
- `frontend/src/api/services/core.ts`
- `changes.md`

